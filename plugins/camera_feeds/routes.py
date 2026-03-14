# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Camera Feeds plugin.

Provides REST endpoints for listing, adding, removing, snapshotting,
and streaming camera feeds from any source type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from .sources import CameraSourceConfig, SOURCE_TYPES

if TYPE_CHECKING:
    from .plugin import CameraFeedsPlugin


class AddSourceRequest(BaseModel):
    """Request body for adding a camera source."""

    source_id: str
    source_type: str = "synthetic"
    name: str = ""
    width: int = 640
    height: int = 480
    fps: int = 10
    uri: str = ""
    extra: dict = {}


def create_router(plugin: CameraFeedsPlugin) -> APIRouter:
    """Create FastAPI router for camera feed endpoints."""

    router = APIRouter(prefix="/api/camera-feeds", tags=["camera-feeds"])

    @router.get("/sources")
    async def list_sources():
        """List all camera sources."""
        sources = plugin.list_sources()
        return {"sources": sources, "count": len(sources)}

    @router.get("/sources/types")
    async def list_source_types():
        """List available camera source types."""
        return {"types": list(SOURCE_TYPES.keys())}

    @router.get("/sources/{source_id}")
    async def get_source(source_id: str):
        """Get a specific camera source."""
        source = plugin.get_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
        return source.to_dict()

    @router.post("/sources", status_code=201)
    async def add_source(request: AddSourceRequest):
        """Add a new camera source."""
        config = CameraSourceConfig(
            source_id=request.source_id,
            source_type=request.source_type,
            name=request.name,
            width=request.width,
            height=request.height,
            fps=request.fps,
            uri=request.uri,
            extra=request.extra,
        )
        try:
            source = plugin.register_source(config)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return source.to_dict()

    @router.delete("/sources/{source_id}")
    async def remove_source(source_id: str):
        """Remove a camera source."""
        try:
            plugin.remove_source(source_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {"status": "removed", "source_id": source_id}

    @router.get("/sources/{source_id}/snapshot")
    async def get_snapshot(source_id: str):
        """Get a single JPEG snapshot from a camera source."""
        source = plugin.get_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
        jpeg = source.get_snapshot()
        if jpeg is None:
            raise HTTPException(status_code=503, detail="No frame available")
        return Response(content=jpeg, media_type="image/jpeg")

    @router.get("/sources/{source_id}/mjpeg")
    async def get_mjpeg_stream(source_id: str):
        """Stream MJPEG from a camera source.

        Returns a multipart/x-mixed-replace response suitable for <img> tags:
            <img src="/api/camera-feeds/sources/{source_id}/mjpeg" />
        """
        source = plugin.get_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
        return StreamingResponse(
            source.mjpeg_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    return router
