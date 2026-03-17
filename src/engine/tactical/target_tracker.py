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

import math
import threading
import time
from dataclasses import dataclass, field

from .target_history import TargetHistory
from .target_reappearance import TargetReappearanceMonitor


# ---------------------------------------------------------------------------
# Confidence decay — exponential decay per source type
# ---------------------------------------------------------------------------
# half-life in seconds: after this time, confidence drops to 50%
_HALF_LIVES: dict[str, float] = {
    "ble": 30.0,
    "wifi": 45.0,
    "yolo": 15.0,
    "rf_motion": 10.0,
    "mesh": 120.0,
    "simulation": 0.0,   # never decays
    "manual": 300.0,
}
_MIN_CONFIDENCE = 0.05
_LN2 = math.log(2)

# Multi-source confidence boosting — multiplicative bonus per confirming source
_MULTI_SOURCE_BOOST = 1.3  # 30% boost per additional confirming source
_MAX_BOOSTED_CONFIDENCE = 0.99

# Velocity consistency — max plausible speed in meters/second
# 50 m/s ~ 180 km/h, anything above is suspicious
_MAX_PLAUSIBLE_SPEED_MPS = 50.0
_TELEPORT_FLAG_COOLDOWN = 30.0  # seconds before re-flagging same target


def _decayed_confidence(source: str, initial: float, elapsed: float) -> float:
    """Compute exponentially decayed confidence."""
    if elapsed <= 0.0:
        return max(0.0, min(1.0, initial))
    hl = _HALF_LIVES.get(source, 300.0)
    if hl <= 0.0:
        return max(0.0, min(1.0, initial))
    decayed = initial * math.exp(-_LN2 / hl * elapsed)
    return min(1.0, decayed) if decayed >= _MIN_CONFIDENCE else 0.0


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
    threat_score: float = 0.0  # 0.0 = no threat, 1.0 = maximum threat probability
    _initial_confidence: float = 0.0  # stored at detection time for decay
    confirming_sources: set = field(default_factory=set)  # source types that confirmed this target
    correlated_ids: list = field(default_factory=list)  # IDs of targets fused into this one
    correlation_confidence: float = 0.0  # weighted correlation score from correlator
    velocity_suspicious: bool = False  # flagged if target teleported
    _last_velocity_flag: float = 0.0  # monotonic time of last velocity flag
    classification: str = "unknown"  # RL/ML classification (person, vehicle, phone, etc.)
    classification_confidence: float = 0.0  # confidence of the classification model

    @property
    def effective_confidence(self) -> float:
        """Position confidence with exponential time decay and multi-source boost."""
        elapsed = time.monotonic() - self.last_seen
        initial = self._initial_confidence if self._initial_confidence > 0 else self.position_confidence
        decayed = _decayed_confidence(self.source, initial, elapsed)
        # Multi-source boost: each additional confirming source multiplies confidence
        extra_sources = max(0, len(self.confirming_sources) - 1)
        if extra_sources > 0:
            boosted = decayed * (_MULTI_SOURCE_BOOST ** extra_sources)
            return min(_MAX_BOOSTED_CONFIDENCE, boosted)
        return decayed

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
            "position_confidence": self.effective_confidence,
            "threat_score": self.threat_score,
            "confirming_sources": list(self.confirming_sources),
            "sources": list(self.confirming_sources),
            "source_count": len(self.confirming_sources),
            "correlated_ids": list(self.correlated_ids),
            "correlation_confidence": self.correlation_confidence,
            "velocity_suspicious": self.velocity_suspicious,
            "classification": self.classification,
            "classification_confidence": self.classification_confidence,
        }
        if history is not None:
            d["trail"] = history.get_trail_dicts(self.target_id, max_points=20)
        return d


class TargetTracker:
    """Thread-safe registry of all tracked targets in the battlespace."""

    # Stale timeout — remove YOLO detections older than this
    STALE_TIMEOUT = 30.0

    def __init__(self, event_bus=None) -> None:
        self._targets: dict[str, TrackedTarget] = {}
        self._lock = threading.Lock()
        self._detection_counter: int = 0
        self._event_bus = event_bus
        self._geofence_engine = None  # Set via set_geofence_engine()
        self.history = TargetHistory()
        self.reappearance_monitor = TargetReappearanceMonitor(
            event_bus=event_bus,
            min_absence_seconds=60.0,
        )

    def set_geofence_engine(self, engine) -> None:
        """Wire geofence engine for automatic zone checks on position updates."""
        self._geofence_engine = engine

    def _check_geofence(self, target_id: str, game_x: float, game_y: float) -> None:
        """Check if a target's position triggers geofence enter/exit events.

        Zone polygons are stored in game coordinates (meters from geo center),
        so we pass game coordinates directly for point-in-polygon tests.
        """
        if not self._geofence_engine:
            return
        try:
            self._geofence_engine.check(target_id, (game_x, game_y))
        except Exception:
            pass  # Don't let geofence errors break target tracking

    def _check_velocity(self, target: TrackedTarget, new_pos: tuple[float, float]) -> None:
        """Check if position change implies impossible velocity (teleportation).

        Flags the target as velocity_suspicious if the implied speed exceeds
        _MAX_PLAUSIBLE_SPEED_MPS. This catches GPS glitches, MAC rotation
        misattribution, and spoofing.
        """
        now = time.monotonic()
        dt = now - target.last_seen
        if dt <= 0.0 or dt > 120.0:  # skip if first update or very stale
            return

        dx = new_pos[0] - target.position[0]
        dy = new_pos[1] - target.position[1]
        dist = math.sqrt(dx * dx + dy * dy)
        speed = dist / dt  # meters per second (assuming local coords are meters)

        if speed > _MAX_PLAUSIBLE_SPEED_MPS:
            if (now - target._last_velocity_flag) > _TELEPORT_FLAG_COOLDOWN:
                target.velocity_suspicious = True
                target._last_velocity_flag = now
        else:
            # Clear flag if velocity is now plausible
            target.velocity_suspicious = False

    def _add_confirming_source(self, target: TrackedTarget, source: str) -> None:
        """Register an additional source that confirms this target's existence.

        Multi-source confirmation boosts confidence multiplicatively via
        effective_confidence property.
        """
        target.confirming_sources.add(source)

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
                self._check_velocity(t, position)
                t.position = position
                t.heading = sim_data.get("heading", 0.0)
                t.speed = sim_data.get("speed", 0.0)
                t.battery = sim_data.get("battery", 1.0)
                t.status = sim_data.get("status", "active")
                t.last_seen = time.monotonic()
                self._add_confirming_source(t, "simulation")
            else:
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
                    _initial_confidence=1.0,
                    confirming_sources={"simulation"},
                )
        self.history.record(tid, position)
        self._check_geofence(tid, position[0], position[1])

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
                dist_sq = dx * dx + dy * dy
                # Adaptive threshold: if coords are in game space (meters),
                # use 9 sq meters (3m radius); if normalized (0-1), use 0.04.
                threshold = 9.0 if (abs(cx) > 2.0 or abs(cy) > 2.0) else 0.04
                if dist_sq < threshold:  # within proximity
                    matched = existing
                    break

            if matched:
                self._check_velocity(matched, (cx, cy))
                matched.position = (cx, cy)
                matched.last_seen = time.monotonic()
                self._add_confirming_source(matched, "yolo")
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
                    _initial_confidence=0.1,
                    confirming_sources={"yolo"},
                    classification=class_name,
                    classification_confidence=detection.get("confidence", 0.0),
                )
        self.history.record(tid, (cx, cy))

    def update_from_camera_detection(
        self,
        detection: dict,
        camera_lat: float,
        camera_lng: float,
    ) -> None:
        """Update or create a target from a camera detection, positioned near the camera.

        Converts normalized pixel coordinates (0-1) into game coordinates
        offset from the camera's lat/lng, so detections appear on the
        tactical map near their source camera.

        Args:
            detection: Dict with keys: label/class_name, confidence, bbox.
            camera_lat: Camera latitude.
            camera_lng: Camera longitude.
        """
        from .geo import latlng_to_local

        label = detection.get("label") or detection.get("class_name", "unknown")
        confidence = detection.get("confidence", 0.5)
        if confidence < 0.4:
            return

        # Get camera position in game coordinates
        cam_x, cam_y, _ = latlng_to_local(camera_lat, camera_lng)

        # Compute a small offset from the camera based on pixel position.
        # Normalized bbox center: (0,0)=top-left, (1,1)=bottom-right.
        bbox = detection.get("bbox", {})
        if isinstance(bbox, dict):
            px = bbox.get("x", 0.5)
            py = bbox.get("y", 0.5)
        else:
            px, py = 0.5, 0.5

        # Map pixel position to a scatter area around the camera (up to 30m)
        offset_x = (px - 0.5) * 60.0  # -30m to +30m
        offset_y = (0.5 - py) * 30.0   # higher in frame = further away

        game_x = cam_x + offset_x
        game_y = cam_y + offset_y

        self.update_from_detection({
            "class_name": label,
            "confidence": confidence,
            "center_x": game_x,
            "center_y": game_y,
        })

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
                if pos_source != "unknown":
                    self._check_velocity(t, position)
                    t.position = position
                    t.position_source = pos_source
                t.last_seen = time.monotonic()
                t.position_confidence = confidence
                t._initial_confidence = confidence
                self._add_confirming_source(t, "ble")
                # Update asset_type if we got a specific classification
                if asset_type != "ble_device":
                    t.asset_type = asset_type
                # Update classification from sighting data (RL/ML model output)
                if sighting.get("classification"):
                    t.classification = sighting["classification"]
                    t.classification_confidence = float(sighting.get("classification_confidence", 0.0))
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
                    _initial_confidence=confidence,
                    confirming_sources={"ble"},
                    classification=sighting.get("classification", asset_type),
                    classification_confidence=float(sighting.get("classification_confidence", 0.0)),
                )
                # Check if this is a returning target
                self.reappearance_monitor.check_reappearance(
                    target_id=tid,
                    name=name,
                    source="ble",
                    asset_type=asset_type,
                    position=position,
                )
        # Only record position if we have a meaningful location
        if pos_source != "unknown":
            self.history.record(tid, position)
            self._check_geofence(tid, position[0], position[1])

    # Mesh radio targets — nodes can be stationary for long periods
    MESH_STALE_TIMEOUT = 300.0

    def update_from_mesh(self, mesh_data: dict) -> None:
        """Update or create a tracked target from a Meshtastic mesh node.

        Mesh nodes are friendly infrastructure with GPS. They report position
        via LoRa and have longer stale timeouts since nodes can be stationary
        repeaters that only update periodically.

        Args:
            mesh_data: Dict with keys: target_id, name, lat, lng, alt,
                       battery (0-1 float), short_name, hw_model, firmware, snr.
                       Position can also be in position: {x, y} (local coords).
        """
        tid = mesh_data.get("target_id", "")
        if not tid:
            return

        name = mesh_data.get("name", tid)
        battery = mesh_data.get("battery", 1.0)
        alliance = mesh_data.get("alliance", "friendly")
        asset_type = mesh_data.get("asset_type", "mesh_radio")

        # Convert lat/lng to local coordinates if provided
        lat = mesh_data.get("lat")
        lng = mesh_data.get("lng")
        alt = mesh_data.get("alt", 0.0)

        if lat is not None and lng is not None and (lat != 0.0 or lng != 0.0):
            try:
                from .geo import latlng_to_local
                x, y, _z = latlng_to_local(lat, lng, alt or 0.0)
                position = (x, y)
                pos_source = "gps"
                confidence = 0.9  # GPS from mesh radio is high confidence
            except Exception:
                position = (0.0, 0.0)
                pos_source = "unknown"
                confidence = 0.0
        elif mesh_data.get("position"):
            pos = mesh_data["position"]
            position = (float(pos.get("x", 0)), float(pos.get("y", 0)))
            pos_source = "gps"
            confidence = 0.9
        else:
            position = (0.0, 0.0)
            pos_source = "unknown"
            confidence = 0.0

        with self._lock:
            if tid in self._targets:
                t = self._targets[tid]
                if pos_source != "unknown":
                    self._check_velocity(t, position)
                    t.position = position
                    t.position_source = pos_source
                t.name = name
                t.battery = battery
                t.last_seen = time.monotonic()
                t.position_confidence = confidence
                t._initial_confidence = confidence
                self._add_confirming_source(t, "mesh")
            else:
                self._targets[tid] = TrackedTarget(
                    target_id=tid,
                    name=name,
                    alliance=alliance,
                    asset_type=asset_type,
                    position=position,
                    last_seen=time.monotonic(),
                    source="mesh",
                    battery=battery,
                    position_source=pos_source,
                    position_confidence=confidence,
                    _initial_confidence=confidence,
                    confirming_sources={"mesh"},
                    classification="mesh_radio",
                )
                # Check if this is a returning node
                self.reappearance_monitor.check_reappearance(
                    target_id=tid,
                    name=name,
                    source="mesh",
                    asset_type=asset_type,
                    position=position,
                )
        # Record position if we have a meaningful location
        if pos_source != "unknown":
            self.history.record(tid, position)
            self._check_geofence(tid, position[0], position[1])

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
                self._check_velocity(t, position)
                t.position = position
                t.position_confidence = confidence
                t._initial_confidence = confidence
                t.last_seen = time.monotonic()
                t.status = f"motion:{direction}"
                self._add_confirming_source(t, "rf_motion")
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
                    _initial_confidence=confidence,
                    status=f"motion:{direction}",
                    confirming_sources={"rf_motion"},
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
        """Remove targets that haven't been updated recently.

        Records departures in the reappearance monitor so returning
        targets can be detected.
        """
        now = time.monotonic()
        with self._lock:
            stale = [
                tid for tid, t in self._targets.items()
                if (t.source == "yolo" and (now - t.last_seen) > self.STALE_TIMEOUT)
                or (t.source == "simulation" and (now - t.last_seen) > self.SIM_STALE_TIMEOUT)
                or (t.source == "ble" and (now - t.last_seen) > self.BLE_STALE_TIMEOUT)
                or (t.source == "rf_motion" and (now - t.last_seen) > self.RF_MOTION_STALE_TIMEOUT)
                or (t.source == "mesh" and (now - t.last_seen) > self.MESH_STALE_TIMEOUT)
            ]
            for tid in stale:
                t = self._targets[tid]
                # Record departure for reappearance monitoring
                self.reappearance_monitor.record_departure(
                    target_id=tid,
                    name=t.name,
                    source=t.source,
                    asset_type=t.asset_type,
                    last_position=t.position,
                )
                del self._targets[tid]
                self.history.clear(tid)
