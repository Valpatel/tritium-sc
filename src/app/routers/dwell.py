# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Dwell detection API — active and historical dwell events for loitering detection."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from app.auth import optional_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dwell", tags=["dwell"])


def _get_dwell_tracker(request: Request):
    """Get the DwellTracker from app state, or None."""
    return getattr(request.app.state, "dwell_tracker", None)


@router.get("/active")
async def dwell_active(request: Request, user: dict | None = Depends(optional_auth)):
    """GET /api/dwell/active — list all currently active dwell events.

    Returns targets that have been stationary for longer than the dwell
    threshold (default 5 minutes).
    """
    tracker = _get_dwell_tracker(request)
    if tracker is None:
        return {"dwells": [], "count": 0, "source": "unavailable"}

    dwells = tracker.active_dwells
    return {
        "dwells": [d.model_dump(mode="json") for d in dwells],
        "count": len(dwells),
        "source": "live",
    }


@router.get("/history")
async def dwell_history(request: Request, user: dict | None = Depends(optional_auth)):
    """GET /api/dwell/history — list completed dwell events.

    Returns up to 200 most recent completed dwell events.
    """
    tracker = _get_dwell_tracker(request)
    if tracker is None:
        return {"dwells": [], "count": 0, "source": "unavailable"}

    history = tracker.history
    return {
        "dwells": [d.model_dump(mode="json") for d in history],
        "count": len(history),
        "source": "live",
    }


@router.get("/target/{target_id}")
async def dwell_for_target(request: Request, target_id: str, user: dict | None = Depends(optional_auth)):
    """GET /api/dwell/target/{target_id} — get active dwell for a specific target."""
    tracker = _get_dwell_tracker(request)
    if tracker is None:
        return {"dwell": None, "source": "unavailable"}

    dwell = tracker.get_dwell_for_target(target_id)
    if dwell is None:
        return {"dwell": None, "source": "live"}

    return {
        "dwell": dwell.model_dump(mode="json"),
        "source": "live",
    }
