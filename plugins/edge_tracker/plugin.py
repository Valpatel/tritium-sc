# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""EdgeTrackerPlugin — BLE and WiFi device tracking from tritium-edge sensor nodes.

Bridges fleet BLE and WiFi presence data into the command center's EventBus and
TargetTracker for live visualization on the map.  Uses tritium-lib's
shared BleStore for persistence.
"""

from __future__ import annotations

import logging
import os
import queue as queue_mod
import threading
import time
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

# BleStore import — may fail if tritium-lib is not installed yet.
try:
    from tritium_lib.store.ble import BleStore
except ImportError:  # pragma: no cover
    BleStore = None  # type: ignore[assignment,misc]

log = logging.getLogger("edge-tracker")


class EdgeTrackerPlugin(PluginInterface):
    """BLE and WiFi device tracking from tritium-edge sensor nodes.

    Uses tritium-lib's shared BleStore for persistence.
    Bridges fleet BLE and WiFi presence data into the command center's
    EventBus and TargetTracker for live visualization on the map.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None
        self._store: Any = None

        self._running = False
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_thread: Optional[threading.Thread] = None

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.edge-tracker"

    @property
    def name(self) -> str:
        return "Edge Tracker"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"bridge", "data_source", "routes", "ui"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        """Store references and initialize BleStore + routes."""
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._app = ctx.app
        self._logger = ctx.logger or log

        # Initialize BleStore at data/ble_sightings.db
        if BleStore is not None:
            db_dir = os.path.join(os.getcwd(), "data")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "ble_sightings.db")
            self._store = BleStore(db_path)
            self._logger.info("BleStore opened at %s", db_path)
        else:
            self._logger.warning(
                "tritium_lib.store.ble not available — "
                "BLE persistence disabled"
            )

        # Register FastAPI routes
        self._register_routes()

        self._logger.info("Edge Tracker plugin configured")

    def start(self) -> None:
        """Start background polling of fleet bridge BLE data."""
        if self._running:
            return
        self._running = True

        # Subscribe to EventBus for fleet events
        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_thread = threading.Thread(
                target=self._event_drain_loop,
                daemon=True,
                name="edge-tracker-events",
            )
            self._event_thread.start()

        self._logger.info("Edge Tracker plugin started")

    def stop(self) -> None:
        """Clean up resources."""
        if not self._running:
            return
        self._running = False

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        if self._store is not None:
            self._store.close()

        self._logger.info("Edge Tracker plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Event handling ----------------------------------------------------

    def _event_drain_loop(self) -> None:
        """Background loop: drain EventBus for fleet BLE events."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.5)
                self._handle_event(event)
            except queue_mod.Empty:
                pass
            except Exception as exc:
                log.error("Edge tracker event error: %s", exc)

    def _handle_event(self, event: dict) -> None:
        """Process a single EventBus event."""
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type == "fleet.ble_presence":
            self._on_ble_presence(data)
        elif event_type == "fleet.wifi_presence":
            self._on_wifi_presence(data)
        elif event_type == "fleet.heartbeat":
            self._on_fleet_heartbeat(data)

    def _on_ble_presence(self, data: dict) -> None:
        """Handle fleet.ble_presence — record sightings and emit update."""
        if self._store is None:
            return

        devices = data.get("devices", [])
        node_id = data.get("node_id", "unknown")
        node_ip = data.get("node_ip", "")

        sightings = []
        for dev in devices:
            sightings.append({
                "mac": dev.get("mac", ""),
                "name": dev.get("name", ""),
                "rssi": dev.get("rssi", -100),
                "node_id": node_id,
                "node_ip": node_ip,
                "is_known": dev.get("is_known", False),
                "seen_count": dev.get("seen_count", 1),
            })

        if sightings:
            self._store.record_sightings_batch(sightings)

        self._emit_ble_update()

    def _on_wifi_presence(self, data: dict) -> None:
        """Handle fleet.wifi_presence — record sightings and emit update."""
        if self._store is None:
            return

        networks = data.get("networks", [])
        node_id = data.get("node_id", "unknown")

        sightings = []
        for net in networks:
            sightings.append({
                "ssid": net.get("ssid", ""),
                "bssid": net.get("bssid", ""),
                "rssi": net.get("rssi", -100),
                "channel": net.get("channel", 0),
                "auth_type": net.get("auth_type", ""),
                "node_id": node_id,
            })

        if sightings:
            self._store.record_wifi_sightings_batch(sightings)

        self._emit_wifi_update()

    def _on_fleet_heartbeat(self, data: dict) -> None:
        """Handle fleet.heartbeat — extract embedded BLE and WiFi data if present."""
        if self._store is None:
            return

        node_id = data.get("node_id", data.get("id", "unknown"))
        node_ip = data.get("ip", "")

        # -- BLE data --
        ble_data = data.get("ble", data.get("ble_devices", []))
        if ble_data:
            sightings = []
            for dev in ble_data:
                sightings.append({
                    "mac": dev.get("mac", ""),
                    "name": dev.get("name", ""),
                    "rssi": dev.get("rssi", -100),
                    "node_id": node_id,
                    "node_ip": node_ip,
                    "is_known": dev.get("is_known", False),
                    "seen_count": dev.get("seen_count", 1),
                })
            if sightings:
                self._store.record_sightings_batch(sightings)
                self._emit_ble_update()

        # -- WiFi data --
        wifi_data = data.get("wifi", data.get("wifi_networks", []))
        if wifi_data:
            wifi_sightings = []
            for net in wifi_data:
                wifi_sightings.append({
                    "ssid": net.get("ssid", ""),
                    "bssid": net.get("bssid", ""),
                    "rssi": net.get("rssi", -100),
                    "channel": net.get("channel", 0),
                    "auth_type": net.get("auth_type", ""),
                    "node_id": node_id,
                })
            if wifi_sightings:
                self._store.record_wifi_sightings_batch(wifi_sightings)
                self._emit_wifi_update()

    def _emit_ble_update(self) -> None:
        """Emit edge:ble_update with current active devices."""
        if self._event_bus is None or self._store is None:
            return

        try:
            active = self._store.get_active_devices()
            self._event_bus.publish("edge:ble_update", data={
                "devices": active,
                "count": len(active),
                "timestamp": time.time(),
            })
        except Exception as exc:
            log.error("Failed to emit BLE update: %s", exc)

    def _emit_wifi_update(self) -> None:
        """Emit edge:wifi_update with current active WiFi networks."""
        if self._event_bus is None or self._store is None:
            return

        try:
            active = self._store.get_active_wifi_networks()
            self._event_bus.publish("edge:wifi_update", data={
                "networks": active,
                "count": len(active),
                "timestamp": time.time(),
            })
        except Exception as exc:
            log.error("Failed to emit WiFi update: %s", exc)

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        """Register FastAPI routes for the BLE and WiFi tracker API."""
        if not self._app:
            return

        from .routes import create_router

        router, wifi_router = create_router(self._store)
        self._app.include_router(router)
        self._app.include_router(wifi_router)
