# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FleetDashboardPlugin — aggregated fleet device registry and dashboard API.

Subscribes to fleet.heartbeat and edge:ble_update events on the EventBus,
maintains an in-memory device registry with status tracking, and exposes
REST endpoints for the fleet dashboard frontend panel.

Devices not seen within PRUNE_TIMEOUT_S are pruned automatically.
"""

from __future__ import annotations

import logging
import queue as queue_mod
import threading
import time
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

log = logging.getLogger("fleet-dashboard")

PRUNE_TIMEOUT_S = 300  # 5 minutes


class FleetDashboardPlugin(PluginInterface):
    """Aggregated fleet device registry with dashboard API."""

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None

        self._running = False
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_thread: Optional[threading.Thread] = None
        self._prune_thread: Optional[threading.Thread] = None

        # device_id -> device info dict
        self._devices: dict[str, dict] = {}
        self._lock = threading.Lock()

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.fleet-dashboard"

    @property
    def name(self) -> str:
        return "Fleet Dashboard"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "ui"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._app = ctx.app
        self._logger = ctx.logger or log

        self._register_routes()
        self._logger.info("Fleet Dashboard plugin configured")

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_thread = threading.Thread(
                target=self._event_drain_loop,
                daemon=True,
                name="fleet-dashboard-events",
            )
            self._event_thread.start()

        self._prune_thread = threading.Thread(
            target=self._prune_loop,
            daemon=True,
            name="fleet-dashboard-prune",
        )
        self._prune_thread.start()

        self._logger.info("Fleet Dashboard plugin started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._prune_thread and self._prune_thread.is_alive():
            self._prune_thread.join(timeout=2.0)

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        self._logger.info("Fleet Dashboard plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Device registry ---------------------------------------------------

    def get_devices(self) -> list[dict]:
        """Return list of all tracked devices with computed status."""
        now = time.time()
        with self._lock:
            result = []
            for dev in self._devices.values():
                entry = dict(dev)
                age = now - entry.get("last_seen", 0)
                if age > 180:
                    entry["status"] = "offline"
                elif age > 60:
                    entry["status"] = "stale"
                else:
                    entry["status"] = "online"
                result.append(entry)
            return result

    def get_device(self, device_id: str) -> Optional[dict]:
        """Return a single device by ID, or None."""
        now = time.time()
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return None
            entry = dict(dev)
            age = now - entry.get("last_seen", 0)
            if age > 180:
                entry["status"] = "offline"
            elif age > 60:
                entry["status"] = "stale"
            else:
                entry["status"] = "online"
            return entry

    def get_summary(self) -> dict:
        """Return fleet summary: counts by status, avg battery, total sightings."""
        devices = self.get_devices()
        online = sum(1 for d in devices if d["status"] == "online")
        stale = sum(1 for d in devices if d["status"] == "stale")
        offline = sum(1 for d in devices if d["status"] == "offline")
        batteries = [
            d["battery"] for d in devices
            if d.get("battery") is not None
        ]
        avg_battery = (
            round(sum(batteries) / len(batteries), 1)
            if batteries else None
        )
        total_ble = sum(d.get("ble_count", 0) for d in devices)
        total_wifi = sum(d.get("wifi_count", 0) for d in devices)
        return {
            "total": len(devices),
            "online": online,
            "stale": stale,
            "offline": offline,
            "avg_battery": avg_battery,
            "total_ble_sightings": total_ble,
            "total_wifi_sightings": total_wifi,
        }

    # -- Event handling ----------------------------------------------------

    def _event_drain_loop(self) -> None:
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.5)
                self._handle_event(event)
            except queue_mod.Empty:
                pass
            except Exception as exc:
                log.error("Fleet dashboard event error: %s", exc)

    def _handle_event(self, event: dict) -> None:
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type == "fleet.heartbeat":
            self._on_heartbeat(data)
        elif event_type == "edge:ble_update":
            self._on_ble_update(data)

    def _on_heartbeat(self, data: dict) -> None:
        device_id = data.get("device_id", data.get("id", data.get("node_id")))
        if not device_id:
            return

        now = time.time()
        with self._lock:
            existing = self._devices.get(device_id, {})
            existing.update({
                "device_id": device_id,
                "name": data.get("name", data.get("hostname", existing.get("name", device_id))),
                "ip": data.get("ip", existing.get("ip", "")),
                "battery": data.get("battery_pct", data.get("battery", existing.get("battery"))),
                "uptime": data.get("uptime_s", data.get("uptime", existing.get("uptime"))),
                "ble_count": data.get("ble_count", data.get("ble_device_count", existing.get("ble_count", 0))),
                "wifi_count": data.get("wifi_count", data.get("wifi_network_count", existing.get("wifi_count", 0))),
                "free_heap": data.get("free_heap", existing.get("free_heap")),
                "firmware": data.get("version", data.get("firmware", existing.get("firmware", ""))),
                "rssi": data.get("rssi", data.get("wifi_rssi", existing.get("rssi"))),
                "last_seen": now,
            })
            self._devices[device_id] = existing

    def _on_ble_update(self, data: dict) -> None:
        """Handle edge:ble_update — update BLE counts for relevant devices."""
        count = data.get("count", 0)
        devices = data.get("devices", [])

        # Try to attribute BLE count to a specific device
        node_ids = set()
        for dev in devices:
            nid = dev.get("node_id")
            if nid:
                node_ids.add(nid)

        now = time.time()
        with self._lock:
            for nid in node_ids:
                if nid in self._devices:
                    self._devices[nid]["ble_count"] = count
                    self._devices[nid]["last_seen"] = now

    # -- Pruning -----------------------------------------------------------

    def _prune_loop(self) -> None:
        while self._running:
            time.sleep(30)
            self._prune_stale()

    def _prune_stale(self) -> None:
        now = time.time()
        with self._lock:
            stale_ids = [
                did for did, dev in self._devices.items()
                if now - dev.get("last_seen", 0) > PRUNE_TIMEOUT_S
            ]
            for did in stale_ids:
                del self._devices[did]
                log.debug("Pruned stale device: %s", did)

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return

        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
