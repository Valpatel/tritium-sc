# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""GISLayersPlugin — manage geographic data sources for the Command Center.

Provides a registry of GIS layer providers (tile servers, vector feature
sources) and exposes them through REST endpoints. Implements both
PluginInterface (lifecycle) and acts as a data provider for the map
frontend.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

from .providers import (
    BBox,
    BuildingFootprintProvider,
    LayerProvider,
    OSMTileProvider,
    SatelliteProvider,
    TerrainProvider,
)

log = logging.getLogger("gis-layers")


class GISLayersPlugin(PluginInterface):
    """Geographic data source management plugin.

    Maintains a registry of LayerProvider instances and exposes them
    through /api/gis/* endpoints for the layers panel.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._app: Any = None
        self._logger: logging.Logger = log
        self._running = False

        # layer_id -> LayerProvider
        self._providers: dict[str, LayerProvider] = {}

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.gis-layers"

    @property
    def name(self) -> str:
        return "GIS Layers"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "ui"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        """Store references, register built-in providers, and mount routes."""
        self._event_bus = ctx.event_bus
        self._app = ctx.app
        self._logger = ctx.logger or log

        # Register built-in providers
        self.register_provider(OSMTileProvider())
        self.register_provider(SatelliteProvider())
        self.register_provider(BuildingFootprintProvider())
        self.register_provider(TerrainProvider())

        self._register_routes()
        self._logger.info(
            "GIS Layers plugin configured (%d providers)", len(self._providers)
        )

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._logger.info("GIS Layers plugin started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._logger.info("GIS Layers plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Provider registry -------------------------------------------------

    def register_provider(self, provider: LayerProvider) -> None:
        """Register a layer provider.

        Args:
            provider: LayerProvider instance to register.

        Raises:
            ValueError: If a provider with the same layer_id already exists.
        """
        lid = provider.layer_id
        if lid in self._providers:
            raise ValueError(f"Layer provider '{lid}' already registered")
        self._providers[lid] = provider

    def remove_provider(self, layer_id: str) -> None:
        """Remove a provider by layer_id.

        Raises:
            KeyError: If provider does not exist.
        """
        if layer_id not in self._providers:
            raise KeyError(f"Layer provider '{layer_id}' not found")
        del self._providers[layer_id]

    def get_provider(self, layer_id: str) -> LayerProvider | None:
        """Return a provider by layer_id, or None."""
        return self._providers.get(layer_id)

    def list_layers(self) -> list[dict[str, Any]]:
        """Return metadata dicts for all registered layers."""
        return [p.to_dict() for p in self._providers.values()]

    def get_tile_url(self, layer_id: str, z: int, x: int, y: int) -> str | None:
        """Get the upstream tile URL for a tile layer."""
        provider = self._providers.get(layer_id)
        if provider is None:
            return None
        return provider.tile_url(z, x, y)

    def query_features(
        self, layer_id: str, bounds: BBox
    ) -> dict[str, Any] | None:
        """Query features from a provider. Returns None if layer not found."""
        provider = self._providers.get(layer_id)
        if provider is None:
            return None
        return provider.query(bounds)

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return
        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
