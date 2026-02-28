# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Plugin management API.

Lists installed plugins, their status, capabilities, and health.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


def _get_manager(request: Request):
    """Get plugin manager from app state, or None."""
    try:
        return request.app.state.plugin_manager
    except (AttributeError, KeyError):
        return None


@router.get("")
async def list_plugins(request: Request):
    """List all registered plugins with status."""
    mgr = _get_manager(request)
    if mgr is None:
        return []
    return mgr.list_plugins()


@router.get("/health")
async def plugin_health(request: Request):
    """Health check for all running plugins."""
    mgr = _get_manager(request)
    if mgr is None:
        return {}
    return mgr.health_check()


@router.get("/{plugin_id}")
async def get_plugin(plugin_id: str, request: Request):
    """Get details for a specific plugin."""
    mgr = _get_manager(request)
    if mgr is None:
        return JSONResponse(status_code=404, content={"detail": "No plugin manager"})

    plugin = mgr.get_plugin(plugin_id)
    if plugin is None:
        return JSONResponse(status_code=404, content={"detail": f"Plugin '{plugin_id}' not found"})

    return {
        "id": plugin.plugin_id,
        "name": plugin.name,
        "version": plugin.version,
        "capabilities": sorted(plugin.capabilities),
        "dependencies": list(plugin.dependencies),
        "healthy": plugin.healthy,
    }
