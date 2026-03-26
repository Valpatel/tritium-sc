# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SitAware API — unified operating picture endpoints.

Endpoints:
    GET /api/sitaware/picture  — full OperatingPicture as JSON
    GET /api/sitaware/updates  — recent PictureUpdate deltas
    GET /api/sitaware/health   — system health for all subsystems
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sitaware", tags=["sitaware"])


def _get_engine(request: Request):
    """Get SitAwareEngine from app state, or None."""
    return getattr(request.app.state, "sitaware_engine", None)


@router.get("/picture")
async def sitaware_picture(request: Request):
    """Full operating picture — targets, alerts, anomalies, incidents,
    missions, health, analytics, zones, threat level, and summary.

    Returns the complete OperatingPicture as a JSON dict.
    """
    engine = _get_engine(request)
    if engine is None:
        return {
            "available": False,
            "error": "SitAwareEngine not initialized",
        }

    try:
        picture = engine.get_picture()
        result = picture.to_dict()
        result["available"] = True
        return result
    except Exception as e:
        logger.warning("SitAware picture error: %s", e)
        return {
            "available": False,
            "error": str(e),
        }


@router.get("/updates")
async def sitaware_updates(
    request: Request,
    since: float = Query(0.0, description="Epoch timestamp — return updates after this time"),
    limit: int = Query(100, ge=1, le=1000, description="Max updates to return"),
    type: str | None = Query(None, description="Filter by update_type (e.g. alert_fired, target_new)"),
):
    """Recent PictureUpdate deltas since a given timestamp.

    Used for incremental synchronization: fetch /picture once, then
    poll /updates?since=<picture.timestamp> for changes only.

    Optional ``type`` parameter filters to a single update_type value.
    """
    engine = _get_engine(request)
    if engine is None:
        return {
            "available": False,
            "updates": [],
            "server_time": time.time(),
        }

    try:
        updates = engine.get_updates_since(since)
        if type:
            updates = [u for u in updates if u.update_type.value == type]
        if len(updates) > limit:
            updates = updates[-limit:]
        return {
            "available": True,
            "updates": [u.to_dict() for u in updates],
            "count": len(updates),
            "server_time": time.time(),
        }
    except Exception as e:
        logger.warning("SitAware updates error: %s", e)
        return {
            "available": False,
            "updates": [],
            "error": str(e),
            "server_time": time.time(),
        }


@router.get("/status")
async def sitaware_status(request: Request):
    """Situational awareness engine status.

    Returns whether the SitAware engine is running, its uptime, and
    high-level operating picture statistics.
    """
    engine = _get_engine(request)
    if engine is None:
        return {
            "status": "stopped",
            "available": False,
            "error": "SitAwareEngine not initialized",
        }

    try:
        stats = engine.get_stats()
        sa_stats = stats.get("sitaware", {})
        return {
            "status": "running",
            "available": True,
            "targets_tracked": sa_stats.get("targets_tracked", 0),
            "active_alerts": sa_stats.get("active_alerts", 0),
            "anomalies_detected": sa_stats.get("anomalies_detected", 0),
            "threat_level": sa_stats.get("threat_level", "unknown"),
            "uptime_s": sa_stats.get("uptime_s", 0),
        }
    except Exception as e:
        logger.warning("SitAware status error: %s", e)
        return {
            "status": "error",
            "available": False,
            "error": str(e),
        }


@router.get("/health")
async def sitaware_health(request: Request):
    """System health for all subsystems monitored by the SitAwareEngine.

    Returns per-subsystem status (fusion, alerting, anomaly, analytics,
    incidents, missions) and an overall health summary.
    """
    engine = _get_engine(request)
    if engine is None:
        return {
            "available": False,
            "error": "SitAwareEngine not initialized",
        }

    try:
        health_status = engine.health.check_all()
        result = health_status.to_dict()
        result["available"] = True

        # Add high-level stats from get_stats()
        stats = engine.get_stats()
        result["sitaware_stats"] = stats.get("sitaware", {})

        return result
    except Exception as e:
        logger.warning("SitAware health error: %s", e)
        return {
            "available": False,
            "error": str(e),
        }
