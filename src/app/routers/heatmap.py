# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Heatmap API — activity heatmap grid for the tactical map.

    GET /api/heatmap  — returns intensity grid for a given layer / time window
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from tritium_lib.tracking.heatmap import HeatmapEngine, VALID_LAYERS

router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])

# ---------------------------------------------------------------------------
# Singleton engine — populated by event subscribers during boot
# ---------------------------------------------------------------------------

_engine = HeatmapEngine()


def get_engine() -> HeatmapEngine:
    """Return the global HeatmapEngine singleton."""
    return _engine


def set_engine(engine: HeatmapEngine) -> None:
    """Replace the global engine (useful for testing)."""
    global _engine
    _engine = engine


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/timeline")
async def get_heatmap_timeline(
    layer: str = Query("all", description="Layer: all, ble_activity, camera_activity, motion_activity"),
    start: float = Query(0, description="Start timestamp (unix seconds)"),
    end: float = Query(0, description="End timestamp (unix seconds)"),
    buckets: int = Query(48, description="Number of time buckets", ge=1, le=200),
    resolution: int = Query(30, description="Grid resolution (NxN)", ge=5, le=100),
):
    """Return time-bucketed heatmap frames for timeline playback."""
    import time as _time

    valid = {"all"} | set(VALID_LAYERS)
    if layer not in valid:
        return {"error": f"Invalid layer '{layer}', valid: {sorted(valid)}"}

    if end <= 0:
        end = _time.time()
    if start <= 0:
        start = end - 24 * 3600

    return _engine.get_timeline(
        start=start,
        end=end,
        buckets=buckets,
        resolution=resolution,
        layer=layer,
    )


@router.get("")
async def get_heatmap(
    layer: str = Query("all", description="Layer: all, ble_activity, camera_activity, motion_activity"),
    window: float = Query(60, description="Time window in minutes", ge=1, le=1440),
    resolution: int = Query(50, description="Grid resolution (NxN)", ge=5, le=200),
):
    """Return an NxN intensity grid for the requested heatmap layer."""
    valid = {"all"} | set(VALID_LAYERS)
    if layer not in valid:
        return {"error": f"Invalid layer '{layer}', valid: {sorted(valid)}"}

    return _engine.get_heatmap(
        time_window_minutes=window,
        resolution=resolution,
        layer=layer,
    )
