# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FusionScenario — correlated multi-sensor targets for demo mode.

Generates three scripted actors whose BLE devices and camera detections
share spatial and temporal proximity, so the TargetCorrelator can fuse
them into unified dossiers.  This is the core value demo of Tritium:
showing that a person's phone, watch, and camera silhouette all converge
into a single tracked entity.

Actors
------
  Person A  — walks a patrol path carrying a phone and wearing a watch.
              Camera sees "person" at the same world position.
  Vehicle B — drives along a road.  Driver's phone BLE is inside.
              Camera sees "car" at the same position.
  Person C  — approaches and enters a restricted geofence zone,
              triggering an alert.

The scenario injects BLE sightings and YOLO-style detections directly
into the TargetTracker (and optionally the GeofenceEngine) so the
correlator can merge them.  It also publishes EventBus events for
downstream consumers (map UI, Amy sensorium, WebSocket).
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from tritium_lib.tracking.geofence import GeofenceEngine
    from tritium_lib.tracking.target_tracker import TargetTracker

logger = logging.getLogger("synthetic.fusion_scenario")

# ── Actor definitions ────────────────────────────────────────────────────

# OUI prefixes mapped to manufacturers (simulates enrichment)
_OUI_ENRICHMENT: dict[str, dict[str, str]] = {
    "AA:11": {"manufacturer": "Apple Inc.", "device_class": "smartphone"},
    "AA:22": {"manufacturer": "Apple Inc.", "device_class": "wearable"},
    "BB:11": {"manufacturer": "Samsung Electronics", "device_class": "smartphone"},
    "DD:EE": {"manufacturer": "Unknown", "device_class": "unknown"},
}


@dataclass
class _BLEDevice:
    """A BLE device carried by an actor."""
    mac: str
    name: str
    device_type: str  # phone, wearable, automotive, unknown


@dataclass
class _Actor:
    """A scripted entity in the fusion scenario."""
    actor_id: str
    label: str  # human-readable
    camera_label: str  # YOLO class: "person", "car"
    ble_devices: list[_BLEDevice]
    # Path: list of (x, y) waypoints the actor walks/drives through
    path: list[tuple[float, float]]
    speed: float  # units per second along path
    # Current state
    path_index: float = 0.0  # fractional index into path
    dossier_uuid: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


# ── Scenario description (static) ───────────────────────────────────────

SCENARIO_DESCRIPTION: dict = {
    "name": "Multi-Sensor Target Fusion Demo",
    "description": (
        "Demonstrates Tritium's core capability: fusing detections from "
        "BLE scanners and cameras into unified target dossiers. Three "
        "scripted actors generate correlated sensor data that the "
        "TargetCorrelator merges automatically."
    ),
    "actors": [
        {
            "id": "person-a",
            "label": "Person A",
            "description": (
                "A person carrying an iPhone (AA:11:22:33:44:01) and wearing "
                "an Apple Watch (AA:22:33:44:55:01). Camera sees them as a "
                "'person' detection. All three signals converge spatially, "
                "producing a fused dossier with boosted confidence."
            ),
            "ble_devices": [
                {"mac": "AA:11:22:33:44:01", "name": "iPhone-PersonA", "type": "phone"},
                {"mac": "AA:22:33:44:55:01", "name": "Watch-PersonA", "type": "wearable"},
            ],
            "camera_class": "person",
            "fusion_expected": "BLE phone + BLE watch + camera person -> 1 dossier",
        },
        {
            "id": "vehicle-b",
            "label": "Vehicle B",
            "description": (
                "A car with the driver's Samsung phone (BB:11:22:33:44:01) "
                "detected via BLE. Camera sees the vehicle as a 'car' detection. "
                "Both signals fuse into a single vehicle dossier."
            ),
            "ble_devices": [
                {"mac": "BB:11:22:33:44:01", "name": "Galaxy-Driver", "type": "phone"},
            ],
            "camera_class": "car",
            "fusion_expected": "BLE phone + camera car -> 1 dossier",
        },
        {
            "id": "person-c",
            "label": "Person C",
            "description": (
                "A person with an unknown BLE device (DD:EE:FF:00:11:01) "
                "who enters a restricted geofence zone, triggering an alert. "
                "Demonstrates geofence integration and unknown device classification."
            ),
            "ble_devices": [
                {"mac": "DD:EE:FF:00:11:01", "name": "", "type": "unknown"},
            ],
            "camera_class": "person",
            "fusion_expected": "BLE unknown + camera person + geofence alert -> 1 dossier",
        },
    ],
    "demonstrated_capabilities": [
        "BLE + camera fusion into unique dossier UUID",
        "Target movement trails visible on map",
        "BLE classifier marking unknown devices",
        "OUI manufacturer enrichment (Apple, Samsung, Unknown)",
        "Geofence zone entry alert",
        "Dossier building over time (signal accumulation)",
        "Correlated multi-sensor confidence boosting",
    ],
    "geofence_zones": [
        {
            "name": "Restricted Area",
            "zone_type": "restricted",
            "polygon": [[-2.0, 8.0], [2.0, 8.0], [2.0, 12.0], [-2.0, 12.0]],
        },
        {
            "name": "Patrol Sector",
            "zone_type": "monitored",
            "polygon": [[3.0, -2.0], [10.0, -2.0], [10.0, 5.0], [3.0, 5.0]],
        },
    ],
}


# ── Fusion Scenario Engine ───────────────────────────────────────────────

def _interpolate_path(
    path: list[tuple[float, float]], index: float
) -> tuple[float, float]:
    """Interpolate position along a path given a fractional index."""
    if not path:
        return (0.0, 0.0)
    if index <= 0:
        return path[0]
    if index >= len(path) - 1:
        return path[-1]

    i = int(index)
    frac = index - i
    x0, y0 = path[i]
    x1, y1 = path[min(i + 1, len(path) - 1)]
    return (x0 + (x1 - x0) * frac, y0 + (y1 - y0) * frac)


def _segment_length(
    path: list[tuple[float, float]], i: int
) -> float:
    """Distance between waypoint i and i+1."""
    if i < 0 or i >= len(path) - 1:
        return 0.0
    dx = path[i + 1][0] - path[i][0]
    dy = path[i + 1][1] - path[i][1]
    return math.hypot(dx, dy)


def _enrich_oui(mac: str) -> dict[str, str]:
    """Simulate OUI manufacturer lookup from MAC prefix."""
    prefix = mac[:5]  # "AA:11"
    return _OUI_ENRICHMENT.get(prefix, {"manufacturer": "Unknown", "device_class": "unknown"})


class FusionScenario:
    """Generates correlated multi-sensor data for three scripted actors.

    Each tick:
      1. Advances actor positions along their paths
      2. Publishes BLE sightings for each actor's devices
      3. Publishes camera detections at matching positions
      4. Injects into TargetTracker for correlator fusion
      5. Checks geofence for Person C
      6. Publishes enrichment/dossier events
    """

    def __init__(
        self,
        event_bus: EventBus,
        target_tracker: TargetTracker | None = None,
        geofence_engine: GeofenceEngine | None = None,
        interval: float = 2.0,
    ) -> None:
        self._event_bus = event_bus
        self._target_tracker = target_tracker
        self._geofence = geofence_engine
        self._interval = interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._tick_count = 0
        self._dossiers: dict[str, dict] = {}  # actor_id -> dossier state
        self._geofence_zone_added = False

        # Build actors
        self._actors = self._build_actors()

    @property
    def running(self) -> bool:
        return self._running

    def _build_actors(self) -> list[_Actor]:
        """Create the three scripted actors with paths."""
        return [
            _Actor(
                actor_id="person-a",
                label="Person A",
                camera_label="person",
                ble_devices=[
                    _BLEDevice(
                        mac="AA:11:22:33:44:01",
                        name="iPhone-PersonA",
                        device_type="phone",
                    ),
                    _BLEDevice(
                        mac="AA:22:33:44:55:01",
                        name="Watch-PersonA",
                        device_type="wearable",
                    ),
                ],
                # Person A walks a loop: start at (-5, 0), walk east then north
                path=[
                    (-5.0, 0.0), (-3.0, 0.0), (-1.0, 1.0), (1.0, 2.0),
                    (3.0, 3.0), (5.0, 3.0), (5.0, 1.0), (3.0, 0.0),
                    (1.0, -1.0), (-1.0, -1.0), (-3.0, 0.0), (-5.0, 0.0),
                ],
                speed=0.8,  # walking speed
            ),
            _Actor(
                actor_id="vehicle-b",
                label="Vehicle B",
                camera_label="car",
                ble_devices=[
                    _BLEDevice(
                        mac="BB:11:22:33:44:01",
                        name="Galaxy-Driver",
                        device_type="phone",
                    ),
                ],
                # Vehicle B drives a straight east-west road
                path=[
                    (-10.0, -3.0), (-5.0, -3.0), (0.0, -3.0),
                    (5.0, -3.0), (10.0, -3.0),
                    (10.0, -3.0), (5.0, -3.0), (0.0, -3.0),
                    (-5.0, -3.0), (-10.0, -3.0),
                ],
                speed=3.0,  # driving speed
            ),
            _Actor(
                actor_id="person-c",
                label="Person C",
                camera_label="person",
                ble_devices=[
                    _BLEDevice(
                        mac="DD:EE:FF:00:11:01",
                        name="",  # unknown device
                        device_type="unknown",
                    ),
                ],
                # Person C walks toward and into the restricted zone
                path=[
                    (-1.0, 7.5), (-0.5, 8.0), (0.0, 8.5), (0.0, 9.5),
                    (0.0, 10.0), (0.0, 10.5), (0.0, 11.0),
                    (0.5, 10.0), (1.0, 9.0), (0.0, 8.0), (-0.5, 7.5),
                    (-1.0, 7.5),
                ],
                speed=1.0,  # deliberate approach
            ),
        ]

    def start(self) -> None:
        """Start the fusion scenario background loop."""
        if self._running:
            return
        self._running = True
        self._tick_count = 0
        self._dossiers = {}

        # Reset actor positions
        for actor in self._actors:
            actor.path_index = 0.0

        # Set up geofence zones if engine available
        if self._geofence is not None and not self._geofence_zone_added:
            from tritium_lib.tracking.geofence import GeoZone
            zone = GeoZone(
                zone_id="demo-restricted-01",
                name="Restricted Area",
                polygon=[(-2.0, 8.0), (2.0, 8.0), (2.0, 12.0), (-2.0, 12.0)],
                zone_type="restricted",
                alert_on_enter=True,
                alert_on_exit=True,
            )
            self._geofence.add_zone(zone)
            # Add a monitored zone that covers the main patrol area —
            # this one stays "MONITORING" (armed, no occupants) so the
            # map pulse animation and badge are always visible in demo.
            monitored_zone = GeoZone(
                zone_id="demo-monitored-01",
                name="Patrol Sector",
                polygon=[(3.0, -2.0), (10.0, -2.0), (10.0, 5.0), (3.0, 5.0)],
                zone_type="monitored",
                alert_on_enter=True,
                alert_on_exit=True,
            )
            self._geofence.add_zone(monitored_zone)
            self._geofence_zone_added = True

        self._thread = threading.Thread(
            target=self._loop, name="fusion-scenario", daemon=True
        )
        self._thread.start()
        logger.info("Fusion scenario started with %d actors", len(self._actors))

    def stop(self) -> None:
        """Stop the fusion scenario."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1)
            self._thread = None

        # Clean up geofence zones
        if self._geofence is not None and self._geofence_zone_added:
            self._geofence.remove_zone("demo-restricted-01")
            self._geofence.remove_zone("demo-monitored-01")
            self._geofence_zone_added = False

        logger.info("Fusion scenario stopped")

    def _loop(self) -> None:
        """Background tick loop."""
        while self._running:
            try:
                self._tick()
            except Exception:
                logger.debug("Fusion scenario tick error", exc_info=True)
            time.sleep(self._interval)

    def _tick(self) -> None:
        """Advance all actors and emit correlated sensor data."""
        self._tick_count += 1

        for actor in self._actors:
            # Advance position along path
            total_path_len = len(actor.path) - 1
            if total_path_len <= 0:
                continue

            # Compute how far to advance this tick
            seg_idx = int(actor.path_index)
            seg_len = _segment_length(actor.path, min(seg_idx, total_path_len - 1))
            if seg_len > 0:
                advance = (actor.speed * self._interval) / seg_len
            else:
                advance = 0.1
            actor.path_index += advance

            # Loop back to start when path ends
            if actor.path_index >= total_path_len:
                actor.path_index = 0.0

            pos = _interpolate_path(actor.path, actor.path_index)

            # 1. Emit BLE sightings for each device
            for ble_dev in actor.ble_devices:
                enrichment = _enrich_oui(ble_dev.mac)
                ble_sighting = {
                    "mac": ble_dev.mac,
                    "name": ble_dev.name,
                    "rssi": -45 + (self._tick_count % 10),  # stable strong signal
                    "node_id": "demo-scanner-01",
                    "type": ble_dev.device_type,
                    "position": {"x": pos[0], "y": pos[1]},
                    "manufacturer": enrichment["manufacturer"],
                    "device_class": enrichment["device_class"],
                }
                self._event_bus.publish("fleet.ble_sighting", {"sighting": ble_sighting})

                # Inject into tracker
                if self._target_tracker is not None:
                    self._target_tracker.update_from_ble({
                        "mac": ble_dev.mac,
                        "name": ble_dev.name or ble_dev.mac,
                        "rssi": ble_sighting["rssi"],
                        "node_id": "demo-scanner-01",
                        "position": {"x": pos[0], "y": pos[1]},
                    })

            # 2. Emit camera detection at same position (with slight offset)
            cam_offset_x = 0.3 * math.sin(self._tick_count * 0.5)
            cam_offset_y = 0.2 * math.cos(self._tick_count * 0.7)
            cam_pos = (pos[0] + cam_offset_x, pos[1] + cam_offset_y)

            cam_detection = {
                "camera_id": "demo-cam-01",
                "detection": {
                    "id": f"fusion-{actor.actor_id}-{self._tick_count}",
                    "label": actor.camera_label,
                    "confidence": 0.85 + 0.1 * math.sin(self._tick_count * 0.3),
                    "bbox": {
                        "x": round(max(0.0, min(1.0, (cam_pos[0] + 10) / 20)), 4),
                        "y": round(max(0.0, min(1.0, (cam_pos[1] + 10) / 20)), 4),
                        "w": 0.05 if actor.camera_label == "person" else 0.12,
                        "h": 0.15 if actor.camera_label == "person" else 0.08,
                    },
                    "world_position": {"x": cam_pos[0], "y": cam_pos[1]},
                },
            }
            self._event_bus.publish("detection:camera:fusion", cam_detection)

            # Inject camera detection into tracker
            if self._target_tracker is not None:
                class_name = actor.camera_label
                self._target_tracker.update_from_detection({
                    "class_name": class_name,
                    "confidence": cam_detection["detection"]["confidence"],
                    "center_x": cam_pos[0],
                    "center_y": cam_pos[1],
                })

            # 3. Check geofence for this actor
            if self._geofence is not None:
                geo_events = self._geofence.check(
                    f"fusion-{actor.actor_id}", pos
                )
                for gev in geo_events:
                    action = gev.event_type  # "enter" or "exit"
                    # Publish demo-specific event for any listeners
                    self._event_bus.publish("demo:geofence_alert", {
                        "actor": actor.label,
                        "actor_id": actor.actor_id,
                        "zone": gev.zone_name,
                        "zone_type": gev.zone_type,
                        "position": list(pos),
                        "event_type": action,
                    })
                    # Also publish as geofence:enter/exit so the
                    # NotificationManager picks it up and creates
                    # a real notification in the alert feed.
                    self._event_bus.publish(f"geofence:{action}", {
                        "zone_name": gev.zone_name,
                        "zone_type": gev.zone_type,
                        "target_id": f"fusion-{actor.actor_id}",
                        "source": "fusion_scenario",
                    })

            # 4. Build/update dossier state
            self._update_dossier(actor, pos)

        # 5. Publish dossier summary event
        self._event_bus.publish("demo:dossier_update", {
            "dossiers": list(self._dossiers.values()),
            "tick": self._tick_count,
        })

    def _update_dossier(
        self, actor: _Actor, pos: tuple[float, float]
    ) -> None:
        """Build up a dossier for this actor over time."""
        if actor.actor_id not in self._dossiers:
            self._dossiers[actor.actor_id] = {
                "dossier_uuid": actor.dossier_uuid,
                "actor_id": actor.actor_id,
                "label": actor.label,
                "first_seen_tick": self._tick_count,
                "signals": [],
                "ble_devices": [],
                "camera_detections": 0,
                "geofence_alerts": [],
                "enrichment": {},
                "confidence": 0.0,
            }

        dossier = self._dossiers[actor.actor_id]
        dossier["last_seen_tick"] = self._tick_count
        dossier["position"] = list(pos)
        dossier["camera_detections"] = dossier.get("camera_detections", 0) + 1

        # Add BLE devices to dossier if not already present
        for ble_dev in actor.ble_devices:
            dev_entry = {
                "mac": ble_dev.mac,
                "name": ble_dev.name,
                "type": ble_dev.device_type,
            }
            if dev_entry not in dossier["ble_devices"]:
                dossier["ble_devices"].append(dev_entry)
                dossier["signals"].append(f"BLE: {ble_dev.mac} ({ble_dev.device_type})")

                # Add enrichment
                enrichment = _enrich_oui(ble_dev.mac)
                dossier["enrichment"][ble_dev.mac] = enrichment

        # Camera signal (add once)
        cam_signal = f"Camera: {actor.camera_label}"
        if cam_signal not in dossier["signals"]:
            dossier["signals"].append(cam_signal)

        # Confidence grows with accumulated signals (diminishing returns)
        n_signals = len(dossier["signals"])
        dossier["confidence"] = min(1.0, 0.3 * n_signals)

    def get_dossiers(self) -> list[dict]:
        """Return current dossier state for all actors."""
        return list(self._dossiers.values())

    def get_scenario_info(self) -> dict:
        """Return static scenario description plus live dossier state."""
        info = dict(SCENARIO_DESCRIPTION)
        info["running"] = self._running
        info["tick_count"] = self._tick_count
        info["dossiers"] = self.get_dossiers()
        return info
