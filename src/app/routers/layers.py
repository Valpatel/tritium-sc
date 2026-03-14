# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""API endpoints for the data provider layer registry.

Exposes registered data-provider layers for map rendering:
    GET  /api/layers              — list all registered layers
    POST /api/layers/{name}/toggle — show/hide a layer
    GET  /api/layers/{name}/data  — get GeoJSON for a layer viewport
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from engine.plugins.data_provider import Bounds
from engine.plugins.layer_registry import LayerRegistry

router = APIRouter(prefix="/api/layers", tags=["layers"])

# ---------------------------------------------------------------------------
# Singleton registry — populated by plugins during boot
# ---------------------------------------------------------------------------

_registry = LayerRegistry()


def get_registry() -> LayerRegistry:
    """Return the global LayerRegistry singleton.

    Plugins call this during configure() to register their layers.
    """
    return _registry


def set_registry(registry: LayerRegistry) -> None:
    """Replace the global registry (useful for testing)."""
    global _registry
    _registry = registry


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class ToggleRequest(BaseModel):
    """Request body for layer toggle."""
    visible: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_layers():
    """List all registered data-provider layers."""
    return _registry.list_layers()


@router.post("/{name}/toggle")
async def toggle_layer(name: str, body: ToggleRequest):
    """Show or hide a layer on the map."""
    try:
        _registry.toggle_layer(name, body.visible)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Layer not found: {name}")
    return {"layer_name": name, "visible": body.visible}


@router.get("/{name}/data")
async def get_layer_data(
    name: str,
    south: float | None = Query(None),
    west: float | None = Query(None),
    north: float | None = Query(None),
    east: float | None = Query(None),
):
    """Get GeoJSON FeatureCollection for a layer, optionally within bounds."""
    bounds = None
    if all(v is not None for v in (south, west, north, east)):
        bounds = Bounds(south=south, west=west, north=north, east=east)

    try:
        return await _registry.get_layer_data(name, bounds=bounds)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Layer not found: {name}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
