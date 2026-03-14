# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TargetTracker — unified registry of all tracked entities in the battlespace.

Merges simulation targets (friendly rovers/drones) with real-world detections
(YOLO person/vehicle) into a single view Amy can reason about.

Architecture
------------
The tracker is a *read model* — a denormalised view of targets from two
independent sources:

  1. Simulation telemetry: SimulationEngine publishes ``sim_telemetry``
     events at 10 Hz.  Commander._sim_bridge_loop forwards these to
     update_from_simulation(), which upserts TrackedTarget entries.

  2. YOLO detections: Vision pipeline publishes ``detections`` events.
     The bridge loop forwards person/vehicle detections to
     update_from_detection(), which matches by class+proximity or creates
     new entries.  Stale YOLO detections are pruned after 30s.

Why double-tracking (engine + tracker)?
  The engine owns *simulation physics* — waypoints, tick, battery drain.
  The tracker owns *Amy's perception* — what she can reason about.  These
  are different concerns:
    - The engine has targets the tracker doesn't (e.g. neutral animals
      that haven't triggered a zone yet).
    - The tracker has targets the engine doesn't (YOLO detections of real
      people and vehicles).
    - Dispatch latency is one tick (~100ms) which is invisible to
      tactical decision-making.

TrackedTarget is a lightweight projection.  It does NOT carry waypoints
or tick state — that remains on SimulationTarget in the engine.

Threat classification is NOT in the tracker.  ThreatClassifier in
escalation.py runs its own 2Hz loop over tracker.get_all() and maintains
ThreatRecord separately.  The tracker only tracks *identity and position*.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .target_history import TargetHistory


@dataclass
class TrackedTarget:
    """A target Amy is aware of — real or virtual."""

    target_id: str
    name: str
    alliance: str  # "friendly", "hostile", "unknown"
    asset_type: str  # "rover", "drone", "turret", "person", "vehicle", etc.
    position: tuple[float, float] = (0.0, 0.0)
    heading: float = 0.0
    speed: float = 0.0
    battery: float = 1.0
    last_seen: float = field(default_factory=time.monotonic)
    source: str = "manual"  # "simulation", "yolo", "manual"
    status: str = "active"
    position_source: str = "unknown"  # "gps", "simulation", "mqtt", "fixed", "yolo", "unknown"
    position_confidence: float = 0.0  # 0.0 = no confidence, 1.0 = high

    def to_dict(self, history: TargetHistory | None = None) -> dict:
        from .geo import local_to_latlng
        geo = local_to_latlng(self.position[0], self.position[1])
        d = {
            "target_id": self.target_id,
            "name": self.name,
            "alliance": self.alliance,
            "asset_type": self.asset_type,
            "position": {"x": self.position[0], "y": self.position[1]},
            "lat": geo["lat"],
            "lng": geo["lng"],
            "alt": geo["alt"],
            "heading": self.heading,
            "speed": self.speed,
            "battery": self.battery,
            "last_seen": self.last_seen,
            "source": self.source,
            "status": self.status,
            "position_source": self.position_source,
            "position_confidence": self.position_confidence,
        }
        if history is not None:
            d["trail"] = history.get_trail_dicts(self.target_id, max_points=20)
        return d


class TargetTracker:
    """Thread-safe registry of all tracked targets in the battlespace."""

    # Stale timeout — remove YOLO detections older than this
    STALE_TIMEOUT = 30.0

    def __init__(self) -> None:
        self._targets: dict[str, TrackedTarget] = {}
        self._lock = threading.Lock()
        self._detection_counter: int = 0
        self.history = TargetHistory()

    def update_from_simulation(self, sim_data: dict) -> None:
        """Update or create a tracked target from simulation telemetry.

        Args:
            sim_data: Dict from SimulationTarget.to_dict()
        """
        tid = sim_data["target_id"]
        pos = sim_data.get("position", {})
        position = (pos.get("x", 0.0), pos.get("y", 0.0))
        with self._lock:
            if tid in self._targets:
                t = self._targets[tid]
                t.position = position
                t.heading = sim_data.get("heading", 0.0)
                t.speed = sim_data.get("speed", 0.0)
                t.battery = sim_data.get("battery", 1.0)
                t.status = sim_data.get("status", "active")
                t.last_seen = time.monotonic()
            else:
                # Map SimulationTarget source to tracker source:
                # "sim" -> "simulation", "graphling" -> "simulation" (still sim-managed),
                # "real" -> "simulation" (real targets come through YOLO path instead)
                self._targets[tid] = TrackedTarget(
                    target_id=tid,
                    name=sim_data.get("name", tid[:8]),
                    alliance=sim_data.get("alliance", "unknown"),
                    asset_type=sim_data.get("asset_type", "unknown"),
                    position=position,
                    heading=sim_data.get("heading", 0.0),
                    speed=sim_data.get("speed", 0.0),
                    battery=sim_data.get("battery", 1.0),
                    last_seen=time.monotonic(),
                    source="simulation",
                    status=sim_data.get("status", "active"),
                    position_source="simulation",
                    position_confidence=1.0,
                )
        self.history.record(tid, position)

    def update_from_detection(self, detection: dict) -> None:
        """Update or create a tracked target from a YOLO detection.

        Args:
            detection: Dict with keys: class_name, confidence, bbox, center_x, center_y
        """
        # Ignore low-confidence detections
        if detection.get("confidence", 0) < 0.4:
            return

        class_name = detection.get("class_name", "unknown")
        cx = detection.get("center_x", 0.0)
        cy = detection.get("center_y", 0.0)

        # Determine alliance from detection class
        if class_name == "person":
            alliance = "hostile"
            asset_type = "person"
        elif class_name in ("car", "motorcycle", "bicycle"):
            alliance = "unknown"
            asset_type = "vehicle"
        else:
            alliance = "unknown"
            asset_type = class_name

        # Use detection class + approximate position as coarse ID
        # (real tracking would use ReID embeddings)
        tid = f"det_{class_name}_{self._detection_counter}"

        with self._lock:
            # Try to find an existing detection of same class near same position
            matched = None
            for existing in self._targets.values():
                if existing.source != "yolo":
                    continue
                if existing.asset_type != asset_type:
                    continue
                dx = existing.position[0] - cx
                dy = existing.position[1] - cy
                if (dx * dx + dy * dy) < 0.04:  # within ~0.2 normalized
                    matched = existing
                    break

            if matched:
                matched.position = (cx, cy)
                matched.last_seen = time.monotonic()
                tid = matched.target_id
            else:
                self._detection_counter += 1
                tid = f"det_{class_name}_{self._detection_counter}"
                self._targets[tid] = TrackedTarget(
                    target_id=tid,
                    name=f"{class_name.title()} #{self._detection_counter}",
                    alliance=alliance,
                    asset_type=asset_type,
                    position=(cx, cy),
                    last_seen=time.monotonic(),
                    source="yolo",
                    position_source="yolo",
                    position_confidence=0.1,
                )
        self.history.record(tid, (cx, cy))

    # BLE sightings have longer stale timeout — devices can be stationary
    BLE_STALE_TIMEOUT = 120.0

    def update_from_ble(self, sighting: dict) -> None:
        """Update or create a tracked target from a BLE sighting.

        Args:
            sighting: Dict with keys: mac, name, rssi, node_id,
                      and optionally position (x, y) from trilateration
                      and device_type from DeviceClassifier.
        """
        mac = sighting.get("mac", "")
        if not mac:
            return

        # Normalize MAC as target ID
        tid = f"ble_{mac.replace(':', '').lower()}"
        name = sighting.get("name") or mac
        rssi = sighting.get("rssi", -100)

        # Device type from DeviceClassifier (phone, watch, laptop, etc.)
        # Falls back to generic "ble_device" if not classified.
        asset_type = sighting.get("device_type") or "ble_device"

        # RSSI → confidence: -30dBm=1.0, -60dBm=0.7, -90dBm=0.1
        confidence = max(0.0, min(1.0, (rssi + 100) / 70))

        # Position from trilateration if available, else from observer node
        pos = sighting.get("position")
        if pos:
            position = (float(pos.get("x", 0)), float(pos.get("y", 0)))
            pos_source = "trilateration"
        else:
            # Use node position if available
            node_pos = sighting.get("node_position")
            if node_pos:
                position = (float(node_pos.get("x", 0)), float(node_pos.get("y", 0)))
                pos_source = "node_proximity"
            else:
                position = (0.0, 0.0)
                pos_source = "unknown"

        with self._lock:
            if tid in self._targets:
                t = self._targets[tid]
                t.last_seen = time.monotonic()
                t.position_confidence = confidence
                if pos_source != "unknown":
                    t.position = position
                    t.position_source = pos_source
                # Update asset_type if we got a specific classification
                if asset_type != "ble_device":
                    t.asset_type = asset_type
            else:
                self._targets[tid] = TrackedTarget(
                    target_id=tid,
                    name=name,
                    alliance="unknown",
                    asset_type=asset_type,
                    position=position,
                    last_seen=time.monotonic(),
                    source="ble",
                    position_source=pos_source,
                    position_confidence=confidence,
                )
        # Only record position if we have a meaningful location
        if pos_source != "unknown":
            self.history.record(tid, position)

    # RF motion targets have shorter stale timeout — transient detections
    RF_MOTION_STALE_TIMEOUT = 30.0

    def update_from_rf_motion(self, motion: dict) -> None:
        """Update or create a tracked target from an RF motion event.

        Args:
            motion: Dict with keys: target_id, pair_id, position (x, y tuple),
                    confidence, direction_hint, variance.
        """
        tid = motion.get("target_id", "")
        if not tid:
            return

        position = motion.get("position", (0.0, 0.0))
        if isinstance(position, dict):
            position = (float(position.get("x", 0)), float(position.get("y", 0)))

        confidence = float(motion.get("confidence", 0.5))
        direction = motion.get("direction_hint", "unknown")
        pair_id = motion.get("pair_id", "")

        with self._lock:
            if tid in self._targets:
                t = self._targets[tid]
                t.position = position
                t.position_confidence = confidence
                t.last_seen = time.monotonic()
                t.status = f"motion:{direction}"
            else:
                self._targets[tid] = TrackedTarget(
                    target_id=tid,
                    name=f"RF Motion ({pair_id})",
                    alliance="unknown",
                    asset_type="motion_detected",
                    position=position,
                    last_seen=time.monotonic(),
                    source="rf_motion",
                    position_source="rf_pair_midpoint",
                    position_confidence=confidence,
                    status=f"motion:{direction}",
                )
        self.history.record(tid, position)

    def get_all(self) -> list[TrackedTarget]:
        """Return all tracked targets (pruning stale YOLO detections)."""
        self._prune_stale()
        with self._lock:
            return list(self._targets.values())

    def get_hostiles(self) -> list[TrackedTarget]:
        """Return only hostile targets."""
        return [t for t in self.get_all() if t.alliance == "hostile"]

    def get_friendlies(self) -> list[TrackedTarget]:
        """Return only friendly targets."""
        return [t for t in self.get_all() if t.alliance == "friendly"]

    def get_target(self, target_id: str) -> TrackedTarget | None:
        """Get a specific target by ID."""
        with self._lock:
            return self._targets.get(target_id)

    def remove(self, target_id: str) -> bool:
        """Remove a target from tracking."""
        with self._lock:
            return self._targets.pop(target_id, None) is not None

    def summary(self) -> str:
        """Battlespace summary for Amy's thinking context."""
        all_targets = self.get_all()
        if not all_targets:
            return ""
        friendlies = [t for t in all_targets if t.alliance == "friendly"]
        hostiles = [t for t in all_targets if t.alliance == "hostile"]
        unknowns = [t for t in all_targets if t.alliance == "unknown"]

        parts = []
        if friendlies:
            parts.append(f"{len(friendlies)} friendly")
        if hostiles:
            parts.append(f"{len(hostiles)} hostile")
        if unknowns:
            parts.append(f"{len(unknowns)} unknown")

        result = f"BATTLESPACE: {', '.join(parts)} target(s) tracked"

        # Urgency alerts: hostiles near friendlies (capped to avoid O(n*m) blowup)
        import math
        alerts = []
        _max_proximity_checks = 200  # cap each side to keep summary fast
        _h_sample = hostiles[:_max_proximity_checks]
        _f_sample = friendlies[:_max_proximity_checks]
        for h in _h_sample:
            for f in _f_sample:
                dx = h.position[0] - f.position[0]
                dy = h.position[1] - f.position[1]
                dist_sq = dx * dx + dy * dy
                if dist_sq < 25.0:  # 5.0^2
                    dist = math.sqrt(dist_sq)
                    alerts.append(f"ALERT: {h.name} within {dist:.1f} units of {f.name}")
                    if len(alerts) >= 3:
                        break
            if len(alerts) >= 3:
                break
        if alerts:
            result += "\n" + "\n".join(alerts[:3])

        # Sector grouping for hostiles
        if hostiles:
            sectors: dict[str, list[str]] = {}
            for h in hostiles:
                sx = "E" if h.position[0] > 5 else ("W" if h.position[0] < -5 else "")
                sy = "N" if h.position[1] > 5 else ("S" if h.position[1] < -5 else "")
                sector = (sy + sx) or "center"
                sectors.setdefault(sector, []).append(h.name)
            sector_parts = [f"{len(names)} in {s}" for s, names in sectors.items()]
            result += f"\nHostile sectors: {', '.join(sector_parts)}"

        return result

    # Simulation targets that stop receiving telemetry updates are stale —
    # the engine has removed them.  Use a longer timeout than YOLO since
    # sim telemetry arrives at 10Hz (100ms); 10s of silence means gone.
    SIM_STALE_TIMEOUT = 10.0

    def _prune_stale(self) -> None:
        """Remove targets that haven't been updated recently."""
        now = time.monotonic()
        with self._lock:
            stale = [
                tid for tid, t in self._targets.items()
                if (t.source == "yolo" and (now - t.last_seen) > self.STALE_TIMEOUT)
                or (t.source == "simulation" and (now - t.last_seen) > self.SIM_STALE_TIMEOUT)
                or (t.source == "ble" and (now - t.last_seen) > self.BLE_STALE_TIMEOUT)
                or (t.source == "rf_motion" and (now - t.last_seen) > self.RF_MOTION_STALE_TIMEOUT)
            ]
            for tid in stale:
                del self._targets[tid]
                self.history.clear(tid)
