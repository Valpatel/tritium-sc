"""POI data module for building-centric mission generation.

Queries Overpass API for real POIs, named buildings, and street names
near a given lat/lng.  Follows the same synchronous-httpx + disk-caching
pattern as ``engine.tactical.street_graph`` and
``engine.tactical.obstacles``.

The primary purpose is to generate tactically meaningful BattleScenarios
that reference real neighborhood landmarks: "defend Dublin Library from
hostiles approaching via Amador Valley Blvd" instead of "defend (50, 30)
from target_7".
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_USER_AGENT = "TRITIUM-SC/0.1.0"
_DEFAULT_CACHE_DIR = "~/.cache/tritium-sc"
_METERS_PER_DEG_LAT = 111_320.0

# ---------------------------------------------------------------------------
# Rich category mappings
# ---------------------------------------------------------------------------

# Amenity types that map to specific high-level categories instead of generic "amenity"
_GOVERNMENT_AMENITIES = frozenset({
    "townhall", "courthouse", "police", "fire_station", "post_office",
})
_EDUCATION_AMENITIES = frozenset({
    "school", "university", "college", "library", "kindergarten",
})
_RELIGION_AMENITIES = frozenset({
    "place_of_worship",
})
_HEALTHCARE_AMENITIES = frozenset({
    "hospital", "clinic", "pharmacy",
})
_TRANSPORT_AMENITIES = frozenset({
    "bus_station",
})

# Human-readable labels for OSM poi_type values
POI_TYPE_LABELS: dict[str, str] = {
    "townhall": "Town Hall",
    "courthouse": "Courthouse",
    "police": "Police Station",
    "fire_station": "Fire Station",
    "post_office": "Post Office",
    "school": "School",
    "university": "University",
    "college": "College",
    "library": "Library",
    "kindergarten": "Kindergarten",
    "place_of_worship": "Church/Mosque/Temple",
    "hospital": "Hospital",
    "clinic": "Clinic",
    "pharmacy": "Pharmacy",
    "bus_station": "Bus Station",
    "station": "Train Station",
    "stadium": "Stadium",
    "sports_centre": "Sports Center",
    "park": "Park",
    "playground": "Playground",
    "attraction": "Attraction",
    "monument": "Monument",
    "museum": "Museum",
}

# Significance by category (0.0-1.0) for mission center prioritization
CATEGORY_SIGNIFICANCE: dict[str, float] = {
    "government": 0.9,
    "education": 0.9,
    "healthcare": 0.9,
    "landmark": 0.8,
    "religion": 0.7,
    "sports": 0.6,
    "transport": 0.6,
    "amenity": 0.4,
    "shop": 0.3,
    "building": 0.2,
    "street": 0.1,
}


def get_significance(category: str) -> float:
    """Return significance score (0.0-1.0) for a POI category."""
    return CATEGORY_SIGNIFICANCE.get(category, 0.1)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class POI:
    """A point of interest from OpenStreetMap."""

    name: str               # "Circle K", "Dublin Elementary", "7850 Amador Valley Blvd"
    poi_type: str           # "convenience", "school", "residential"
    category: str           # "shop", "amenity", "building", "street"
    address: str            # "7850 Amador Valley Blvd" (from addr:* tags)
    lat: float
    lng: float
    local_x: float          # meters east of geo reference
    local_y: float          # meters north of geo reference
    osm_id: int = 0


@dataclass
class MissionArea:
    """A circle around a chosen building -- the combat zone."""

    center_poi: POI                     # the chosen mission focus building
    radius_m: float                     # combat radius (100-300m)
    buildings: list[POI]                # all buildings within radius
    streets: list[str]                  # named streets within radius
    defensive_positions: list[tuple[float, float]]  # positions near buildings good for turrets
    approach_routes: list[str]          # street names hostiles approach from


# ---------------------------------------------------------------------------
# Coordinate conversion (self-contained, same math as geo.py)
# ---------------------------------------------------------------------------


def _latlng_to_local(
    lat: float, lng: float, ref_lat: float, ref_lng: float
) -> tuple[float, float]:
    """Convert lat/lng to local (x, y) meters relative to reference point.

    Uses the same math as engine.tactical.geo but without depending on
    the module-level singleton, so this module is self-contained.
    """
    y = (lat - ref_lat) * _METERS_PER_DEG_LAT
    meters_per_deg_lng = _METERS_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    x = (lng - ref_lng) * meters_per_deg_lng
    return (x, y)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Euclidean distance between two 2D points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ---------------------------------------------------------------------------
# Overpass query
# ---------------------------------------------------------------------------


def _fetch_overpass(lat: float, lng: float, radius_m: float) -> dict:
    """Fetch POI data from Overpass API (synchronous).

    Returns the raw JSON response dict with an ``elements`` list.
    """
    r = int(radius_m)
    query = (
        f"[out:json];"
        f"("
        # Amenities (schools, hospitals, fire stations, etc.)
        f'node["amenity"](around:{r},{lat},{lng});'
        f'way["amenity"](around:{r},{lat},{lng});'
        # Shops
        f'node["shop"](around:{r},{lat},{lng});'
        f'way["shop"](around:{r},{lat},{lng});'
        # Named buildings + addressed buildings
        f'way["building"]["name"](around:{r},{lat},{lng});'
        f'way["building"]["addr:street"](around:{r},{lat},{lng});'
        # Government buildings (building tag)
        f'way["building"="government"](around:{r},{lat},{lng});'
        # Sports / Leisure
        f'node["leisure"="stadium"](around:{r},{lat},{lng});'
        f'way["leisure"="sports_centre"](around:{r},{lat},{lng});'
        f'node["leisure"="park"](around:{r},{lat},{lng});'
        f'way["leisure"="park"](around:{r},{lat},{lng});'
        f'node["leisure"="playground"](around:{r},{lat},{lng});'
        # Tourism / Landmarks
        f'node["tourism"="attraction"](around:{r},{lat},{lng});'
        f'way["tourism"="attraction"](around:{r},{lat},{lng});'
        f'node["tourism"="museum"](around:{r},{lat},{lng});'
        f'node["historic"="monument"](around:{r},{lat},{lng});'
        # Transport
        f'node["railway"="station"](around:{r},{lat},{lng});'
        # Streets (residential, tertiary, secondary, primary)
        f'way["highway"="residential"]["name"](around:{r},{lat},{lng});'
        f'way["highway"="tertiary"]["name"](around:{r},{lat},{lng});'
        f'way["highway"="secondary"]["name"](around:{r},{lat},{lng});'
        f'way["highway"="primary"]["name"](around:{r},{lat},{lng});'
        f");"
        f"out center tags;"
    )
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            _OVERPASS_URL,
            data={"data": query},
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_key(lat: float, lng: float, radius_m: float) -> str:
    key = f"pois_{lat:.6f}_{lng:.6f}_{radius_m:.0f}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _cache_path(lat: float, lng: float, radius_m: float, cache_dir: str) -> Path:
    h = _cache_key(lat, lng, radius_m)
    base = Path(cache_dir).expanduser() / "pois"
    return base / f"{h}.json"


def _save_cache(pois: list[POI], lat: float, lng: float, radius_m: float, cache_dir: str) -> None:
    path = _cache_path(lat, lng, radius_m, cache_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(p) for p in pois]
        with open(path, "w") as f:
            json.dump(data, f)
        logger.info(f"POI cache saved: {path} ({len(pois)} entries)")
    except Exception as e:
        logger.warning(f"POI cache save failed: {e}")


def _load_cache(lat: float, lng: float, radius_m: float, cache_dir: str) -> list[POI] | None:
    path = _cache_path(lat, lng, radius_m, cache_dir)
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
        pois = [POI(**d) for d in data]
        logger.info(f"POI cache loaded: {path} ({len(pois)} entries)")
        return pois
    except Exception as e:
        logger.warning(f"POI cache load failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Element parsing
# ---------------------------------------------------------------------------


def _parse_element(el: dict, ref_lat: float, ref_lng: float) -> POI | None:
    """Parse a single Overpass element into a POI, or None if not useful."""
    tags = el.get("tags", {})
    el_type = el.get("type", "")
    osm_id = el.get("id", 0)

    # Determine lat/lng
    if el_type == "node":
        lat = el.get("lat", 0.0)
        lng = el.get("lon", 0.0)
    elif el_type == "way":
        center = el.get("center", {})
        lat = center.get("lat", 0.0)
        lng = center.get("lon", 0.0)
        if lat == 0.0 and lng == 0.0:
            return None
    else:
        return None

    # Determine category + poi_type
    # Rich category classification: map OSM tags to high-level categories
    category = ""
    poi_type = ""

    if "amenity" in tags:
        amenity_val = tags["amenity"]
        poi_type = amenity_val
        if amenity_val in _GOVERNMENT_AMENITIES:
            category = "government"
        elif amenity_val in _EDUCATION_AMENITIES:
            category = "education"
        elif amenity_val in _RELIGION_AMENITIES:
            category = "religion"
        elif amenity_val in _HEALTHCARE_AMENITIES:
            category = "healthcare"
        elif amenity_val in _TRANSPORT_AMENITIES:
            category = "transport"
        else:
            category = "amenity"
    elif "leisure" in tags:
        category = "sports"
        poi_type = tags["leisure"]
    elif "tourism" in tags:
        category = "landmark"
        poi_type = tags["tourism"]
    elif "historic" in tags:
        category = "landmark"
        poi_type = tags["historic"]
    elif "railway" in tags and tags.get("railway") == "station":
        category = "transport"
        poi_type = "station"
    elif "shop" in tags:
        category = "shop"
        poi_type = tags["shop"]
    elif "building" in tags:
        btype = tags.get("building", "yes")
        if btype == "government":
            category = "government"
            poi_type = "government"
        elif "name" in tags or "addr:street" in tags:
            category = "building"
            poi_type = btype if btype != "yes" else "building"
        else:
            return None
    elif "highway" in tags and "name" in tags:
        category = "street"
        poi_type = tags.get("highway", "residential")
    else:
        return None

    # Determine name
    name = tags.get("name", "")
    if not name:
        # Build name from address
        housenumber = tags.get("addr:housenumber", "")
        street = tags.get("addr:street", "")
        if housenumber and street:
            name = f"{housenumber} {street}"
        elif street:
            name = street
        else:
            name = f"POI {osm_id}"

    # Build address
    housenumber = tags.get("addr:housenumber", "")
    street = tags.get("addr:street", "")
    if housenumber and street:
        address = f"{housenumber} {street}"
    elif street:
        address = street
    else:
        address = ""

    # Convert to local coordinates
    local_x, local_y = _latlng_to_local(lat, lng, ref_lat, ref_lng)

    return POI(
        name=name,
        poi_type=poi_type,
        category=category,
        address=address,
        lat=lat,
        lng=lng,
        local_x=local_x,
        local_y=local_y,
        osm_id=osm_id,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_pois(
    lat: float,
    lng: float,
    radius_m: float = 500,
    cache_dir: str | None = _DEFAULT_CACHE_DIR,
) -> list[POI]:
    """Query Overpass for amenities, shops, named buildings, streets.

    Cache to ``~/.cache/tritium-sc/pois/``.  Returns empty list on
    network failure.

    Args:
        lat: Center latitude
        lng: Center longitude
        radius_m: Search radius in meters
        cache_dir: Directory for disk cache, or None to disable caching

    Returns:
        List of POI objects with local_x/local_y set relative to (lat, lng).
    """
    # Try cache first
    if cache_dir is not None:
        cached = _load_cache(lat, lng, radius_m, cache_dir)
        if cached is not None:
            return cached

    # Fetch from Overpass
    try:
        data = _fetch_overpass(lat, lng, radius_m)
    except Exception as e:
        logger.warning(f"Overpass POI fetch failed: {e}")
        return []

    elements = data.get("elements", [])
    if not elements:
        return []

    # Parse elements
    pois: list[POI] = []
    for el in elements:
        poi = _parse_element(el, lat, lng)
        if poi is not None:
            pois.append(poi)

    # Deduplicate by osm_id (same element may appear as both amenity and building)
    seen_ids: set[int] = set()
    unique_pois: list[POI] = []
    for p in pois:
        if p.osm_id not in seen_ids:
            seen_ids.add(p.osm_id)
            unique_pois.append(p)
    pois = unique_pois

    # Save to cache
    if cache_dir is not None:
        _save_cache(pois, lat, lng, radius_m, cache_dir)

    logger.info(f"Fetched {len(pois)} POIs near ({lat:.4f}, {lng:.4f})")
    return pois


def load_cached(
    lat: float,
    lng: float,
    radius_m: float = 500,
    cache_dir: str = _DEFAULT_CACHE_DIR,
) -> list[POI] | None:
    """Cache-only mode for offline scripted generation.

    Returns the cached POI list if available, None otherwise.
    Never makes network calls.
    """
    return _load_cache(lat, lng, radius_m, cache_dir)


def pick_mission_center(
    pois: list[POI],
    preference: str | None = None,
) -> POI | None:
    """Choose a POI as the battle focus.

    If *preference* is given, tries to match by name (substring,
    case-insensitive) or by poi_type.  Falls back to random selection
    from named non-street POIs.

    Args:
        pois: Available POIs
        preference: Name substring or type to prefer

    Returns:
        A POI, or None if the list is empty.
    """
    if not pois:
        return None

    if preference is not None:
        pref_lower = preference.lower()
        # Try exact name match first
        for p in pois:
            if pref_lower in p.name.lower():
                return p
        # Try type match
        for p in pois:
            if p.poi_type.lower() == pref_lower:
                return p

    # Prefer named non-street POIs, weighted by significance
    candidates = [
        p for p in pois
        if p.category != "street" and p.name and not p.name.startswith("POI ")
    ]
    if candidates:
        weights = [get_significance(p.category) for p in candidates]
        return random.choices(candidates, weights=weights, k=1)[0]

    # Fallback: any POI
    return random.choice(pois)


def get_street_names(pois: list[POI]) -> list[str]:
    """Extract unique named streets from POI data."""
    seen: set[str] = set()
    result: list[str] = []
    for p in pois:
        if p.category == "street" and p.name and p.name not in seen:
            seen.add(p.name)
            result.append(p.name)
    return result


def build_mission_area(
    center: POI,
    pois: list[POI],
    radius_m: float = 200,
) -> MissionArea:
    """Filter buildings within radius, identify defensive positions,
    extract approach streets.

    Args:
        center: The chosen mission focus POI
        pois: All available POIs
        radius_m: Combat radius in meters

    Returns:
        A MissionArea with buildings, streets, defensive positions, and
        approach routes all within (or relevant to) the radius.
    """
    cx, cy = center.local_x, center.local_y

    # Filter buildings within radius
    buildings: list[POI] = []
    for p in pois:
        if p.category not in ("building", "amenity", "shop"):
            continue
        dist = _distance((p.local_x, p.local_y), (cx, cy))
        if dist <= radius_m:
            buildings.append(p)

    # Extract streets (all named streets from POI data)
    streets = get_street_names(pois)

    # Generate defensive positions: 8m offset from each building centroid
    # in cardinal + intercardinal directions (outward from center)
    defensive_positions: list[tuple[float, float]] = []
    for b in buildings:
        bx, by = b.local_x, b.local_y
        # Direction from center to building
        dx = bx - cx
        dy = by - cy
        dist = math.hypot(dx, dy)
        if dist > 0.5:
            # Normalize and place 8m outward
            nx = dx / dist
            ny = dy / dist
            defensive_positions.append((bx + nx * 8.0, by + ny * 8.0))
        else:
            # Building is at center -- offset in 4 cardinal directions
            for angle_deg in (0, 90, 180, 270):
                angle = math.radians(angle_deg)
                defensive_positions.append(
                    (bx + 8.0 * math.cos(angle), by + 8.0 * math.sin(angle))
                )

    # Approach routes: streets that connect from outside the radius
    approach_routes = streets[:4] if streets else []

    return MissionArea(
        center_poi=center,
        radius_m=radius_m,
        buildings=buildings,
        streets=streets,
        defensive_positions=defensive_positions,
        approach_routes=approach_routes,
    )


def get_poi_context_text(area: MissionArea) -> str:
    """Format a text block for LLM prompts with real names, addresses, distances.

    Returns a multi-line string describing the mission area for use
    in Amy's tactical briefing prompts.
    """
    lines: list[str] = []
    lines.append(f"MISSION CENTER: {area.center_poi.name}")
    if area.center_poi.address:
        lines.append(f"  Address: {area.center_poi.address}")
    lines.append(f"  Combat radius: {area.radius_m:.0f}m")
    lines.append("")

    if area.buildings:
        lines.append(f"BUILDINGS IN AREA ({len(area.buildings)}):")
        cx, cy = area.center_poi.local_x, area.center_poi.local_y
        for b in area.buildings:
            dist = _distance((b.local_x, b.local_y), (cx, cy))
            addr_str = f" ({b.address})" if b.address else ""
            lines.append(f"  - {b.name}{addr_str} [{dist:.0f}m from center]")
        lines.append("")

    if area.streets:
        lines.append(f"STREETS ({len(area.streets)}):")
        for s in area.streets:
            lines.append(f"  - {s}")
        lines.append("")

    if area.approach_routes:
        lines.append(f"APPROACH ROUTES ({len(area.approach_routes)}):")
        for s in area.approach_routes:
            lines.append(f"  - {s}")
        lines.append("")

    return "\n".join(lines)


def place_defenders_around_buildings(
    area: MissionArea,
    unit_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Place defenders around buildings in the mission area.

    This is the core placement algorithm.  It places turrets near
    building edges facing outward, rovers on street patrol routes,
    and drones overhead.

    Args:
        area: The mission area with buildings and streets
        unit_specs: List of dicts with "type" and "count" keys, e.g.
            [{"type": "turret", "count": 2}, {"type": "rover", "count": 1}]

    Returns:
        List of dicts with "asset_type", "position" [x, y], and "name".
    """
    result: list[dict[str, Any]] = []
    used_positions: set[tuple[float, float]] = set()
    cx, cy = area.center_poi.local_x, area.center_poi.local_y

    # Sort buildings by distance from center (largest spread first for turrets)
    sorted_buildings = sorted(
        area.buildings,
        key=lambda b: _distance((b.local_x, b.local_y), (cx, cy)),
        reverse=True,
    )
    if not sorted_buildings:
        # If no buildings in area, use center as fallback
        sorted_buildings = [area.center_poi]

    building_idx = 0
    street_idx = 0

    for spec in unit_specs:
        unit_type = spec.get("type", "turret")
        count = spec.get("count", 0)

        for i in range(count):
            if unit_type == "turret":
                pos, name = _place_turret(
                    sorted_buildings, building_idx, i, cx, cy,
                    area.radius_m, used_positions,
                )
                building_idx = (building_idx + 1) % len(sorted_buildings)
                result.append({
                    "asset_type": "turret",
                    "position": list(pos),
                    "name": name,
                })
                used_positions.add(pos)

            elif unit_type == "rover":
                pos, name = _place_rover(
                    area.streets, street_idx, i, cx, cy,
                    area.radius_m, used_positions,
                )
                if area.streets:
                    street_idx = (street_idx + 1) % len(area.streets)
                result.append({
                    "asset_type": "rover",
                    "position": list(pos),
                    "name": name,
                })
                used_positions.add(pos)

            elif unit_type == "drone":
                pos, name = _place_drone(
                    area.center_poi, i, used_positions,
                )
                result.append({
                    "asset_type": "drone",
                    "position": list(pos),
                    "name": name,
                })
                used_positions.add(pos)

            elif unit_type == "scout_drone":
                pos, name = _place_scout_drone(
                    area.center_poi, i, area.radius_m, used_positions,
                )
                result.append({
                    "asset_type": "scout_drone",
                    "position": list(pos),
                    "name": name,
                })
                used_positions.add(pos)

            else:
                # Generic fallback: place near center
                offset = (i + 1) * 10.0
                pos = _unique_position(
                    (cx + offset, cy + offset), used_positions
                )
                result.append({
                    "asset_type": unit_type,
                    "position": list(pos),
                    "name": f"{area.center_poi.name} {unit_type.title()} {i + 1}",
                })
                used_positions.add(pos)

    return result


# ---------------------------------------------------------------------------
# Placement helpers
# ---------------------------------------------------------------------------


def _unique_position(
    desired: tuple[float, float],
    used: set[tuple[float, float]],
    jitter_m: float = 3.0,
) -> tuple[float, float]:
    """Return *desired* if unused, otherwise jitter until unique."""
    pos = (round(desired[0], 2), round(desired[1], 2))
    if pos not in used:
        return pos
    # Try small offsets
    for attempt in range(20):
        angle = random.random() * 2 * math.pi
        r = jitter_m * (1 + attempt * 0.5)
        candidate = (
            round(desired[0] + r * math.cos(angle), 2),
            round(desired[1] + r * math.sin(angle), 2),
        )
        if candidate not in used:
            return candidate
    # Last resort: large offset
    return (
        round(desired[0] + random.uniform(-20, 20), 2),
        round(desired[1] + random.uniform(-20, 20), 2),
    )


def _place_turret(
    buildings: list[POI],
    building_idx: int,
    turret_num: int,
    cx: float,
    cy: float,
    radius_m: float,
    used: set[tuple[float, float]],
) -> tuple[tuple[float, float], str]:
    """Place a turret 5-10m outside a building edge, facing outward."""
    building = buildings[building_idx % len(buildings)]
    bx, by = building.local_x, building.local_y

    # Direction from center to building (outward)
    dx = bx - cx
    dy = by - cy
    dist_to_center = math.hypot(dx, dy)

    if dist_to_center > 0.5:
        # Normalize direction and offset 5-10m outward
        nx = dx / dist_to_center
        ny = dy / dist_to_center
    else:
        # Building at center -- use turret_num to pick direction
        angle = (turret_num * 90 + 45) * math.pi / 180
        nx = math.cos(angle)
        ny = math.sin(angle)

    # Offset distance: 5-10m from building centroid
    offset = 5.0 + random.random() * 5.0
    desired = (bx + nx * offset, by + ny * offset)

    # Clamp to radius
    d = math.hypot(desired[0] - cx, desired[1] - cy)
    if d > radius_m:
        scale = radius_m / d
        desired = (cx + (desired[0] - cx) * scale, cy + (desired[1] - cy) * scale)

    pos = _unique_position(desired, used)
    name = f"{building.name} Turret"
    # Make name unique if needed
    if turret_num > 0 or pos in used:
        name = f"{building.name} Turret {turret_num + 1}"

    return pos, name


def _place_rover(
    streets: list[str],
    street_idx: int,
    rover_num: int,
    cx: float,
    cy: float,
    radius_m: float,
    used: set[tuple[float, float]],
) -> tuple[tuple[float, float], str]:
    """Place a rover on a street patrol route within combat radius."""
    if streets:
        street_name = streets[street_idx % len(streets)]
    else:
        street_name = "Area"

    # Place rovers at different positions around the perimeter
    angle = (rover_num * 137.5 + 30) * math.pi / 180  # golden angle spread
    patrol_radius = radius_m * 0.4 + random.random() * radius_m * 0.3
    desired = (
        cx + patrol_radius * math.cos(angle),
        cy + patrol_radius * math.sin(angle),
    )

    pos = _unique_position(desired, used)

    # Unique name using street + number if needed
    if rover_num == 0 and len(streets) > 0:
        name = f"{street_name} Patrol"
    else:
        name = f"{street_name} Patrol {rover_num + 1}"

    return pos, name


def _place_drone(
    center_poi: POI,
    drone_num: int,
    used: set[tuple[float, float]],
) -> tuple[tuple[float, float], str]:
    """Place a drone at or near the combat center (they fly above)."""
    offset = drone_num * 15.0
    desired = (center_poi.local_x + offset, center_poi.local_y + offset)
    pos = _unique_position(desired, used)

    if drone_num == 0:
        name = f"{center_poi.name} Overwatch"
    else:
        name = f"{center_poi.name} Overwatch {drone_num + 1}"

    return pos, name


def _place_scout_drone(
    center_poi: POI,
    scout_num: int,
    radius_m: float,
    used: set[tuple[float, float]],
) -> tuple[tuple[float, float], str]:
    """Place a scout drone at the perimeter."""
    angle = (scout_num * 120 + 60) * math.pi / 180
    perimeter_r = radius_m * 0.7 + random.random() * radius_m * 0.2
    desired = (
        center_poi.local_x + perimeter_r * math.cos(angle),
        center_poi.local_y + perimeter_r * math.sin(angle),
    )
    pos = _unique_position(desired, used)

    if scout_num == 0:
        name = "Perimeter Scout"
    else:
        name = f"Perimeter Scout {scout_num + 1}"

    return pos, name
