# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Target watch list — curate a list of targets of interest with
real-time status tracking and movement alerts.

Watch entries persist in-memory (reset on server restart). Each entry
tracks a target ID, optional notes, alert preferences, and the last
known state snapshot.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import html
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.auth import require_auth

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"], dependencies=[Depends(require_auth)])

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
_MAX_TARGET_ID_LEN = 200
_MAX_LABEL_LEN = 200
_MAX_NOTES_LEN = 5000
_MAX_TAG_LEN = 100
_MAX_TAGS = 50
_MAX_WATCH_ENTRIES = 5000

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _sanitize(value: str, max_len: int) -> str:
    """Strip HTML tags and enforce length limit."""
    value = _HTML_TAG_RE.sub("", value)
    value = html.escape(value)
    return value[:max_len]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class WatchEntryCreate(BaseModel):
    """Add a target to the watch list."""
    target_id: str = Field(..., max_length=_MAX_TARGET_ID_LEN, description="Target ID to watch")
    label: str = Field(default="", max_length=_MAX_LABEL_LEN)
    notes: str = Field(default="", max_length=_MAX_NOTES_LEN)
    priority: int = Field(default=3, ge=1, le=5, description="1=highest, 5=lowest")
    alert_on_move: bool = True
    alert_on_state_change: bool = True
    alert_on_zone_enter: bool = False
    alert_on_zone_exit: bool = False
    tags: list[str] = Field(default_factory=list)

    @field_validator("target_id", "label", "notes")
    @classmethod
    def sanitize_strings(cls, v: str) -> str:
        return _sanitize(v, _MAX_NOTES_LEN)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        if len(v) > _MAX_TAGS:
            raise ValueError(f"Too many tags (max {_MAX_TAGS})")
        return [_sanitize(t, _MAX_TAG_LEN) for t in v]


class WatchEntryUpdate(BaseModel):
    """Update a watch entry."""
    label: Optional[str] = Field(default=None, max_length=_MAX_LABEL_LEN)
    notes: Optional[str] = Field(default=None, max_length=_MAX_NOTES_LEN)
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    alert_on_move: Optional[bool] = None
    alert_on_state_change: Optional[bool] = None
    alert_on_zone_enter: Optional[bool] = None
    alert_on_zone_exit: Optional[bool] = None
    tags: Optional[list[str]] = None

    @field_validator("label", "notes")
    @classmethod
    def sanitize_strings(cls, v):
        if v is not None:
            return _sanitize(v, _MAX_NOTES_LEN)
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v):
        if v is not None:
            if len(v) > _MAX_TAGS:
                raise ValueError(f"Too many tags (max {_MAX_TAGS})")
            return [_sanitize(t, _MAX_TAG_LEN) for t in v]
        return v


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_watch_entries: dict[str, dict[str, Any]] = {}
# Snapshots: target_id -> last known state dict
_target_snapshots: dict[str, dict[str, Any]] = {}
# Alert history: list of alert dicts
_alert_history: list[dict[str, Any]] = []
_MAX_ALERT_HISTORY = 500


def _record_alert(entry_id: str, target_id: str, alert_type: str, details: str) -> dict:
    """Record an alert event."""
    alert = {
        "id": f"wa_{uuid.uuid4().hex[:8]}",
        "entry_id": entry_id,
        "target_id": target_id,
        "type": alert_type,
        "details": details,
        "timestamp": time.time(),
    }
    _alert_history.append(alert)
    if len(_alert_history) > _MAX_ALERT_HISTORY:
        _alert_history.pop(0)
    return alert


def update_target_snapshot(target_id: str, state: dict) -> list[dict]:
    """Update the snapshot for a watched target and generate alerts.

    Called by the WebSocket event bridge or periodic polling.
    Returns list of generated alerts.
    """
    alerts = []
    old = _target_snapshots.get(target_id)
    _target_snapshots[target_id] = {
        "state": state,
        "updated_at": time.time(),
    }

    # Find watch entries for this target
    entries = [e for e in _watch_entries.values() if e["target_id"] == target_id]
    if not entries:
        return alerts

    for entry in entries:
        if old and old.get("state"):
            old_state = old["state"]
            # Movement detection
            if entry.get("alert_on_move"):
                old_pos = old_state.get("position")
                new_pos = state.get("position")
                if old_pos and new_pos:
                    dx = (new_pos.get("x", 0) - old_pos.get("x", 0))
                    dy = (new_pos.get("y", 0) - old_pos.get("y", 0))
                    dist = (dx * dx + dy * dy) ** 0.5
                    if dist > 5.0:  # moved more than 5m
                        a = _record_alert(
                            entry["id"], target_id, "movement",
                            f"Target moved {dist:.1f}m"
                        )
                        alerts.append(a)

            # State change detection
            if entry.get("alert_on_state_change"):
                old_status = old_state.get("status")
                new_status = state.get("status")
                if old_status and new_status and old_status != new_status:
                    a = _record_alert(
                        entry["id"], target_id, "state_change",
                        f"Status changed: {old_status} -> {new_status}"
                    )
                    alerts.append(a)

    return alerts


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_watch_entries():
    """List all watch list entries with latest snapshots."""
    entries = []
    for entry in _watch_entries.values():
        e = dict(entry)
        snapshot = _target_snapshots.get(entry["target_id"])
        e["last_state"] = snapshot.get("state") if snapshot else None
        e["last_seen"] = snapshot.get("updated_at") if snapshot else None
        entries.append(e)
    return {
        "entries": sorted(entries, key=lambda e: e.get("priority", 3)),
        "count": len(entries),
    }


@router.post("")
async def add_watch_entry(body: WatchEntryCreate):
    """Add a target to the watch list."""
    if len(_watch_entries) >= _MAX_WATCH_ENTRIES:
        raise HTTPException(
            status_code=429,
            detail=f"Watch list limit reached ({_MAX_WATCH_ENTRIES})",
        )
    # Check for duplicate
    for existing in _watch_entries.values():
        if existing["target_id"] == body.target_id:
            raise HTTPException(
                status_code=409,
                detail=f"Target {body.target_id} is already on the watch list"
            )

    now = time.time()
    entry_id = f"we_{uuid.uuid4().hex[:8]}"
    entry = {
        "id": entry_id,
        "target_id": body.target_id,
        "label": body.label or body.target_id,
        "notes": body.notes,
        "priority": body.priority,
        "alert_on_move": body.alert_on_move,
        "alert_on_state_change": body.alert_on_state_change,
        "alert_on_zone_enter": body.alert_on_zone_enter,
        "alert_on_zone_exit": body.alert_on_zone_exit,
        "tags": body.tags,
        "created_at": now,
        "updated_at": now,
    }
    _watch_entries[entry_id] = entry
    return entry


@router.get("/{entry_id}")
async def get_watch_entry(entry_id: str):
    """Get a single watch entry by ID."""
    entry = _watch_entries.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watch entry not found")
    e = dict(entry)
    snapshot = _target_snapshots.get(entry["target_id"])
    e["last_state"] = snapshot.get("state") if snapshot else None
    e["last_seen"] = snapshot.get("updated_at") if snapshot else None
    return e


@router.put("/{entry_id}")
async def update_watch_entry(entry_id: str, body: WatchEntryUpdate):
    """Update a watch entry."""
    entry = _watch_entries.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    updates = body.model_dump(exclude_none=True)
    if updates:
        entry.update(updates)
        entry["updated_at"] = time.time()

    return entry


@router.delete("/{entry_id}")
async def remove_watch_entry(entry_id: str):
    """Remove a target from the watch list."""
    if entry_id not in _watch_entries:
        raise HTTPException(status_code=404, detail="Watch entry not found")
    del _watch_entries[entry_id]
    return {"ok": True, "deleted": entry_id}


@router.get("/alerts/history")
async def get_alert_history(limit: int = 50):
    """Get recent watch list alerts."""
    limit = max(1, min(limit, _MAX_ALERT_HISTORY))
    return {
        "alerts": _alert_history[-limit:],
        "total": len(_alert_history),
    }


@router.delete("/alerts/clear")
async def clear_alert_history():
    """Clear all watch list alert history."""
    count = len(_alert_history)
    _alert_history.clear()
    return {"ok": True, "cleared": count}
