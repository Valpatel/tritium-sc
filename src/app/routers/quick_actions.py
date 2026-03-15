# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Quick tactical actions API — one-click operations on targets.

Provides a single endpoint that dispatches to the correct subsystem:
- investigate -> creates investigation
- watch -> adds to watchlist
- classify -> overrides alliance classification
- track -> enables prediction cones
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/quick-actions", tags=["quick-actions"])


class QuickActionRequest(BaseModel):
    """One-click tactical action on a target."""
    action_type: str = Field(..., description="investigate|watch|classify|track|dismiss|escalate")
    target_id: str = Field(..., max_length=200)
    params: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2000)


class QuickActionResponse(BaseModel):
    """Result of a quick action."""
    action_id: str
    action_type: str
    target_id: str
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


# In-memory action log (recent actions for dashboard display)
_action_log: list[dict] = []
_MAX_LOG = 500


def _log_action(action: dict) -> None:
    """Append to the in-memory action log, trimming if needed."""
    _action_log.append(action)
    if len(_action_log) > _MAX_LOG:
        del _action_log[: len(_action_log) - _MAX_LOG]


@router.post("", response_model=QuickActionResponse)
async def execute_quick_action(request: Request, body: QuickActionRequest):
    """Execute a quick tactical action on a target.

    Dispatches to the appropriate subsystem based on action_type.
    All actions are logged for audit trail.
    """
    action_id = str(uuid.uuid4())
    now = time.time()

    result = QuickActionResponse(
        action_id=action_id,
        action_type=body.action_type,
        target_id=body.target_id,
        status="ok",
    )

    if body.action_type == "investigate":
        result.details = await _do_investigate(request, body)
    elif body.action_type == "watch":
        result.details = await _do_watch(request, body)
    elif body.action_type == "classify":
        result.details = await _do_classify(request, body)
    elif body.action_type == "track":
        result.details = await _do_track(request, body)
    elif body.action_type == "dismiss":
        result.details = {"dismissed": True}
    elif body.action_type == "escalate":
        result.details = await _do_escalate(request, body)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action_type: {body.action_type}")

    # Log the action
    _log_action({
        "action_id": action_id,
        "action_type": body.action_type,
        "target_id": body.target_id,
        "params": body.params,
        "notes": body.notes,
        "timestamp": now,
        "result": result.details,
    })

    # Publish to event bus if available
    event_bus = getattr(request.app.state, "event_bus", None)
    if event_bus is not None:
        try:
            event_bus.publish("quick_action", {
                "action_id": action_id,
                "action_type": body.action_type,
                "target_id": body.target_id,
                "timestamp": now,
            })
        except Exception:
            pass

    return result


@router.get("/log")
async def get_action_log(limit: int = 50):
    """Get recent quick actions."""
    return {
        "actions": list(reversed(_action_log[-limit:])),
        "total": len(_action_log),
    }


async def _do_investigate(request: Request, body: QuickActionRequest) -> dict:
    """Create an investigation for this target."""
    try:
        from app.routers.investigations import _get_engine
        engine = _get_engine()
        if engine is None:
            return {"created": False, "reason": "Investigation engine not available"}
        inv = engine.create(
            title=f"Investigation: {body.target_id}",
            seed_ids=[body.target_id],
            notes=body.notes or f"Quick action investigation for target {body.target_id}",
        )
        return {"created": True, "investigation_id": inv.get("id", "")}
    except Exception as e:
        return {"created": False, "reason": str(e)}


async def _do_watch(request: Request, body: QuickActionRequest) -> dict:
    """Add target to watchlist."""
    try:
        from app.routers.watchlist import _store
        entry_id = str(uuid.uuid4())
        entry = {
            "id": entry_id,
            "target_id": body.target_id,
            "label": body.params.get("label", body.target_id),
            "notes": body.notes,
            "priority": body.params.get("priority", 2),
            "alert_on_move": True,
            "alert_on_state_change": True,
            "created_at": time.time(),
            "tags": ["quick-action"],
        }
        _store[entry_id] = entry
        return {"added": True, "watch_id": entry_id}
    except Exception as e:
        return {"added": False, "reason": str(e)}


async def _do_classify(request: Request, body: QuickActionRequest) -> dict:
    """Override target alliance classification."""
    new_alliance = body.params.get("alliance", "hostile")
    try:
        from app.routers.classification_override import _overrides
        _overrides[body.target_id] = {
            "alliance": new_alliance,
            "reason": body.notes or "Quick action override",
            "timestamp": time.time(),
        }
        return {"classified": True, "alliance": new_alliance}
    except Exception as e:
        return {"classified": False, "reason": str(e)}


async def _do_track(request: Request, body: QuickActionRequest) -> dict:
    """Enable prediction cones for this target."""
    # Publish tracking enable event to frontend via WebSocket
    event_bus = getattr(request.app.state, "event_bus", None)
    if event_bus is not None:
        try:
            event_bus.publish("track_target", {
                "target_id": body.target_id,
                "prediction_cone": True,
                "minutes_ahead": body.params.get("minutes_ahead", 5),
            })
        except Exception:
            pass
    return {
        "tracking": True,
        "prediction_cone": True,
        "minutes_ahead": body.params.get("minutes_ahead", 5),
    }


async def _do_escalate(request: Request, body: QuickActionRequest) -> dict:
    """Escalate target threat level."""
    event_bus = getattr(request.app.state, "event_bus", None)
    if event_bus is not None:
        try:
            event_bus.publish("target_escalated", {
                "target_id": body.target_id,
                "reason": body.notes or "Manual escalation",
            })
        except Exception:
            pass
    return {"escalated": True}
