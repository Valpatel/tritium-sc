# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FloorPlanPlugin — indoor spatial intelligence for Tritium-SC.

Manages floor plan uploads, geo-referencing, room definitions,
indoor target localization, and building occupancy tracking.
Listens for BLE trilateration and WiFi fingerprint events to
automatically assign targets to rooms.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.plugins.base import EventDrainPlugin, PluginContext

from .localizer import IndoorLocalizer
from .routes import create_router
from .store import FloorPlanStore

log = logging.getLogger("floorplan")


class FloorPlanPlugin(EventDrainPlugin):
    """Indoor spatial intelligence plugin."""

    def __init__(self) -> None:
        super().__init__()
        self._store = FloorPlanStore()
        self._localizer = IndoorLocalizer(self._store)

    # -- PluginInterface identity ----------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.floorplan"

    @property
    def name(self) -> str:
        return "Floor Plan"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "ui"}

    # -- EventDrainPlugin overrides --------------------------------------------

    def _on_configure(self, ctx: PluginContext) -> None:
        """Register routes and store references."""
        if self._app is not None:
            router = create_router(self._store)
            self._app.include_router(router)
            self._logger.info("Floor plan routes registered")

        self._logger.info("Floor Plan plugin configured")

    def _on_start(self) -> None:
        self._logger.info("Floor Plan plugin started")

    def _on_stop(self) -> None:
        self._logger.info("Floor Plan plugin stopped")

    def _handle_event(self, event: dict) -> None:
        """Process events for indoor localization.

        Listens for:
        - trilateration.position_estimate — BLE trilateration results
        - wifi_fingerprint.observation — WiFi RSSI observations
        - fleet.ble_presence — BLE sightings with position
        """
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type == "trilateration.position_estimate":
            self._handle_position_estimate(data)
        elif event_type == "wifi_fingerprint.observation":
            self._handle_wifi_observation(data)
        elif event_type == "fleet.ble_presence":
            self._handle_ble_presence(data)

    # -- Event handlers --------------------------------------------------------

    def _handle_position_estimate(self, data: dict) -> None:
        """Handle a BLE trilateration position estimate."""
        target_id = data.get("target_id") or data.get("mac", "")
        lat = data.get("lat")
        lon = data.get("lon")
        confidence = data.get("confidence", 0.5)

        if not target_id or lat is None or lon is None:
            return

        if not target_id.startswith("ble_"):
            target_id = f"ble_{target_id}"

        result = self._localizer.localize_target(
            target_id=target_id,
            lat=lat,
            lon=lon,
            confidence=confidence,
            method="trilateration",
        )

        if result and self._event_bus:
            self._event_bus.publish({
                "type": "floorplan.target_localized",
                "data": result,
            })

    def _handle_wifi_observation(self, data: dict) -> None:
        """Handle a WiFi RSSI observation for fingerprint matching."""
        target_id = data.get("target_id") or data.get("device_id", "")
        rssi_map = data.get("rssi_map", {})

        if not target_id or not rssi_map:
            return

        result = self._localizer.localize_from_fingerprint(
            target_id=target_id,
            rssi_map=rssi_map,
        )

        if result and self._event_bus:
            self._event_bus.publish({
                "type": "floorplan.target_localized",
                "data": result,
            })

    def _handle_ble_presence(self, data: dict) -> None:
        """Handle BLE presence with position data."""
        mac = data.get("mac", "")
        position = data.get("position")
        if not mac or not position:
            return

        lat = position.get("lat")
        lon = position.get("lon")
        if lat is None or lon is None:
            return

        target_id = f"ble_{mac}"
        confidence = position.get("confidence", 0.3)

        self._localizer.localize_target(
            target_id=target_id,
            lat=lat,
            lon=lon,
            confidence=confidence,
            method="ble_proximity",
        )

    # -- Public API ------------------------------------------------------------

    @property
    def store(self) -> FloorPlanStore:
        return self._store

    @property
    def localizer(self) -> IndoorLocalizer:
        return self._localizer
