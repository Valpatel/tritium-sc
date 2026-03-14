# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Notifications API — list and manage cross-plugin notifications.

Endpoints:
    GET  /api/notifications                — list notifications (optional ?unread_only, ?limit, ?since)
    POST /api/notifications/read           — mark one or all notifications as read
    GET  /api/notifications/count          — unread count (lightweight poll)
    GET  /api/notifications/preferences    — get notification preferences/rules
    PUT  /api/notifications/preferences    — update notification preferences/rules
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from engine.comms.notifications import NotificationManager

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# Module-level singleton; set externally via set_manager() during boot
_manager: NotificationManager | None = None


def get_manager() -> NotificationManager:
    """Get or create the singleton NotificationManager."""
    global _manager
    if _manager is None:
        _manager = NotificationManager()
    return _manager


def set_manager(mgr: NotificationManager) -> None:
    """Set the NotificationManager instance (wired at boot with EventBus)."""
    global _manager
    _manager = mgr


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------

class MarkReadRequest(BaseModel):
    notification_id: Optional[str] = None  # None = mark all read


class NotificationResponse(BaseModel):
    id: str
    title: str
    message: str
    severity: str
    source: str
    timestamp: float
    read: bool
    entity_id: Optional[str] = None


class CountResponse(BaseModel):
    unread: int


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(100, le=500),
    since: Optional[float] = Query(None),
):
    """List notifications, newest first."""
    mgr = get_manager()
    if unread_only:
        return mgr.get_unread()
    return mgr.get_all(limit=limit, since=since)


@router.post("/read")
async def mark_read(request: MarkReadRequest):
    """Mark a single notification or all notifications as read."""
    mgr = get_manager()
    if request.notification_id:
        found = mgr.mark_read(request.notification_id)
        if not found:
            raise HTTPException(status_code=404, detail="Notification not found")
        return {"status": "marked_read", "notification_id": request.notification_id}
    else:
        count = mgr.mark_all_read()
        return {"status": "all_marked_read", "count": count}


@router.get("/count", response_model=CountResponse)
async def unread_count():
    """Get the unread notification count (lightweight polling endpoint)."""
    mgr = get_manager()
    return CountResponse(unread=mgr.count_unread())


# ------------------------------------------------------------------
# Notification preferences (per-type enable/disable + severity)
# ------------------------------------------------------------------

# In-memory preferences with optional file persistence
_prefs_lock = threading.Lock()
_prefs: dict = {}
_prefs_file: Path | None = None

# Default notification type definitions
_DEFAULT_PREFS: dict = {
    "geofence_enter": {"enabled": True, "severity": "warning", "label": "Geofence Entry"},
    "geofence_exit": {"enabled": True, "severity": "info", "label": "Geofence Exit"},
    "ble_new_device": {"enabled": True, "severity": "info", "label": "New BLE Device"},
    "ble_suspicious": {"enabled": True, "severity": "warning", "label": "Suspicious BLE Device"},
    "target_new": {"enabled": True, "severity": "info", "label": "New Target Detected"},
    "target_hostile": {"enabled": True, "severity": "critical", "label": "Hostile Target"},
    "node_offline": {"enabled": True, "severity": "warning", "label": "Node Offline"},
    "node_online": {"enabled": False, "severity": "info", "label": "Node Online"},
    "battery_low": {"enabled": True, "severity": "warning", "label": "Low Battery"},
    "reid_match": {"enabled": True, "severity": "info", "label": "ReID Cross-Camera Match"},
    "threat_escalation": {"enabled": True, "severity": "critical", "label": "Threat Escalation"},
    "automation_alert": {"enabled": True, "severity": "warning", "label": "Automation Alert"},
    "system_error": {"enabled": True, "severity": "error", "label": "System Error"},
}


def _load_prefs() -> dict:
    """Load preferences from file or return defaults."""
    global _prefs
    with _prefs_lock:
        if _prefs:
            return copy.deepcopy(_prefs)
        # Try loading from file
        if _prefs_file and _prefs_file.exists():
            try:
                _prefs = json.loads(_prefs_file.read_text())
                return copy.deepcopy(_prefs)
            except Exception:
                pass
        _prefs = copy.deepcopy(_DEFAULT_PREFS)
        return copy.deepcopy(_prefs)


def _save_prefs(prefs: dict) -> None:
    """Save preferences to memory and optionally to file."""
    global _prefs
    with _prefs_lock:
        _prefs = copy.deepcopy(prefs)
        if _prefs_file:
            try:
                _prefs_file.parent.mkdir(parents=True, exist_ok=True)
                _prefs_file.write_text(json.dumps(prefs, indent=2))
            except Exception:
                pass


def set_prefs_file(path: str | Path) -> None:
    """Set the file path for persistent preference storage."""
    global _prefs_file
    _prefs_file = Path(path)


class PreferenceUpdate(BaseModel):
    """Update for a single notification type preference."""
    enabled: Optional[bool] = None
    severity: Optional[str] = None


@router.get("/preferences")
async def get_preferences():
    """Get all notification type preferences.

    Returns a dict of notification_type -> {enabled, severity, label}.
    """
    return _load_prefs()


@router.put("/preferences")
async def update_preferences(updates: dict[str, PreferenceUpdate]):
    """Update notification preferences for specific types.

    Body is a dict of notification_type -> {enabled?: bool, severity?: str}.
    Only provided fields are updated; others remain unchanged.
    """
    prefs = _load_prefs()
    valid_severities = {"debug", "info", "warning", "error", "critical"}

    for ntype, update in updates.items():
        if ntype not in prefs:
            # Allow adding new custom types
            prefs[ntype] = {"enabled": True, "severity": "info", "label": ntype}

        if update.enabled is not None:
            prefs[ntype]["enabled"] = update.enabled
        if update.severity is not None:
            if update.severity not in valid_severities:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid severity '{update.severity}'. "
                           f"Must be one of: {', '.join(sorted(valid_severities))}",
                )
            prefs[ntype]["severity"] = update.severity

    _save_prefs(prefs)
    return {"status": "updated", "preferences": prefs}


@router.post("/preferences/reset")
async def reset_preferences():
    """Reset all notification preferences to defaults."""
    defaults = copy.deepcopy(_DEFAULT_PREFS)
    _save_prefs(defaults)
    return {"status": "reset", "preferences": defaults}
