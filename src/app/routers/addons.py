# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Addon management API — discover, enable, disable, list addons."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.auth import require_auth

router = APIRouter(prefix="/api/addons", tags=["addons"])


@router.get("/")
async def list_addons(request: Request):
    """List all discovered addons with their status."""
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"addons": [], "error": "Addon loader not initialized"}
    return {"addons": loader.get_all_addons()}


@router.get("/manifests")
async def get_manifests(request: Request):
    """Get frontend manifest data for all enabled addons.

    The frontend uses this to dynamically load addon panels and layers.
    """
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return []
    return loader.get_manifests()


@router.get("/geojson-layers")
async def get_geojson_layers(request: Request):
    """Return GeoJSON layer definitions from all enabled addons.

    The frontend polls this once at startup to discover which addon
    GeoJSON endpoints to render on the tactical map.
    """
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return []
    layers = []
    for addon_id in loader.enabled:
        entry = loader.registry.get(addon_id)
        if not entry or not entry.instance:
            continue
        try:
            geo_layers = entry.instance.get_geojson_layers()
            for gl in geo_layers:
                layers.append(gl.to_dict() if hasattr(gl, "to_dict") else gl)
        except Exception:
            pass
    return layers


@router.get("/health")
async def addon_health(request: Request):
    """Addon system health summary."""
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"error": "Addon loader not initialized"}
    return loader.get_health()


@router.post("/{addon_id}/enable")
async def enable_addon(addon_id: str, request: Request, _user: dict = Depends(require_auth)):
    """Enable a specific addon."""
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"error": "Addon loader not initialized"}
    ok = await loader.enable(addon_id)
    return {"addon_id": addon_id, "enabled": ok}


@router.post("/{addon_id}/disable")
async def disable_addon(addon_id: str, request: Request, _user: dict = Depends(require_auth)):
    """Disable a specific addon."""
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"error": "Addon loader not initialized"}
    ok = await loader.disable(addon_id)
    return {"addon_id": addon_id, "disabled": ok}


@router.post("/{addon_id}/reload")
async def reload_addon(addon_id: str, request: Request, _user: dict = Depends(require_auth)):
    """Hot-reload an addon: re-read manifest, purge module cache, re-enable.

    This is the key endpoint for addon development. Change code, hit reload,
    see changes without restarting the server.
    """
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"error": "Addon loader not initialized"}
    ok = await loader.reload(addon_id)
    return {
        "addon_id": addon_id,
        "reloaded": ok,
        # Return a version token the frontend can use to bust its JS module cache
        "version": int(__import__("time").time()),
    }


@router.post("/rediscover")
async def rediscover_addons(request: Request, _user: dict = Depends(require_auth)):
    """Re-scan addon directories for new addons.

    Call this after dropping a new addon folder into the addons/ directory.
    Returns list of newly discovered addon IDs.
    """
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"error": "Addon loader not initialized"}
    new_ids = loader.rediscover()
    return {"new_addons": new_ids, "total": len(loader.registry)}


@router.get("/{addon_id}/health")
async def addon_specific_health(addon_id: str, request: Request):
    """Health check for a specific addon."""
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"error": "Addon loader not initialized"}
    entry = loader.registry.get(addon_id)
    if not entry:
        return {"error": f"Unknown addon: {addon_id}"}
    if not entry.instance:
        return {"status": "not_enabled", "addon_id": addon_id}
    return entry.instance.health_check()
