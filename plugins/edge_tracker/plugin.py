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

# DeviceClassifier import — multi-signal BLE/WiFi device type classification.
try:
    from tritium_lib.classifier import DeviceClassifier
except ImportError:  # pragma: no cover
    DeviceClassifier = None  # type: ignore[assignment,misc]

# BLE interrogation models — GATT profile enrichment
try:
    from tritium_lib.models.ble_interrogation import (
        BleDeviceProfile as BleGATTProfile,
        BleInterrogationResult,
        classify_device_from_profile,
    )
except ImportError:  # pragma: no cover
    BleGATTProfile = None  # type: ignore[assignment,misc]
    BleInterrogationResult = None  # type: ignore[assignment,misc]
    classify_device_from_profile = None  # type: ignore[assignment]

# Geofence engine for zone checking on edge-tracked targets
try:
    from app.routers.geofence import get_engine as get_geofence_engine
except ImportError:  # pragma: no cover
    get_geofence_engine = None  # type: ignore[assignment]

from engine.tactical.ble_classifier import BLEClassifier
from engine.tactical.sensor_health_monitor import SensorHealthMonitor
from engine.tactical.target_handoff import HandoffTracker, HandoffEvent
from engine.tactical.trilateration import TrilaterationEngine

# Indoor/outdoor transition detector
try:
    from plugins.edge_tracker.transition_detector import IndoorOutdoorDetector
except ImportError:  # pragma: no cover
    IndoorOutdoorDetector = None  # type: ignore[assignment,misc]

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
        self._ble_classifier: Optional[BLEClassifier] = None
        self._device_classifier: Any = None
        self._trilateration: Optional[TrilaterationEngine] = None
        self._handoff_tracker: Optional[HandoffTracker] = None
        self._sensor_health: Optional[SensorHealthMonitor] = None
        self._transition_detector: Any = None

        self._running = False
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_thread: Optional[threading.Thread] = None
        # Cache edge-sourced device type/class per MAC (from Apple Continuity etc.)
        self._edge_device_types: dict[str, str] = {}  # mac -> device_type
        # Cache GATT interrogation profiles per MAC
        self._gatt_profiles: dict[str, Any] = {}  # mac -> BleGATTProfile dict

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

        # Initialize BLE classifier for threat classification
        if self._event_bus is not None:
            self._ble_classifier = BLEClassifier(event_bus=self._event_bus)
            self._logger.info("BLE classifier initialized")

        # Initialize DeviceClassifier for multi-signal device type classification
        if DeviceClassifier is not None:
            self._device_classifier = DeviceClassifier()
            self._logger.info("DeviceClassifier initialized (tritium-lib)")
        else:
            self._logger.warning(
                "tritium_lib.classifier not available — "
                "DeviceClassifier disabled"
            )

        # Initialize trilateration engine for multi-node position estimation
        self._trilateration = TrilaterationEngine()
        self._logger.info("Trilateration engine initialized")

        # Initialize sensor health monitor
        self._sensor_health = SensorHealthMonitor(event_bus=self._event_bus)
        self._logger.info("Sensor health monitor initialized")

        # Initialize indoor/outdoor transition detector
        if IndoorOutdoorDetector is not None:
            self._transition_detector = IndoorOutdoorDetector(event_bus=self._event_bus)
            self._logger.info("Indoor/outdoor transition detector initialized")
        else:
            self._logger.warning("IndoorOutdoorDetector not available")

        # Initialize handoff tracker for edge-to-edge target continuity
        self._handoff_tracker = HandoffTracker(
            max_gap=120.0,
            visibility_timeout=15.0,
            on_handoff=self._on_target_handoff,
        )
        self._logger.info("Handoff tracker initialized")

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
        elif event_type == "fleet.ble_interrogation":
            self._on_ble_interrogation(data)

    def _on_ble_presence(self, data: dict) -> None:
        """Handle fleet.ble_presence — record sightings and emit update."""
        if self._store is None:
            return

        devices = data.get("devices", [])
        node_id = data.get("node_id", "unknown")
        node_ip = data.get("node_ip", "")

        # Auto-register node lat/lon if provided in event data (e.g. from demo generators)
        node_lat = data.get("node_lat")
        node_lon = data.get("node_lon")
        if node_lat is not None and node_lon is not None:
            try:
                self._store.set_node_position(
                    node_id, x=0, y=0, lat=node_lat, lon=node_lon, label=node_id,
                )
            except Exception:
                pass

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

        # Track sensor health — record a sighting for this node
        if self._sensor_health is not None and devices:
            self._sensor_health.record_sighting(node_id)

        # Record sightings in trilateration engine
        if self._trilateration is not None and self._store is not None:
            self._record_trilateration_sightings(devices, node_id)

        # Cache edge-sourced device type/class (from Apple Continuity etc.)
        for dev in devices:
            mac = dev.get("mac", "")
            edge_type = dev.get("device_type") or dev.get("class")
            if mac and edge_type:
                self._edge_device_types[mac] = edge_type

        # Classify each device through the BLE classifier
        if self._ble_classifier is not None:
            for dev in devices:
                self._ble_classifier.classify(
                    mac=dev.get("mac", ""),
                    name=dev.get("name", ""),
                    rssi=dev.get("rssi", -100),
                )

        # Feed handoff tracker for edge-to-edge target continuity
        for dev in devices:
            mac = dev.get("mac", "")
            if mac:
                self._feed_handoff_tracker(mac, node_id)

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

        # Track sensor health for WiFi
        if self._sensor_health is not None and networks:
            self._sensor_health.record_sighting(node_id)

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
                # Cache edge-sourced device type/class
                for dev in ble_data:
                    mac = dev.get("mac", "")
                    edge_type = dev.get("device_type") or dev.get("class")
                    if mac and edge_type:
                        self._edge_device_types[mac] = edge_type
                # Record sightings in trilateration engine
                if self._trilateration is not None:
                    self._record_trilateration_sightings(ble_data, node_id)
                # Classify each device through the BLE classifier
                if self._ble_classifier is not None:
                    for dev in ble_data:
                        self._ble_classifier.classify(
                            mac=dev.get("mac", ""),
                            name=dev.get("name", ""),
                            rssi=dev.get("rssi", -100),
                        )
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

    def _on_ble_interrogation(self, data: dict) -> None:
        """Handle fleet.ble_interrogation — enrich device dossier with GATT profile."""
        mac = data.get("mac", "")
        success = data.get("success", False)
        node_id = data.get("node_id", "unknown")

        if not mac or not success:
            if mac:
                log.info("BLE interrogation failed for %s: %s", mac, data.get("error", ""))
            return

        profile_data = data.get("profile", {})
        if not profile_data:
            return

        # Parse into BleGATTProfile if available
        if BleGATTProfile is not None:
            try:
                profile = BleGATTProfile(**profile_data)
            except Exception as exc:
                log.warning("Failed to parse GATT profile for %s: %s", mac, exc)
                profile = None
        else:
            profile = None

        # Cache the profile
        self._gatt_profiles[mac] = profile_data

        # Classify device type from GATT profile
        device_type = None
        if profile is not None and classify_device_from_profile is not None:
            device_type = classify_device_from_profile(profile)
            if device_type and device_type != "unknown":
                self._edge_device_types[mac] = device_type

        # Emit enrichment event
        if self._event_bus is not None:
            enrichment = {
                "mac": mac,
                "node_id": node_id,
                "source": "gatt_interrogation",
                "profile": profile_data,
                "device_type": device_type,
                "timestamp": time.time(),
            }
            if profile is not None:
                enrichment["manufacturer"] = profile.manufacturer
                enrichment["model"] = profile.model
                enrichment["device_name"] = profile.device_name
                enrichment["battery_level"] = profile.battery_level
                enrichment["service_count"] = len(profile.services)

            self._event_bus.publish("edge:ble_interrogation", data=enrichment)

        self._logger.info(
            "BLE GATT profile for %s: mfr=%s model=%s type=%s (%d services)",
            mac,
            profile_data.get("manufacturer", "n/a"),
            profile_data.get("model", "n/a"),
            device_type or "unknown",
            len(profile_data.get("services", [])),
        )

    def _record_trilateration_sightings(
        self, devices: list[dict], node_id: str
    ) -> None:
        """Feed BLE device sightings into the trilateration engine."""
        if self._trilateration is None or self._store is None:
            return

        try:
            node_pos = self._store.get_node_position(node_id)
        except Exception:
            node_pos = None

        if not node_pos:
            return

        lat = node_pos.get("lat")
        lon = node_pos.get("lon")
        if lat is None or lon is None:
            return

        for dev in devices:
            mac = dev.get("mac", "")
            rssi = dev.get("rssi", -100)
            if mac:
                self._trilateration.record_sighting(
                    mac=mac,
                    node_id=node_id,
                    node_lat=lat,
                    node_lon=lon,
                    rssi=rssi,
                )

        # Prune stale sightings periodically
        self._trilateration.prune_stale()

    def _emit_ble_update(self) -> None:
        """Emit edge:ble_update with current active devices and push to TargetTracker."""
        if self._event_bus is None or self._store is None:
            return

        try:
            active = self._store.get_active_devices()
            self._event_bus.publish("edge:ble_update", data={
                "devices": active,
                "count": len(active),
                "timestamp": time.time(),
            })

            # Push BLE devices into TargetTracker so they appear on the tactical map
            if self._tracker is not None:
                for dev in active:
                    mac = dev.get("mac", "")
                    node_id = dev.get("node_id", "unknown")
                    node_pos = None
                    try:
                        np_data = self._store.get_node_position(node_id)
                        if np_data:
                            node_pos = {"x": np_data.get("x", 0), "y": np_data.get("y", 0)}
                    except Exception:
                        pass

                    # Use trilateration position if available
                    trilat_pos = None
                    if self._trilateration is not None and mac:
                        est = self._trilateration.estimate_position(mac)
                        if est is not None:
                            trilat_pos = est.to_dict()
                            dev["position"] = trilat_pos

                    # Classify device type using DeviceClassifier
                    device_type = None
                    if self._device_classifier is not None:
                        classification = self._device_classifier.classify_ble(
                            mac=mac,
                            name=dev.get("name", ""),
                            company_id=dev.get("company_id"),
                            appearance=dev.get("appearance"),
                            service_uuids=dev.get("service_uuids"),
                        )
                        if classification.device_type != "unknown":
                            device_type = classification.device_type

                    # Fallback: use edge-sourced Apple Continuity type
                    if device_type is None and mac in self._edge_device_types:
                        device_type = self._edge_device_types[mac]

                    self._tracker.update_from_ble({
                        "mac": mac,
                        "name": dev.get("name", ""),
                        "rssi": dev.get("rssi", -100),
                        "node_id": node_id,
                        "node_position": node_pos,
                        "trilateration": trilat_pos,
                        "device_type": device_type,
                    })

                    # Check target position against geofence zones
                    if get_geofence_engine is not None:
                        try:
                            geo_engine = get_geofence_engine()
                            target_pos = None
                            if trilat_pos:
                                target_pos = (trilat_pos.get("lat", 0), trilat_pos.get("lon", 0))
                            elif node_pos:
                                target_pos = (node_pos.get("x", 0), node_pos.get("y", 0))
                            if target_pos and (target_pos[0] != 0 or target_pos[1] != 0):
                                tid = f"ble_{mac.replace(':', '').lower()}"
                                geo_engine.check(tid, target_pos)
                        except Exception:
                            pass  # geofence engine may not be initialized yet

                    # Feed indoor/outdoor transition detector
                    if self._transition_detector is not None and mac:
                        has_gps = trilat_pos is not None and trilat_pos.get("method") == "gps"
                        pos_method = "unknown"
                        if trilat_pos:
                            pos_method = trilat_pos.get("method", "trilateration")
                        elif node_pos:
                            pos_method = "proximity"
                        position = None
                        if trilat_pos:
                            position = (trilat_pos.get("lat", 0), trilat_pos.get("lon", 0))
                        elif node_pos:
                            position = (node_pos.get("x", 0), node_pos.get("y", 0))
                        self._transition_detector.update_target(
                            target_id=f"ble_{mac.replace(':', '').lower()}",
                            position=position,
                            positioning_method=pos_method,
                            has_gps=has_gps,
                            trilateration=trilat_pos,
                            node_count=trilat_pos.get("node_count", 1) if trilat_pos else 1,
                            node_id=node_id,
                        )
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

    # -- Handoff tracking --------------------------------------------------

    def _on_target_handoff(self, event: HandoffEvent) -> None:
        """Callback when a target hands off between edge nodes."""
        self._logger.info(
            "Target handoff: %s from %s -> %s (gap=%.1fs, conf=%.2f)",
            event.target_id, event.from_sensor, event.to_sensor,
            event.gap_seconds, event.confidence,
        )
        if self._event_bus is not None:
            self._event_bus.publish("edge:target_handoff", data=event.to_dict())

    def _feed_handoff_tracker(self, mac: str, node_id: str, position: tuple[float, float] = (0.0, 0.0)) -> None:
        """Update handoff tracker with a BLE sighting."""
        if self._handoff_tracker is None:
            return
        tid = f"ble_{mac.replace(':', '').lower()}"
        self._handoff_tracker.update_visibility(
            sensor_id=node_id,
            target_id=tid,
            position=position,
            target_type="ble_device",
        )
        # Periodically check for departures
        self._handoff_tracker.check_departures()

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        """Register FastAPI routes for the BLE and WiFi tracker API."""
        if not self._app:
            return

        from .routes import create_router

        router, wifi_router = create_router(
            self._store,
            ble_classifier=self._ble_classifier,
            trilateration_engine=self._trilateration,
            gatt_profiles=self._gatt_profiles,
            sensor_health_monitor=self._sensor_health,
        )
        self._app.include_router(router)
        self._app.include_router(wifi_router)
