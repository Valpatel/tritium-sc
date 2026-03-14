# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the YOLO Detector plugin.

Provides REST endpoints for checking detector status, configuring
thresholds, and retrieving detection statistics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

if TYPE_CHECKING:
    from .plugin import YOLODetectorPlugin


class ConfigureRequest(BaseModel):
    """Request body for updating detector configuration."""

    confidence_threshold: float | None = None
    inference_interval: float | None = None


def create_router(plugin: YOLODetectorPlugin) -> APIRouter:
    """Create FastAPI router for YOLO detector endpoints."""

    router = APIRouter(prefix="/api/yolo", tags=["yolo-detector"])

    @router.get("/status")
    async def get_status():
        """Get detector status and model info."""
        return {
            "healthy": plugin.healthy,
            "confidence_threshold": plugin.confidence_threshold,
            "inference_interval": plugin._inference_interval,
            "stats": plugin.stats,
        }

    @router.post("/configure")
    async def configure(request: ConfigureRequest):
        """Update detector configuration."""
        if request.confidence_threshold is not None:
            if not (0.0 <= request.confidence_threshold <= 1.0):
                raise HTTPException(
                    status_code=400,
                    detail="confidence_threshold must be between 0.0 and 1.0",
                )
            plugin.confidence_threshold = request.confidence_threshold

        if request.inference_interval is not None:
            if request.inference_interval < 0.0:
                raise HTTPException(
                    status_code=400,
                    detail="inference_interval must be non-negative",
                )
            plugin._inference_interval = request.inference_interval

        return {
            "status": "updated",
            "confidence_threshold": plugin.confidence_threshold,
            "inference_interval": plugin._inference_interval,
        }

    @router.get("/stats")
    async def get_stats():
        """Get detection statistics."""
        return plugin.stats

    @router.get("/last")
    async def get_last_result():
        """Get the most recent detection result."""
        result = plugin.last_result
        if result is None:
            return {"detections": [], "message": "No detections yet"}
        return result.to_dict()

    @router.get("/reid/stats")
    async def get_reid_stats():
        """Get ReID cross-camera matching statistics."""
        if plugin._reid is None:
            return {"enabled": False, "message": "ReID integration not available"}
        return {"enabled": True, **plugin._reid.stats}

    return router
