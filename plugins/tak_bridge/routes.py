# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the TAK Bridge plugin.

Provides REST endpoints for:
    GET  /api/tak/status   — bridge status and stats
    GET  /api/tak/clients  — connected TAK clients
    GET  /api/tak/config   — current configuration
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from .plugin import TAKBridgePlugin


def create_router(plugin: TAKBridgePlugin) -> APIRouter:
    """Create the TAK Bridge API router."""
    router = APIRouter(prefix="/api/tak", tags=["tak"])

    @router.get("/status")
    def tak_status():
        """Return TAK Bridge status and statistics."""
        return plugin.stats

    @router.get("/clients")
    def tak_clients():
        """Return connected TAK clients."""
        clients = plugin.connected_clients
        return {
            "count": len(clients),
            "clients": list(clients.values()),
        }

    @router.get("/config")
    def tak_config():
        """Return current TAK Bridge configuration."""
        stats = plugin.stats
        return {
            "enabled": stats.get("enabled", False),
            "callsign": stats.get("callsign", ""),
            "multicast": stats.get("multicast", ""),
            "server": stats.get("server", ""),
            "site_id": stats.get("site_id", ""),
        }

    return router
