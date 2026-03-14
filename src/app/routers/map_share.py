# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Map sharing API — operators share their current map view with others.

Supports two sharing mechanisms:
1. Share link — encode view state into a URL fragment for copy/paste
2. WebSocket broadcast — push "look at what I'm seeing" to all connected operators
"""

from __future__ import annotations

import hashlib
import time
from typing import Optional

from fastapi import APIRouter, Request, Body
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/map-share", tags=["map-share"])

# In-memory store of shared views (ephemeral, cleared on restart)
_shared_views: dict[str, dict] = {}


class MapViewState(BaseModel):
    """Represents a shared map view state."""
    center_lat: float = 0.0
    center_lng: float = 0.0
    zoom: float = 1.0
    bearing: float = 0.0
    pitch: float = 0.0
    active_layers: list[str] = Field(default_factory=list)
    selected_targets: list[str] = Field(default_factory=list)
    mode: str = "observe"  # observe | tactical | setup
    operator: str = ""
    message: str = ""  # optional "look at this" message


class SharedView(BaseModel):
    """A stored shared view with metadata."""
    share_id: str = ""
    view: MapViewState = Field(default_factory=MapViewState)
    created_at: float = 0.0
    expires_at: float = 0.0


@router.post("/create")
async def create_share(view: MapViewState = Body(...)):
    """Create a shareable link from the current map view state.

    Returns a share_id that can be used to retrieve the view.
    Link expires after 24 hours.
    """
    ts = time.time()
    raw = f"{view.center_lat}:{view.center_lng}:{view.zoom}:{ts}"
    share_id = hashlib.sha256(raw.encode()).hexdigest()[:12]

    shared = SharedView(
        share_id=share_id,
        view=view,
        created_at=ts,
        expires_at=ts + 86400,  # 24 hour expiry
    )
    _shared_views[share_id] = shared.model_dump()

    # Prune expired entries
    now = time.time()
    expired = [k for k, v in _shared_views.items() if v.get("expires_at", 0) < now]
    for k in expired:
        del _shared_views[k]

    return {
        "share_id": share_id,
        "url_fragment": f"#share={share_id}",
        "expires_at": shared.expires_at,
    }


@router.get("/{share_id}")
async def get_shared_view(share_id: str):
    """Retrieve a shared map view by ID."""
    entry = _shared_views.get(share_id)
    if entry is None:
        return {"error": "Share not found or expired", "share_id": share_id}

    if entry.get("expires_at", 0) < time.time():
        del _shared_views[share_id]
        return {"error": "Share expired", "share_id": share_id}

    return entry


@router.post("/broadcast")
async def broadcast_view(request: Request, view: MapViewState = Body(...)):
    """Broadcast current map view to all connected operators via WebSocket.

    Sends a 'map_view_shared' event through the WebSocket manager so all
    connected clients receive the view state and can optionally snap to it.
    """
    try:
        from app.routers.ws import manager as ws_manager
        import asyncio

        msg = {
            "type": "map_view_shared",
            "data": {
                "center_lat": view.center_lat,
                "center_lng": view.center_lng,
                "zoom": view.zoom,
                "bearing": view.bearing,
                "pitch": view.pitch,
                "active_layers": view.active_layers,
                "selected_targets": view.selected_targets,
                "mode": view.mode,
                "operator": view.operator,
                "message": view.message,
                "timestamp": time.time(),
            },
        }
        await ws_manager.broadcast(msg)
        return {"status": "broadcast_sent", "operator": view.operator}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.get("")
async def list_shared_views(limit: int = 20):
    """List active (non-expired) shared views."""
    now = time.time()
    active = [
        v for v in _shared_views.values()
        if v.get("expires_at", 0) > now
    ]
    # Sort by created_at descending
    active.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return {"shares": active[:limit], "total": len(active)}
