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
# Each device has a "placement" key that controls positioning behavior:
#   "building" — stationary inside a building (IoT devices, home electronics)
#   "mobile"   — walking speed random walk (phones, wearables, tablets)
#   "vehicle"  — driving speed, moves along roads (automotive)
#   "roaming"  — slow drift, occasionally disappears (trackers, unknowns)

_BLE_DEVICE_POOL: list[dict[str, str]] = [
    {"name": "iPhone-Matt", "mac": "AA:BB:CC:11:22:01", "type": "phone", "placement": "mobile"},
    {"name": "Galaxy-S24", "mac": "AA:BB:CC:11:22:02", "type": "phone", "placement": "mobile"},
    {"name": "Pixel-9", "mac": "AA:BB:CC:11:22:03", "type": "phone", "placement": "mobile"},
    {"name": "AirPods-Pro", "mac": "AA:BB:CC:11:22:04", "type": "audio", "placement": "mobile"},
    {"name": "WH-1000XM5", "mac": "AA:BB:CC:11:22:05", "type": "audio", "placement": "mobile"},
    {"name": "Apple-Watch-7", "mac": "AA:BB:CC:11:22:06", "type": "wearable", "placement": "mobile"},
    {"name": "Fitbit-Charge", "mac": "AA:BB:CC:11:22:07", "type": "wearable", "placement": "mobile"},
    {"name": "Tile-Mate", "mac": "AA:BB:CC:11:22:08", "type": "tracker", "placement": "roaming"},
    {"name": "AirTag", "mac": "AA:BB:CC:11:22:09", "type": "tracker", "placement": "roaming"},
    {"name": "Ring-Doorbell", "mac": "AA:BB:CC:11:22:0A", "type": "iot", "placement": "building"},
    {"name": "Nest-Thermostat", "mac": "AA:BB:CC:11:22:0B", "type": "iot", "placement": "building"},
    {"name": "Echo-Dot", "mac": "AA:BB:CC:11:22:0C", "type": "iot", "placement": "building"},
    {"name": "", "mac": "DD:EE:FF:11:22:01", "type": "unknown", "placement": "roaming"},
    {"name": "", "mac": "DD:EE:FF:11:22:02", "type": "unknown", "placement": "roaming"},
    {"name": "", "mac": "DD:EE:FF:11:22:03", "type": "unknown", "placement": "roaming"},
    {"name": "", "mac": "DD:EE:FF:11:22:04", "type": "unknown", "placement": "roaming"},
    {"name": "JBL-Flip6", "mac": "AA:BB:CC:11:22:0D", "type": "audio", "placement": "building"},
    {"name": "iPad-Air", "mac": "AA:BB:CC:11:22:0E", "type": "tablet", "placement": "mobile"},
    {"name": "Surface-Go", "mac": "AA:BB:CC:11:22:0F", "type": "tablet", "placement": "building"},
    {"name": "Tesla-Key", "mac": "AA:BB:CC:11:22:10", "type": "automotive", "placement": "vehicle"},
]

# Fixed building positions — offsets from scanner center (lat/lng degrees).
# Each represents a realistic building location near the demo neighborhood.
# ~0.0003 degrees ≈ 30m, so these are within a few blocks.
_BUILDING_POSITIONS: list[tuple[float, float]] = [
    (0.0004, -0.0002),   # building NE — Ring Doorbell at entrance
    (-0.0001, 0.0003),   # building NW — Nest Thermostat inside
    (0.0002, 0.0005),    # building E  — Echo Dot inside
    (-0.0003, -0.0004),  # building SW — JBL speaker in living room
    (0.0005, 0.0001),    # building SE — Surface tablet on desk
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
        node_lat: float | None = None,
        node_lon: float | None = None,
    ) -> None:
        super().__init__(interval=interval)
        self._max_devices = max_devices
        self._known_ratio = known_ratio
        self._node_id = node_id
        self._node_lat = node_lat
        self._node_lon = node_lon
        self._active_devices: list[dict[str, str]] = []
        self._rng = random.Random(42)
        # Per-device position offsets that drift over time (simulates movement)
        self._device_offsets: dict[str, tuple[float, float]] = {}
        # Building position assignments (mac -> fixed offset index)
        self._building_assignments: dict[str, int] = {}
        self._next_building_idx = 0

    def _assign_building(self, mac: str) -> tuple[float, float]:
        """Assign a fixed building position to an IoT device."""
        if mac not in self._building_assignments:
            self._building_assignments[mac] = self._next_building_idx % len(_BUILDING_POSITIONS)
            self._next_building_idx += 1
        idx = self._building_assignments[mac]
        return _BUILDING_POSITIONS[idx]

    def _tick(self) -> None:
        assert self._event_bus is not None
        self._rotate_devices()
        devices = []
        for dev in self._active_devices:
            mac = dev["mac"]
            placement = dev.get("placement", "mobile")

            if placement == "building":
                # Stationary inside a building — fixed position, strong RSSI
                rssi = self._rng.randint(-55, -30)
                bld_offset = self._assign_building(mac)
                dlat, dlng = bld_offset
            elif placement == "vehicle":
                # Driving speed — faster drift along a direction
                rssi = self._rng.randint(-70, -40)
                if mac not in self._device_offsets:
                    self._device_offsets[mac] = (
                        self._rng.uniform(-0.0003, 0.0003),
                        self._rng.uniform(-0.0003, 0.0003),
                    )
                old_dlat, old_dlng = self._device_offsets[mac]
                old_dlat += self._rng.gauss(0, 0.00005)
                old_dlng += self._rng.gauss(0, 0.00005)
                old_dlat = max(-0.002, min(0.002, old_dlat))
                old_dlng = max(-0.002, min(0.002, old_dlng))
                self._device_offsets[mac] = (old_dlat, old_dlng)
                dlat, dlng = old_dlat, old_dlng
            elif placement == "roaming":
                # Slow drift, weaker signal
                rssi = self._rng.randint(-85, -50)
                if mac not in self._device_offsets:
                    self._device_offsets[mac] = (
                        self._rng.uniform(-0.0004, 0.0004),
                        self._rng.uniform(-0.0004, 0.0004),
                    )
                old_dlat, old_dlng = self._device_offsets[mac]
                old_dlat += self._rng.gauss(0, 0.000008)
                old_dlng += self._rng.gauss(0, 0.000008)
                old_dlat = max(-0.0006, min(0.0006, old_dlat))
                old_dlng = max(-0.0006, min(0.0006, old_dlng))
                self._device_offsets[mac] = (old_dlat, old_dlng)
                dlat, dlng = old_dlat, old_dlng
            else:
                # "mobile" — walking speed, default behavior for phones/wearables
                rssi = self._rng.randint(-75, -35)
                if mac not in self._device_offsets:
                    self._device_offsets[mac] = (
                        self._rng.uniform(-0.0003, 0.0003),
                        self._rng.uniform(-0.0003, 0.0003),
                    )
                old_dlat, old_dlng = self._device_offsets[mac]
                old_dlat += self._rng.gauss(0, 0.000015)
                old_dlng += self._rng.gauss(0, 0.000015)
                old_dlat = max(-0.0005, min(0.0005, old_dlat))
                old_dlng = max(-0.0005, min(0.0005, old_dlng))
                self._device_offsets[mac] = (old_dlat, old_dlng)
                dlat, dlng = old_dlat, old_dlng

            dev_entry: dict = {
                "mac": mac,
                "name": dev["name"],
                "rssi": rssi,
                "type": dev["type"],
            }
            if self._node_lat is not None and self._node_lon is not None:
                dev_entry["lat"] = self._node_lat + dlat
                dev_entry["lng"] = self._node_lon + dlng
            devices.append(dev_entry)

        payload: dict = {
            "node_id": self._node_id,
            "devices": devices,
            "count": len(devices),
        }
        # Include scanner position so edge_tracker registers it and
        # targets get geographic coordinates for position history.
        if self._node_lat is not None and self._node_lon is not None:
            payload["node_lat"] = self._node_lat
            payload["node_lon"] = self._node_lon

        self._event_bus.publish("fleet.ble_presence", payload)

    def _rotate_devices(self) -> None:
        """Randomly add/remove devices to simulate movement.

        Building-placed devices (IoT) never rotate out — they are always
        present since they are stationary inside buildings.  Mobile and
        roaming devices churn to simulate people coming and going.
        """
        pool = list(_BLE_DEVICE_POOL)
        known = [d for d in pool if d["name"]]
        unknown = [d for d in pool if not d["name"]]

        n_known = int(self._max_devices * self._known_ratio)
        n_unknown = self._max_devices - n_known

        # Building devices never rotate out; others have 20% churn
        self._active_devices = [
            d for d in self._active_devices
            if d.get("placement") == "building" or self._rng.random() > 0.2
        ]

        # Ensure building devices are always present (up to max capacity)
        current_macs = {d["mac"] for d in self._active_devices}
        building_pool = [d for d in pool if d.get("placement") == "building"]
        for d in building_pool:
            if len(self._active_devices) >= self._max_devices:
                break
            if d["mac"] not in current_macs:
                self._active_devices.append(d)
                current_macs.add(d["mac"])

        # Fill up to max with mobile/roaming devices
        available_known = [d for d in known if d["mac"] not in current_macs and d.get("placement") != "building"]
        available_unknown = [d for d in unknown if d["mac"] not in current_macs]

        # Respect max_devices overall
        remaining = self._max_devices - len(self._active_devices)
        if remaining <= 0:
            return

        n_need_known = max(0, min(remaining, n_known - sum(1 for d in self._active_devices if d["name"])))
        remaining -= n_need_known
        n_need_unknown = max(0, min(remaining, n_unknown - sum(1 for d in self._active_devices if not d["name"])))

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

    # Detection class weights: (label, probability, speed_range, width, height)
    _DETECTION_CLASSES: list[tuple[str, float, tuple[float, float], float, float]] = [
        ("person",     0.40, (0.005, 0.020), 0.05, 0.15),
        ("vehicle",    0.18, (0.020, 0.060), 0.12, 0.08),
        ("dog",        0.10, (0.008, 0.025), 0.06, 0.06),
        ("bicycle",    0.10, (0.012, 0.035), 0.07, 0.08),
        ("motorcycle", 0.07, (0.025, 0.055), 0.09, 0.07),
        ("backpack",   0.05, (0.004, 0.012), 0.04, 0.05),
        ("truck",      0.05, (0.015, 0.040), 0.15, 0.10),
        ("cat",        0.05, (0.006, 0.018), 0.04, 0.04),
    ]

    def _spawn(self) -> None:
        """Spawn a new tracked object entering from a random edge."""
        self._next_id += 1
        obj_id = f"det-{self._next_id:04d}"

        # Weighted random selection from detection classes
        roll = self._rng.random()
        cumulative = 0.0
        label, speed_range, w, h = "person", (0.005, 0.02), 0.05, 0.15
        for cls_label, prob, spd_range, cls_w, cls_h in self._DETECTION_CLASSES:
            cumulative += prob
            if roll < cumulative:
                label = cls_label
                speed_range = spd_range
                w, h = cls_w, cls_h
                break

        speed = self._rng.uniform(*speed_range)

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


# ── Multi-Node BLE Trilateration Demo Generator ─────────────────────────

# Three fixed edge nodes at known positions around a neighborhood area.
# A handful of BLE targets move between them so the trilateration engine
# always has >= 3 RSSI readings and can compute a live position.

_TRILAT_NODES: list[dict] = [
    {"node_id": "trilat-node-north", "lat": 37.7760, "lon": -122.4180},
    {"node_id": "trilat-node-east",  "lat": 37.7745, "lon": -122.4160},
    {"node_id": "trilat-node-west",  "lat": 37.7745, "lon": -122.4200},
]

_TRILAT_BLE_TARGETS: list[dict] = [
    {"mac": "TT:RI:LA:T0:00:01", "name": "Trilat-Phone-A"},
    {"mac": "TT:RI:LA:T0:00:02", "name": "Trilat-Watch-B"},
    {"mac": "TT:RI:LA:T0:00:03", "name": "Trilat-Tag-C"},
]


@dataclass
class _TrilatTargetState:
    """Moving BLE target for trilateration demo."""
    mac: str
    name: str
    lat: float
    lon: float
    heading: float = 0.0  # radians


class TrilaterationDemoGenerator(_BaseGenerator):
    """Generates multi-node BLE sightings that exercise the trilateration engine.

    Simulates 3 fixed edge nodes and 3 moving BLE targets.  Each tick,
    every node "sees" every target with an RSSI computed from the
    distance between node and target (path-loss model).  This feeds the
    trilateration engine which computes a live position from 3 readings.

    Publishes ``fleet.ble_presence`` events (one per node per tick) so
    the EdgeTrackerPlugin picks them up identically to real hardware.
    Also publishes ``trilat:position_update`` with computed positions
    for direct frontend consumption.
    """

    def __init__(
        self,
        interval: float = 3.0,
        tx_power: float = -59.0,
        path_loss_exp: float = 2.5,
    ) -> None:
        super().__init__(interval=interval)
        self._tx_power = tx_power
        self._path_loss_exp = path_loss_exp
        self._targets: list[_TrilatTargetState] = []
        self._rng = random.Random(314)
        self._tick_count = 0

    def start(self, event_bus: EventBus) -> None:
        # Initialize target states near the center of the 3 nodes
        center_lat = sum(n["lat"] for n in _TRILAT_NODES) / len(_TRILAT_NODES)
        center_lon = sum(n["lon"] for n in _TRILAT_NODES) / len(_TRILAT_NODES)
        self._targets = []
        for cfg in _TRILAT_BLE_TARGETS:
            self._targets.append(_TrilatTargetState(
                mac=cfg["mac"],
                name=cfg["name"],
                lat=center_lat + self._rng.uniform(-0.0005, 0.0005),
                lon=center_lon + self._rng.uniform(-0.0005, 0.0005),
                heading=self._rng.uniform(0, 2 * math.pi),
            ))
        super().start(event_bus)

    def _tick(self) -> None:
        assert self._event_bus is not None
        self._tick_count += 1

        # Move targets (walking speed ~1.4 m/s)
        drift = 0.0000126 * self._interval
        for t in self._targets:
            t.heading += self._rng.gauss(0, 0.5)
            t.lat += math.cos(t.heading) * drift
            t.lon += math.sin(t.heading) * drift

        # For each node, publish a fleet.ble_presence with RSSI for all targets
        for node in _TRILAT_NODES:
            devices = []
            for t in self._targets:
                dist_m = self._haversine_m(
                    node["lat"], node["lon"], t.lat, t.lon
                )
                # Path-loss RSSI model: RSSI = tx_power - 10 * n * log10(d)
                dist_m = max(dist_m, 0.5)  # clamp to avoid log(0)
                rssi = self._tx_power - 10 * self._path_loss_exp * math.log10(dist_m)
                rssi += self._rng.gauss(0, 2)  # noise
                rssi = max(-100, min(-20, rssi))
                devices.append({
                    "mac": t.mac,
                    "name": t.name,
                    "rssi": round(rssi),
                    "device_type": "phone" if "Phone" in t.name else "wearable",
                })

            self._event_bus.publish("fleet.ble_presence", {
                "node_id": node["node_id"],
                "node_lat": node["lat"],
                "node_lon": node["lon"],
                "devices": devices,
                "count": len(devices),
            })

        # Publish computed positions for frontend overlay
        positions = []
        for t in self._targets:
            positions.append({
                "mac": t.mac,
                "name": t.name,
                "lat": round(t.lat, 8),
                "lon": round(t.lon, 8),
            })

        self._event_bus.publish("trilat:position_update", {
            "positions": positions,
            "nodes": [
                {"node_id": n["node_id"], "lat": n["lat"], "lon": n["lon"]}
                for n in _TRILAT_NODES
            ],
            "tick": self._tick_count,
        })

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Approximate distance in meters between two lat/lon points."""
        dlat = (lat2 - lat1) * 111320
        dlon = (lon2 - lon1) * 111320 * math.cos(math.radians((lat1 + lat2) / 2))
        return math.sqrt(dlat * dlat + dlon * dlon)
