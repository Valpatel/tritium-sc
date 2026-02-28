# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""GIS data layer endpoints — Dublin, CA government ArcGIS services.

All data sources are FREE government services (no API keys):
- Dublin city GIS (gis.dublin.ca.gov) for local layers
- USGS National Map for federal layers (hydro, structures)

Responses are GeoJSON FeatureCollections passed through from ArcGIS.
Results cached on disk with 24-hour TTL.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import settings

router = APIRouter(prefix="/api/geo/layers", tags=["geo-layers"])

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CACHE_DIR = Path(settings.geo_cache_dir).expanduser() / "geodata"
_CACHE_TTL = 86400  # 24 hours in seconds
_FETCH_TIMEOUT = 30.0
_USER_AGENT = "TRITIUM-SC/0.1.0"

_EMPTY_FC: dict[str, Any] = {"type": "FeatureCollection", "features": []}

# ---------------------------------------------------------------------------
# Layer definitions
# ---------------------------------------------------------------------------

_LAYERS: dict[str, dict[str, Any]] = {
    "streams": {
        "name": "Creeks & Streams",
        "type": "line",
        "color": "#00bfff",
        "urls": [
            "https://gis.dublin.ca.gov/arcgis/rest/services/Environmental_Services/"
            "CDFW_Streams/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson"
        ],
    },
    "water": {
        "name": "Water Features (NHD)",
        "type": "line",
        "color": "#1e90ff",
        "urls": [
            # Flowlines (layer 6)
            "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query"
            "?geometry=-121.95,37.66,-121.85,37.76"
            "&geometryType=esriGeometryEnvelope&inSR=4326"
            "&spatialRel=esriSpatialRelIntersects"
            "&outFields=GNIS_Name,FType,FCode,LengthKM&f=geojson",
            # Waterbodies (layer 12)
            "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/12/query"
            "?geometry=-121.95,37.66,-121.85,37.76"
            "&geometryType=esriGeometryEnvelope&inSR=4326"
            "&spatialRel=esriSpatialRelIntersects"
            "&outFields=GNIS_Name,FType,FCode,LengthKM&f=geojson",
        ],
    },
    "traffic-signals": {
        "name": "Traffic Signals",
        "type": "point",
        "color": "#ff4444",
        "urls": [
            "https://gis.dublin.ca.gov/arcgis/rest/services/Public_Works/"
            "Traffic_Signals_FS/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson"
        ],
    },
    "parks": {
        "name": "Parks & Recreation",
        "type": "polygon",
        "color": "#05ffa1",
        "urls": [
            "https://gis.dublin.ca.gov/arcgis/rest/services/Parks_and_Recreation/"
            "Parks_and_Recreation_MS/MapServer/2/query?where=1%3D1&outFields=*&f=geojson"
        ],
    },
    "schools": {
        "name": "Schools",
        "type": "point",
        "color": "#fcee0a",
        "urls": [
            "https://gis.dublin.ca.gov/arcgis/rest/services/Schools/"
            "Schools_FS/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson"
        ],
    },
    "fire-stations": {
        "name": "Fire Stations",
        "type": "point",
        "color": "#ff2a6d",
        "urls": [
            "https://carto.nationalmap.gov/arcgis/rest/services/structures/MapServer/16/query"
            "?geometry=-121.95,37.66,-121.85,37.76"
            "&geometryType=esriGeometryEnvelope&inSR=4326"
            "&spatialRel=esriSpatialRelIntersects"
            "&outFields=NAME,ADDRESS,CITY,STATE,FTYPE&f=geojson"
        ],
    },
    "street-lights": {
        "name": "Street Lights",
        "type": "point",
        "color": "#ffa500",
        "urls": [
            "https://gis.dublin.ca.gov/arcgis/rest/services/Public_Works/"
            "Street_Lights_FS/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson"
        ],
    },
    "trees": {
        "name": "Tree Inventory",
        "type": "point",
        "color": "#228b22",
        "urls": [
            "https://gis.dublin.ca.gov/arcgis/rest/services/Public_Works/"
            "TreeInventory/MapServer/2/query?where=1%3D1&outFields=*"
            "&f=geojson&resultRecordCount=5000"
        ],
    },
    "parcels": {
        "name": "Property Parcels",
        "type": "polygon",
        "color": "#888888",
        "urls": [
            "https://gis.dublin.ca.gov/arcgis/rest/services/Basemaps/"
            "DublinProperty/MapServer/0/query?where=1%3D1"
            "&outFields=APN,OwnerName,SitusNumber,SitusName"
            "&f=geojson&resultRecordCount=5000"
        ],
    },
}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path(layer_id: str) -> Path:
    """Return the on-disk cache path for a layer."""
    return _CACHE_DIR / f"{layer_id}.geojson"


def _cache_is_fresh(path: Path) -> bool:
    """Check whether cached file exists and is within TTL."""
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < _CACHE_TTL


def _read_cache(path: Path) -> dict[str, Any] | None:
    """Read and parse cached GeoJSON, returning None on any error."""
    try:
        data = json.loads(path.read_text())
        return data
    except Exception:
        return None


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    """Write GeoJSON to disk cache. Silently ignores errors."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(data))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Fetch helper
# ---------------------------------------------------------------------------

async def _fetch_geojson(urls: list[str]) -> dict[str, Any]:
    """Fetch GeoJSON from one or more ArcGIS URLs and merge features.

    If multiple URLs are provided (e.g. water flowlines + waterbodies),
    features from all responses are merged into a single FeatureCollection.

    Returns an empty FeatureCollection on any failure.
    """
    all_features: list[dict[str, Any]] = []

    async with httpx.AsyncClient() as client:
        for url in urls:
            try:
                resp = await client.get(
                    url,
                    headers={"User-Agent": _USER_AGENT},
                    timeout=_FETCH_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()

                # ArcGIS sometimes returns an error object instead of GeoJSON
                if "error" in data:
                    logger.warning(f"ArcGIS error for {url}: {data['error']}")
                    continue

                features = data.get("features", [])
                all_features.extend(features)

            except httpx.HTTPError as e:
                logger.warning(f"GeoJSON fetch failed for {url}: {e}")
            except json.JSONDecodeError as e:
                logger.warning(f"GeoJSON decode failed for {url}: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error fetching {url}: {e}")

    return {"type": "FeatureCollection", "features": all_features}


# ---------------------------------------------------------------------------
# Generic layer fetch with caching
# ---------------------------------------------------------------------------

async def _get_layer(layer_id: str) -> dict[str, Any]:
    """Fetch a GIS layer by ID, using disk cache with 24h TTL."""
    layer_def = _LAYERS.get(layer_id)
    if layer_def is None:
        return dict(_EMPTY_FC)

    cache = _cache_path(layer_id)

    # Check cache
    if _cache_is_fresh(cache):
        cached = _read_cache(cache)
        if cached is not None:
            logger.debug(f"GIS layer '{layer_id}' served from cache")
            return cached

    # Fetch from source
    logger.info(f"GIS layer '{layer_id}' fetching from ArcGIS...")
    data = await _fetch_geojson(layer_def["urls"])

    feature_count = len(data.get("features", []))
    logger.info(f"GIS layer '{layer_id}': {feature_count} features fetched")

    # Cache result (even if empty, to avoid hammering the server)
    _write_cache(cache, data)

    return data


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/streams")
async def get_streams():
    """Fetch creek/stream polylines from Dublin CDFW Streams."""
    return await _get_layer("streams")


@router.get("/water")
async def get_water():
    """Fetch water features from USGS National Hydrography Dataset.

    Combines flowlines (layer 6) and waterbodies (layer 12) within the
    Dublin, CA bounding box.
    """
    return await _get_layer("water")


@router.get("/traffic-signals")
async def get_traffic_signals():
    """Fetch traffic signal locations from Dublin Public Works."""
    return await _get_layer("traffic-signals")


@router.get("/parks")
async def get_parks():
    """Fetch parks and recreation areas from Dublin."""
    return await _get_layer("parks")


@router.get("/schools")
async def get_schools():
    """Fetch school locations from Dublin."""
    return await _get_layer("schools")


@router.get("/fire-stations")
async def get_fire_stations():
    """Fetch fire station locations from USGS National Structures Dataset."""
    return await _get_layer("fire-stations")


@router.get("/street-lights")
async def get_street_lights():
    """Fetch street light locations from Dublin Public Works."""
    return await _get_layer("street-lights")


@router.get("/trees")
async def get_trees():
    """Fetch tree inventory from Dublin Public Works.

    Limited to 5000 records per request (ArcGIS server limit).
    """
    return await _get_layer("trees")


@router.get("/parcels")
async def get_parcels():
    """Fetch property parcels from Dublin basemap.

    Returns APN, owner name, and situs address for each parcel.
    Limited to 5000 records per request.
    """
    return await _get_layer("parcels")


@router.get("/catalog")
async def get_catalog():
    """Return a catalog of all available GIS layers.

    Lists each layer's name, geometry type, display color, and whether
    cached data is currently available on disk.
    """
    catalog = []
    for layer_id, layer_def in _LAYERS.items():
        cache = _cache_path(layer_id)
        cached = cache.exists()
        feature_count = 0
        if cached:
            data = _read_cache(cache)
            if data is not None:
                feature_count = len(data.get("features", []))

        catalog.append({
            "id": layer_id,
            "name": layer_def["name"],
            "type": layer_def["type"],
            "color": layer_def["color"],
            "cached": cached,
            "fresh": _cache_is_fresh(cache),
            "feature_count": feature_count,
            "endpoint": f"/api/geo/layers/{layer_id}",
        })

    return catalog
