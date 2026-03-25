# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Terrain analysis — RF coverage AND geospatial segmentation endpoints.

RF propagation:
    POST /api/terrain/propagation  — estimate RF signal at distance
    POST /api/terrain/coverage     — compute coverage grid for a sensor
    POST /api/terrain/los          — line-of-sight check between two points
    GET  /api/terrain/types        — list terrain types

Geospatial segmentation:
    POST /api/terrain/process      — segment satellite imagery for a bbox
    GET  /api/terrain/layer        — get cached terrain as GeoJSON
    GET  /api/terrain/brief        — terrain brief text for commander AI
    GET  /api/terrain/status       — pipeline status and cache info
    GET  /api/terrain/query        — query terrain type at a point
"""

import json
import logging
import math
import time
from pathlib import Path
from threading import Lock
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/terrain", tags=["terrain"])


# --- Request/Response models ---


class PropagationRequest(BaseModel):
    """Request to estimate RF signal propagation."""

    tx_power_dbm: float = 0.0
    distance_m: float = 100.0
    frequency_mhz: float = 2400.0
    terrain_type: str = "suburban"
    sensor_height_m: float = 2.0


class PropagationResponse(BaseModel):
    """RF propagation estimate result."""

    distance_m: float
    frequency_mhz: float
    terrain_type: str
    free_space_loss_db: float
    terrain_loss_db: float
    estimated_rssi_dbm: float
    coverage_quality: str  # excellent, good, fair, poor, none


class CoverageRequest(BaseModel):
    """Request to compute sensor coverage analysis."""

    sensor_lat: float
    sensor_lng: float
    sensor_height_m: float = 2.0
    tx_power_dbm: float = 0.0
    frequency_mhz: float = 2400.0
    range_m: float = 100.0
    terrain_type: str = "suburban"
    grid_resolution_m: float = 10.0
    sensitivity_dbm: float = -90.0  # minimum detectable signal


class LOSRequest(BaseModel):
    """Line-of-sight check request."""

    start_lat: float
    start_lng: float
    start_height_m: float = 2.0
    end_lat: float
    end_lng: float
    end_height_m: float = 2.0


# --- Helpers ---

_TERRAIN_MAP = {
    "urban": "urban",
    "suburban": "suburban",
    "rural": "rural",
    "forest": "forest",
    "water": "water",
    "desert": "desert",
    "mountain": "mountain",
    "indoor": "indoor",
    "unknown": "unknown",
}

# Terrain loss factors (dB per decade of distance at 2.4 GHz)
_TERRAIN_FACTORS = {
    "urban": 30.0,
    "suburban": 20.0,
    "rural": 10.0,
    "forest": 25.0,
    "water": 5.0,
    "desert": 8.0,
    "mountain": 15.0,
    "indoor": 35.0,
    "unknown": 20.0,
}


def _fspl(distance_m: float, frequency_mhz: float) -> float:
    """Free-space path loss in dB."""
    if distance_m <= 0 or frequency_mhz <= 0:
        return 0.0
    freq_hz = frequency_mhz * 1e6
    c = 299792458.0
    return (
        20 * math.log10(distance_m)
        + 20 * math.log10(freq_hz)
        + 20 * math.log10(4 * math.pi / c)
    )


def _terrain_loss(distance_m: float, frequency_mhz: float, terrain: str) -> float:
    """Total path loss including terrain effects."""
    fspl = _fspl(distance_m, frequency_mhz)
    extra = _TERRAIN_FACTORS.get(terrain, 20.0)
    if distance_m > 1:
        extra *= math.log2(max(distance_m, 2)) / 10.0
    return fspl + extra


def _quality_label(rssi_dbm: float) -> str:
    """Map RSSI to a human-readable quality label."""
    if rssi_dbm >= -50:
        return "excellent"
    elif rssi_dbm >= -70:
        return "good"
    elif rssi_dbm >= -85:
        return "fair"
    elif rssi_dbm >= -100:
        return "poor"
    return "none"


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in meters."""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# --- Endpoints ---


@router.post("/propagation", response_model=PropagationResponse)
async def estimate_propagation(request: PropagationRequest):
    """Estimate RF signal strength at a given distance and terrain."""
    terrain = _TERRAIN_MAP.get(request.terrain_type, "unknown")
    fspl = _fspl(request.distance_m, request.frequency_mhz)
    total_loss = _terrain_loss(request.distance_m, request.frequency_mhz, terrain)
    rssi = request.tx_power_dbm - total_loss

    return PropagationResponse(
        distance_m=request.distance_m,
        frequency_mhz=request.frequency_mhz,
        terrain_type=terrain,
        free_space_loss_db=round(fspl, 2),
        terrain_loss_db=round(total_loss, 2),
        estimated_rssi_dbm=round(rssi, 2),
        coverage_quality=_quality_label(rssi),
    )


@router.post("/coverage")
async def compute_coverage(request: CoverageRequest):
    """Compute coverage grid for a sensor placement.

    Returns a grid of cells with signal strength estimates.
    Limited to 10,000 cells max to prevent DoS.
    """
    terrain = _TERRAIN_MAP.get(request.terrain_type, "unknown")
    resolution = max(request.grid_resolution_m, 5.0)  # minimum 5m resolution
    max_cells = 10000

    # Generate grid
    cells = []
    covered_count = 0

    # Convert range to lat/lng steps
    meters_per_deg_lat = 111320
    meters_per_deg_lng = meters_per_deg_lat * math.cos(math.radians(request.sensor_lat))

    step_lat = resolution / meters_per_deg_lat
    step_lng = resolution / max(meters_per_deg_lng, 1)

    half_range_lat = request.range_m / meters_per_deg_lat
    half_range_lng = request.range_m / max(meters_per_deg_lng, 1)

    lat = request.sensor_lat - half_range_lat
    while lat <= request.sensor_lat + half_range_lat and len(cells) < max_cells:
        lng = request.sensor_lng - half_range_lng
        while lng <= request.sensor_lng + half_range_lng and len(cells) < max_cells:
            dist = _haversine_m(request.sensor_lat, request.sensor_lng, lat, lng)
            if dist <= request.range_m and dist > 0:
                loss = _terrain_loss(dist, request.frequency_mhz, terrain)
                rssi = request.tx_power_dbm - loss
                covered = rssi >= request.sensitivity_dbm
                if covered:
                    covered_count += 1
                cells.append({
                    "latitude": round(lat, 7),
                    "longitude": round(lng, 7),
                    "signal_strength_dbm": round(rssi, 1),
                    "covered": covered,
                    "distance_m": round(dist, 1),
                })
            lng += step_lng
        lat += step_lat

    total = len(cells) if cells else 1
    return {
        "sensor_lat": request.sensor_lat,
        "sensor_lng": request.sensor_lng,
        "terrain_type": terrain,
        "range_m": request.range_m,
        "grid_resolution_m": resolution,
        "total_cells": len(cells),
        "covered_cells": covered_count,
        "coverage_percent": round(100 * covered_count / total, 1),
        "cells": cells,
    }


@router.post("/los")
async def check_line_of_sight(request: LOSRequest):
    """Check line-of-sight between two points.

    Simplified flat-earth model (no elevation data).
    Returns distance and estimated LOS status.
    """
    distance = _haversine_m(
        request.start_lat, request.start_lng,
        request.end_lat, request.end_lng,
    )

    # Without real elevation data, assume LOS is clear for short distances
    # and questionable for longer ones
    los_clear = distance < 500  # simple heuristic

    return {
        "distance_m": round(distance, 1),
        "has_line_of_sight": los_clear,
        "note": "Simplified model — no elevation data loaded" if not los_clear else "Clear LOS (flat terrain assumed)",
        "start": {"lat": request.start_lat, "lng": request.start_lng, "height_m": request.start_height_m},
        "end": {"lat": request.end_lat, "lng": request.end_lng, "height_m": request.end_height_m},
    }


@router.get("/types")
async def get_terrain_types():
    """List available terrain types with their RF characteristics."""
    return [
        {
            "type": t,
            "loss_factor_db": f,
            "description": {
                "urban": "Dense buildings, high multipath",
                "suburban": "Mixed residential/commercial",
                "rural": "Open fields, few obstructions",
                "forest": "Tree canopy, foliage absorption",
                "water": "Open water, minimal obstruction",
                "desert": "Flat, dry, minimal vegetation",
                "mountain": "Elevation changes, rock reflections",
                "indoor": "Walls, floors, furniture",
                "unknown": "Default propagation model",
            }.get(t, ""),
        }
        for t, f in _TERRAIN_FACTORS.items()
    ]


# ═══════════════════════════════════════════════════════════════════════════
# GEOSPATIAL SEGMENTATION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

_terrain_layer = None
_processing = False


class GeoProcessRequest(BaseModel):
    """Request to process an area of operations via satellite segmentation."""
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    zoom: int = 16
    ao_id: str = "default"
    source: str = "satellite"
    use_llm: bool = True
    fuse_osm: bool = True  # fuse with OSM data for richer terrain


@router.post("/process")
async def process_terrain_area(req: GeoProcessRequest):
    """Process an area — download satellite tiles, segment, classify, cache.

    Runs the full geospatial pipeline and makes results available via
    /api/terrain/layer and the map overlay.
    """
    global _terrain_layer, _processing

    if _processing:
        raise HTTPException(status_code=409, detail="Processing already in progress")

    _processing = True
    t0 = time.monotonic()

    try:
        from tritium_lib.models.gis import TileBounds
        from tritium_lib.intelligence.geospatial.models import (
            AreaOfOperations, SegmentationConfig, SegmentedRegion,
            TerrainLayerMetadata,
        )
        from tritium_lib.intelligence.geospatial.tile_downloader import TileDownloader
        from tritium_lib.intelligence.geospatial.segmentation import SegmentationEngine
        from tritium_lib.intelligence.geospatial.terrain_classifier import TerrainClassifier
        from tritium_lib.intelligence.geospatial.vector_converter import VectorConverter
        from tritium_lib.intelligence.geospatial.terrain_layer import TerrainLayer

        import numpy as np
        from PIL import Image

        ao = AreaOfOperations(
            id=req.ao_id,
            name=f"AO {req.ao_id}",
            bounds=TileBounds(
                min_lat=req.min_lat, min_lon=req.min_lon,
                max_lat=req.max_lat, max_lon=req.max_lon,
            ),
            zoom=req.zoom,
        )

        # Check for llama-server
        llm_ok = False
        if req.use_llm:
            try:
                import requests as http_req
                llm_ok = http_req.get("http://127.0.0.1:8081/health", timeout=1).status_code == 200
            except Exception:
                pass

        config = SegmentationConfig(llm_classify=llm_ok, llm_endpoint="http://127.0.0.1:8081")

        # Pipeline
        dl = TileDownloader(cache_dir=Path("data/cache/tiles"))
        image_path = dl.download_tiles(ao, source=req.source)

        engine = SegmentationEngine(config)
        segments = engine.segment_image(image_path)

        img = Image.open(image_path)
        img_array = np.array(img.convert("RGB"))
        geo_transform = dl.get_geo_transform(ao, img.width, img.height)

        classifier = TerrainClassifier(config)
        classifications = classifier.classify_segments(img_array, segments)

        converter = VectorConverter(min_area_px=50)
        regions = []
        for i, seg in enumerate(segments):
            tt, conf = classifications[i]
            for poly in converter.mask_to_polygons(seg["mask"], geo_transform):
                area = poly.get("area_m2", 0)
                if area < 10 or area > 100000:
                    continue
                c = poly.get("centroid", (0, 0))
                regions.append(SegmentedRegion(
                    geometry_wkt=poly["wkt"], terrain_type=tt, confidence=conf,
                    area_m2=area, centroid_lon=c[0], centroid_lat=c[1],
                ))

        elapsed = time.monotonic() - t0

        layer = TerrainLayer(cache_dir=Path("data/cache/terrain"))
        layer._regions = regions
        layer._bounds = ao.bounds
        layer._metadata = TerrainLayerMetadata(
            ao_id=ao.id, segment_count=len(regions),
            processing_time_s=elapsed, source_imagery=req.source, bounds=ao.bounds,
        )
        # Fuse with OSM data for richer terrain (real road/building names)
        if req.fuse_osm:
            try:
                from tritium_lib.intelligence.geospatial.osm_enrichment import OSMEnrichment
                osm_enrichment = OSMEnrichment()
                osm_features = osm_enrichment.fetch_osm(ao.bounds)
                if osm_features:
                    osm_regions = []
                    osm_cells = set()
                    for f in osm_features:
                        if f.lat == 0 and f.lon == 0:
                            continue
                        props = {"osm_id": f.osm_id, "source": "osm"}
                        if f.name:
                            props["osm_name"] = f.name
                        osm_regions.append(SegmentedRegion(
                            geometry_wkt="POLYGON EMPTY", terrain_type=f.terrain_type,
                            confidence=0.85, area_m2=100,
                            centroid_lat=f.lat, centroid_lon=f.lon, properties=props,
                        ))
                        osm_cells.add((int(f.lon * 10000), int(f.lat * 10000)))
                    sat_fill = sum(1 for r in regions if (int(r.centroid_lon * 10000), int(r.centroid_lat * 10000)) not in osm_cells)
                    regions = osm_regions + [r for r in regions if (int(r.centroid_lon * 10000), int(r.centroid_lat * 10000)) not in osm_cells]
                    layer._regions = regions
                    logger.info("Fused %d OSM + %d satellite = %d features", len(osm_features), sat_fill, len(regions))
            except Exception as e:
                logger.debug("OSM fusion skipped: %s", e)

        layer._build_grid_index()
        layer._save_cache(ao.id)
        _terrain_layer = layer

        # Wire into simulation engine + Amy
        _wire_terrain_to_sim(layer)

        type_counts = {}
        for r in regions:
            t = r.terrain_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

        logger.info("Terrain processed: %d features in %.1fs", len(regions), elapsed)

        return {
            "status": "complete",
            "ao_id": ao.id,
            "features": len(regions),
            "processing_time_s": round(elapsed, 1),
            "terrain_types": type_counts,
            "llm_used": llm_ok,
            "brief": layer.terrain_brief(),
        }

    except Exception as e:
        logger.error("Terrain processing failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Terrain processing failed")
    finally:
        _processing = False


@router.get("/layer")
async def get_geo_layer(
    ao_id: str = Query("default"),
    bbox: Optional[str] = Query(None, description="west,south,east,north"),
):
    """Get cached terrain layer as GeoJSON for map rendering."""
    layer = _load_terrain(ao_id)
    if layer is None:
        return {"type": "FeatureCollection", "features": []}

    geojson = layer.to_geojson()

    # Add rendering hints per feature
    colors = {
        "building": "#404040", "road": "#333333", "water": "#0066cc",
        "vegetation": "#228B22", "sidewalk": "#999999", "parking": "#666666",
        "bridge": "#4682B4", "barren": "#D2B48C", "rail": "#8B0000",
    }
    opacities = {
        "building": 0.6, "road": 0.4, "water": 0.4, "vegetation": 0.3,
        "sidewalk": 0.3, "parking": 0.3, "bridge": 0.5, "barren": 0.3, "rail": 0.5,
    }
    for f in geojson.get("features", []):
        tt = f.get("properties", {}).get("terrain_type", "unknown")
        f["properties"]["fill_color"] = colors.get(tt, "#808080")
        f["properties"]["fill_opacity"] = opacities.get(tt, 0.3)

    return geojson


@router.get("/brief")
async def get_geo_brief(ao_id: str = Query("default")):
    """Get terrain brief text for commander AI."""
    layer = _load_terrain(ao_id)
    if layer is None:
        return {"brief": "No terrain data. POST /api/terrain/process to segment an area."}
    return {"brief": layer.terrain_brief()}


@router.get("/status")
async def get_geo_status():
    """Pipeline status and cached areas."""
    cache_dir = Path("data/cache/terrain")
    areas = []
    if cache_dir.exists():
        for d in sorted(cache_dir.iterdir()):
            meta_path = d / "metadata.json"
            if d.is_dir() and meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                    areas.append({
                        "ao_id": meta.get("ao_id", d.name),
                        "features": meta.get("segment_count", 0),
                        "time_s": meta.get("processing_time_s", 0),
                        "source": meta.get("source_imagery", ""),
                    })
                except Exception:
                    pass

    return {
        "processing": _processing,
        "active": _terrain_layer is not None,
        "cached_areas": areas,
    }


@router.get("/query")
async def query_terrain_at(
    lat: float = Query(...), lon: float = Query(...),
    ao_id: str = Query("default"),
):
    """Query terrain type at a geographic point."""
    layer = _load_terrain(ao_id)
    if layer is None:
        return {"terrain_type": "unknown"}

    return {"terrain_type": layer.terrain_at(lat, lon).value, "lat": lat, "lon": lon}


def _load_terrain(ao_id: str):
    """Get active terrain layer or load from cache."""
    global _terrain_layer
    if _terrain_layer and _terrain_layer.metadata and _terrain_layer.metadata.ao_id == ao_id:
        return _terrain_layer

    try:
        from tritium_lib.intelligence.geospatial.terrain_layer import TerrainLayer
        tl = TerrainLayer(cache_dir=Path("data/cache/terrain"))
        if tl.load_cached(ao_id):
            _terrain_layer = tl
            return tl
    except Exception:
        pass
    return _terrain_layer


def _wire_terrain_to_sim(layer) -> None:
    """Wire terrain layer into running simulation engine + Amy."""
    try:
        from app.main import get_amy
        amy = get_amy()
        if amy is not None:
            amy.terrain_layer = layer
            eng = getattr(amy, "simulation_engine", None)
            if eng and hasattr(eng, "load_terrain_layer"):
                eng.load_terrain_layer(layer)
                logger.info("Wired terrain into simulation engine")
    except Exception:
        pass


def set_terrain_layer(layer) -> None:
    """Set the active terrain layer (called by other modules)."""
    global _terrain_layer
    _terrain_layer = layer
