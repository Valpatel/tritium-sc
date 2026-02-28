"""Geo engine — address geocoding, satellite tile proxy, building footprints,
GIS interoperability protocols (KML, MGRS, UTM, WMS).

All data sources are FREE with no API keys:
- Nominatim (OpenStreetMap) for geocoding
- ESRI World Imagery for satellite tiles
- Overpass API for building footprints
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/api/geo", tags=["geo"])

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CACHE_DIR = Path(settings.geo_cache_dir).expanduser()
_TILE_CACHE = _CACHE_DIR / "tiles"
_GEOCODE_CACHE = _CACHE_DIR / "geocode"
_BUILDINGS_CACHE = _CACHE_DIR / "buildings"
_GIS_CACHE = _CACHE_DIR / "gis"

_USER_AGENT = "TRITIUM-SC/0.1.0"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_ESRI_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
_ESRI_ROAD_URL = "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}"
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class GeocodeRequest(BaseModel):
    """Geocode an address to lat/lng."""
    address: str


class GeocodeResponse(BaseModel):
    """Geocoding result."""
    lat: float
    lng: float
    display_name: str
    bbox: list[float]


class BuildingPolygon(BaseModel):
    """A building footprint polygon."""
    id: int
    polygon: list[list[float]]  # [[lat, lng], ...]
    tags: dict


class SetReferenceRequest(BaseModel):
    """Set the geo-reference from geocoding or manual entry."""
    lat: float
    lng: float
    alt: float = 0.0


# ---------------------------------------------------------------------------
# Geo reference — the real-world origin for all local coordinates
# ---------------------------------------------------------------------------

@router.get("/reference")
async def get_reference():
    """Get the current geo-reference point (map origin).

    Returns the real-world lat/lng/alt that defines local (0, 0, 0).
    The frontend uses this to initialize the map center and coordinate transforms.
    """
    from engine.tactical.geo import get_reference
    ref = get_reference()
    return {
        "lat": ref.lat,
        "lng": ref.lng,
        "alt": ref.alt,
        "initialized": ref.initialized,
    }


@router.post("/reference")
async def set_reference(body: SetReferenceRequest):
    """Set the geo-reference point (map origin).

    This anchors local coordinates to a real-world location.
    Call this after geocoding an address, or set manually.
    All existing simulation targets keep their local positions;
    their lat/lng will be recomputed from the new reference.
    """
    from engine.tactical.geo import init_reference
    ref = init_reference(body.lat, body.lng, body.alt)
    logger.info(f"Geo reference set: {ref.lat:.7f}, {ref.lng:.7f}, alt={ref.alt:.1f}")
    return {
        "lat": ref.lat,
        "lng": ref.lng,
        "alt": ref.alt,
        "initialized": ref.initialized,
    }


@router.post("/geocode-and-set-reference")
async def geocode_and_set_reference(request: GeocodeRequest):
    """Geocode an address AND set it as the geo-reference point.

    Convenience endpoint: geocodes the address, then sets the result
    as the map origin. Returns the geocoding result.
    """
    # Reuse the geocode logic
    result = await geocode(request)

    # Set as reference
    from engine.tactical.geo import init_reference
    init_reference(result.lat, result.lng)
    logger.info(f"Geo reference set from geocode: {result.lat:.7f}, {result.lng:.7f}")

    return result


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

@router.post("/geocode", response_model=GeocodeResponse)
async def geocode(request: GeocodeRequest):
    """Geocode an address to lat/lng using Nominatim (OpenStreetMap).

    Results are cached on disk. Nominatim requires a User-Agent header
    and allows 1 request/second.
    """
    address = request.address.strip()
    if not address:
        raise HTTPException(status_code=400, detail="Address is required")

    # Check disk cache
    cache_key = hashlib.sha256(address.lower().encode()).hexdigest()
    cache_path = _GEOCODE_CACHE / f"{cache_key}.json"
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            return GeocodeResponse(**data)
        except Exception:
            pass  # Cache corrupt, re-fetch

    # Query Nominatim
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                _NOMINATIM_URL,
                params={"q": address, "format": "json", "limit": 1},
                headers={"User-Agent": _USER_AGENT},
                timeout=10.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"Nominatim request failed: {e}")
            raise HTTPException(status_code=502, detail="Geocoding service unavailable")

    results = resp.json()
    if not results:
        raise HTTPException(status_code=404, detail="Address not found")

    hit = results[0]
    result = {
        "lat": float(hit["lat"]),
        "lng": float(hit["lon"]),
        "display_name": hit.get("display_name", address),
        "bbox": [float(x) for x in hit.get("boundingbox", [])],
    }

    # Write cache
    _GEOCODE_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_text(json.dumps(result))
    except Exception:
        pass

    return GeocodeResponse(**result)


# ---------------------------------------------------------------------------
# Satellite tile proxy
# ---------------------------------------------------------------------------

@router.get("/tile/{z}/{x}/{y}")
async def get_tile(z: int, x: int, y: int):
    """Proxy ESRI World Imagery satellite tiles.

    Tiles are cached on disk in ~/.cache/tritium-sc/tiles/{z}/{x}/{y}.jpg.
    Returns JPEG with long cache headers.
    """
    if z < 0 or z > 22:
        raise HTTPException(status_code=400, detail="Zoom level must be 0-22")

    # Check disk cache
    cache_path = _TILE_CACHE / str(z) / str(x) / f"{y}.jpg"
    if cache_path.exists():
        return Response(
            content=cache_path.read_bytes(),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=604800"},  # 7 days
        )

    # Fetch from ESRI
    url = _ESRI_TILE_URL.format(z=z, y=y, x=x)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=15.0)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"Tile fetch failed: {z}/{x}/{y}: {e}")
            raise HTTPException(status_code=502, detail="Tile service unavailable")

    tile_data = resp.content

    # Write cache
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_bytes(tile_data)
    except Exception:
        pass

    return Response(
        content=tile_data,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800"},
    )


# ---------------------------------------------------------------------------
# Terrain tile proxy (Mapzen Terrarium DEM from AWS Public Dataset)
# ---------------------------------------------------------------------------

_TERRAIN_TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
_TERRAIN_CACHE = _CACHE_DIR / "tiles" / "terrain"


@router.get("/terrain-tile/{z}/{x}/{y}.png")
async def get_terrain_tile(z: int, x: int, y: int):
    """Proxy Mapzen Terrarium terrain tiles (DEM) from AWS Public Dataset.

    Terrarium encoding: elevation = (red * 256 + green + blue / 256) - 32768
    Tiles are cached on disk at tiles/terrain/{z}/{x}/{y}.png.
    No API key required (AWS Public Dataset).
    """
    if z < 0 or z > 15:
        raise HTTPException(status_code=400, detail="Terrain tile zoom must be 0-15")

    cache_path = _TERRAIN_CACHE / str(z) / str(x) / f"{y}.png"
    if cache_path.exists():
        return Response(
            content=cache_path.read_bytes(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=2592000"},  # 30 days
        )

    url = _TERRAIN_TILE_URL.format(z=z, y=y, x=x)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=15.0)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"Terrain tile fetch failed: {z}/{x}/{y}: {e}")
            raise HTTPException(status_code=502, detail="Terrain tile service unavailable")

    tile_data = resp.content

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_bytes(tile_data)
    except Exception:
        pass

    return Response(
        content=tile_data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=2592000"},
    )


# ---------------------------------------------------------------------------
# Road tile proxy (transparent overlay)
# ---------------------------------------------------------------------------

_ROAD_TILE_CACHE = _CACHE_DIR / "tiles" / "road"


@router.get("/road-tile/{z}/{x}/{y}")
async def get_road_tile(z: int, x: int, y: int):
    """Proxy ESRI World Transportation road tiles (transparent PNG overlay).

    These tiles contain only road lines on a transparent background,
    designed to be composited on top of satellite imagery.
    Cached on disk at tiles/road/{z}/{x}/{y}.png.
    """
    if z < 0 or z > 22:
        raise HTTPException(status_code=400, detail="Zoom level must be 0-22")

    cache_path = _ROAD_TILE_CACHE / str(z) / str(x) / f"{y}.png"
    if cache_path.exists():
        return Response(
            content=cache_path.read_bytes(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=604800"},
        )

    url = _ESRI_ROAD_URL.format(z=z, y=y, x=x)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=15.0)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"Road tile fetch failed: {z}/{x}/{y}: {e}")
            raise HTTPException(status_code=502, detail="Road tile service unavailable")

    tile_data = resp.content

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_bytes(tile_data)
    except Exception:
        pass

    return Response(
        content=tile_data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800"},
    )


# ---------------------------------------------------------------------------
# Building footprints
# ---------------------------------------------------------------------------

@router.get("/buildings", response_model=list[BuildingPolygon])
async def get_buildings(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius: float = Query(200.0, description="Search radius in meters", ge=10, le=1000),
):
    """Fetch building footprints from OpenStreetMap Overpass API.

    Returns building polygons within `radius` meters of the center point.
    Results are cached on disk.
    """
    # Check disk cache
    cache_key = f"{lat:.6f}_{lng:.6f}_{radius:.0f}"
    cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
    cache_path = _BUILDINGS_CACHE / f"{cache_hash}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            pass

    # Query Overpass
    query = f'[out:json];way["building"](around:{radius},{lat},{lng});out geom;'
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                _OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": _USER_AGENT},
                timeout=30.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"Overpass request failed: {e}")
            raise HTTPException(status_code=502, detail="Building data service unavailable")

    data = resp.json()
    elements = data.get("elements", [])

    buildings = []
    for el in elements:
        if el.get("type") != "way":
            continue
        geometry = el.get("geometry", [])
        if not geometry:
            continue

        polygon = [[pt["lat"], pt["lon"]] for pt in geometry]
        tags = el.get("tags", {})

        buildings.append({
            "id": el["id"],
            "polygon": polygon,
            "tags": tags,
        })

    # Write cache
    _BUILDINGS_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_text(json.dumps(buildings))
    except Exception:
        pass

    return buildings


# ---------------------------------------------------------------------------
# Microsoft Building Footprints (satellite-aligned, from ESRI vector tiles)
# ---------------------------------------------------------------------------

_MSFT_VT_URL = (
    "https://tiles.arcgis.com/tiles/P3ePLMYs2RVChkJx/arcgis/rest/services/"
    "Microsoft_Building_Footprints/VectorTileServer/tile/{z}/{y}/{x}.pbf"
)
_MSFT_CACHE = _CACHE_DIR / "msft_buildings"


def _tile_to_latlng(
    tx: int, ty: int, zoom: int, px: float, py: float, extent: int = 4096
) -> tuple[float, float]:
    """Convert tile-local pixel coords to lat/lng."""
    import math

    n = 2**zoom
    lng = (tx + px / extent) / n * 360 - 180
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * (ty + py / extent) / n)))
    lat = math.degrees(lat_rad)
    return lat, lng


@router.get("/msft-buildings")
async def get_msft_buildings(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius: float = Query(300.0, description="Search radius in meters", ge=50, le=1000),
):
    """Fetch Microsoft Building Footprints from ESRI-hosted PBF vector tiles.

    These footprints are ML-derived from satellite imagery and align much
    better with ESRI World Imagery tiles than OSM building data.

    Returns building polygons as [[lat, lng], ...] with an integer ID.
    """
    import math

    try:
        import mapbox_vector_tile
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="mapbox-vector-tile package not installed (pip install mapbox-vector-tile)",
        )

    # Use zoom 16 for good coverage (~600m per tile at mid-latitudes)
    zoom = 16
    n = 2**zoom
    lat_rad = math.radians(lat)

    center_tx = int((lng + 180) / 360 * n)
    center_ty = int(
        (1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n
    )

    # Determine how many tiles we need to cover the radius
    tile_size_m = 40075016.686 * math.cos(lat_rad) / n
    tiles_needed = math.ceil(radius / tile_size_m) + 1

    all_buildings: list[dict] = []
    bid = 0

    async with httpx.AsyncClient() as client:
        for dx in range(-tiles_needed, tiles_needed + 1):
            for dy in range(-tiles_needed, tiles_needed + 1):
                tx = center_tx + dx
                ty = center_ty + dy
                if ty < 0 or ty >= n:
                    continue

                # Check disk cache
                cache_path = _MSFT_CACHE / f"{zoom}_{tx}_{ty}.json"
                if cache_path.exists():
                    try:
                        cached = json.loads(cache_path.read_text())
                        all_buildings.extend(cached)
                        continue
                    except Exception:
                        pass

                # Fetch PBF tile
                url = _MSFT_VT_URL.format(z=zoom, y=ty, x=tx)
                try:
                    resp = await client.get(url, timeout=10.0)
                    if resp.status_code != 200:
                        continue
                except httpx.HTTPError:
                    continue

                # Decode PBF
                try:
                    tile = mapbox_vector_tile.decode(resp.content)
                except Exception as e:
                    logger.warning(f"PBF decode failed for {zoom}/{ty}/{tx}: {e}")
                    continue

                tile_buildings = []
                for layer_name, layer in tile.items():
                    for feature in layer.get("features", []):
                        geom = feature.get("geometry", {})
                        if geom.get("type") != "Polygon":
                            continue
                        rings = geom.get("coordinates", [])
                        if not rings or len(rings[0]) < 3:
                            continue

                        # Convert tile-local pixels to lat/lng
                        polygon = []
                        for px, py in rings[0]:
                            flat, flng = _tile_to_latlng(tx, ty, zoom, px, py)
                            polygon.append([flat, flng])

                        # Filter by radius
                        centroid_lat = sum(p[0] for p in polygon) / len(polygon)
                        centroid_lng = sum(p[1] for p in polygon) / len(polygon)
                        dy_m = (centroid_lat - lat) * 111320.0
                        dx_m = (centroid_lng - lng) * 111320.0 * math.cos(lat_rad)
                        dist = math.sqrt(dx_m**2 + dy_m**2)
                        if dist > radius:
                            continue

                        bid += 1
                        tile_buildings.append(
                            {"id": bid, "polygon": polygon, "tags": {}}
                        )

                # Cache this tile's buildings
                _MSFT_CACHE.mkdir(parents=True, exist_ok=True)
                try:
                    cache_path.write_text(json.dumps(tile_buildings))
                except Exception:
                    pass

                all_buildings.extend(tile_buildings)

    logger.info(
        f"Microsoft buildings: {len(all_buildings)} footprints at ({lat:.5f}, {lng:.5f})"
    )
    return all_buildings


# ---------------------------------------------------------------------------
# Overlay: pre-loaded road polylines + building polygons for 3D renderer
# ---------------------------------------------------------------------------

@router.get("/overlay")
async def get_overlay(request: Request):
    """Return pre-loaded road polylines and building polygons.

    This data is loaded at startup from the street graph and building
    obstacles (Overpass API). The frontend uses it to render 3D roads
    and extruded buildings on the Three.js map.

    Returns:
        {"roads": [...], "buildings": [...]}
    """
    roads = getattr(request.app.state, "road_polylines", None) or []
    buildings = getattr(request.app.state, "building_dicts", None) or []
    return {"roads": roads, "buildings": buildings}


# ---------------------------------------------------------------------------
# Layout position corrections — save/load corrected unit/sensor positions
# ---------------------------------------------------------------------------

_CORRECTIONS_FILE = _CACHE_DIR / "position_corrections.json"


class PositionCorrection(BaseModel):
    """A position correction for a unit or sensor."""
    unit_id: str
    x: float
    y: float
    label: Optional[str] = None


class PositionCorrectionsPayload(BaseModel):
    """Payload for saving position corrections."""
    corrections: list[PositionCorrection]


@router.get("/layout/corrections")
async def get_layout_corrections():
    """Load saved position corrections.

    Returns a list of corrections, each with unit_id, x, y, and optional label.
    Used by the frontend to restore manually-repositioned units/sensors.
    """
    if _CORRECTIONS_FILE.exists():
        try:
            data = json.loads(_CORRECTIONS_FILE.read_text())
            return {"corrections": data}
        except Exception:
            return {"corrections": []}
    return {"corrections": []}


@router.post("/layout/corrections")
async def save_layout_corrections(payload: PositionCorrectionsPayload):
    """Save position corrections to disk.

    Overwrites the entire corrections file with the provided list.
    The frontend sends all current corrections when the user saves.
    """
    _CORRECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = [c.model_dump() for c in payload.corrections]
    _CORRECTIONS_FILE.write_text(json.dumps(data, indent=2))
    logger.info(f"Saved {len(data)} position corrections")
    return {"saved": len(data)}


# ---------------------------------------------------------------------------
# GIS Infrastructure Layers (Overpass API)
# ---------------------------------------------------------------------------

# Meters per story for estimating building height from levels
_METERS_PER_LEVEL = 3.0

# Layer catalog: metadata for all available GIS data layers
_LAYER_CATALOG = [
    {
        "id": "power-lines",
        "name": "Power Lines",
        "type": "line",
        "color": "#fcee0a",
        "endpoint": "/api/geo/layers/power",
    },
    {
        "id": "traffic-signals",
        "name": "Traffic Signals",
        "type": "point",
        "color": "#ff2a6d",
        "endpoint": "/api/geo/layers/traffic",
    },
    {
        "id": "waterways",
        "name": "Waterways",
        "type": "line",
        "color": "#0066ff",
        "endpoint": "/api/geo/layers/water",
    },
    {
        "id": "water-towers",
        "name": "Water Towers",
        "type": "point",
        "color": "#0088ff",
        "endpoint": "/api/geo/layers/water",
    },
    {
        "id": "telecom-lines",
        "name": "Telecom Lines",
        "type": "line",
        "color": "#ff8800",
        "endpoint": "/api/geo/layers/cable",
    },
    {
        "id": "building-heights",
        "name": "Building Heights",
        "type": "polygon",
        "color": "#00f0ff",
        "endpoint": "/api/geo/layers/building-heights",
    },
]


def _overpass_to_geojson(
    elements: list[dict],
    *,
    as_polygon: bool = False,
) -> dict:
    """Convert Overpass API elements to a GeoJSON FeatureCollection.

    Args:
        elements: List of Overpass elements (nodes and ways).
        as_polygon: If True, closed ways become Polygon; otherwise LineString.

    Returns:
        A GeoJSON FeatureCollection dict.
    """
    features = []
    for el in elements:
        el_type = el.get("type")
        tags = el.get("tags", {})

        if el_type == "node":
            lat = el.get("lat")
            lon = el.get("lon")
            if lat is None or lon is None:
                continue
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "properties": tags,
            })

        elif el_type == "way":
            geometry = el.get("geometry")
            if not geometry or len(geometry) < 2:
                continue

            coords = [[pt["lon"], pt["lat"]] for pt in geometry]

            if as_polygon:
                # Ensure ring is closed
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [coords],
                    },
                    "properties": tags,
                })
            else:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords,
                    },
                    "properties": tags,
                })

    return {"type": "FeatureCollection", "features": features}


async def _fetch_overpass_geojson(
    query: str,
    cache_key: str,
    *,
    as_polygon: bool = False,
) -> dict:
    """Execute an Overpass query and return GeoJSON, with disk caching.

    Args:
        query: Overpass QL query string.
        cache_key: Unique key for disk cache.
        as_polygon: Pass through to _overpass_to_geojson.

    Returns:
        GeoJSON FeatureCollection dict.

    Raises:
        HTTPException: On Overpass API failure (502).
    """
    cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
    cache_path = _GIS_CACHE / f"{cache_hash}.json"

    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            pass

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                _OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": _USER_AGENT},
                timeout=30.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"Overpass GIS query failed: {e}")
            raise HTTPException(status_code=502, detail="GIS data service unavailable")

    data = resp.json()
    elements = data.get("elements", [])
    geojson = _overpass_to_geojson(elements, as_polygon=as_polygon)

    _GIS_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_text(json.dumps(geojson))
    except Exception:
        pass

    return geojson


@router.get("/layers/catalog")
async def get_layer_catalog():
    """Return the catalog of available GIS data layers.

    Each entry contains:
      - id: unique layer identifier
      - name: human-readable layer name
      - type: geometry type (point, line, polygon)
      - color: hex color for rendering
      - endpoint: API endpoint to fetch GeoJSON data
    """
    return _LAYER_CATALOG


@router.get("/layers/power")
async def get_power_lines(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius: float = Query(500.0, description="Search radius in meters", ge=50, le=2000),
):
    """Fetch power lines and towers from OpenStreetMap.

    Returns a GeoJSON FeatureCollection with:
      - LineString features for power lines
      - Point features for power towers/poles
    """
    query = (
        f'[out:json];'
        f'('
        f'  way["power"="line"](around:{radius},{lat},{lng});'
        f'  way["power"="minor_line"](around:{radius},{lat},{lng});'
        f'  node["power"="tower"](around:{radius},{lat},{lng});'
        f'  node["power"="pole"](around:{radius},{lat},{lng});'
        f');'
        f'out geom;'
    )
    cache_key = f"power_{lat:.6f}_{lng:.6f}_{radius:.0f}"
    return await _fetch_overpass_geojson(query, cache_key)


@router.get("/layers/traffic")
async def get_traffic_signals(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius: float = Query(500.0, description="Search radius in meters", ge=50, le=2000),
):
    """Fetch traffic signals and stop signs from OpenStreetMap.

    Returns a GeoJSON FeatureCollection with Point features.
    """
    query = (
        f'[out:json];'
        f'('
        f'  node["highway"="traffic_signals"](around:{radius},{lat},{lng});'
        f'  node["highway"="stop"](around:{radius},{lat},{lng});'
        f'  node["highway"="crossing"](around:{radius},{lat},{lng});'
        f');'
        f'out;'
    )
    cache_key = f"traffic_{lat:.6f}_{lng:.6f}_{radius:.0f}"
    return await _fetch_overpass_geojson(query, cache_key)


@router.get("/layers/water")
async def get_water_infrastructure(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius: float = Query(500.0, description="Search radius in meters", ge=50, le=2000),
):
    """Fetch water infrastructure from OpenStreetMap.

    Returns a GeoJSON FeatureCollection with:
      - LineString features for waterways (streams, rivers, canals)
      - Point features for water towers
    """
    query = (
        f'[out:json];'
        f'('
        f'  way["waterway"](around:{radius},{lat},{lng});'
        f'  node["man_made"="water_tower"](around:{radius},{lat},{lng});'
        f'  way["man_made"="pipeline"]["substance"="water"](around:{radius},{lat},{lng});'
        f');'
        f'out geom;'
    )
    cache_key = f"water_{lat:.6f}_{lng:.6f}_{radius:.0f}"
    return await _fetch_overpass_geojson(query, cache_key)


@router.get("/layers/cable")
async def get_cable_lines(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius: float = Query(500.0, description="Search radius in meters", ge=50, le=2000),
):
    """Fetch telecom and utility cable lines from OpenStreetMap.

    Returns a GeoJSON FeatureCollection with LineString features.
    """
    query = (
        f'[out:json];'
        f'('
        f'  way["utility"](around:{radius},{lat},{lng});'
        f'  way["communication"="line"](around:{radius},{lat},{lng});'
        f'  way["telecom"="line"](around:{radius},{lat},{lng});'
        f');'
        f'out geom;'
    )
    cache_key = f"cable_{lat:.6f}_{lng:.6f}_{radius:.0f}"
    return await _fetch_overpass_geojson(query, cache_key)


@router.get("/layers/building-heights")
async def get_building_heights(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius: float = Query(500.0, description="Search radius in meters", ge=50, le=2000),
):
    """Fetch buildings with height data from OpenStreetMap.

    Returns a GeoJSON FeatureCollection with Polygon features.
    Each feature has `height` and `levels` in its properties.
    Height is derived from `building:height` tag or estimated from
    `building:levels` * 3m.
    """
    query = (
        f'[out:json];'
        f'('
        f'  way["building"]["building:height"](around:{radius},{lat},{lng});'
        f'  way["building"]["building:levels"](around:{radius},{lat},{lng});'
        f');'
        f'out geom;'
    )
    cache_key = f"bldg_heights_{lat:.6f}_{lng:.6f}_{radius:.0f}"
    geojson = await _fetch_overpass_geojson(query, cache_key, as_polygon=True)

    # Enrich features with numeric height/levels
    for feat in geojson.get("features", []):
        props = feat.get("properties", {})
        height = None
        levels = None

        # Parse height
        raw_height = props.get("building:height", "")
        if raw_height:
            try:
                height = float(str(raw_height).replace("m", "").strip())
            except (ValueError, TypeError):
                pass

        # Parse levels
        raw_levels = props.get("building:levels", "")
        if raw_levels:
            try:
                levels = int(str(raw_levels).strip())
            except (ValueError, TypeError):
                pass

        # Estimate height from levels if no explicit height
        if height is None and levels is not None:
            height = levels * _METERS_PER_LEVEL

        props["height"] = height or 0.0
        props["levels"] = levels or 0

    return geojson


# ---------------------------------------------------------------------------
# GIS Interoperability Protocol Endpoints
# ---------------------------------------------------------------------------

class KMLImportRequest(BaseModel):
    """Import KML text to GeoJSON."""
    kml: str


class KMLExportRequest(BaseModel):
    """Export GeoJSON to KML text."""
    geojson: dict


class WMSValidateRequest(BaseModel):
    """Validate a WMS/WMTS URL template."""
    url: str


@router.post("/import/kml")
async def import_kml(body: KMLImportRequest):
    """Parse KML XML text and return a GeoJSON FeatureCollection.

    Supports Point, LineString, and Polygon Placemarks.
    Useful for importing TAK markers, Google Earth overlays, etc.
    """
    from engine.tactical.geo_protocols import kml_to_geojson

    if not body.kml.strip():
        raise HTTPException(status_code=400, detail="KML text is required")

    try:
        return kml_to_geojson(body.kml)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid KML: {e}")


@router.post("/export/kml")
async def export_kml(body: KMLExportRequest):
    """Convert a GeoJSON FeatureCollection to KML XML string.

    Supports Point, LineString, and Polygon features.
    Useful for exporting to TAK, Google Earth, etc.
    """
    from engine.tactical.geo_protocols import geojson_to_kml

    try:
        kml_text = geojson_to_kml(body.geojson)
        return {"kml": kml_text}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"KML export failed: {e}")


@router.get("/convert/mgrs")
async def convert_mgrs(
    lat: Optional[float] = Query(None, description="Latitude (for lat/lng -> MGRS)"),
    lng: Optional[float] = Query(None, description="Longitude (for lat/lng -> MGRS)"),
    mgrs: Optional[str] = Query(None, description="MGRS string (for MGRS -> lat/lng)"),
    precision: int = Query(5, description="MGRS precision (1-5)", ge=1, le=5),
):
    """Convert between lat/lng and MGRS coordinates.

    Provide either:
      - lat + lng: returns MGRS string
      - mgrs: returns lat/lng

    MGRS (Military Grid Reference System) is used by TAK, NATO, and
    military operations worldwide.
    """
    from engine.tactical.geo_protocols import latlng_to_mgrs, mgrs_to_latlng

    if mgrs is not None:
        try:
            lat_out, lng_out = mgrs_to_latlng(mgrs)
            return {"lat": lat_out, "lng": lng_out, "mgrs": mgrs}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if lat is not None and lng is not None:
        try:
            mgrs_str = latlng_to_mgrs(lat, lng, precision=precision)
            return {"lat": lat, "lng": lng, "mgrs": mgrs_str}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    raise HTTPException(
        status_code=400,
        detail="Provide either lat+lng or mgrs parameter",
    )


@router.get("/convert/utm")
async def convert_utm(
    lat: Optional[float] = Query(None, description="Latitude (for lat/lng -> UTM)"),
    lng: Optional[float] = Query(None, description="Longitude (for lat/lng -> UTM)"),
    zone: Optional[int] = Query(None, description="UTM zone (for UTM -> lat/lng)"),
    easting: Optional[float] = Query(None, description="UTM easting"),
    northing: Optional[float] = Query(None, description="UTM northing"),
    band: Optional[str] = Query(None, description="UTM band letter"),
):
    """Convert between lat/lng and UTM coordinates.

    Provide either:
      - lat + lng: returns UTM zone, easting, northing, band
      - zone + easting + northing + band: returns lat/lng
    """
    from engine.tactical.geo_protocols import latlng_to_utm, utm_to_latlng

    if zone is not None and easting is not None and northing is not None and band is not None:
        try:
            lat_out, lng_out = utm_to_latlng(zone, easting, northing, band)
            return {
                "lat": lat_out,
                "lng": lng_out,
                "zone": zone,
                "easting": easting,
                "northing": northing,
                "band": band,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if lat is not None and lng is not None:
        try:
            z, e, n, b = latlng_to_utm(lat, lng)
            return {
                "lat": lat,
                "lng": lng,
                "zone": z,
                "easting": e,
                "northing": n,
                "band": b,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    raise HTTPException(
        status_code=400,
        detail="Provide either lat+lng or zone+easting+northing+band parameters",
    )


@router.post("/validate-wms")
async def validate_wms(body: WMSValidateRequest):
    """Validate a WMS/WMTS/TMS tile URL template.

    Returns validation result with detected service type.
    Useful for the frontend to verify user-configured tile sources
    before adding them to the map.
    """
    from engine.tactical.geo_protocols import validate_wms_url

    if not body.url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    return validate_wms_url(body.url)


# ---------------------------------------------------------------------------
# POI (Points of Interest) from OpenStreetMap
# ---------------------------------------------------------------------------

@router.get("/pois")
async def get_pois(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius: float = Query(400.0, description="Search radius in meters", ge=50, le=2000),
):
    """Fetch POIs (amenities, shops, landmarks, buildings) from OpenStreetMap.

    Returns list of POI dicts with name, type, category, address, lat/lng, local coords.
    Results cached on disk by the underlying fetch_pois function.
    """
    from engine.simulation.poi_data import fetch_pois

    pois = fetch_pois(lat, lng, radius)
    return [
        {
            "name": p.name,
            "poi_type": p.poi_type,
            "category": p.category,
            "address": p.address,
            "lat": p.lat,
            "lng": p.lng,
            "local_x": p.local_x,
            "local_y": p.local_y,
            "osm_id": p.osm_id,
        }
        for p in pois
    ]
