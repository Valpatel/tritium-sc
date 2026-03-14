# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Synthetic data generators for full pipeline testing.

Three generators that produce realistic fake data and publish to EventBus:

- BLEScanGenerator: BLE sighting events (fleet.ble_presence)
- MeshtasticNodeGenerator: Meshtastic node telemetry (meshtastic:nodes_updated)
- CameraDetectionGenerator: YOLO-style detections (detection:camera)
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus

logger = logging.getLogger("synthetic.data_generators")

# ── BLE device pool ─────────────────────────────────────────────────────

_BLE_DEVICE_POOL: list[dict[str, str]] = [
    {"name": "iPhone-Matt", "mac": "AA:BB:CC:11:22:01", "type": "phone"},
    {"name": "Galaxy-S24", "mac": "AA:BB:CC:11:22:02", "type": "phone"},
    {"name": "Pixel-9", "mac": "AA:BB:CC:11:22:03", "type": "phone"},
    {"name": "AirPods-Pro", "mac": "AA:BB:CC:11:22:04", "type": "audio"},
    {"name": "WH-1000XM5", "mac": "AA:BB:CC:11:22:05", "type": "audio"},
    {"name": "Apple-Watch-7", "mac": "AA:BB:CC:11:22:06", "type": "wearable"},
    {"name": "Fitbit-Charge", "mac": "AA:BB:CC:11:22:07", "type": "wearable"},
    {"name": "Tile-Mate", "mac": "AA:BB:CC:11:22:08", "type": "tracker"},
    {"name": "AirTag", "mac": "AA:BB:CC:11:22:09", "type": "tracker"},
    {"name": "Ring-Doorbell", "mac": "AA:BB:CC:11:22:0A", "type": "iot"},
    {"name": "Nest-Thermostat", "mac": "AA:BB:CC:11:22:0B", "type": "iot"},
    {"name": "Echo-Dot", "mac": "AA:BB:CC:11:22:0C", "type": "iot"},
    {"name": "", "mac": "DD:EE:FF:11:22:01", "type": "unknown"},
    {"name": "", "mac": "DD:EE:FF:11:22:02", "type": "unknown"},
    {"name": "", "mac": "DD:EE:FF:11:22:03", "type": "unknown"},
    {"name": "", "mac": "DD:EE:FF:11:22:04", "type": "unknown"},
    {"name": "JBL-Flip6", "mac": "AA:BB:CC:11:22:0D", "type": "audio"},
    {"name": "iPad-Air", "mac": "AA:BB:CC:11:22:0E", "type": "tablet"},
    {"name": "Surface-Go", "mac": "AA:BB:CC:11:22:0F", "type": "tablet"},
    {"name": "Tesla-Key", "mac": "AA:BB:CC:11:22:10", "type": "automotive"},
]

# ── Meshtastic node pool ────────────────────────────────────────────────

_MESHTASTIC_NODES: list[dict] = [
    {"node_id": "!a1b2c3d4", "long_name": "BaseStation-1", "short_name": "BS1",
     "hardware": "HELTEC_V3", "lat": 37.7749, "lng": -122.4194},
    {"node_id": "!e5f6a7b8", "long_name": "Rover-Alpha", "short_name": "RVA",
     "hardware": "TBEAM_V1.1", "lat": 37.7755, "lng": -122.4180},
    {"node_id": "!c9d0e1f2", "long_name": "Drone-Relay", "short_name": "DR1",
     "hardware": "RAK4631", "lat": 37.7742, "lng": -122.4200},
    {"node_id": "!a3b4c5d6", "long_name": "Mobile-Unit", "short_name": "MU1",
     "hardware": "TBEAM_V1.1", "lat": 37.7760, "lng": -122.4170},
    {"node_id": "!e7f8a9b0", "long_name": "Sensor-Post", "short_name": "SP1",
     "hardware": "HELTEC_V3", "lat": 37.7735, "lng": -122.4210},
]


@dataclass
class _MeshNodeState:
    """Mutable state for a simulated Meshtastic node."""
    node_id: str
    long_name: str
    short_name: str
    hardware: str
    lat: float
    lng: float
    battery: float = 100.0
    snr: float = 10.0
    heading: float = 0.0  # radians


# ── Base Generator ──────────────────────────────────────────────────────

class _BaseGenerator:
    """Common start/stop lifecycle for background generators."""

    def __init__(self, interval: float = 5.0) -> None:
        self._interval = interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._event_bus: EventBus | None = None

    @property
    def running(self) -> bool:
        return self._running

    def start(self, event_bus: EventBus) -> None:
        if self._running:
            return
        self._event_bus = event_bus
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1)
            self._thread = None

    def _loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.debug(f"{self.__class__.__name__} tick error: {e}")
            time.sleep(self._interval)

    def _tick(self) -> None:
        raise NotImplementedError


# ── BLE Scan Generator ─────────────────────────────────────────────────

class BLEScanGenerator(_BaseGenerator):
    """Generates realistic BLE sighting events.

    Publishes ``fleet.ble_presence`` events containing a ``node_id``
    (the reporting device) and a ``devices`` array of nearby BLE devices
    with RSSI jitter.  Devices appear and disappear over time.
    """

    def __init__(
        self,
        interval: float = 5.0,
        max_devices: int = 12,
        known_ratio: float = 0.6,
        node_id: str = "synth-scanner-01",
    ) -> None:
        super().__init__(interval=interval)
        self._max_devices = max_devices
        self._known_ratio = known_ratio
        self._node_id = node_id
        self._active_devices: list[dict[str, str]] = []
        self._rng = random.Random(42)

    def _tick(self) -> None:
        assert self._event_bus is not None
        self._rotate_devices()
        devices = []
        for dev in self._active_devices:
            rssi = self._rng.randint(-90, -30)
            devices.append({
                "addr": dev["mac"],
                "name": dev["name"],
                "rssi": rssi,
                "type": dev["type"],
            })
        self._event_bus.publish("fleet.ble_presence", {
            "node_id": self._node_id,
            "devices": devices,
            "count": len(devices),
        })

    def _rotate_devices(self) -> None:
        """Randomly add/remove devices to simulate movement."""
        pool = list(_BLE_DEVICE_POOL)
        known = [d for d in pool if d["name"]]
        unknown = [d for d in pool if not d["name"]]

        n_known = int(self._max_devices * self._known_ratio)
        n_unknown = self._max_devices - n_known

        # Slight churn: 20% chance each device rotates out
        self._active_devices = [
            d for d in self._active_devices
            if self._rng.random() > 0.2
        ]

        # Fill up to max
        current_macs = {d["mac"] for d in self._active_devices}
        available_known = [d for d in known if d["mac"] not in current_macs]
        available_unknown = [d for d in unknown if d["mac"] not in current_macs]

        n_need_known = max(0, n_known - sum(1 for d in self._active_devices if d["name"]))
        n_need_unknown = max(0, n_unknown - sum(1 for d in self._active_devices if not d["name"]))

        if available_known and n_need_known > 0:
            self._active_devices.extend(
                self._rng.sample(available_known, min(n_need_known, len(available_known)))
            )
        if available_unknown and n_need_unknown > 0:
            self._active_devices.extend(
                self._rng.sample(available_unknown, min(n_need_unknown, len(available_unknown)))
            )


# ── Meshtastic Node Generator ──────────────────────────────────────────

class MeshtasticNodeGenerator(_BaseGenerator):
    """Generates fake Meshtastic node telemetry.

    3-5 nodes with GPS coordinates that drift slowly (walking speed),
    battery draining over time, SNR varying.  Publishes
    ``meshtastic:nodes_updated`` events via EventBus.
    """

    def __init__(
        self,
        interval: float = 10.0,
        node_count: int = 5,
    ) -> None:
        super().__init__(interval=interval)
        self._node_count = min(node_count, len(_MESHTASTIC_NODES))
        self._nodes: list[_MeshNodeState] = []
        self._rng = random.Random(99)
        self._tick_count = 0

    def start(self, event_bus: EventBus) -> None:
        # Initialize node states
        self._nodes = []
        for cfg in _MESHTASTIC_NODES[: self._node_count]:
            self._nodes.append(_MeshNodeState(
                node_id=cfg["node_id"],
                long_name=cfg["long_name"],
                short_name=cfg["short_name"],
                hardware=cfg["hardware"],
                lat=cfg["lat"],
                lng=cfg["lng"],
                battery=self._rng.uniform(60.0, 100.0),
                snr=self._rng.uniform(5.0, 15.0),
                heading=self._rng.uniform(0, 2 * math.pi),
            ))
        super().start(event_bus)

    def _tick(self) -> None:
        assert self._event_bus is not None
        self._tick_count += 1
        nodes_data = []
        for node in self._nodes:
            # Walking speed drift: ~1.4 m/s ≈ 0.0000126 degrees/tick
            drift = 0.0000126 * self._interval
            node.heading += self._rng.gauss(0, 0.3)
            node.lat += math.cos(node.heading) * drift
            node.lng += math.sin(node.heading) * drift

            # Battery drain: ~0.1% per tick
            node.battery = max(0.0, node.battery - self._rng.uniform(0.05, 0.15))

            # SNR jitter
            node.snr = max(-5.0, min(20.0, node.snr + self._rng.gauss(0, 1.0)))

            nodes_data.append({
                "node_id": node.node_id,
                "long_name": node.long_name,
                "short_name": node.short_name,
                "hardware": node.hardware,
                "position": {
                    "lat": node.lat,
                    "lng": node.lng,
                    "alt": 0.0,
                },
                "battery": node.battery,
                "snr": node.snr,
            })

        self._event_bus.publish("meshtastic:nodes_updated", {
            "nodes": nodes_data,
            "count": len(nodes_data),
        })


# ── Camera Detection Generator ─────────────────────────────────────────

@dataclass
class _TrackedObject:
    """A moving object in normalized camera space (0-1)."""
    obj_id: str
    label: str
    x: float
    y: float
    w: float
    h: float
    vx: float  # velocity x per tick
    vy: float  # velocity y per tick
    confidence: float = 0.85
    alive: bool = True


class CameraDetectionGenerator(_BaseGenerator):
    """Generates fake YOLO detections in normalized camera space.

    People walk slowly across the frame, vehicles pass at higher speed.
    Publishes ``detection:camera`` events via EventBus.
    """

    def __init__(
        self,
        interval: float = 1.0,
        camera_id: str = "synth-cam-01",
        max_objects: int = 8,
    ) -> None:
        super().__init__(interval=interval)
        self._camera_id = camera_id
        self._max_objects = max_objects
        self._objects: list[_TrackedObject] = []
        self._rng = random.Random(7)
        self._next_id = 0
        self._tick_count = 0

    def _tick(self) -> None:
        assert self._event_bus is not None
        self._tick_count += 1

        # Spawn new objects occasionally
        if len(self._objects) < self._max_objects and self._rng.random() < 0.3:
            self._spawn()

        # Move existing objects
        for obj in self._objects:
            obj.x += obj.vx
            obj.y += obj.vy
            # Jitter confidence
            obj.confidence = max(0.3, min(0.99,
                obj.confidence + self._rng.gauss(0, 0.02)))
            # Mark dead if out of frame
            if obj.x < -0.1 or obj.x > 1.1 or obj.y < -0.1 or obj.y > 1.1:
                obj.alive = False

        # Remove dead objects
        self._objects = [o for o in self._objects if o.alive]

        # Publish detections
        detections = []
        for obj in self._objects:
            detections.append({
                "id": obj.obj_id,
                "label": obj.label,
                "confidence": round(obj.confidence, 3),
                "bbox": {
                    "x": round(max(0.0, min(1.0, obj.x)), 4),
                    "y": round(max(0.0, min(1.0, obj.y)), 4),
                    "w": round(obj.w, 4),
                    "h": round(obj.h, 4),
                },
            })

        self._event_bus.publish("detection:camera", {
            "camera_id": self._camera_id,
            "detections": detections,
            "count": len(detections),
            "frame_number": self._tick_count,
        })

    def _spawn(self) -> None:
        """Spawn a new tracked object entering from a random edge."""
        self._next_id += 1
        obj_id = f"det-{self._next_id:04d}"

        # 70% person, 30% vehicle
        if self._rng.random() < 0.7:
            label = "person"
            speed = self._rng.uniform(0.005, 0.02)
            w, h = 0.05, 0.15
        else:
            label = "vehicle"
            speed = self._rng.uniform(0.02, 0.06)
            w, h = 0.12, 0.08

        # Enter from left or right edge
        if self._rng.random() < 0.5:
            x, vx = 0.0, speed
        else:
            x, vx = 1.0, -speed

        y = self._rng.uniform(0.2, 0.8)
        vy = self._rng.gauss(0, 0.002)

        self._objects.append(_TrackedObject(
            obj_id=obj_id,
            label=label,
            x=x, y=y, w=w, h=h,
            vx=vx, vy=vy,
            confidence=self._rng.uniform(0.7, 0.95),
        ))
