# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Collaboration API — shared investigation workspaces, map drawing, operator chat.

Provides real-time multi-operator collaboration via WebSocket broadcasts:
- Shared investigation editing (add entity, annotate, change status)
- Map drawing collaboration (freehand, shapes, measurements, geofences)
- Operator text chat for coordination during operations
"""

from __future__ import annotations

import html
import re
import time
import uuid
from collections import deque
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
_MAX_CHAT_LEN = 2000
_MAX_LABEL_LEN = 200
_MAX_WORKSPACES = 100
_MAX_CHAT_HISTORY = 500
_MAX_DRAWING_POINTS = 5000
_MAX_DRAWINGS = 1000
_MAX_WORKSPACE_EVENTS = 200
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _sanitize(value: str, max_len: int) -> str:
    """Strip HTML tags and truncate."""
    cleaned = _HTML_TAG_RE.sub("", value)
    cleaned = html.escape(cleaned)
    return cleaned[:max_len]


# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

# Shared workspaces: workspace_id -> workspace dict
_workspaces: dict[str, dict] = {}

# Chat messages: channel -> deque of messages
_chat_history: dict[str, deque] = {}

# Map drawings: drawing_id -> drawing dict
_drawings: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Workspace endpoints
# ---------------------------------------------------------------------------

class CreateWorkspaceRequest(BaseModel):
    investigation_id: str
    title: str = ""
    operator_id: str = "system"
    operator_name: str = ""


@router.post("/workspaces")
async def create_workspace(req: CreateWorkspaceRequest):
    """Create a shared workspace for collaborative investigation editing."""
    if len(_workspaces) >= _MAX_WORKSPACES:
        raise HTTPException(status_code=429, detail="Maximum workspace limit reached")

    workspace_id = str(uuid.uuid4())[:12]
    workspace = {
        "workspace_id": workspace_id,
        "investigation_id": req.investigation_id,
        "title": _sanitize(req.title, _MAX_LABEL_LEN) if req.title else req.investigation_id,
        "created_at": time.time(),
        "active_operators": [req.operator_id] if req.operator_id != "system" else [],
        "recent_events": [],
        "version": 0,
    }
    _workspaces[workspace_id] = workspace

    # Broadcast workspace creation
    await _broadcast_workspace_event(workspace_id, {
        "event_type": "workspace_created",
        "workspace_id": workspace_id,
        "investigation_id": req.investigation_id,
        "operator_id": req.operator_id,
        "operator_name": req.operator_name,
    })

    return workspace


@router.get("/workspaces")
async def list_workspaces(investigation_id: Optional[str] = Query(None)):
    """List active shared workspaces, optionally filtered by investigation."""
    result = list(_workspaces.values())
    if investigation_id:
        result = [w for w in result if w["investigation_id"] == investigation_id]
    return {"workspaces": result, "total": len(result)}


@router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str):
    """Get workspace details including active operators and recent events."""
    ws = _workspaces.get(workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.post("/workspaces/{workspace_id}/join")
async def join_workspace(
    workspace_id: str,
    operator_id: str = Body(...),
    operator_name: str = Body(default=""),
):
    """Join a shared workspace. Broadcasts join event to all operators."""
    ws = _workspaces.get(workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if operator_id not in ws["active_operators"]:
        ws["active_operators"].append(operator_id)

    event = {
        "event_type": "operator_joined",
        "workspace_id": workspace_id,
        "operator_id": operator_id,
        "operator_name": operator_name,
        "active_operators": ws["active_operators"],
    }
    _add_workspace_event(ws, event)
    await _broadcast_workspace_event(workspace_id, event)

    return {"ok": True, "active_operators": ws["active_operators"]}


@router.post("/workspaces/{workspace_id}/leave")
async def leave_workspace(
    workspace_id: str,
    operator_id: str = Body(...),
    operator_name: str = Body(default=""),
):
    """Leave a shared workspace. Broadcasts leave event."""
    ws = _workspaces.get(workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if operator_id in ws["active_operators"]:
        ws["active_operators"].remove(operator_id)

    event = {
        "event_type": "operator_left",
        "workspace_id": workspace_id,
        "operator_id": operator_id,
        "operator_name": operator_name,
        "active_operators": ws["active_operators"],
    }
    _add_workspace_event(ws, event)
    await _broadcast_workspace_event(workspace_id, event)

    return {"ok": True, "active_operators": ws["active_operators"]}


@router.post("/workspaces/{workspace_id}/entity")
async def add_entity_to_workspace(
    workspace_id: str,
    entity_id: str = Body(...),
    operator_id: str = Body(default="system"),
    operator_name: str = Body(default=""),
):
    """Add an entity to the investigation via shared workspace. Broadcasts to all."""
    ws = _workspaces.get(workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ws["version"] += 1
    event = {
        "event_type": "entity_added",
        "workspace_id": workspace_id,
        "entity_id": entity_id,
        "operator_id": operator_id,
        "operator_name": operator_name,
        "version": ws["version"],
    }
    _add_workspace_event(ws, event)
    await _broadcast_workspace_event(workspace_id, event)

    return {"ok": True, "entity_id": entity_id, "version": ws["version"]}


@router.post("/workspaces/{workspace_id}/annotate")
async def annotate_in_workspace(
    workspace_id: str,
    entity_id: str = Body(...),
    note: str = Body(...),
    operator_id: str = Body(default="system"),
    operator_name: str = Body(default=""),
):
    """Add an annotation in the shared workspace. Broadcasts to all operators."""
    ws = _workspaces.get(workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not note or not note.strip():
        raise HTTPException(status_code=400, detail="Note is required")

    ws["version"] += 1
    event = {
        "event_type": "annotation_added",
        "workspace_id": workspace_id,
        "entity_id": entity_id,
        "note": _sanitize(note.strip(), _MAX_CHAT_LEN),
        "operator_id": operator_id,
        "operator_name": operator_name,
        "version": ws["version"],
    }
    _add_workspace_event(ws, event)
    await _broadcast_workspace_event(workspace_id, event)

    return {"ok": True, "entity_id": entity_id, "version": ws["version"]}


@router.post("/workspaces/{workspace_id}/status")
async def change_workspace_status(
    workspace_id: str,
    new_status: str = Body(...),
    operator_id: str = Body(default="system"),
    operator_name: str = Body(default=""),
):
    """Change investigation status via shared workspace. Broadcasts to all."""
    ws = _workspaces.get(workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    valid_statuses = {"open", "closed", "archived", "in_progress", "review"}
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Valid: {valid_statuses}")

    ws["version"] += 1
    event = {
        "event_type": "status_changed",
        "workspace_id": workspace_id,
        "new_status": new_status,
        "operator_id": operator_id,
        "operator_name": operator_name,
        "version": ws["version"],
    }
    _add_workspace_event(ws, event)
    await _broadcast_workspace_event(workspace_id, event)

    return {"ok": True, "new_status": new_status, "version": ws["version"]}


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str):
    """Delete a shared workspace."""
    if workspace_id not in _workspaces:
        raise HTTPException(status_code=404, detail="Workspace not found")
    del _workspaces[workspace_id]
    return {"ok": True, "workspace_id": workspace_id}


# ---------------------------------------------------------------------------
# Map drawing collaboration endpoints
# ---------------------------------------------------------------------------

class CreateDrawingRequest(BaseModel):
    drawing_type: str = "freehand"
    operator_id: str
    operator_name: str = ""
    color: str = "#00f0ff"
    coordinates: list[list[float]] = Field(default_factory=list)
    radius: Optional[float] = None
    text: Optional[str] = None
    label: Optional[str] = None
    line_width: float = 2.0
    opacity: float = 0.8
    layer: str = "default"
    persistent: bool = False


@router.post("/drawings")
async def create_drawing(req: CreateDrawingRequest):
    """Create a map drawing. Broadcasts to all operators in real time."""
    if len(_drawings) >= _MAX_DRAWINGS:
        # Remove oldest non-persistent drawing
        non_persistent = [
            (did, d) for did, d in _drawings.items() if not d.get("persistent")
        ]
        if non_persistent:
            non_persistent.sort(key=lambda x: x[1].get("created_at", 0))
            del _drawings[non_persistent[0][0]]
        else:
            raise HTTPException(status_code=429, detail="Maximum drawing limit reached")

    valid_types = {
        "freehand", "line", "circle", "rectangle", "polygon",
        "measurement", "geofence", "text", "arrow",
    }
    if req.drawing_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid drawing type. Valid: {valid_types}")

    if len(req.coordinates) > _MAX_DRAWING_POINTS:
        raise HTTPException(status_code=400, detail=f"Too many points (max {_MAX_DRAWING_POINTS})")

    drawing_id = str(uuid.uuid4())[:12]
    now = time.time()
    drawing = {
        "drawing_id": drawing_id,
        "drawing_type": req.drawing_type,
        "operator_id": req.operator_id,
        "operator_name": req.operator_name,
        "color": req.color[:20],
        "coordinates": req.coordinates,
        "radius": req.radius,
        "text": _sanitize(req.text, _MAX_LABEL_LEN) if req.text else None,
        "label": _sanitize(req.label, _MAX_LABEL_LEN) if req.label else None,
        "line_width": max(0.5, min(20.0, req.line_width)),
        "opacity": max(0.0, min(1.0, req.opacity)),
        "layer": req.layer[:50],
        "persistent": req.persistent,
        "created_at": now,
        "updated_at": now,
    }
    _drawings[drawing_id] = drawing

    # Broadcast to all operators
    await _broadcast_drawing_event("drawing_created", drawing)

    return drawing


@router.get("/drawings")
async def list_drawings(
    layer: Optional[str] = Query(None),
    operator_id: Optional[str] = Query(None),
):
    """List all map drawings, optionally filtered by layer or operator."""
    result = list(_drawings.values())
    if layer:
        result = [d for d in result if d.get("layer") == layer]
    if operator_id:
        result = [d for d in result if d.get("operator_id") == operator_id]
    return {"drawings": result, "total": len(result)}


@router.put("/drawings/{drawing_id}")
async def update_drawing(
    drawing_id: str,
    coordinates: list[list[float]] = Body(default=None),
    color: Optional[str] = Body(default=None),
    label: Optional[str] = Body(default=None),
    text: Optional[str] = Body(default=None),
    opacity: Optional[float] = Body(default=None),
    operator_id: str = Body(default="system"),
):
    """Update a map drawing. Broadcasts the update to all operators."""
    drawing = _drawings.get(drawing_id)
    if drawing is None:
        raise HTTPException(status_code=404, detail="Drawing not found")

    if coordinates is not None:
        if len(coordinates) > _MAX_DRAWING_POINTS:
            raise HTTPException(status_code=400, detail=f"Too many points (max {_MAX_DRAWING_POINTS})")
        drawing["coordinates"] = coordinates
    if color is not None:
        drawing["color"] = color[:20]
    if label is not None:
        drawing["label"] = _sanitize(label, _MAX_LABEL_LEN)
    if text is not None:
        drawing["text"] = _sanitize(text, _MAX_LABEL_LEN)
    if opacity is not None:
        drawing["opacity"] = max(0.0, min(1.0, opacity))
    drawing["updated_at"] = time.time()

    await _broadcast_drawing_event("drawing_updated", drawing)

    return drawing


@router.delete("/drawings/{drawing_id}")
async def delete_drawing(drawing_id: str, operator_id: str = Query(default="system")):
    """Delete a map drawing. Broadcasts deletion to all operators."""
    drawing = _drawings.get(drawing_id)
    if drawing is None:
        raise HTTPException(status_code=404, detail="Drawing not found")

    del _drawings[drawing_id]
    await _broadcast_drawing_event("drawing_deleted", {
        "drawing_id": drawing_id,
        "operator_id": operator_id,
    })

    return {"ok": True, "drawing_id": drawing_id}


@router.delete("/drawings")
async def clear_drawings(
    layer: Optional[str] = Query(None),
    operator_id: Optional[str] = Query(None),
    persistent_only: bool = Query(False),
):
    """Clear map drawings, optionally filtered by layer or operator."""
    to_remove = []
    for did, d in _drawings.items():
        if layer and d.get("layer") != layer:
            continue
        if operator_id and d.get("operator_id") != operator_id:
            continue
        if persistent_only and not d.get("persistent"):
            continue
        to_remove.append(did)

    for did in to_remove:
        del _drawings[did]

    await _broadcast_drawing_event("drawings_cleared", {
        "count": len(to_remove),
        "layer": layer,
        "operator_id": operator_id,
    })

    return {"ok": True, "removed": len(to_remove)}


# ---------------------------------------------------------------------------
# Operator chat endpoints
# ---------------------------------------------------------------------------

class ChatMessageRequest(BaseModel):
    operator_id: str
    operator_name: str = ""
    content: str
    message_type: str = "text"
    channel: str = "general"
    workspace_id: Optional[str] = None


@router.post("/chat")
async def send_chat_message(req: ChatMessageRequest):
    """Send a chat message. Broadcasts to all operators and stores in audit log."""
    if not req.content or not req.content.strip():
        raise HTTPException(status_code=400, detail="Message content is required")

    valid_types = {"text", "alert", "system", "command"}
    if req.message_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid message type. Valid: {valid_types}")

    message_id = str(uuid.uuid4())[:12]
    message = {
        "message_id": message_id,
        "operator_id": req.operator_id,
        "operator_name": req.operator_name,
        "message_type": req.message_type,
        "content": _sanitize(req.content.strip(), _MAX_CHAT_LEN),
        "timestamp": time.time(),
        "channel": req.channel[:50],
        "workspace_id": req.workspace_id,
    }

    # Store in history
    channel = req.channel
    if channel not in _chat_history:
        _chat_history[channel] = deque(maxlen=_MAX_CHAT_HISTORY)
    _chat_history[channel].append(message)

    # Broadcast to all operators
    await _broadcast_chat_message(message)

    # Log to audit
    try:
        from app.routers.audit import _store
        if _store is not None:
            _store.append({
                "type": "operator_chat",
                "operator_id": req.operator_id,
                "operator_name": req.operator_name,
                "content": message["content"],
                "channel": channel,
                "timestamp": message["timestamp"],
            })
    except Exception:
        pass  # Audit logging is non-critical

    return message


@router.get("/chat")
async def get_chat_history(
    channel: str = Query("general"),
    limit: int = Query(50, ge=1, le=500),
    since: Optional[float] = Query(None, description="Only messages after this timestamp"),
):
    """Get chat message history for a channel."""
    history = _chat_history.get(channel, deque())
    messages = list(history)

    if since is not None:
        messages = [m for m in messages if m["timestamp"] > since]

    # Return most recent messages
    messages = messages[-limit:]

    return {"messages": messages, "channel": channel, "total": len(messages)}


@router.get("/chat/channels")
async def list_chat_channels():
    """List active chat channels with message counts."""
    channels = []
    for channel, msgs in _chat_history.items():
        channels.append({
            "channel": channel,
            "message_count": len(msgs),
            "last_message": msgs[-1]["timestamp"] if msgs else 0,
        })
    channels.sort(key=lambda c: c["last_message"], reverse=True)
    return {"channels": channels}


# ---------------------------------------------------------------------------
# WebSocket broadcast helpers
# ---------------------------------------------------------------------------

async def _broadcast_workspace_event(workspace_id: str, event_data: dict):
    """Broadcast a workspace event to all WebSocket clients."""
    try:
        from app.routers.ws import manager
        from datetime import datetime

        await manager.broadcast({
            "type": "workspace_event",
            "workspace_id": workspace_id,
            "data": event_data,
            "timestamp": datetime.now(tz=None).isoformat(),
        })
    except Exception as e:
        logger.debug(f"Workspace broadcast failed: {e}")


async def _broadcast_drawing_event(event_type: str, drawing_data: dict):
    """Broadcast a map drawing event to all WebSocket clients."""
    try:
        from app.routers.ws import manager
        from datetime import datetime

        await manager.broadcast({
            "type": "map_drawing",
            "event": event_type,
            "data": drawing_data,
            "timestamp": datetime.now(tz=None).isoformat(),
        })
    except Exception as e:
        logger.debug(f"Drawing broadcast failed: {e}")


async def _broadcast_chat_message(message: dict):
    """Broadcast a chat message to all WebSocket clients."""
    try:
        from app.routers.ws import manager
        from datetime import datetime

        await manager.broadcast({
            "type": "operator_chat",
            "data": message,
            "timestamp": datetime.now(tz=None).isoformat(),
        })
    except Exception as e:
        logger.debug(f"Chat broadcast failed: {e}")


def _add_workspace_event(ws: dict, event: dict):
    """Add an event to the workspace's recent event list (capped)."""
    event["timestamp"] = time.time()
    event["event_id"] = str(uuid.uuid4())[:8]
    ws["recent_events"].append(event)
    if len(ws["recent_events"]) > _MAX_WORKSPACE_EVENTS:
        ws["recent_events"] = ws["recent_events"][-_MAX_WORKSPACE_EVENTS:]
