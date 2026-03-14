# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""RFMotionPlugin — passive motion detection using RSSI variance analysis.

Monitors RSSI between stationary radios to detect movement in the RF
environment. No cameras needed — uses the radios already deployed as
part of the tritium-edge mesh.

Motion events are published to EventBus and wired into TargetTracker
as temporary "motion_detected" targets on the tactical map.
"""

from __future__ import annotations

import logging
import queue as queue_mod
import threading
import time
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

from .detector import RSSIMotionDetector, MotionEvent, MOTION_HOLD_TIME
from .zones import ZoneManager

log = logging.getLogger("rf-motion")

# How often to run the detection loop (seconds)
DEFAULT_POLL_INTERVAL = 2.0

# Stale timeout for motion targets in TargetTracker
MOTION_TARGET_TTL = 30.0


class RFMotionPlugin(PluginInterface):
    """Passive RF motion detection using RSSI variance between fixed radios."""

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None

        self._detector = RSSIMotionDetector()
        self._zone_manager = ZoneManager(self._detector)

        self._running = False
        self._poll_interval = DEFAULT_POLL_INTERVAL
        self._detect_thread: Optional[threading.Thread] = None
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_thread: Optional[threading.Thread] = None

    # -- PluginInterface identity ----------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.rf-motion"

    @property
    def name(self) -> str:
        return "RF Motion Detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "background"}

    # -- PluginInterface lifecycle ---------------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._app = ctx.app
        self._logger = ctx.logger or log

        # Apply settings
        settings = ctx.settings or {}
        if "poll_interval" in settings:
            self._poll_interval = float(settings["poll_interval"])
        if "static_threshold" in settings:
            self._detector._static_threshold = float(settings["static_threshold"])
        if "motion_threshold" in settings:
            self._detector._motion_threshold = float(settings["motion_threshold"])
        if "window_seconds" in settings:
            self._detector._window_seconds = float(settings["window_seconds"])

        # Pre-configure node positions from settings
        nodes = settings.get("nodes", {})
        for node_id, pos in nodes.items():
            self._detector.set_node_position(
                node_id, (float(pos.get("x", 0)), float(pos.get("y", 0)))
            )

        # Pre-configure zones from settings
        zones = settings.get("zones", [])
        for zconf in zones:
            self._zone_manager.add_zone(
                zone_id=zconf["zone_id"],
                name=zconf.get("name", zconf["zone_id"]),
                pair_ids=zconf.get("pair_ids", []),
                vacancy_timeout=float(zconf.get("vacancy_timeout", 30.0)),
            )

        # Register routes
        self._register_routes()

        self._logger.info("RF Motion plugin configured")

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        # Start detection polling thread
        self._detect_thread = threading.Thread(
            target=self._detection_loop,
            daemon=True,
            name="rf-motion-detect",
        )
        self._detect_thread.start()

        # Subscribe to EventBus for RSSI data from edge fleet
        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_thread = threading.Thread(
                target=self._event_drain_loop,
                daemon=True,
                name="rf-motion-events",
            )
            self._event_thread.start()

        self._logger.info("RF Motion plugin started (poll=%.1fs)", self._poll_interval)

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if self._detect_thread and self._detect_thread.is_alive():
            self._detect_thread.join(timeout=3.0)

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        self._logger.info("RF Motion plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Detection loop --------------------------------------------------------

    def _detection_loop(self) -> None:
        """Background loop: run detection and publish events."""
        while self._running:
            try:
                events = self._detector.detect()

                if events:
                    self._publish_motion_events(events)
                    self._update_tracker(events)

                # Check zones
                changed_zones = self._zone_manager.check_all(events)
                for zone in changed_zones:
                    self._publish_zone_change(zone)

            except Exception as exc:
                log.error("RF motion detection error: %s", exc)

            # Sleep in small increments for responsive shutdown
            deadline = time.monotonic() + self._poll_interval
            while self._running and time.monotonic() < deadline:
                time.sleep(0.25)

    def _publish_motion_events(self, events: list[MotionEvent]) -> None:
        """Publish motion events to EventBus."""
        if self._event_bus is None:
            return

        for event in events:
            self._event_bus.publish("rf_motion:detected", data=event.to_dict())

    def _publish_zone_change(self, zone: Any) -> None:
        """Publish zone occupancy change to EventBus."""
        if self._event_bus is None:
            return

        event_type = "rf_motion:zone_occupied" if zone.occupied else "rf_motion:zone_vacant"
        self._event_bus.publish(event_type, data=zone.to_dict())

    def _update_tracker(self, events: list[MotionEvent]) -> None:
        """Push motion events into TargetTracker as temporary targets."""
        if self._tracker is None:
            return

        for event in events:
            target_id = f"rfm_{event.pair_id.replace('::', '_')}"
            try:
                self._tracker.update_from_rf_motion({
                    "target_id": target_id,
                    "pair_id": event.pair_id,
                    "position": event.estimated_position,
                    "confidence": event.confidence,
                    "direction_hint": event.direction_hint,
                    "variance": event.variance,
                })
            except AttributeError:
                # TargetTracker may not have update_from_rf_motion yet —
                # fall back to manual target injection
                self._inject_motion_target(target_id, event)

    def _inject_motion_target(self, target_id: str, event: MotionEvent) -> None:
        """Fallback: inject a motion target directly into TargetTracker."""
        if self._tracker is None:
            return

        try:
            from engine.tactical.target_tracker import TrackedTarget
            import time as _time

            with self._tracker._lock:
                if target_id in self._tracker._targets:
                    t = self._tracker._targets[target_id]
                    t.position = event.estimated_position
                    t.position_confidence = event.confidence
                    t.last_seen = _time.monotonic()
                    t.status = f"motion:{event.direction_hint}"
                else:
                    self._tracker._targets[target_id] = TrackedTarget(
                        target_id=target_id,
                        name=f"RF Motion ({event.pair_id})",
                        alliance="unknown",
                        asset_type="motion_detected",
                        position=event.estimated_position,
                        last_seen=_time.monotonic(),
                        source="rf_motion",
                        position_source="rf_pair_midpoint",
                        position_confidence=event.confidence,
                        status=f"motion:{event.direction_hint}",
                    )
        except Exception as exc:
            log.error("Failed to inject motion target: %s", exc)

    # -- Event bus listener (incoming RSSI data) -------------------------------

    def _event_drain_loop(self) -> None:
        """Background loop: drain EventBus for RSSI data from edge fleet."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.5)
                self._handle_event(event)
            except queue_mod.Empty:
                pass
            except Exception as exc:
                log.error("RF motion event error: %s", exc)

    def _handle_event(self, event: dict) -> None:
        """Process incoming events for RSSI data."""
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type == "fleet.heartbeat":
            self._on_fleet_heartbeat(data)
        elif event_type == "fleet.ble_presence":
            self._on_ble_presence(data)
        elif event_type == "rf_motion:rssi_pair":
            # Direct pair RSSI feed
            self._detector.record_pair_rssi(
                data.get("node_a", ""),
                data.get("node_b", ""),
                data.get("rssi", -100),
            )

    def _on_fleet_heartbeat(self, data: dict) -> None:
        """Extract RSSI data from fleet heartbeats for motion detection."""
        node_id = data.get("node_id", data.get("id", ""))
        if not node_id:
            return

        # WiFi RSSI from the node itself (node-to-AP signal)
        wifi_rssi = data.get("wifi_rssi")
        if wifi_rssi is not None:
            self._detector.record_device_rssi("ap", node_id, float(wifi_rssi))

        # Mesh peer RSSI values (node-to-node)
        mesh_peers = data.get("mesh_peers", [])
        for peer in mesh_peers:
            peer_id = peer.get("id", peer.get("node_id", ""))
            peer_rssi = peer.get("rssi")
            if peer_id and peer_rssi is not None:
                self._detector.record_pair_rssi(node_id, peer_id, float(peer_rssi))

        # BLE devices seen by this node (single-observer mode)
        ble_devices = data.get("ble", data.get("ble_devices", []))
        for dev in ble_devices:
            mac = dev.get("mac", "")
            rssi = dev.get("rssi")
            if mac and rssi is not None:
                self._detector.record_device_rssi(node_id, mac, float(rssi))

    def _on_ble_presence(self, data: dict) -> None:
        """Extract per-device RSSI for single-observer motion detection."""
        node_id = data.get("node_id", "unknown")
        devices = data.get("devices", [])
        for dev in devices:
            mac = dev.get("mac", "")
            rssi = dev.get("rssi")
            if mac and rssi is not None:
                self._detector.record_device_rssi(node_id, mac, float(rssi))

    # -- Routes ----------------------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return

        from .routes import create_router

        router = create_router(self._detector, self._zone_manager)
        self._app.include_router(router)
