"""Geo engine — address geocoding, satellite tile proxy, building footprints.

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
from fastapi import APIRouter, HTTPException, Query
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

_USER_AGENT = "TRITIUM-SC/0.1.0"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_ESRI_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
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
    from amy.geo import get_reference
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
    from amy.geo import init_reference
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
    from amy.geo import init_reference
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
