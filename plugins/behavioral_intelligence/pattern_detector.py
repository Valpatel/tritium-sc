# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Behavioral pattern detector — analyzes target movement history to detect:
- Daily routines (same time, same place)
- Regular commuters (same route repeated)
- Anomalous behavior (deviation from established patterns)
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections import defaultdict
from typing import Any, Optional

log = logging.getLogger("behavioral-intelligence")

try:
    from tritium_lib.models.pattern import (
        BehaviorPattern,
        CoPresenceRelationship,
        DeviationType,
        LocationCluster,
        PatternAlert,
        PatternAnomaly,
        PatternStatus,
        PatternType,
        TimeSlot,
        compute_temporal_correlation,
        detect_time_regularity,
    )
except ImportError:
    BehaviorPattern = None  # type: ignore[assignment,misc]


class SightingRecord:
    """Lightweight sighting record for pattern analysis."""

    __slots__ = ("target_id", "timestamp", "lat", "lng", "node_id", "rssi")

    def __init__(
        self,
        target_id: str,
        timestamp: float,
        lat: float = 0.0,
        lng: float = 0.0,
        node_id: str = "",
        rssi: int = -100,
    ):
        self.target_id = target_id
        self.timestamp = timestamp
        self.lat = lat
        self.lng = lng
        self.node_id = node_id
        self.rssi = rssi


class PatternDetector:
    """Detects behavioral patterns from target movement history.

    Maintains a sliding window of sightings per target and periodically
    analyzes them to extract patterns. Uses circular time-of-day statistics
    to detect daily routines and spatial clustering to detect dwell patterns.
    """

    def __init__(
        self,
        min_observations: int = 5,
        time_window_s: float = 7 * 86400,  # 7 days
        co_presence_window_s: float = 60.0,
        co_presence_threshold: float = 0.8,
    ):
        self._min_observations = min_observations
        self._time_window_s = time_window_s
        self._co_presence_window_s = co_presence_window_s
        self._co_presence_threshold = co_presence_threshold

        # Per-target sighting history: target_id -> list[SightingRecord]
        self._sightings: dict[str, list[SightingRecord]] = defaultdict(list)

        # Detected patterns: pattern_id -> BehaviorPattern
        self._patterns: dict[str, Any] = {}

        # Co-presence relationships: (target_a, target_b) -> CoPresenceRelationship
        self._relationships: dict[tuple[str, str], Any] = {}

        # Pattern alerts: alert_id -> PatternAlert
        self._alerts: dict[str, Any] = {}

        # Anomalies: list of recent PatternAnomaly
        self._anomalies: list[Any] = []
        self._max_anomalies = 500

        # Track last analysis time per target to avoid redundant work
        self._last_analysis: dict[str, float] = {}
        self._analysis_interval_s = 300.0  # analyze every 5 minutes

    def record_sighting(
        self,
        target_id: str,
        timestamp: float,
        lat: float = 0.0,
        lng: float = 0.0,
        node_id: str = "",
        rssi: int = -100,
    ) -> None:
        """Record a target sighting for pattern analysis."""
        record = SightingRecord(target_id, timestamp, lat, lng, node_id, rssi)
        self._sightings[target_id].append(record)
        self._prune_old_sightings(target_id)

    def analyze_target(self, target_id: str) -> list[Any]:
        """Analyze a target's sighting history and detect/update patterns.

        Returns list of newly detected or reinforced patterns.
        """
        if BehaviorPattern is None:
            return []

        now = time.time()
        last = self._last_analysis.get(target_id, 0.0)
        if now - last < self._analysis_interval_s:
            return []
        self._last_analysis[target_id] = now

        sightings = self._sightings.get(target_id, [])
        if len(sightings) < self._min_observations:
            return []

        new_patterns = []

        # Detect time-of-day regularity
        timestamps = [s.timestamp for s in sightings]
        time_slot = detect_time_regularity(timestamps)
        if time_slot is not None:
            pattern = self._find_or_create_pattern(
                target_id, PatternType.DAILY_ROUTINE, time_slot
            )
            pattern.reinforce()
            new_patterns.append(pattern)

        # Detect location clusters (dwell patterns)
        clusters = self._cluster_locations(sightings)
        for cluster in clusters:
            if cluster.visit_count >= self._min_observations:
                pattern = self._find_or_create_pattern(
                    target_id, PatternType.DWELL_PATTERN, None, cluster
                )
                pattern.reinforce()
                new_patterns.append(pattern)

        # Detect arrival/departure patterns at clusters
        for cluster in clusters:
            arrival_times = self._get_arrival_times(sightings, cluster)
            if len(arrival_times) >= 3:
                arrival_slot = detect_time_regularity(arrival_times)
                if arrival_slot is not None:
                    pattern = self._find_or_create_pattern(
                        target_id, PatternType.ARRIVAL_PATTERN, arrival_slot, cluster
                    )
                    pattern.reinforce()
                    new_patterns.append(pattern)

        return new_patterns

    def analyze_co_presence(self) -> list[Any]:
        """Analyze all targets for co-presence relationships.

        Returns list of new or updated CoPresenceRelationships.
        """
        if BehaviorPattern is None:
            return []

        targets = list(self._sightings.keys())
        new_rels = []

        for i, tid_a in enumerate(targets):
            for tid_b in targets[i + 1:]:
                sightings_a = [s.timestamp for s in self._sightings[tid_a]]
                sightings_b = [s.timestamp for s in self._sightings[tid_b]]

                if len(sightings_a) < 3 or len(sightings_b) < 3:
                    continue

                sightings_a.sort()
                sightings_b.sort()

                temporal = compute_temporal_correlation(
                    sightings_a, sightings_b, self._co_presence_window_s
                )

                if temporal < 0.3:
                    continue

                key = (min(tid_a, tid_b), max(tid_a, tid_b))
                rel = self._relationships.get(key)
                if rel is None:
                    rel = CoPresenceRelationship(
                        target_a=key[0],
                        target_b=key[1],
                    )
                    self._relationships[key] = rel

                rel.temporal_correlation = temporal
                rel.co_occurrence_count = self._count_co_occurrences(
                    sightings_a, sightings_b
                )
                rel.total_observations = max(len(sightings_a), len(sightings_b))
                rel.spatial_correlation = self._compute_spatial_correlation(
                    tid_a, tid_b
                )
                rel.last_seen = time.time()
                rel.compute_confidence()

                if rel.confidence >= self._co_presence_threshold:
                    rel.relationship_type = "travels_with"
                    new_rels.append(rel)

        return new_rels

    def check_pattern_violations(self) -> list[Any]:
        """Check all established patterns for violations.

        Returns list of PatternAnomaly objects for broken patterns.
        """
        if BehaviorPattern is None:
            return []

        anomalies = []
        now = time.time()
        from datetime import datetime, timezone
        now_dt = datetime.fromtimestamp(now, tz=timezone.utc)

        for pid, pattern in list(self._patterns.items()):
            if pattern.status != PatternStatus.ESTABLISHED:
                continue

            # Check if pattern should be occurring now
            if not pattern.schedule.contains_time(now_dt):
                continue

            # Check if target was recently seen
            target_id = pattern.target_id
            sightings = self._sightings.get(target_id, [])
            recent = [s for s in sightings if now - s.timestamp < 3600]

            if not recent and pattern.pattern_type in (
                PatternType.DAILY_ROUTINE,
                PatternType.ARRIVAL_PATTERN,
            ):
                # Target expected but not seen
                anomaly = PatternAnomaly(
                    anomaly_id=f"anom_{uuid.uuid4().hex[:12]}",
                    target_id=target_id,
                    pattern_id=pid,
                    deviation_type=DeviationType.MISSING,
                    deviation_score=0.8,
                    expected_behavior=(
                        f"Target {target_id} usually seen during "
                        f"{pattern.schedule.hour_start}:00-{pattern.schedule.hour_end}:00"
                    ),
                    actual_behavior=f"Target {target_id} not seen in the last hour",
                    timestamp=now,
                )
                anomalies.append(anomaly)
                self._anomalies.append(anomaly)
                pattern.status = PatternStatus.BREAKING

            elif recent and pattern.pattern_type == PatternType.DWELL_PATTERN:
                # Check if target is at expected location
                if pattern.locations:
                    loc = pattern.locations[0]
                    latest = recent[-1]
                    if latest.lat != 0.0 and latest.lng != 0.0:
                        dist = self._haversine_m(
                            latest.lat, latest.lng, loc.center_lat, loc.center_lng
                        )
                        if dist > loc.radius_m * 3:
                            anomaly = PatternAnomaly(
                                anomaly_id=f"anom_{uuid.uuid4().hex[:12]}",
                                target_id=target_id,
                                pattern_id=pid,
                                deviation_type=DeviationType.WRONG_LOCATION,
                                deviation_score=min(1.0, dist / (loc.radius_m * 10)),
                                expected_behavior=(
                                    f"Target {target_id} usually at "
                                    f"({loc.center_lat:.4f}, {loc.center_lng:.4f})"
                                ),
                                actual_behavior=(
                                    f"Target {target_id} at "
                                    f"({latest.lat:.4f}, {latest.lng:.4f}) "
                                    f"({dist:.0f}m away)"
                                ),
                                location_lat=latest.lat,
                                location_lng=latest.lng,
                                timestamp=now,
                            )
                            anomalies.append(anomaly)
                            self._anomalies.append(anomaly)

        # Check co-presence violations
        for key, rel in list(self._relationships.items()):
            if rel.confidence < self._co_presence_threshold:
                continue
            tid_a, tid_b = key
            recent_a = any(
                time.time() - s.timestamp < 600 for s in self._sightings.get(tid_a, [])
            )
            recent_b = any(
                time.time() - s.timestamp < 600 for s in self._sightings.get(tid_b, [])
            )
            if recent_a and not recent_b:
                anomaly = PatternAnomaly(
                    anomaly_id=f"anom_{uuid.uuid4().hex[:12]}",
                    target_id=tid_a,
                    pattern_id=f"rel_{tid_a}_{tid_b}",
                    deviation_type=DeviationType.LOST_COMPANION,
                    deviation_score=0.6,
                    expected_behavior=f"{tid_a} usually seen with {tid_b}",
                    actual_behavior=f"{tid_b} not seen in the last 10 minutes",
                    timestamp=time.time(),
                )
                anomalies.append(anomaly)
                self._anomalies.append(anomaly)

        # Trim anomaly history
        if len(self._anomalies) > self._max_anomalies:
            self._anomalies = self._anomalies[-self._max_anomalies:]

        return anomalies

    def check_alerts(self, anomalies: list[Any]) -> list[dict]:
        """Check anomalies against alert rules and fire matching alerts.

        Returns list of fired alert dicts.
        """
        fired = []
        for anomaly in anomalies:
            for alert_id, alert in self._alerts.items():
                if alert.pattern_id != anomaly.pattern_id:
                    continue
                if anomaly.deviation_score < alert.deviation_threshold:
                    continue
                if not alert.can_fire():
                    continue

                alert.fire()
                fired.append({
                    "alert_id": alert_id,
                    "alert_name": alert.name,
                    "severity": alert.severity,
                    "target_id": anomaly.target_id,
                    "anomaly_id": anomaly.anomaly_id,
                    "deviation_type": anomaly.deviation_type.value
                    if hasattr(anomaly.deviation_type, "value")
                    else str(anomaly.deviation_type),
                    "expected": anomaly.expected_behavior,
                    "actual": anomaly.actual_behavior,
                    "deviation_score": anomaly.deviation_score,
                    "timestamp": anomaly.timestamp,
                })
                anomaly.alert_generated = True

        return fired

    # -- Alert CRUD --

    def add_alert(self, alert: Any) -> None:
        """Register a pattern alert rule."""
        self._alerts[alert.alert_id] = alert

    def remove_alert(self, alert_id: str) -> bool:
        """Remove an alert rule. Returns True if found."""
        return self._alerts.pop(alert_id, None) is not None

    def list_alerts(self) -> list[Any]:
        """List all alert rules."""
        return list(self._alerts.values())

    # -- Getters --

    def get_patterns(self, target_id: Optional[str] = None) -> list[Any]:
        """Get all patterns, optionally filtered by target."""
        patterns = list(self._patterns.values())
        if target_id:
            patterns = [p for p in patterns if p.target_id == target_id]
        return patterns

    def get_relationships(self, target_id: Optional[str] = None) -> list[Any]:
        """Get all co-presence relationships, optionally filtered by target."""
        rels = list(self._relationships.values())
        if target_id:
            rels = [r for r in rels if r.target_a == target_id or r.target_b == target_id]
        return rels

    def get_anomalies(
        self, target_id: Optional[str] = None, limit: int = 50
    ) -> list[Any]:
        """Get recent anomalies, optionally filtered by target."""
        anomalies = self._anomalies
        if target_id:
            anomalies = [a for a in anomalies if a.target_id == target_id]
        return anomalies[-limit:]

    def get_stats(self) -> dict:
        """Return detector statistics."""
        return {
            "tracked_targets": len(self._sightings),
            "total_sightings": sum(len(s) for s in self._sightings.values()),
            "detected_patterns": len(self._patterns),
            "established_patterns": sum(
                1 for p in self._patterns.values()
                if getattr(p, "status", None) == PatternStatus.ESTABLISHED
            ),
            "co_presence_relationships": len(self._relationships),
            "strong_relationships": sum(
                1 for r in self._relationships.values()
                if getattr(r, "confidence", 0) >= self._co_presence_threshold
            ),
            "total_anomalies": len(self._anomalies),
            "active_alerts": len(self._alerts),
        }

    # -- Internal helpers --

    def _prune_old_sightings(self, target_id: str) -> None:
        """Remove sightings older than the time window."""
        cutoff = time.time() - self._time_window_s
        self._sightings[target_id] = [
            s for s in self._sightings[target_id] if s.timestamp > cutoff
        ]

    def _find_or_create_pattern(
        self,
        target_id: str,
        pattern_type: Any,
        time_slot: Optional[Any] = None,
        location: Optional[Any] = None,
    ) -> Any:
        """Find existing matching pattern or create new one."""
        for pid, p in self._patterns.items():
            if p.target_id != target_id or p.pattern_type != pattern_type:
                continue
            if location and p.locations:
                existing_loc = p.locations[0]
                dist = self._haversine_m(
                    location.center_lat, location.center_lng,
                    existing_loc.center_lat, existing_loc.center_lng,
                )
                if dist < existing_loc.radius_m * 2:
                    return p
            elif time_slot and not location:
                return p

        pid = f"pat_{uuid.uuid4().hex[:12]}"
        pattern = BehaviorPattern(
            pattern_id=pid,
            target_id=target_id,
            pattern_type=pattern_type,
            confidence=0.3,
            schedule=time_slot or TimeSlot(),
            locations=[location] if location else [],
        )
        self._patterns[pid] = pattern
        return pattern

    def _cluster_locations(self, sightings: list[SightingRecord]) -> list[Any]:
        """Simple spatial clustering of sighting locations."""
        if LocationCluster is None:
            return []

        geo_sightings = [s for s in sightings if s.lat != 0.0 or s.lng != 0.0]
        if not geo_sightings:
            return []

        clusters: list[Any] = []
        assigned = set()

        for i, s in enumerate(geo_sightings):
            if i in assigned:
                continue

            members = [s]
            assigned.add(i)

            for j, other in enumerate(geo_sightings):
                if j in assigned:
                    continue
                dist = self._haversine_m(s.lat, s.lng, other.lat, other.lng)
                if dist < 100:  # 100m cluster radius
                    members.append(other)
                    assigned.add(j)

            if len(members) >= 2:
                avg_lat = sum(m.lat for m in members) / len(members)
                avg_lng = sum(m.lng for m in members) / len(members)
                max_dist = max(
                    self._haversine_m(avg_lat, avg_lng, m.lat, m.lng)
                    for m in members
                )
                clusters.append(LocationCluster(
                    center_lat=avg_lat,
                    center_lng=avg_lng,
                    radius_m=max(50.0, max_dist),
                    visit_count=len(members),
                ))

        return clusters

    def _get_arrival_times(
        self, sightings: list[SightingRecord], cluster: Any
    ) -> list[float]:
        """Get arrival timestamps at a location cluster."""
        arrivals = []
        prev_at_cluster = False
        for s in sorted(sightings, key=lambda x: x.timestamp):
            if s.lat == 0.0 and s.lng == 0.0:
                continue
            dist = self._haversine_m(
                s.lat, s.lng, cluster.center_lat, cluster.center_lng
            )
            at_cluster = dist <= cluster.radius_m * 2
            if at_cluster and not prev_at_cluster:
                arrivals.append(s.timestamp)
            prev_at_cluster = at_cluster
        return arrivals

    def _count_co_occurrences(
        self, times_a: list[float], times_b: list[float]
    ) -> int:
        """Count co-occurrence events within the time window."""
        count = 0
        j = 0
        for t_a in times_a:
            while j < len(times_b) and times_b[j] < t_a - self._co_presence_window_s:
                j += 1
            if j < len(times_b) and abs(times_b[j] - t_a) <= self._co_presence_window_s:
                count += 1
        return count

    def _compute_spatial_correlation(self, tid_a: str, tid_b: str) -> float:
        """Compute spatial correlation: how close the two targets' sightings are."""
        sightings_a = self._sightings.get(tid_a, [])
        sightings_b = self._sightings.get(tid_b, [])

        geo_a = [s for s in sightings_a if s.lat != 0.0 or s.lng != 0.0]
        geo_b = [s for s in sightings_b if s.lat != 0.0 or s.lng != 0.0]

        if not geo_a or not geo_b:
            return 0.5  # unknown — assume moderate

        # Average minimum distance between concurrent sightings
        distances = []
        for a in geo_a:
            best_dist = float("inf")
            for b in geo_b:
                if abs(a.timestamp - b.timestamp) < self._co_presence_window_s:
                    d = self._haversine_m(a.lat, a.lng, b.lat, b.lng)
                    best_dist = min(best_dist, d)
            if best_dist < float("inf"):
                distances.append(best_dist)

        if not distances:
            return 0.0

        avg_dist = sum(distances) / len(distances)
        # Score: closer = higher correlation, 0m=1.0, 100m=0.0
        return max(0.0, 1.0 - avg_dist / 100.0)

    @staticmethod
    def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Haversine distance in meters."""
        R = 6371000.0
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlng / 2) ** 2
        )
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
