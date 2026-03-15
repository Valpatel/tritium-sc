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

try:
    from tritium_lib.models.clustering import (
        BehaviorCluster,
        ClusterSummary,
        CommonPattern,
        FormationType,
    )
except ImportError:
    BehaviorCluster = None  # type: ignore[assignment,misc]


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

        # Behavior clusters: cluster_id -> BehaviorCluster
        self._clusters: dict[str, Any] = {}
        self._last_cluster_analysis: float = 0.0
        self._cluster_interval_s = 600.0  # re-cluster every 10 minutes

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

    # -- Behavioral clustering ------------------------------------------------

    def cluster_by_behavior(self) -> list[Any]:
        """Group targets with similar movement patterns into clusters.

        Analyzes speed range, time-of-day activity, and spatial overlap
        to find targets that behave similarly. Returns list of new or
        updated BehaviorCluster objects.
        """
        if BehaviorCluster is None or BehaviorPattern is None:
            return []

        now = time.time()
        if now - self._last_cluster_analysis < self._cluster_interval_s:
            return list(self._clusters.values())
        self._last_cluster_analysis = now

        # Build per-target behavior profiles
        profiles: dict[str, dict] = {}
        for target_id, sightings in self._sightings.items():
            if len(sightings) < self._min_observations:
                continue
            profile = self._build_behavior_profile(target_id, sightings)
            if profile:
                profiles[target_id] = profile

        if len(profiles) < 2:
            return list(self._clusters.values())

        # Pairwise similarity and greedy clustering
        target_ids = list(profiles.keys())
        assigned: set[str] = set()
        new_clusters: list[Any] = []

        for i, tid_a in enumerate(target_ids):
            if tid_a in assigned:
                continue
            group = [tid_a]
            assigned.add(tid_a)

            for tid_b in target_ids[i + 1:]:
                if tid_b in assigned:
                    continue
                sim = self._behavior_similarity(profiles[tid_a], profiles[tid_b])
                if sim >= 0.6:  # similarity threshold
                    group.append(tid_b)
                    assigned.add(tid_b)

            if len(group) >= 2:
                cluster = self._build_cluster(group, profiles)
                new_clusters.append(cluster)

        # Update stored clusters
        self._clusters = {c.cluster_id: c for c in new_clusters}
        return new_clusters

    def get_clusters(self) -> list[Any]:
        """Get all current behavior clusters."""
        return list(self._clusters.values())

    def _build_behavior_profile(
        self, target_id: str, sightings: list[SightingRecord]
    ) -> Optional[dict]:
        """Build a behavior profile for clustering."""
        from datetime import datetime, timezone

        timestamps = [s.timestamp for s in sightings]
        if not timestamps:
            return None

        # Speed estimation from consecutive sightings
        speeds = []
        sorted_sightings = sorted(sightings, key=lambda s: s.timestamp)
        for j in range(1, len(sorted_sightings)):
            s_prev = sorted_sightings[j - 1]
            s_curr = sorted_sightings[j]
            dt = s_curr.timestamp - s_prev.timestamp
            if dt > 0 and dt < 3600:  # within 1 hour
                if (s_prev.lat != 0 or s_prev.lng != 0) and (s_curr.lat != 0 or s_curr.lng != 0):
                    dist = self._haversine_m(s_prev.lat, s_prev.lng, s_curr.lat, s_curr.lng)
                    speeds.append(dist / dt)

        # Time of day distribution (hour histogram)
        hour_counts = [0] * 24
        for ts in timestamps:
            dt_obj = datetime.fromtimestamp(ts, tz=timezone.utc)
            hour_counts[dt_obj.hour] += 1

        # Active hours (hours with >10% of sightings)
        total = sum(hour_counts)
        threshold = total * 0.1
        active_hours = [h for h in range(24) if hour_counts[h] >= threshold]

        # Spatial centroid
        geo = [s for s in sightings if s.lat != 0 or s.lng != 0]
        centroid_lat = sum(s.lat for s in geo) / len(geo) if geo else 0.0
        centroid_lng = sum(s.lng for s in geo) / len(geo) if geo else 0.0

        return {
            "target_id": target_id,
            "speed_min": min(speeds) if speeds else 0.0,
            "speed_max": max(speeds) if speeds else 0.0,
            "speed_avg": sum(speeds) / len(speeds) if speeds else 0.0,
            "active_hours": active_hours,
            "hour_counts": hour_counts,
            "centroid_lat": centroid_lat,
            "centroid_lng": centroid_lng,
            "sighting_count": len(sightings),
        }

    def _behavior_similarity(self, profile_a: dict, profile_b: dict) -> float:
        """Compute behavioral similarity between two target profiles (0-1)."""
        scores = []

        # Speed range overlap
        a_min, a_max = profile_a["speed_min"], profile_a["speed_max"]
        b_min, b_max = profile_b["speed_min"], profile_b["speed_max"]
        if a_max > 0 or b_max > 0:
            overlap_min = max(a_min, b_min)
            overlap_max = min(a_max, b_max)
            union_range = max(a_max, b_max) - min(a_min, b_min)
            if union_range > 0:
                speed_sim = max(0.0, (overlap_max - overlap_min) / union_range)
            else:
                speed_sim = 1.0
            scores.append(speed_sim)

        # Time-of-day similarity (cosine similarity of hour histograms)
        ha = profile_a["hour_counts"]
        hb = profile_b["hour_counts"]
        dot = sum(ha[i] * hb[i] for i in range(24))
        mag_a = math.sqrt(sum(x * x for x in ha))
        mag_b = math.sqrt(sum(x * x for x in hb))
        if mag_a > 0 and mag_b > 0:
            time_sim = dot / (mag_a * mag_b)
        else:
            time_sim = 0.0
        scores.append(time_sim)

        # Spatial proximity (closer = more similar)
        if (profile_a["centroid_lat"] != 0 or profile_a["centroid_lng"] != 0) and \
           (profile_b["centroid_lat"] != 0 or profile_b["centroid_lng"] != 0):
            dist = self._haversine_m(
                profile_a["centroid_lat"], profile_a["centroid_lng"],
                profile_b["centroid_lat"], profile_b["centroid_lng"],
            )
            spatial_sim = max(0.0, 1.0 - dist / 500.0)  # 500m = 0 similarity
            scores.append(spatial_sim)

        return sum(scores) / len(scores) if scores else 0.0

    def _build_cluster(self, target_ids: list[str], profiles: dict) -> Any:
        """Build a BehaviorCluster from a group of similar targets."""
        cluster_id = f"bclust_{uuid.uuid4().hex[:12]}"

        # Aggregate profiles
        all_speeds_min = []
        all_speeds_max = []
        all_lats = []
        all_lngs = []
        all_hour_counts = [0] * 24
        obs_count = 0

        for tid in target_ids:
            p = profiles[tid]
            all_speeds_min.append(p["speed_min"])
            all_speeds_max.append(p["speed_max"])
            if p["centroid_lat"] != 0 or p["centroid_lng"] != 0:
                all_lats.append(p["centroid_lat"])
                all_lngs.append(p["centroid_lng"])
            for h in range(24):
                all_hour_counts[h] += p["hour_counts"][h]
            obs_count += p["sighting_count"]

        # Determine active hours
        total = sum(all_hour_counts)
        threshold = total * 0.1
        active_start = 0
        active_end = 23
        for h in range(24):
            if all_hour_counts[h] >= threshold:
                active_start = h
                break
        for h in range(23, -1, -1):
            if all_hour_counts[h] >= threshold:
                active_end = h
                break

        centroid_lat = sum(all_lats) / len(all_lats) if all_lats else 0.0
        centroid_lng = sum(all_lngs) / len(all_lngs) if all_lngs else 0.0

        # Compute radius from centroid
        radius = 100.0
        for lat, lng in zip(all_lats, all_lngs):
            d = self._haversine_m(centroid_lat, centroid_lng, lat, lng)
            radius = max(radius, d * 1.5)

        # Determine formation type based on speed
        avg_speed = sum(all_speeds_max) / len(all_speeds_max) if all_speeds_max else 0.0
        if avg_speed < 0.5:
            formation = FormationType.STATIONARY
        elif avg_speed < 2.0:
            formation = FormationType.DISPERSED
        elif avg_speed < 5.0:
            formation = FormationType.PATROL
        else:
            formation = FormationType.CONVOY

        common = CommonPattern(
            speed_min_mps=min(all_speeds_min) if all_speeds_min else 0.0,
            speed_max_mps=max(all_speeds_max) if all_speeds_max else 0.0,
            active_hour_start=active_start,
            active_hour_end=active_end,
            regularity_score=0.7,
        )

        return BehaviorCluster(
            cluster_id=cluster_id,
            targets=target_ids,
            common_pattern=common,
            centroid_lat=centroid_lat,
            centroid_lng=centroid_lng,
            radius_m=radius,
            formation_type=formation,
            confidence=min(1.0, obs_count / 50.0),
            observation_count=obs_count,
        )

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
            "behavior_clusters": len(self._clusters),
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
