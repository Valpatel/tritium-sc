# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the GIS Layers plugin.

Endpoints:
    GET  /api/gis/layers                         — list available layers
    GET  /api/gis/layers/{name}/tiles/{z}/{x}/{y} — proxy tile request
    GET  /api/gis/layers/{name}/features          — GeoJSON features for bbox
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

if TYPE_CHECKING:
    from .plugin import GISLayersPlugin

from .providers import BBox


def create_router(plugin: "GISLayersPlugin") -> APIRouter:
    """Build and return the GIS layers APIRouter."""

    router = APIRouter(prefix="/api/gis", tags=["gis-layers"])

    @router.get("/layers")
    async def list_layers():
        """List all available GIS layers with metadata."""
        layers = plugin.list_layers()
        return {"layers": layers, "count": len(layers)}

    @router.get("/layers/{name}/tiles/{z}/{x}/{y}")
    async def get_tile(name: str, z: int, x: int, y: int):
        """Redirect to the upstream tile URL for a tile layer.

        Returns 404 if the layer does not exist or is not a tile layer.
        """
        provider = plugin.get_provider(name)
        if provider is None:
            raise HTTPException(status_code=404, detail=f"Layer '{name}' not found")

        url = provider.tile_url(z, x, y)
        if url is None:
            raise HTTPException(
                status_code=400,
                detail=f"Layer '{name}' is not a tile layer",
            )

        return RedirectResponse(url=url, status_code=302)

    @router.get("/layers/{name}/features")
    async def get_features(
        name: str,
        bbox: str = Query(
            ...,
            description="Bounding box as west,south,east,north",
            examples=["10.0,48.0,10.1,48.1"],
        ),
    ):
        """Return GeoJSON features for a layer within a bounding box."""
        provider = plugin.get_provider(name)
        if provider is None:
            raise HTTPException(status_code=404, detail=f"Layer '{name}' not found")

        try:
            bounds = BBox.from_string(bbox)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid bbox: {exc}",
            )

        result = provider.query(bounds)
        return JSONResponse(content=result)

    return router
