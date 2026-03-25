# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""CitySimPlugin — city simulation as a proper SC plugin.

Manages city simulation lifecycle: load OSM data, spawn vehicles and
pedestrians, generate sensor data, feed the target tracker. Exposes
API routes for control and configuration.

Frontend JS modules handle rendering (map3d.js + sim/*.js).
This plugin handles the backend: API, config, sensor bridge.
"""

from __future__ import annotations

import logging
from typing import Any

from engine.plugins.base import PluginContext, PluginInterface

log = logging.getLogger("city-sim")


class CitySimPlugin(PluginInterface):
    """City simulation plugin for the Command Center."""

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._app: Any = None
        self._logger: logging.Logger = log
        self._running = False
        self._config = {
            "max_vehicles": 200,
            "max_pedestrians": 100,
            "radius": 300,
            "auto_start": False,
            "sensor_bridge_enabled": False,
            "time_scale": 60,
        }

    @property
    def plugin_id(self) -> str:
        return "tritium.city-sim"

    @property
    def name(self) -> str:
        return "City Simulation"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"routes", "ui", "data_source"}

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._app = ctx.app
        self._logger = ctx.logger or log

        self._register_routes()
        self._logger.info("City Simulation plugin configured")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._logger.info("City Simulation plugin started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._logger.info("City Simulation plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    def _register_routes(self) -> None:
        if not self._app:
            return
        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
