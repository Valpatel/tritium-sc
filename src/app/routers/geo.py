# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
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
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
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

_CACHE_TTL_S = 86400  # 24 hours for non-tile caches

_USER_AGENT = "TRITIUM-SC/0.1.0"


def _cache_fresh(path: Path) -> bool:
    """Return True if cache file exists and is younger than _CACHE_TTL_S."""
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    if age > _CACHE_TTL_S:
        logger.info(f"Cache expired ({age:.0f}s old): {path.name}")
        return False
    return True
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
    if _cache_fresh(cache_path):
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
# Elevation grid — decoded terrain heightmap for 3D rendering
# ---------------------------------------------------------------------------

@router.get("/elevation-grid")
async def get_elevation_grid(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius: float = Query(300.0, description="Radius in meters", ge=50, le=2000),
    resolution: int = Query(64, description="Grid resolution (NxN)", ge=16, le=256),
):
    """Return a decoded elevation height grid for 3D terrain rendering.

    Fetches Terrarium-encoded terrain tiles, decodes RGB to meters,
    and returns a flat height array (row-major, south-to-north) plus
    metadata for mesh generation.

    Terrarium encoding: elevation = (red * 256 + green + blue / 256) - 32768
    """
    import math
    import struct

    # Check cache
    cache_key = f"elev_{lat:.5f}_{lng:.5f}_{radius:.0f}_{resolution}"
    cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
    cache_path = _GIS_CACHE / f"{cache_hash}.json"
    if _cache_fresh(cache_path):
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            pass

    # Calculate tile coordinates
    lat_rad = math.radians(lat)
    meters_per_deg_lat = 111320.0
    meters_per_deg_lng = 111320.0 * math.cos(lat_rad)

    dlat = radius / meters_per_deg_lat
    dlng = radius / meters_per_deg_lng

    min_lat, max_lat = lat - dlat, lat + dlat
    min_lng, max_lng = lng - dlng, lng + dlng

    # Use zoom 13 for ~19m/pixel (good for 300m radius)
    zoom = 13
    if radius > 500:
        zoom = 12
    if radius > 1000:
        zoom = 11

    n = 2 ** zoom

    def latlng_to_tile(lt, ln):
        tx = int((ln + 180) / 360 * n)
        ty = int((1 - math.log(math.tan(math.radians(lt)) + 1 / math.cos(math.radians(lt))) / math.pi) / 2 * n)
        return tx, ty

    def tile_to_latlng(tx, ty):
        ln = tx / n * 360 - 180
        lt = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
        return lt, ln

    # Get corner tiles
    tx0, ty0 = latlng_to_tile(max_lat, min_lng)  # NW corner
    tx1, ty1 = latlng_to_tile(min_lat, max_lng)  # SE corner

    # Fetch and decode tiles
    try:
        from PIL import Image
        import io
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Pillow (PIL) not installed for elevation decoding",
        )

    heights_raw = {}  # (px_global, py_global) -> height_m

    async with httpx.AsyncClient() as client:
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                # Try cache first
                tile_cache = _TERRAIN_CACHE / str(zoom) / str(tx) / f"{ty}.png"
                if tile_cache.exists():
                    tile_data = tile_cache.read_bytes()
                else:
                    url = _TERRAIN_TILE_URL.format(z=zoom, y=ty, x=tx)
                    try:
                        resp = await client.get(url, timeout=15.0)
                        resp.raise_for_status()
                        tile_data = resp.content
                        tile_cache.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            tile_cache.write_bytes(tile_data)
                        except Exception:
                            pass
                    except Exception:
                        continue

                # Decode tile
                try:
                    img = Image.open(io.BytesIO(tile_data))
                    pixels = img.load()
                    w, h = img.size
                    for py_local in range(0, h, max(1, h // 32)):
                        for px_local in range(0, w, max(1, w // 32)):
                            r, g, b = pixels[px_local, py_local][:3]
                            elev = (r * 256 + g + b / 256) - 32768
                            # Convert tile pixel to lat/lng
                            px_frac = px_local / w
                            py_frac = py_local / h
                            pt_lat, pt_lng = tile_to_latlng(tx + px_frac, ty + py_frac)
                            # Convert to local meters
                            lx = (pt_lng - lng) * meters_per_deg_lng
                            ly = (pt_lat - lat) * meters_per_deg_lat
                            if abs(lx) <= radius and abs(ly) <= radius:
                                heights_raw[(round(lx, 1), round(ly, 1))] = elev
                except Exception:
                    continue

    if not heights_raw:
        return {"grid": [], "resolution": 0, "radius": radius, "min_elev": 0, "max_elev": 0}

    # Resample to regular grid
    step = (radius * 2) / resolution
    grid = []
    min_elev = float('inf')
    max_elev = float('-inf')

    for iy in range(resolution):
        for ix in range(resolution):
            x = -radius + ix * step
            y = -radius + iy * step

            # Find nearest raw height
            best_dist = float('inf')
            best_h = 0
            for (rx, ry), rh in heights_raw.items():
                d = (rx - x) ** 2 + (ry - y) ** 2
                if d < best_dist:
                    best_dist = d
                    best_h = rh
            grid.append(round(best_h, 1))
            min_elev = min(min_elev, best_h)
            max_elev = max(max_elev, best_h)

    result = {
        "grid": grid,
        "resolution": resolution,
        "radius": radius,
        "min_elev": round(min_elev, 1),
        "max_elev": round(max_elev, 1),
        "center": {"lat": lat, "lng": lng},
    }

    # Cache
    _GIS_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_text(json.dumps(result))
    except Exception:
        pass

    logger.info(
        f"Elevation grid: {resolution}x{resolution}, "
        f"range {min_elev:.1f}-{max_elev:.1f}m at ({lat:.5f}, {lng:.5f})"
    )
    return result


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
    if _cache_fresh(cache_path):
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
                if _cache_fresh(cache_path):
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
# City data — comprehensive OSM features for 3D city rendering
# ---------------------------------------------------------------------------

# Default heights by building type (from arnis study + OSM wiki)
_BUILDING_TYPE_HEIGHTS: dict[str, float] = {
    "apartments": 15.0,
    "residential": 8.0,
    "house": 7.0,
    "detached": 7.0,
    "terrace": 8.0,
    "commercial": 12.0,
    "retail": 5.0,
    "industrial": 8.0,
    "warehouse": 7.0,
    "office": 18.0,
    "hotel": 20.0,
    "hospital": 15.0,
    "school": 10.0,
    "university": 12.0,
    "church": 15.0,
    "cathedral": 25.0,
    "mosque": 12.0,
    "synagogue": 10.0,
    "public": 10.0,
    "civic": 12.0,
    "government": 15.0,
    "garage": 3.0,
    "garages": 3.0,
    "parking": 9.0,
    "shed": 3.0,
    "roof": 4.0,
    "hut": 3.0,
    "cabin": 4.0,
    "farm": 6.0,
    "barn": 7.0,
    "service": 4.0,
    "kiosk": 3.0,
    "supermarket": 6.0,
    "train_station": 10.0,
    "prison": 10.0,
    "temple": 12.0,
    "shrine": 6.0,
    "chapel": 10.0,
    "dormitory": 12.0,
    "semidetached_house": 8.0,
    "manufacture": 8.0,
    "kindergarten": 6.0,
    "fire_station": 10.0,
    "yes": 8.0,
}

# Road width by highway type (meters, from arnis study + OSM wiki)
_ROAD_WIDTHS: dict[str, float] = {
    "motorway": 14.0,
    "trunk": 12.0,
    "primary": 10.0,
    "secondary": 8.0,
    "tertiary": 7.0,
    "residential": 6.0,
    "service": 4.0,
    "unclassified": 6.0,
    "living_street": 5.0,
    "pedestrian": 4.0,
    "footway": 2.0,
    "cycleway": 2.0,
    "path": 1.5,
    "track": 3.0,
    "motorway_link": 6.0,
    "trunk_link": 5.0,
    "primary_link": 5.0,
    "secondary_link": 4.5,
    "tertiary_link": 4.0,
}

# Building category for material selection
_BUILDING_CATEGORIES: dict[str, str] = {
    "apartments": "residential",
    "residential": "residential",
    "house": "residential",
    "detached": "residential",
    "terrace": "residential",
    "semidetached_house": "residential",
    "dormitory": "residential",
    "farm": "residential",
    "cabin": "residential",
    "hut": "residential",
    "commercial": "commercial",
    "retail": "commercial",
    "supermarket": "commercial",
    "kiosk": "commercial",
    "office": "commercial",
    "hotel": "commercial",
    "industrial": "industrial",
    "warehouse": "industrial",
    "manufacture": "industrial",
    "hospital": "civic",
    "school": "civic",
    "university": "civic",
    "kindergarten": "civic",
    "public": "civic",
    "civic": "civic",
    "government": "civic",
    "fire_station": "civic",
    "train_station": "civic",
    "prison": "civic",
    "church": "religious",
    "cathedral": "religious",
    "chapel": "religious",
    "mosque": "religious",
    "synagogue": "religious",
    "temple": "religious",
    "shrine": "religious",
    "garage": "utility",
    "garages": "utility",
    "parking": "utility",
    "shed": "utility",
    "roof": "utility",
    "service": "utility",
}


def _estimate_building_height(tags: dict) -> float:
    """Estimate building height from OSM tags."""
    # Explicit height tag (meters)
    height_str = tags.get("height")
    if height_str:
        try:
            return float(height_str.replace("m", "").strip())
        except (ValueError, TypeError):
            pass

    # building:levels tag
    levels_str = tags.get("building:levels")
    if levels_str:
        try:
            return float(levels_str) * 3.0 + 1.0  # 3m per floor + roof
        except (ValueError, TypeError):
            pass

    # Fallback by building type
    btype = tags.get("building", "yes").lower()
    return _BUILDING_TYPE_HEIGHTS.get(btype, 8.0)


def _classify_building(tags: dict) -> str:
    """Classify building into category for material selection."""
    btype = tags.get("building", "yes").lower()
    return _BUILDING_CATEGORIES.get(btype, "residential")


@router.get("/city-data")
async def get_city_data(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius: float = Query(300.0, description="Search radius in meters", ge=50, le=2000),
):
    """Fetch comprehensive city data from OSM for 3D rendering.

    Returns buildings with types/heights, roads with widths, trees,
    land use polygons, and barriers — everything needed to render
    a realistic 3D city.

    All coordinates are returned as local meters relative to (lat, lng).
    """
    import math

    # Include schema version in cache key to auto-invalidate on schema changes
    _SCHEMA_VERSION = 2  # Bump when response shape changes
    cache_key = f"city_{lat:.6f}_{lng:.6f}_{radius:.0f}_v{_SCHEMA_VERSION}"
    cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
    cache_path = _GIS_CACHE / f"{cache_hash}.json"
    if _cache_fresh(cache_path):
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            pass

    # Single comprehensive Overpass query
    query = f"""[out:json][timeout:60];
(
  way["building"](around:{radius},{lat},{lng});
  way["highway"](around:{radius},{lat},{lng});
  way["landuse"](around:{radius},{lat},{lng});
  way["natural"="water"](around:{radius},{lat},{lng});
  way["leisure"="park"](around:{radius},{lat},{lng});
  way["leisure"="garden"](around:{radius},{lat},{lng});
  way["barrier"](around:{radius},{lat},{lng});
  way["waterway"](around:{radius},{lat},{lng});
  node["natural"="tree"](around:{radius},{lat},{lng});
  node["entrance"](around:{radius},{lat},{lng});
  node["door"](around:{radius},{lat},{lng});
  node["amenity"](around:{radius},{lat},{lng});
  node["amenity"="bench"](around:{radius},{lat},{lng});
  node["emergency"="fire_hydrant"](around:{radius},{lat},{lng});
  node["highway"="street_lamp"](around:{radius},{lat},{lng});
  node["amenity"="waste_basket"](around:{radius},{lat},{lng});
);
out geom;"""

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                _OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": _USER_AGENT},
                timeout=60.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"City data Overpass request failed: {e}")
            raise HTTPException(status_code=502, detail="OSM data service unavailable")

    data = resp.json()
    elements = data.get("elements", [])

    ref_lat_rad = math.radians(lat)
    meters_per_deg_lng = 111320.0 * math.cos(ref_lat_rad)

    def to_local(plat: float, plng: float) -> list[float]:
        x = (plng - lng) * meters_per_deg_lng
        y = (plat - lat) * 111320.0
        return [round(x, 2), round(y, 2)]

    buildings = []
    roads = []
    trees = []
    landuse = []
    barriers = []
    water = []
    entrances = []
    pois = []
    furniture = []

    for el in elements:
        tags = el.get("tags", {})
        el_type = el.get("type", "node")

        if el_type == "node":
            # Trees
            if tags.get("natural") == "tree":
                trees.append({
                    "pos": to_local(el["lat"], el["lon"]),
                    "species": tags.get("species", tags.get("genus", "")),
                    "height": float(tags["height"].replace("m", "")) if tags.get("height") else 6.0,
                    "leaf_type": tags.get("leaf_type", "broadleaved"),
                })
            # Entrances/doors
            elif tags.get("entrance") or tags.get("door"):
                entrances.append({
                    "pos": to_local(el["lat"], el["lon"]),
                    "type": tags.get("entrance", tags.get("door", "yes")),
                    "wheelchair": tags.get("wheelchair", ""),
                    "name": tags.get("name", ""),
                })
            # Street furniture
            elif tags.get("amenity") == "bench":
                furniture.append({
                    "pos": to_local(el["lat"], el["lon"]),
                    "type": "bench",
                })
            elif tags.get("emergency") == "fire_hydrant":
                furniture.append({
                    "pos": to_local(el["lat"], el["lon"]),
                    "type": "hydrant",
                })
            elif tags.get("highway") == "street_lamp":
                furniture.append({
                    "pos": to_local(el["lat"], el["lon"]),
                    "type": "lamp",
                })
            elif tags.get("amenity") == "waste_basket":
                furniture.append({
                    "pos": to_local(el["lat"], el["lon"]),
                    "type": "bin",
                })
            # Amenity POIs
            elif tags.get("amenity"):
                pois.append({
                    "pos": to_local(el["lat"], el["lon"]),
                    "type": tags.get("amenity"),
                    "name": tags.get("name", ""),
                    "cuisine": tags.get("cuisine", ""),
                })
            continue

        geometry = el.get("geometry", [])
        if not geometry or len(geometry) < 2:
            continue

        points = [to_local(pt["lat"], pt["lon"]) for pt in geometry]

        # Validate: skip if any coordinates are NaN/Inf
        if any(math.isnan(c) or math.isinf(c) for pt in points for c in pt):
            continue

        # Buildings (require >= 3 points for valid polygon)
        if "building" in tags and len(points) >= 3:
            buildings.append({
                "id": el["id"],
                "polygon": points,
                "height": round(_estimate_building_height(tags), 1),
                "type": tags.get("building", "yes"),
                "category": _classify_building(tags),
                "name": tags.get("name", ""),
                "levels": int(tags["building:levels"]) if tags.get("building:levels") else None,
                "roof_shape": tags.get("roof:shape", ""),
                "colour": tags.get("building:colour", tags.get("building:color", "")),
                "material": tags.get("building:material", ""),
                "address": tags.get("addr:housenumber", ""),
                "street": tags.get("addr:street", ""),
            })
            continue

        # Roads
        highway = tags.get("highway")
        if highway:
            lane_count = 2
            if tags.get("lanes"):
                try:
                    lane_count = int(tags["lanes"])
                except ValueError:
                    pass
            width = _ROAD_WIDTHS.get(highway, 6.0)
            if tags.get("width"):
                try:
                    width = float(tags["width"].replace("m", "").strip())
                except (ValueError, TypeError):
                    pass

            roads.append({
                "id": el["id"],
                "points": points,
                "class": highway,
                "name": tags.get("name", ""),
                "width": round(width, 1),
                "lanes": lane_count,
                "surface": tags.get("surface", "asphalt"),
                "oneway": tags.get("oneway") == "yes",
                "bridge": tags.get("bridge") == "yes",
                "tunnel": tags.get("tunnel") == "yes",
                "maxspeed": tags.get("maxspeed", ""),
            })
            continue

        # Land use
        landuse_val = tags.get("landuse")
        leisure_val = tags.get("leisure")
        if landuse_val or leisure_val:
            lu_type = landuse_val or leisure_val
            landuse.append({
                "id": el["id"],
                "polygon": points,
                "type": lu_type,
                "name": tags.get("name", ""),
            })
            continue

        # Barriers
        if "barrier" in tags:
            barrier_type = tags.get("barrier", "fence")
            barrier_height = 1.5
            if tags.get("height"):
                try:
                    barrier_height = float(tags["height"].replace("m", "").strip())
                except (ValueError, TypeError):
                    pass
            elif barrier_type == "wall":
                barrier_height = 2.5
            elif barrier_type == "hedge":
                barrier_height = 1.5
            elif barrier_type == "fence":
                barrier_height = 1.2

            barriers.append({
                "id": el["id"],
                "points": points,
                "type": barrier_type,
                "height": round(barrier_height, 1),
            })
            continue

        # Water
        if tags.get("natural") == "water" or tags.get("waterway"):
            water.append({
                "id": el["id"],
                "polygon": points if len(points) >= 3 else None,
                "points": points if len(points) < 3 else None,
                "type": tags.get("waterway", "water"),
                "name": tags.get("name", ""),
            })
            continue

    result = {
        "center": {"lat": lat, "lng": lng},
        "radius": radius,
        "schema_version": _SCHEMA_VERSION,
        "buildings": buildings,
        "roads": roads,
        "trees": trees,
        "landuse": landuse,
        "barriers": barriers,
        "water": water,
        "entrances": entrances,
        "pois": pois,
        "furniture": furniture,
        "stats": {
            "buildings": len(buildings),
            "roads": len(roads),
            "trees": len(trees),
            "landuse": len(landuse),
            "barriers": len(barriers),
            "water": len(water),
            "entrances": len(entrances),
            "pois": len(pois),
            "furniture": len(furniture),
        },
    }

    # Atomic cache write — temp file + rename prevents race condition corruption
    _GIS_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        tmp_path = cache_path.with_suffix('.tmp')
        tmp_path.write_text(json.dumps(result))
        tmp_path.rename(cache_path)
    except Exception:
        pass

    logger.info(
        f"City data: {len(buildings)} buildings, {len(roads)} roads, "
        f"{len(trees)} trees, {len(entrances)} entrances, {len(pois)} POIs, "
        f"{len(furniture)} furniture at ({lat:.5f}, {lng:.5f})"
    )
    return result


@router.get("/city-data/status")
async def get_city_data_status(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius: float = Query(300.0, description="Search radius in meters", ge=50, le=2000),
):
    """Return cache status and summary for a city-data query.

    Reports whether data is cached, how fresh it is, element counts,
    and schema version — without fetching from Overpass.
    """
    import time

    _SCHEMA_VERSION = 2
    cache_key = f"city_{lat:.6f}_{lng:.6f}_{radius:.0f}_v{_SCHEMA_VERSION}"
    cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
    cache_path = _GIS_CACHE / f"{cache_hash}.json"

    status: dict = {
        "cached": False,
        "schema_version": _SCHEMA_VERSION,
        "cache_key": cache_hash,
        "center": {"lat": lat, "lng": lng},
        "radius": radius,
    }

    if cache_path.exists():
        status["cached"] = True
        status["cache_age_s"] = round(time.time() - cache_path.stat().st_mtime, 1)
        try:
            data = json.loads(cache_path.read_text())
            status["stats"] = data.get("stats", {})
            status["schema_version"] = data.get("schema_version", 1)
        except Exception:
            status["cache_corrupt"] = True

    return status


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

    if _cache_fresh(cache_path):
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


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def cleanup_orphaned_tmp_files() -> int:
    """Remove orphaned .tmp files from the GIS cache directory.

    Called on server startup to clean up files left by interrupted
    atomic writes. Returns the number of files deleted.
    """
    deleted = 0
    if not _GIS_CACHE.exists():
        return deleted
    for tmp_file in _GIS_CACHE.glob("*.tmp"):
        try:
            tmp_file.unlink()
            deleted += 1
        except Exception:
            pass
    if deleted:
        logger.info(f"Cleaned up {deleted} orphaned .tmp files from GIS cache")
    return deleted


@router.get("/cache/stats")
async def get_cache_stats():
    """Return cache health statistics.

    Reports total files, total size, oldest file age, and count of
    expired entries across all geo cache directories.
    """
    total_files = 0
    total_size = 0
    oldest_age = 0.0
    expired_count = 0
    now = time.time()

    cache_dirs = [
        _GEOCODE_CACHE, _BUILDINGS_CACHE, _GIS_CACHE,
        _MSFT_CACHE, _TILE_CACHE,
    ]
    for cache_dir in cache_dirs:
        if not cache_dir.exists():
            continue
        for f in cache_dir.rglob("*"):
            if not f.is_file():
                continue
            total_files += 1
            total_size += f.stat().st_size
            age = now - f.stat().st_mtime
            if age > oldest_age:
                oldest_age = age
            # Tiles don't expire, but other caches do
            if cache_dir not in (_TILE_CACHE,) and age > _CACHE_TTL_S:
                expired_count += 1

    return {
        "total_files": total_files,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "oldest_file_age_hours": round(oldest_age / 3600, 1),
        "expired_count": expired_count,
    }


@router.post("/cache/clear")
async def clear_cache():
    """Delete all cached geo files.

    Removes all files from geocode, buildings, GIS, and Microsoft
    building cache directories. Tile caches are also cleared.
    Returns count and size of freed data.
    """
    files_deleted = 0
    bytes_freed = 0

    cache_dirs = [
        _GEOCODE_CACHE, _BUILDINGS_CACHE, _GIS_CACHE,
        _MSFT_CACHE, _TILE_CACHE,
    ]
    for cache_dir in cache_dirs:
        if not cache_dir.exists():
            continue
        for f in cache_dir.rglob("*"):
            if not f.is_file():
                continue
            try:
                size = f.stat().st_size
                f.unlink()
                files_deleted += 1
                bytes_freed += size
            except Exception:
                pass

    logger.info(
        f"Cache cleared: {files_deleted} files, "
        f"{bytes_freed / (1024 * 1024):.1f} MB freed"
    )
    return {
        "files_deleted": files_deleted,
        "bytes_freed": bytes_freed,
    }


# --- City Simulation Scenarios ---

CITY_SIM_SCENARIOS = [
    {
        "id": "rush_hour",
        "name": "Rush Hour",
        "description": "Morning commute, heavy traffic",
        "vehicles": 200,
        "pedestrians": 80,
        "startTime": 8.0,
        "timeScale": 60,
        "weather": "clear",
        "emergencyVehicles": 0,
        "sensorBridgeEnabled": False,
    },
    {
        "id": "night_patrol",
        "name": "Night Patrol",
        "description": "Late night, minimal traffic, surveillance mode",
        "vehicles": 20,
        "pedestrians": 5,
        "startTime": 23.0,
        "timeScale": 60,
        "weather": "clear",
        "emergencyVehicles": 0,
        "sensorBridgeEnabled": True,
    },
    {
        "id": "lunch_rush",
        "name": "Lunch Rush",
        "description": "Midday pedestrian activity near restaurants",
        "vehicles": 100,
        "pedestrians": 60,
        "startTime": 12.0,
        "timeScale": 60,
        "weather": "clear",
        "emergencyVehicles": 0,
        "sensorBridgeEnabled": False,
    },
    {
        "id": "emergency",
        "name": "Emergency Response",
        "description": "Active incident with emergency vehicles",
        "vehicles": 50,
        "pedestrians": 30,
        "startTime": 14.0,
        "timeScale": 30,
        "weather": "clear",
        "emergencyVehicles": 3,
        "sensorBridgeEnabled": True,
    },
    {
        "id": "rainy_commute",
        "name": "Rainy Commute",
        "description": "Evening rush in rain, reduced visibility",
        "vehicles": 150,
        "pedestrians": 40,
        "startTime": 17.5,
        "timeScale": 60,
        "weather": "rain",
        "emergencyVehicles": 0,
        "sensorBridgeEnabled": False,
    },
    {
        "id": "weekend_morning",
        "name": "Weekend Morning",
        "description": "Light traffic, joggers and dog walkers",
        "vehicles": 30,
        "pedestrians": 50,
        "startTime": 9.0,
        "timeScale": 120,
        "weather": "clear",
        "emergencyVehicles": 0,
        "sensorBridgeEnabled": False,
    },
]


@router.get("/city-sim/scenarios")
async def get_city_sim_scenarios():
    """List available city simulation scenarios."""
    return CITY_SIM_SCENARIOS


@router.get("/city-sim/scenarios/{scenario_id}")
async def get_city_sim_scenario(scenario_id: str):
    """Get a specific city simulation scenario by ID."""
    for s in CITY_SIM_SCENARIOS:
        if s["id"] == scenario_id:
            return s
    return JSONResponse(status_code=404, content={"error": f"Scenario '{scenario_id}' not found"})
