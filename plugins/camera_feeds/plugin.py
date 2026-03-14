# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""CameraFeedsPlugin — unified multi-source camera management.

Manages camera sources of multiple types (synthetic, RTSP, MJPEG, MQTT,
USB) through a single plugin interface. Each source type is handled by
a concrete CameraSourceBase implementation.

Replaces the standalone synthetic_feed router with a generic system that
can ingest frames from any camera type and serve them through a uniform
REST API.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from engine.plugins.base import PluginContext, PluginInterface

from .sources import (
    CameraSourceBase,
    CameraSourceConfig,
    MQTTSource,
    SOURCE_TYPES,
)

log = logging.getLogger("camera-feeds")


class CameraFeedsPlugin(PluginInterface):
    """Unified camera feed manager plugin.

    Supports synthetic, RTSP, MJPEG, MQTT, and USB camera sources
    through a common interface.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._app: Any = None
        self._logger: logging.Logger = log
        self._sources: dict[str, CameraSourceBase] = {}
        self._running = False

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.camera-feeds"

    @property
    def name(self) -> str:
        return "Camera Feeds"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "ui", "bridge"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        """Store references and register routes."""
        self._event_bus = ctx.event_bus
        self._app = ctx.app
        self._logger = ctx.logger or log
        self._register_routes()
        self._logger.info("Camera Feeds plugin configured")

    def start(self) -> None:
        """Start all registered camera sources."""
        if self._running:
            return
        self._running = True
        for source in self._sources.values():
            source.start()
        self._logger.info(
            "Camera Feeds plugin started (%d sources)", len(self._sources)
        )

    def stop(self) -> None:
        """Stop all camera sources."""
        if not self._running:
            return
        self._running = False
        for source in self._sources.values():
            source.stop()
        self._logger.info("Camera Feeds plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Source management -------------------------------------------------

    def register_source(self, config: CameraSourceConfig) -> CameraSourceBase:
        """Register a new camera source.

        Args:
            config: Source configuration.

        Returns:
            The created CameraSourceBase instance.

        Raises:
            ValueError: If source_id already exists or source_type unknown.
        """
        if config.source_id in self._sources:
            raise ValueError(f"Source '{config.source_id}' already exists")

        source_cls = SOURCE_TYPES.get(config.source_type)
        if source_cls is None:
            raise ValueError(
                f"Unknown source type '{config.source_type}'. "
                f"Valid types: {', '.join(SOURCE_TYPES)}"
            )

        source = source_cls(config)

        # Wire up MQTT sources with the event bus
        if isinstance(source, MQTTSource) and self._event_bus:
            source.set_event_bus(self._event_bus)

        self._sources[config.source_id] = source

        # Auto-start if plugin is already running
        if self._running:
            source.start()

        if self._logger:
            self._logger.info(
                "Registered camera source: %s (type=%s)",
                config.source_id, config.source_type,
            )
        return source

    def remove_source(self, source_id: str) -> None:
        """Remove and stop a camera source.

        Args:
            source_id: Source identifier.

        Raises:
            KeyError: If source does not exist.
        """
        source = self._sources.pop(source_id, None)
        if source is None:
            raise KeyError(f"Source '{source_id}' not found")
        source.stop()
        if self._logger:
            self._logger.info("Removed camera source: %s", source_id)

    def list_sources(self) -> list[dict]:
        """List all camera sources with metadata."""
        return [s.to_dict() for s in self._sources.values()]

    def get_source(self, source_id: str) -> CameraSourceBase | None:
        """Get a specific camera source."""
        return self._sources.get(source_id)

    def get_frame(self, source_id: str) -> np.ndarray | None:
        """Get the latest frame from a source.

        Args:
            source_id: Source identifier.

        Returns:
            BGR numpy array, or None.

        Raises:
            KeyError: If source does not exist.
        """
        source = self._sources.get(source_id)
        if source is None:
            raise KeyError(f"Source '{source_id}' not found")
        return source.get_frame()

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        """Register FastAPI routes for the camera feeds API."""
        if not self._app:
            return
        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
