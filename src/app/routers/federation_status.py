# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Federation status API.

Endpoints:
    GET /api/federation/status — multi-site federation status
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/federation", tags=["federation"])


def _get_federation(request: Request):
    """Get FederationManager from app state or plugin manager."""
    # Direct app state
    fm = getattr(request.app.state, "federation_manager", None)
    if fm is not None:
        return fm

    # Try plugin manager
    pm = getattr(request.app.state, "plugin_manager", None)
    if pm is not None:
        try:
            plugin = pm.get_plugin("federation")
            if plugin is not None:
                return getattr(plugin, "federation_manager", None)
        except Exception:
            pass

    return None


@router.get("/status")
async def federation_status(request: Request):
    """Federation status.

    Returns whether multi-site federation is active, the local site
    identity, number of connected remote sites, and received target counts.
    """
    fm = _get_federation(request)
    if fm is None:
        return {
            "status": "stopped",
            "available": False,
            "local_site_id": "",
            "local_site_name": "",
            "connected_sites": 0,
            "received_targets": 0,
        }

    try:
        return {
            "status": "running",
            "available": True,
            "local_site_id": fm.local_site_id,
            "local_site_name": fm.local_site_name,
            "connected_sites": fm.site_count,
            "received_targets": len(getattr(fm, "_received_targets", {})),
        }
    except Exception as e:
        logger.warning("Federation status error: %s", e)
        return {
            "status": "error",
            "available": False,
            "error": str(e),
        }
