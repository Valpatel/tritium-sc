# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Notifications API — list and manage cross-plugin notifications.

Endpoints:
    GET  /api/notifications           — list notifications (optional ?unread_only, ?limit, ?since)
    POST /api/notifications/read      — mark one or all notifications as read
    GET  /api/notifications/count     — unread count (lightweight poll)
"""

from __future__ import annotations

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
