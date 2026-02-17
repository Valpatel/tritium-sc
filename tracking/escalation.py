"""Threat escalation — autonomous threat classification and unit dispatch.

Architecture overview:  docs/ESCALATION.md

ThreatClassifier monitors all non-friendly, non-neutral targets against
zone definitions and escalates/de-escalates threat levels on a discrete
ladder:  none -> unknown -> suspicious -> hostile

AutoDispatcher listens for escalation events on the EventBus and
dispatches the nearest available friendly unit to intercept.  Amy's
ThinkingThread can see and override dispatches via escalate() /
clear_threat() / dispatch() Lua actions.

Design philosophy:
    AutoDispatcher handles immediate tactical response (fast, algorithmic).
    Amy handles strategic awareness (she sees dispatches in her thinking
    context and can override, recall, or re-assign).  Both write to the
    same SimulationTarget waypoints — last writer wins.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from comms.event_bus import EventBus
    from tracking.tracker import TargetTracker, TrackedTarget
    from simulation.engine import SimulationEngine

logger = logging.getLogger("amy.escalation")

# Threat ladder levels (ordered)
THREAT_LEVELS = ["none", "unknown", "suspicious", "hostile"]


@dataclass
class ThreatRecord:
    """Tracks threat state for a single target.

    One record exists per non-friendly, non-neutral target that the
    classifier has seen.  Records persist even when threat_level returns
    to ``none`` (they are only pruned when the target disappears from
    the TargetTracker).
    """

    target_id: str
    threat_level: str = "none"
    level_since: float = field(default_factory=time.monotonic)
    in_zone: str = ""       # name of the zone the target is currently in
    zone_enter_time: float = 0.0
    last_update: float = field(default_factory=time.monotonic)
    prior_hostile: bool = False  # was this target ever classified as hostile?


class ThreatClassifier:
    """Monitors targets and classifies threat levels at 2Hz.

    Escalation triggers:
        - Perimeter zone entry: none -> unknown
        - Restricted zone entry: -> suspicious
        - Lingering in zone > 30s: -> hostile
        - Speed toward protected area: escalation boost
        - Manual override via set_threat_level()

    De-escalation:
        - Target leaves all zones for 30s: step down one level
    """

    TICK_INTERVAL = 0.5  # 2Hz
    LINGER_THRESHOLD = 30.0  # seconds in zone before hostile
    DEESCALATION_TIME = 30.0  # seconds out of zones before step-down

    def __init__(
        self,
        event_bus: EventBus,
        target_tracker: TargetTracker,
        zones: list[dict] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._tracker = target_tracker
        self._zones: list[dict] = zones or []
        self._records: dict[str, ThreatRecord] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        # Track when targets left all zones (for de-escalation)
        self._zone_exit_times: dict[str, float] = {}

    @property
    def zones(self) -> list[dict]:
        return self._zones

    @zones.setter
    def zones(self, value: list[dict]) -> None:
        self._zones = value

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._classify_loop, name="threat-classifier", daemon=True
        )
        self._thread.start()
        logger.info("Threat classifier started (2Hz)")

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def get_records(self) -> dict[str, ThreatRecord]:
        with self._lock:
            return dict(self._records)

    def get_active_threats(self) -> list[ThreatRecord]:
        """Return all targets with threat_level > none."""
        with self._lock:
            return [r for r in self._records.values() if r.threat_level != "none"]

    def set_threat_level(self, target_id: str, level: str) -> None:
        """Manual override of threat level."""
        if level not in THREAT_LEVELS:
            return
        with self._lock:
            if target_id in self._records:
                old = self._records[target_id].threat_level
                self._records[target_id].threat_level = level
                self._records[target_id].level_since = time.monotonic()
                self._records[target_id].last_update = time.monotonic()
                if level == "hostile":
                    self._records[target_id].prior_hostile = True
                if old != level:
                    self._publish_escalation(target_id, old, level, "manual_override")

    def _classify_loop(self) -> None:
        while self._running:
            try:
                self._classify_tick()
            except Exception as e:
                logger.debug(f"Threat classifier error: {e}")
            time.sleep(self.TICK_INTERVAL)

    def _classify_tick(self) -> None:
        now = time.monotonic()
        all_targets = self._tracker.get_all()

        with self._lock:
            # Prune records for targets no longer tracked
            tracked_ids = {t.target_id for t in all_targets}
            stale = [tid for tid in self._records if tid not in tracked_ids]
            for tid in stale:
                del self._records[tid]
                self._zone_exit_times.pop(tid, None)

            for target in all_targets:
                # Skip friendly and neutral targets — only classify
                # hostile and unknown alliance entities.  Neutral targets
                # (neighbors, cars, animals from AmbientSpawner) should
                # not trigger zone violations or escalations.
                if target.alliance in ("friendly", "neutral"):
                    continue

                # Get or create record
                if target.target_id not in self._records:
                    self._records[target.target_id] = ThreatRecord(
                        target_id=target.target_id
                    )
                record = self._records[target.target_id]
                record.last_update = now

                # Check zone membership
                current_zone = self._find_zone(target.position)
                old_level = record.threat_level

                if current_zone is not None:
                    zone_type = current_zone.get("type", "")
                    zone_name = current_zone.get("name", zone_type) or "<unnamed>"

                    # Track zone entry
                    if record.in_zone != zone_name:
                        record.in_zone = zone_name
                        record.zone_enter_time = now
                        self._zone_exit_times.pop(target.target_id, None)
                        # Publish zone violation event for frontend
                        self._event_bus.publish("zone_violation", {
                            "target_id": target.target_id,
                            "zone_name": zone_name,
                            "zone_type": zone_type,
                            "position": {"x": target.position[0], "y": target.position[1]},
                        })

                    # Escalation based on zone type
                    if "restricted" in zone_type:
                        if THREAT_LEVELS.index(record.threat_level) < THREAT_LEVELS.index("suspicious"):
                            record.threat_level = "suspicious"
                            record.level_since = now
                    elif record.threat_level == "none":
                        # Prior hostiles skip unknown — they've earned suspicion
                        if record.prior_hostile:
                            record.threat_level = "suspicious"
                        else:
                            record.threat_level = "unknown"
                        record.level_since = now

                    # Linger escalation
                    time_in_zone = now - record.zone_enter_time
                    if time_in_zone > self.LINGER_THRESHOLD:
                        if THREAT_LEVELS.index(record.threat_level) < THREAT_LEVELS.index("hostile"):
                            record.threat_level = "hostile"
                            record.level_since = now
                            record.prior_hostile = True

                else:
                    # Target outside all zones — track for de-escalation
                    if record.in_zone:
                        record.in_zone = ""
                        self._zone_exit_times[target.target_id] = now

                    # De-escalation after time outside zones
                    exit_time = self._zone_exit_times.get(target.target_id, 0)
                    if exit_time > 0 and (now - exit_time) > self.DEESCALATION_TIME:
                        level_idx = THREAT_LEVELS.index(record.threat_level)
                        if level_idx > 0:
                            record.threat_level = THREAT_LEVELS[level_idx - 1]
                            record.level_since = now
                            self._zone_exit_times[target.target_id] = now

                # Publish escalation event if level changed
                if record.threat_level != old_level:
                    reason = f"zone:{record.in_zone}" if record.in_zone else "de-escalation"
                    self._publish_escalation(
                        target.target_id, old_level, record.threat_level, reason
                    )

    def _find_zone(self, position: tuple[float, float]) -> dict | None:
        """Find the most restrictive zone containing the given position.

        Uses simple radius-based containment: a zone contains a point if the
        point is within the zone's radius (default 10 units) of the zone center.
        When a position is inside multiple zones, restricted zones take priority.
        """
        px, py = position
        best: dict | None = None
        for zone in self._zones:
            zpos = zone.get("position", {})
            zx = zpos.get("x", 0.0)
            zy = zpos.get("z", zpos.get("y", 0.0))
            radius = zone.get("properties", {}).get("radius", 10.0)
            dist = math.hypot(px - zx, py - zy)
            if dist <= radius:
                if "restricted" in zone.get("type", ""):
                    return zone  # restricted always wins
                if best is None:
                    best = zone
        return best

    def _publish_escalation(self, target_id: str, old_level: str, new_level: str, reason: str) -> None:
        """Publish threat escalation/de-escalation event."""
        is_escalation = THREAT_LEVELS.index(new_level) > THREAT_LEVELS.index(old_level)
        event_type = "threat_escalation" if is_escalation else "threat_deescalation"
        data = {
            "target_id": target_id,
            "old_level": old_level,
            "new_level": new_level,
            "reason": reason,
        }
        self._event_bus.publish(event_type, data)
        logger.info(f"Threat {event_type}: {target_id} {old_level} -> {new_level} ({reason})")


class AutoDispatcher:
    """Automatically dispatches friendly units to intercept threats.

    Triggered when a target reaches 'hostile' level.  Suspicious targets
    are left for Amy's ThinkingThread to evaluate — she may choose to
    dispatch, clear, or observe depending on context.  This gives Amy
    meaningful decision authority over tactical responses.
    """

    MIN_BATTERY = 0.20  # Don't dispatch units below 20% battery
    # Asset types that can move to intercept (turrets are stationary)
    MOBILE_TYPES = {"rover", "drone", "vehicle"}

    def __init__(
        self,
        event_bus: EventBus,
        target_tracker: TargetTracker,
        simulation_engine: SimulationEngine | None = None,
        mqtt_bridge=None,
        threat_classifier: ThreatClassifier | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._tracker = target_tracker
        self._engine = simulation_engine
        self._mqtt = mqtt_bridge
        self._classifier = threat_classifier
        self._active_dispatches: dict[str, str] = {}  # threat_id -> unit_id
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._sub: queue.Queue | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._sub = self._event_bus.subscribe()
        self._thread = threading.Thread(
            target=self._dispatch_loop, name="auto-dispatcher", daemon=True
        )
        self._thread.start()
        logger.info("Auto-dispatcher started")

    def stop(self) -> None:
        self._running = False
        if self._sub is not None:
            self._event_bus.unsubscribe(self._sub)
            self._sub = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def active_dispatches(self) -> dict[str, str]:
        with self._lock:
            return dict(self._active_dispatches)

    def _dispatch_loop(self) -> None:
        """Listen for escalation events and dispatch units."""
        import queue as _queue
        cleanup_counter = 0
        while self._running:
            try:
                msg = self._sub.get(timeout=1.0)
                event_type = msg.get("type", "")
                if event_type == "threat_escalation":
                    data = msg.get("data", {})
                    new_level = data.get("new_level", "none")
                    target_id = data.get("target_id", "")
                    if new_level == "hostile" and target_id:
                        self._try_dispatch(target_id, new_level)
                elif event_type == "threat_deescalation":
                    data = msg.get("data", {})
                    if data.get("new_level") == "none":
                        self.clear_dispatch(data.get("target_id", ""))
            except _queue.Empty:
                # Periodic cleanup of stale dispatches (every ~10s)
                cleanup_counter += 1
                if cleanup_counter >= 10:
                    cleanup_counter = 0
                    self._cleanup_stale_dispatches()
                continue
            except Exception as e:
                logger.debug(f"Auto-dispatcher error: {e}")

    def _cleanup_stale_dispatches(self) -> None:
        """Remove dispatches where the threat is gone or the unit is unavailable."""
        with self._lock:
            stale = []
            for threat_id, unit_id in self._active_dispatches.items():
                threat = self._tracker.get_target(threat_id)
                unit = self._tracker.get_target(unit_id)
                if threat is None or unit is None:
                    stale.append(threat_id)
                elif threat.status in ("neutralized", "escaped", "destroyed", "despawned"):
                    stale.append(threat_id)
                elif unit.status in ("destroyed", "low_battery", "arrived"):
                    stale.append(threat_id)
            for tid in stale:
                self._active_dispatches.pop(tid, None)
                logger.info(f"Stale dispatch cleared: {tid}")

    def _try_dispatch(self, threat_id: str, threat_level: str) -> None:
        """Find nearest available friendly and dispatch to intercept.

        Selection criteria (in order):
            1. Mobile unit type (rover, drone, vehicle — not turrets)
            2. Battery >= MIN_BATTERY (20%)
            3. Status is 'active' or 'idle'
            4. Not already dispatched to another threat
            5. Nearest by Euclidean distance to threat position

        Known limitations (see docs/ESCALATION.md):
            - Dispatches to threat's current position, not intercept point
            - No force reserve — will commit all available units
        """
        with self._lock:
            # Already dispatched to this threat?
            if threat_id in self._active_dispatches:
                return
            dispatched_units = set(self._active_dispatches.values())

        # Get threat position
        threat = self._tracker.get_target(threat_id)
        if threat is None:
            return

        # Find nearest available mobile friendly
        friendlies = self._tracker.get_friendlies()
        available = [
            f for f in friendlies
            if f.battery >= self.MIN_BATTERY
            and f.status in ("active", "idle", "arrived")
            and f.target_id not in dispatched_units
            and f.asset_type in self.MOBILE_TYPES
        ]

        if not available:
            logger.info(f"No available units to dispatch for threat {threat_id}")
            return

        # Find nearest
        best = min(
            available,
            key=lambda f: math.hypot(
                f.position[0] - threat.position[0],
                f.position[1] - threat.position[1],
            ),
        )

        # Dispatch
        with self._lock:
            self._active_dispatches[threat_id] = best.target_id

        # Move sim target if we have the engine
        if self._engine is not None:
            sim_target = self._engine.get_target(best.target_id)
            if sim_target is not None:
                sim_target.waypoints = [threat.position]
                sim_target._waypoint_index = 0
                sim_target.loop_waypoints = False
                sim_target.status = "active"

        # Publish dispatch event
        self._event_bus.publish("amy_dispatch", {
            "target_id": best.target_id,
            "name": best.name,
            "destination": {"x": threat.position[0], "y": threat.position[1]},
            "reason": f"intercept_{threat_level}",
            "threat_id": threat_id,
        })

        # Publish to MQTT if available
        if self._mqtt is not None:
            self._mqtt.publish_dispatch(
                best.target_id, threat.position[0], threat.position[1]
            )
            self._mqtt.publish_alert({
                "level": threat_level,
                "target_id": threat_id,
                "message": f"Dispatching {best.name} to intercept",
            })

        # Announce via speech event — tactical callout
        dist = math.hypot(
            best.position[0] - threat.position[0],
            best.position[1] - threat.position[1],
        )
        # Compute cardinal bearing from friendly to threat
        dx = threat.position[0] - best.position[0]
        dy = threat.position[1] - best.position[1]
        angle = math.degrees(math.atan2(dx, dy)) % 360
        bearings = ["north", "northeast", "east", "southeast",
                     "south", "southwest", "west", "northwest"]
        bearing = bearings[int((angle + 22.5) % 360 / 45)]

        # Check threat record for zone info
        zone_clause = ""
        if self._classifier is not None:
            records = self._classifier.get_records()
            rec = records.get(threat_id)
            if rec and rec.in_zone:
                zone_clause = f" in {rec.in_zone}"

        threat_name = threat.name if hasattr(threat, "name") else threat_id[:8]
        self._event_bus.publish("auto_dispatch_speech", {
            "text": (
                f"Contact{zone_clause}, bearing {bearing}, {dist:.0f} meters. "
                f"Dispatching {best.name} to intercept {threat_name}."
            ),
        })

        logger.info(
            f"Auto-dispatched {best.name} to intercept {threat_id} "
            f"({threat_level}) at ({threat.position[0]:.1f}, {threat.position[1]:.1f})"
        )

    def clear_dispatch(self, threat_id: str) -> None:
        """Clear an active dispatch (threat resolved)."""
        with self._lock:
            self._active_dispatches.pop(threat_id, None)
