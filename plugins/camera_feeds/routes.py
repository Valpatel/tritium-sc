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
    lat: float | None = None
    lng: float | None = None
    heading: float | None = None
    fov_angle: float | None = None
    fov_range: float | None = None
    extra: dict = {}


def create_router(plugin: CameraFeedsPlugin) -> APIRouter:
    """Create FastAPI router for camera feed endpoints."""

    router = APIRouter(prefix="/api/camera-feeds", tags=["camera-feeds"])

    @router.get("/")
    async def list_feeds():
        """Compatibility endpoint — returns sources as a flat list.

        The camera-feeds panel fetches GET /api/camera-feeds/ and expects
        an array of camera objects with ``id``, ``name``, ``status``,
        ``stream_url``, and ``latest_detection`` keys.
        """
        sources = plugin.list_sources()
        feeds = []
        for s in sources:
            feeds.append({
                "id": s.get("source_id", s.get("id", "")),
                "name": s.get("name", ""),
                "status": "streaming" if s.get("running") else "offline",
                "stream_url": f"/api/camera-feeds/sources/{s.get('source_id', '')}/mjpeg",
                "latest_detection": None,
                "lat": s.get("lat"),
                "lng": s.get("lng"),
                "heading": s.get("heading"),
                "fov_angle": s.get("fov_angle"),
                "fov_range": s.get("fov_range"),
                "source_type": s.get("source_type", ""),
                "uri": s.get("uri", ""),
            })
        return feeds

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
        extra = dict(request.extra)
        if request.lat is not None:
            extra["lat"] = request.lat
        if request.lng is not None:
            extra["lng"] = request.lng
        if request.heading is not None:
            extra["heading"] = request.heading
        if request.fov_angle is not None:
            extra["fov_angle"] = request.fov_angle
        if request.fov_range is not None:
            extra["fov_range"] = request.fov_range
        config = CameraSourceConfig(
            source_id=request.source_id,
            source_type=request.source_type,
            name=request.name,
            width=request.width,
            height=request.height,
            fps=request.fps,
            uri=request.uri,
            extra=extra,
        )
        try:
            source = plugin.register_source(config)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return source.to_dict()

    @router.patch("/sources/{source_id}/position")
    async def update_source_position(source_id: str, body: dict):
        """Update a camera source's map position (lat/lng/heading).

        Used by the camera-feeds panel click-to-place feature (Loop 8).
        Accepts: { lat, lng, heading } — any field can be omitted.
        """
        source = plugin.get_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found")
        lat = body.get("lat")
        lng = body.get("lng")
        heading = body.get("heading")
        if lat is not None:
            source.config.extra["lat"] = float(lat)
        if lng is not None:
            source.config.extra["lng"] = float(lng)
        if heading is not None:
            source.config.extra["heading"] = float(heading)
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
