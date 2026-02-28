# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Synthetic camera feed router — MJPEG streaming from synthetic renderers.

Provides REST endpoints to create, list, snapshot, stream, and delete
synthetic camera feeds. Each feed generates frames on-the-fly using
the amy.synthetic.video_gen renderers (no disk I/O, no GPU required).

Endpoints:
    GET  /api/synthetic/cameras                — List synthetic camera feeds
    GET  /api/synthetic/cameras/{id}/mjpeg     — MJPEG streaming response
    GET  /api/synthetic/cameras/{id}/snapshot   — Single JPEG frame
    POST /api/synthetic/cameras                — Create a new synthetic feed
    DELETE /api/synthetic/cameras/{id}          — Remove a feed
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Generator

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from engine.synthetic.video_gen import (
    render_bird_eye,
    render_cctv_frame,
    render_street_cam,
    render_battle_scene,
    render_neighborhood,
)
from engine.synthetic.video_library import SCENE_TYPES

router = APIRouter(prefix="/api/synthetic", tags=["synthetic-cameras"])

# Scene type -> renderer mapping
_RENDERERS = {
    "bird_eye": render_bird_eye,
    "street_cam": render_street_cam,
    "battle": render_battle_scene,
    "neighborhood": render_neighborhood,
    "cctv": render_cctv_frame,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SyntheticFeedConfig:
    """Configuration for a synthetic camera feed."""

    feed_id: str
    scene_type: str = "bird_eye"
    fps: int = 10
    width: int = 640
    height: int = 480

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _FeedState:
    """Internal state for a running feed."""

    config: SyntheticFeedConfig
    frame_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    seed: int = field(default_factory=lambda: int(time.time() * 1000) % (2**31))


# ---------------------------------------------------------------------------
# Feed Manager
# ---------------------------------------------------------------------------


class SyntheticFeedManager:
    """Manages synthetic camera feeds — create, list, delete, generate frames.

    Thread-safe for read operations. Write operations (create/delete) should
    be called from a single thread (the FastAPI event loop).
    """

    def __init__(self) -> None:
        self._feeds: dict[str, _FeedState] = {}

    def create_feed(self, config: SyntheticFeedConfig) -> dict:
        """Create a new synthetic camera feed.

        Args:
            config: Feed configuration.

        Returns:
            Dict with feed metadata.

        Raises:
            ValueError: If feed_id already exists.
        """
        if config.feed_id in self._feeds:
            raise ValueError(f"Feed '{config.feed_id}' already exists")

        # Validate scene type (support both original scene types and "cctv")
        valid_types = set(SCENE_TYPES) | {"cctv"}
        if config.scene_type not in valid_types:
            config.scene_type = "bird_eye"

        state = _FeedState(config=config)
        self._feeds[config.feed_id] = state
        return self._feed_to_dict(state)

    def delete_feed(self, feed_id: str) -> None:
        """Delete a synthetic camera feed.

        Args:
            feed_id: Feed identifier.

        Raises:
            KeyError: If feed does not exist.
        """
        if feed_id not in self._feeds:
            raise KeyError(f"Feed '{feed_id}' not found")
        del self._feeds[feed_id]

    def list_feeds(self) -> list[dict]:
        """List all synthetic camera feeds with metadata.

        Returns:
            List of feed metadata dicts.
        """
        return [self._feed_to_dict(s) for s in self._feeds.values()]

    def get_feed(self, feed_id: str) -> dict | None:
        """Get a specific feed's metadata.

        Args:
            feed_id: Feed identifier.

        Returns:
            Feed metadata dict, or None if not found.
        """
        state = self._feeds.get(feed_id)
        if state is None:
            return None
        return self._feed_to_dict(state)

    def generate_frame(self, feed_id: str) -> np.ndarray:
        """Generate a single BGR frame for a feed.

        Args:
            feed_id: Feed identifier.

        Returns:
            BGR uint8 numpy array.

        Raises:
            KeyError: If feed does not exist.
        """
        state = self._feeds.get(feed_id)
        if state is None:
            raise KeyError(f"Feed '{feed_id}' not found")

        cfg = state.config
        renderer = _RENDERERS.get(cfg.scene_type, _RENDERERS["bird_eye"])

        kwargs: dict[str, Any] = {
            "resolution": (cfg.width, cfg.height),
            "seed": state.seed + state.frame_count,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }

        if cfg.scene_type == "street_cam":
            kwargs["camera_name"] = f"SYN-{feed_id}"
        elif cfg.scene_type == "neighborhood":
            kwargs["camera_name"] = f"SYN-{feed_id}"
        elif cfg.scene_type == "cctv":
            kwargs["camera_name"] = f"SYN-{feed_id}"
            kwargs["scene_type"] = "front_door"
            kwargs["frame_number"] = state.frame_count

        frame = renderer(**kwargs)
        state.frame_count += 1
        return frame

    def get_snapshot(self, feed_id: str, quality: int = 80) -> bytes:
        """Generate a single JPEG snapshot.

        Args:
            feed_id: Feed identifier.
            quality: JPEG quality (0-100).

        Returns:
            JPEG bytes.

        Raises:
            KeyError: If feed does not exist.
        """
        frame = self.generate_frame(feed_id)
        _, jpeg_buf = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality],
        )
        return jpeg_buf.tobytes()

    def mjpeg_frames(self, feed_id: str) -> Generator[bytes, None, None]:
        """Yield MJPEG-formatted frames for streaming.

        Args:
            feed_id: Feed identifier.

        Yields:
            Bytes with MJPEG boundary and content-type headers.

        Raises:
            KeyError: If feed does not exist.
        """
        state = self._feeds.get(feed_id)
        if state is None:
            raise KeyError(f"Feed '{feed_id}' not found")

        fps = max(1, state.config.fps)
        interval = 1.0 / fps

        while True:
            try:
                jpeg = self.get_snapshot(feed_id)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                    b"\r\n" + jpeg + b"\r\n"
                )
                time.sleep(interval)
            except KeyError:
                break

    # --- Internal helpers ---

    def _feed_to_dict(self, state: _FeedState) -> dict:
        """Convert feed state to a response dict."""
        return {
            "feed_id": state.config.feed_id,
            "scene_type": state.config.scene_type,
            "fps": state.config.fps,
            "width": state.config.width,
            "height": state.config.height,
            "frame_count": state.frame_count,
            "created_at": state.created_at,
        }


# ---------------------------------------------------------------------------
# Singleton manager (created at import time)
# ---------------------------------------------------------------------------

_manager = SyntheticFeedManager()


def get_manager() -> SyntheticFeedManager:
    """Get the global SyntheticFeedManager instance."""
    return _manager


# ---------------------------------------------------------------------------
# Pydantic models for API
# ---------------------------------------------------------------------------


class CreateFeedRequest(BaseModel):
    """Request body for creating a synthetic camera feed."""

    feed_id: str
    scene_type: str = "bird_eye"
    fps: int = 10
    width: int = 640
    height: int = 480


class FeedResponse(BaseModel):
    """Response body for a synthetic camera feed."""

    feed_id: str
    scene_type: str
    fps: int
    width: int
    height: int
    frame_count: int
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/cameras", response_model=list[FeedResponse])
async def list_synthetic_cameras():
    """List all synthetic camera feeds."""
    return _manager.list_feeds()


@router.get("/cameras/{feed_id}", response_model=FeedResponse)
async def get_synthetic_camera(feed_id: str):
    """Get a specific synthetic camera feed."""
    feed = _manager.get_feed(feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")
    return feed


@router.post("/cameras", response_model=FeedResponse, status_code=201)
async def create_synthetic_camera(request: CreateFeedRequest):
    """Create a new synthetic camera feed."""
    config = SyntheticFeedConfig(
        feed_id=request.feed_id,
        scene_type=request.scene_type,
        fps=request.fps,
        width=request.width,
        height=request.height,
    )
    try:
        result = _manager.create_feed(config)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return result


@router.delete("/cameras/{feed_id}")
async def delete_synthetic_camera(feed_id: str):
    """Delete a synthetic camera feed."""
    try:
        _manager.delete_feed(feed_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "deleted", "feed_id": feed_id}


@router.get("/cameras/{feed_id}/snapshot")
async def get_snapshot(feed_id: str):
    """Get a single JPEG snapshot from a synthetic camera."""
    try:
        jpeg = _manager.get_snapshot(feed_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/cameras/{feed_id}/mjpeg")
async def get_mjpeg_stream(feed_id: str):
    """Stream MJPEG from a synthetic camera.

    Returns a multipart/x-mixed-replace response suitable for <img> tags:
        <img src="/api/synthetic/cameras/{feed_id}/mjpeg" />
    """
    feed = _manager.get_feed(feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

    return StreamingResponse(
        _manager.mjpeg_frames(feed_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
