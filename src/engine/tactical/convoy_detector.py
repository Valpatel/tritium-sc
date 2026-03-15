# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ConvoyDetector — detect coordinated target movement.

When 3+ targets move together at similar speed in the same direction,
flag them as a potential convoy. Uses movement patterns from TargetHistory
and publishes convoy events to the EventBus.

Usage::

    detector = ConvoyDetector(history=target_history, event_bus=bus)
    detector.start()  # begins periodic analysis
    convoys = detector.get_active_convoys()
    detector.stop()

Detection algorithm:
  1. For each pair of targets with recent position history, compute
     heading and speed similarity.
  2. Build a graph of "co-moving" pairs (heading within threshold,
     speed within threshold, distance within max convoy spread).
  3. Find connected components of size >= 3 in the co-moving graph.
  4. Each connected component is a potential convoy.
  5. Compute suspicious score based on coordination tightness.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field

from tritium_lib.models import (
    Convoy,
    ConvoyFormation,
    ConvoySummary,
    ConvoyStatus,
    ConvoyVisualization,
    ConvoyFormationType,
    LatLng,
)

logger = logging.getLogger(__name__)

# Detection thresholds
HEADING_TOLERANCE_DEG = 30.0    # Max heading difference to be "same direction"
SPEED_TOLERANCE_MPS = 1.5       # Max speed difference to be "similar speed"
MAX_CONVOY_SPREAD_M = 100.0     # Max distance between any two convoy members
MIN_SPEED_MPS = 0.5             # Minimum speed to be considered moving
MIN_CONVOY_MEMBERS = 3          # Minimum targets to form a convoy
ANALYSIS_INTERVAL_S = 15.0      # How often to run convoy detection
CONVOY_TIMEOUT_S = 120.0        # How long before a convoy is considered dissolved


@dataclass
class TargetMotion:
    """Computed motion state for a target."""
    target_id: str
    x: float
    y: float
    speed_mps: float
    heading_deg: float
    timestamp: float


class ConvoyDetector:
    """Detects coordinated movement among tracked targets.

    Thread-safe. Runs periodic analysis in a background thread
    and publishes convoy events to the EventBus.

    Parameters
    ----------
    history:
        A TargetHistory instance to read position data from.
    event_bus:
        EventBus for publishing convoy_detected / convoy_dissolved events.
    heading_tolerance:
        Maximum heading difference (degrees) for co-movement.
    speed_tolerance:
        Maximum speed difference (m/s) for co-movement.
    max_spread:
        Maximum distance (meters) between convoy members.
    """

    def __init__(
        self,
        history=None,
        event_bus=None,
        heading_tolerance: float = HEADING_TOLERANCE_DEG,
        speed_tolerance: float = SPEED_TOLERANCE_MPS,
        max_spread: float = MAX_CONVOY_SPREAD_M,
    ) -> None:
        self._history = history
        self._event_bus = event_bus
        self._heading_tol = heading_tolerance
        self._speed_tol = speed_tolerance
        self._max_spread = max_spread
        self._lock = threading.Lock()
        self._active_convoys: dict[str, dict] = {}
        self._running = False
        self._thread: threading.Thread | None = None

    def set_history(self, history) -> None:
        """Set or replace the TargetHistory source."""
        with self._lock:
            self._history = history

    def set_event_bus(self, event_bus) -> None:
        """Set or replace the EventBus."""
        with self._lock:
            self._event_bus = event_bus

    def start(self) -> None:
        """Start periodic convoy detection in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._analysis_loop, daemon=True, name="convoy-detector"
        )
        self._thread.start()
        logger.info("ConvoyDetector started")

    def stop(self) -> None:
        """Stop periodic convoy detection."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("ConvoyDetector stopped")

    def _analysis_loop(self) -> None:
        """Background loop that runs convoy detection periodically."""
        while self._running:
            try:
                self.analyze()
            except Exception:
                logger.exception("Convoy analysis error")
            # Sleep in short increments to allow quick shutdown
            for _ in range(int(ANALYSIS_INTERVAL_S * 10)):
                if not self._running:
                    break
                time.sleep(0.1)

    def analyze(self, target_ids: list[str] | None = None) -> list[dict]:
        """Run convoy detection on current targets.

        Returns list of active convoy dicts.
        """
        if self._history is None:
            return []

        # Get motion vectors for all targets
        if target_ids is None:
            target_ids = self._history.get_target_ids() if hasattr(self._history, 'get_target_ids') else []

        motions = self._compute_motions(target_ids)
        if len(motions) < MIN_CONVOY_MEMBERS:
            self._expire_convoys()
            return self.get_active_convoys()

        # Build co-movement graph
        co_moving = self._build_co_movement_graph(motions)

        # Find connected components of size >= 3
        components = self._find_connected_components(co_moving, motions)

        # Update convoy state
        now = time.time()
        detected_ids = set()

        for component in components:
            if len(component) < MIN_CONVOY_MEMBERS:
                continue

            member_motions = [m for m in motions if m.target_id in component]

            # Compute convoy metrics
            avg_speed = sum(m.speed_mps for m in member_motions) / len(member_motions)
            avg_heading = self._circular_mean([m.heading_deg for m in member_motions])
            heading_var = self._circular_variance([m.heading_deg for m in member_motions])
            speed_var = self._variance([m.speed_mps for m in member_motions])
            center_x = sum(m.x for m in member_motions) / len(member_motions)
            center_y = sum(m.y for m in member_motions) / len(member_motions)

            # Check if this matches an existing convoy (>= 50% member overlap)
            convoy_id = self._find_matching_convoy(component)

            if convoy_id is None:
                convoy_id = f"convoy_{uuid.uuid4().hex[:8]}"
                convoy_data = {
                    "convoy_id": convoy_id,
                    "member_target_ids": sorted(component),
                    "speed_avg_mps": round(avg_speed, 2),
                    "heading_avg_deg": round(avg_heading, 1),
                    "heading_variance_deg": round(heading_var, 1),
                    "speed_variance_mps": round(speed_var, 3),
                    "center_x": round(center_x, 2),
                    "center_y": round(center_y, 2),
                    "first_seen": now,
                    "last_seen": now,
                    "status": "active",
                }
                convoy_data["suspicious_score"] = self._compute_suspicious_score(convoy_data)

                with self._lock:
                    self._active_convoys[convoy_id] = convoy_data

                self._publish_event("convoy_detected", convoy_data)
                logger.info(
                    "Convoy detected: %s with %d members, score=%.2f",
                    convoy_id, len(component), convoy_data["suspicious_score"]
                )
            else:
                # Update existing convoy
                with self._lock:
                    c = self._active_convoys[convoy_id]
                    c["member_target_ids"] = sorted(component)
                    c["speed_avg_mps"] = round(avg_speed, 2)
                    c["heading_avg_deg"] = round(avg_heading, 1)
                    c["heading_variance_deg"] = round(heading_var, 1)
                    c["speed_variance_mps"] = round(speed_var, 3)
                    c["center_x"] = round(center_x, 2)
                    c["center_y"] = round(center_y, 2)
                    c["last_seen"] = now
                    c["status"] = "active"
                    c["duration_s"] = round(now - c["first_seen"], 1)
                    c["suspicious_score"] = self._compute_suspicious_score(c)

            detected_ids.add(convoy_id)

        # Expire convoys not detected this cycle
        self._expire_convoys(detected_ids)

        return self.get_active_convoys()

    def get_active_convoys(self) -> list[dict]:
        """Return list of currently active convoy dicts."""
        with self._lock:
            return [
                dict(c) for c in self._active_convoys.values()
                if c["status"] == "active"
            ]

    def get_all_convoys(self) -> list[dict]:
        """Return all convoys including recently dissolved."""
        with self._lock:
            return [dict(c) for c in self._active_convoys.values()]

    def get_summary(self) -> ConvoySummary:
        """Return convoy detection summary as a ConvoySummary model."""
        with self._lock:
            active = [c for c in self._active_convoys.values() if c["status"] == "active"]
            scores = [c["suspicious_score"] for c in active]
            return ConvoySummary(
                total_convoys=len(self._active_convoys),
                active_convoys=len(active),
                total_members=sum(len(c["member_target_ids"]) for c in active),
                avg_suspicious_score=round(sum(scores) / len(scores), 3) if scores else 0.0,
                highest_suspicious_score=round(max(scores), 3) if scores else 0.0,
                largest_convoy_size=max((len(c["member_target_ids"]) for c in active), default=0),
            )

    def to_convoy_model(self, convoy_data: dict) -> Convoy:
        """Convert an internal convoy dict to a tritium-lib Convoy model."""
        from datetime import datetime, timezone
        first_seen = convoy_data.get("first_seen")
        last_seen = convoy_data.get("last_seen")
        return Convoy(
            convoy_id=convoy_data.get("convoy_id", ""),
            member_target_ids=convoy_data.get("member_target_ids", []),
            speed_avg_mps=convoy_data.get("speed_avg_mps", 0.0),
            heading_avg_deg=convoy_data.get("heading_avg_deg", 0.0),
            heading_variance_deg=convoy_data.get("heading_variance_deg", 0.0),
            speed_variance_mps=convoy_data.get("speed_variance_mps", 0.0),
            center_lat=convoy_data.get("center_x", 0.0),
            center_lng=convoy_data.get("center_y", 0.0),
            duration_s=convoy_data.get("duration_s", 0.0),
            suspicious_score=convoy_data.get("suspicious_score", 0.0),
            status=ConvoyStatus(convoy_data.get("status", "active")),
            first_seen=(
                datetime.fromtimestamp(first_seen, tz=timezone.utc)
                if isinstance(first_seen, (int, float)) else None
            ),
            last_seen=(
                datetime.fromtimestamp(last_seen, tz=timezone.utc)
                if isinstance(last_seen, (int, float)) else None
            ),
        )

    def to_visualization(self, convoy_data: dict, member_positions: list[dict] | None = None) -> ConvoyVisualization:
        """Convert an internal convoy dict to a ConvoyVisualization for the frontend.

        Parameters
        ----------
        convoy_data:
            Raw convoy dict from get_active_convoys().
        member_positions:
            Optional list of {"target_id": str, "lat": float, "lng": float} dicts
            for building the bounding polygon.
        """
        bbox_points: list[LatLng] = []
        if member_positions:
            for mp in member_positions:
                lat = mp.get("lat", 0.0) or 0.0
                lng = mp.get("lng", 0.0) or 0.0
                if lat != 0.0 or lng != 0.0:
                    bbox_points.append(LatLng(lat=lat, lng=lng))

        # Determine formation type from heading variance
        heading_var = convoy_data.get("heading_variance_deg", 0.0)
        member_count = len(convoy_data.get("member_target_ids", []))
        if heading_var < 5.0 and member_count >= 3:
            formation = ConvoyFormationType.COLUMN
        elif heading_var < 15.0:
            formation = ConvoyFormationType.PARALLEL
        else:
            formation = ConvoyFormationType.CLUSTER

        return ConvoyVisualization(
            convoy_id=convoy_data.get("convoy_id", ""),
            target_ids=convoy_data.get("member_target_ids", []),
            heading_degrees=convoy_data.get("heading_avg_deg", 0.0),
            speed_estimate=convoy_data.get("speed_avg_mps", 0.0),
            formation_type=formation,
            confidence=min(1.0, convoy_data.get("suspicious_score", 0.0)),
            bounding_box=bbox_points,
            label=f"Convoy ({member_count})",
            color="#fcee0a",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_motions(self, target_ids: list[str]) -> list[TargetMotion]:
        """Compute current motion vector for each target with enough history."""
        motions = []
        for tid in target_ids:
            trail = self._history.get_trail(tid, max_points=10)
            if len(trail) < 2:
                continue

            # Use last two points for instantaneous velocity
            x0, y0, t0 = trail[-2]
            x1, y1, t1 = trail[-1]
            dt = t1 - t0
            if dt <= 0:
                continue

            dx = x1 - x0
            dy = y1 - y0
            speed = math.hypot(dx, dy) / dt

            if speed < MIN_SPEED_MPS:
                continue  # Stationary targets don't form convoys

            heading = math.degrees(math.atan2(dx, dy)) % 360.0

            motions.append(TargetMotion(
                target_id=tid,
                x=x1, y=y1,
                speed_mps=speed,
                heading_deg=heading,
                timestamp=t1,
            ))
        return motions

    def _build_co_movement_graph(self, motions: list[TargetMotion]) -> dict[str, set[str]]:
        """Build adjacency graph of co-moving target pairs."""
        graph: dict[str, set[str]] = {m.target_id: set() for m in motions}

        for i in range(len(motions)):
            for j in range(i + 1, len(motions)):
                a, b = motions[i], motions[j]

                # Check distance
                dist = math.hypot(a.x - b.x, a.y - b.y)
                if dist > self._max_spread:
                    continue

                # Check heading similarity (circular)
                h_diff = abs(a.heading_deg - b.heading_deg)
                if h_diff > 180:
                    h_diff = 360 - h_diff
                if h_diff > self._heading_tol:
                    continue

                # Check speed similarity
                if abs(a.speed_mps - b.speed_mps) > self._speed_tol:
                    continue

                # Co-moving pair
                graph[a.target_id].add(b.target_id)
                graph[b.target_id].add(a.target_id)

        return graph

    def _find_connected_components(
        self, graph: dict[str, set[str]], motions: list[TargetMotion]
    ) -> list[set[str]]:
        """Find connected components in the co-movement graph using BFS."""
        visited: set[str] = set()
        components: list[set[str]] = []

        for node in graph:
            if node in visited:
                continue
            # BFS from this node
            component: set[str] = set()
            queue = [node]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                for neighbor in graph.get(current, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)
            if len(component) >= MIN_CONVOY_MEMBERS:
                components.append(component)

        return components

    def _find_matching_convoy(self, member_ids: set[str]) -> str | None:
        """Find an existing convoy with >= 50% member overlap."""
        with self._lock:
            for cid, convoy in self._active_convoys.items():
                existing = set(convoy["member_target_ids"])
                overlap = len(existing & member_ids)
                if overlap >= max(len(existing), len(member_ids)) * 0.5:
                    return cid
        return None

    def _expire_convoys(self, keep_ids: set[str] | None = None) -> None:
        """Mark convoys as dissolved if not detected this cycle."""
        now = time.time()
        with self._lock:
            for cid, convoy in list(self._active_convoys.items()):
                if keep_ids and cid in keep_ids:
                    continue
                if convoy["status"] != "active":
                    # Remove old dissolved convoys after timeout
                    if now - convoy["last_seen"] > CONVOY_TIMEOUT_S * 2:
                        del self._active_convoys[cid]
                    continue
                if now - convoy["last_seen"] > CONVOY_TIMEOUT_S:
                    convoy["status"] = "dispersed"
                    self._publish_event("convoy_dissolved", convoy)
                    logger.info("Convoy dissolved: %s", cid)

    def _publish_event(self, event_type: str, data: dict) -> None:
        """Publish a convoy event to the EventBus."""
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(event_type, data)
        except Exception:
            logger.debug("Failed to publish %s event", event_type)

    @staticmethod
    def _compute_suspicious_score(convoy: dict) -> float:
        """Compute suspicion score for a convoy."""
        heading_var = convoy.get("heading_variance_deg", 0.0)
        speed_var = convoy.get("speed_variance_mps", 0.0)
        duration = convoy.get("duration_s", 0.0)
        member_count = len(convoy.get("member_target_ids", []))

        # Heading coordination (0-1): lower variance = higher score
        heading_score = max(0.0, 1.0 - (heading_var / 45.0))
        # Speed coordination (0-1)
        speed_score = max(0.0, 1.0 - (speed_var / 2.0))
        # Duration factor (0-1): ramps up over 10 minutes
        duration_score = min(1.0, duration / 600.0)
        # Member count factor (0-1): 3 = 0.25, 6+ = 1.0
        member_score = min(1.0, (member_count - 2) / 4.0)

        return round(
            heading_score * 0.3
            + speed_score * 0.3
            + duration_score * 0.2
            + member_score * 0.2,
            3,
        )

    @staticmethod
    def _circular_mean(angles_deg: list[float]) -> float:
        """Compute circular mean of angles in degrees."""
        if not angles_deg:
            return 0.0
        sin_sum = sum(math.sin(math.radians(a)) for a in angles_deg)
        cos_sum = sum(math.cos(math.radians(a)) for a in angles_deg)
        return math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0

    @staticmethod
    def _circular_variance(angles_deg: list[float]) -> float:
        """Compute circular variance of angles in degrees."""
        if len(angles_deg) < 2:
            return 0.0
        n = len(angles_deg)
        sin_sum = sum(math.sin(math.radians(a)) for a in angles_deg)
        cos_sum = sum(math.cos(math.radians(a)) for a in angles_deg)
        r = math.hypot(sin_sum / n, cos_sum / n)
        # Variance in degrees (0 = all same direction, 180 = uniform)
        return math.degrees(math.acos(max(-1.0, min(1.0, r))))

    @staticmethod
    def _variance(values: list[float]) -> float:
        """Compute variance of a list of values."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / len(values)
