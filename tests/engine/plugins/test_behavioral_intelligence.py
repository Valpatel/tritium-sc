# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Behavioral Intelligence plugin — pattern detection,
relationship inference, anomaly detection, and alert system."""

import time
import pytest

import sys
from pathlib import Path

# Ensure plugins dir is on path
_plugins_dir = str(Path(__file__).resolve().parents[3] / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

from behavioral_intelligence.pattern_detector import PatternDetector, SightingRecord

try:
    from tritium_lib.models.pattern import (
        BehaviorPattern,
        CoPresenceRelationship,
        DeviationType,
        PatternAlert,
        PatternAnomaly,
        PatternStatus,
        PatternType,
    )
    HAS_MODELS = True
except ImportError:
    HAS_MODELS = False


pytestmark = pytest.mark.skipif(not HAS_MODELS, reason="tritium_lib.models.pattern not available")


class TestPatternDetector:
    """Test the PatternDetector core engine."""

    def test_record_sighting(self):
        detector = PatternDetector()
        detector.record_sighting("ble_test", time.time(), 40.0, -74.0, "node1", -60)
        assert "ble_test" in detector._sightings
        assert len(detector._sightings["ble_test"]) == 1

    def test_prune_old_sightings(self):
        detector = PatternDetector(time_window_s=60.0)
        old_time = time.time() - 120
        detector.record_sighting("ble_test", old_time)
        detector.record_sighting("ble_test", time.time())
        assert len(detector._sightings["ble_test"]) == 1

    def test_analyze_target_needs_min_observations(self):
        detector = PatternDetector(min_observations=5)
        detector._analysis_interval_s = 0  # no throttle
        for i in range(3):
            detector.record_sighting("ble_test", time.time() - i * 60)
        patterns = detector.analyze_target("ble_test")
        assert len(patterns) == 0

    def test_analyze_target_detects_time_pattern(self):
        detector = PatternDetector(min_observations=3)
        detector._analysis_interval_s = 0
        from datetime import datetime, timezone
        # Create sightings all around 9 AM
        base = datetime(2026, 3, 9, 9, 0, tzinfo=timezone.utc)
        for day in range(5):
            ts = base.replace(day=9 + day, minute=day * 2).timestamp()
            detector.record_sighting("ble_test", ts, 40.0, -74.0)

        patterns = detector.analyze_target("ble_test")
        assert len(patterns) > 0
        assert any(p.pattern_type == PatternType.DAILY_ROUTINE for p in patterns)

    def test_cluster_locations(self):
        detector = PatternDetector()
        sightings = [
            SightingRecord("t", time.time(), 40.7128, -74.0060),
            SightingRecord("t", time.time(), 40.7129, -74.0061),
            SightingRecord("t", time.time(), 40.7130, -74.0059),
        ]
        clusters = detector._cluster_locations(sightings)
        assert len(clusters) >= 1
        assert clusters[0].visit_count >= 2

    def test_stats(self):
        detector = PatternDetector()
        detector.record_sighting("ble_a", time.time())
        detector.record_sighting("ble_b", time.time())
        stats = detector.get_stats()
        assert stats["tracked_targets"] == 2
        assert stats["total_sightings"] == 2


class TestCoPresenceDetection:
    """Test co-presence relationship inference."""

    def test_detect_co_present_devices(self):
        detector = PatternDetector(
            co_presence_window_s=30.0,
            co_presence_threshold=0.5,
            min_observations=3,
        )
        base = time.time()
        # Two devices always seen within seconds of each other
        for i in range(10):
            t = base - i * 120  # every 2 minutes
            detector.record_sighting("ble_a", t)
            detector.record_sighting("ble_b", t + 5)

        rels = detector.analyze_co_presence()
        assert len(rels) > 0
        rel = rels[0]
        assert rel.temporal_correlation > 0.5

    def test_no_relationship_for_unrelated(self):
        detector = PatternDetector(
            co_presence_window_s=30.0,
            co_presence_threshold=0.8,
            min_observations=3,
        )
        base = time.time()
        for i in range(10):
            detector.record_sighting("ble_a", base - i * 120)
            detector.record_sighting("ble_b", base - 100000 - i * 120)

        rels = detector.analyze_co_presence()
        # Should have no strong relationships
        strong = [r for r in rels if r.confidence >= 0.8]
        assert len(strong) == 0


class TestPatternViolations:
    """Test pattern violation (anomaly) detection."""

    def test_missing_target_anomaly(self):
        detector = PatternDetector(min_observations=3)
        detector._analysis_interval_s = 0

        # Create an established pattern
        from tritium_lib.models.pattern import TimeSlot
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        pattern = BehaviorPattern(
            pattern_id="pat_test",
            target_id="ble_missing",
            pattern_type=PatternType.DAILY_ROUTINE,
            status=PatternStatus.ESTABLISHED,
            confidence=0.9,
            observation_count=10,
            schedule=TimeSlot(
                hour_start=max(0, now.hour - 1),
                hour_end=min(23, now.hour + 1),
                days_of_week=list(range(7)),
            ),
        )
        detector._patterns["pat_test"] = pattern

        # No recent sightings for this target
        anomalies = detector.check_pattern_violations()
        assert len(anomalies) > 0
        assert anomalies[0].deviation_type == DeviationType.MISSING

    def test_wrong_location_anomaly(self):
        detector = PatternDetector()
        from tritium_lib.models.pattern import TimeSlot, LocationCluster
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        pattern = BehaviorPattern(
            pattern_id="pat_loc",
            target_id="ble_wanderer",
            pattern_type=PatternType.DWELL_PATTERN,
            status=PatternStatus.ESTABLISHED,
            confidence=0.9,
            observation_count=10,
            schedule=TimeSlot(
                hour_start=max(0, now.hour - 1),
                hour_end=min(23, now.hour + 1),
                days_of_week=list(range(7)),
            ),
            locations=[LocationCluster(
                center_lat=40.7128,
                center_lng=-74.0060,
                radius_m=50.0,
            )],
        )
        detector._patterns["pat_loc"] = pattern

        # Record recent sighting far from expected location
        detector.record_sighting(
            "ble_wanderer", time.time(), 41.0, -75.0
        )

        anomalies = detector.check_pattern_violations()
        loc_anomalies = [a for a in anomalies if a.deviation_type == DeviationType.WRONG_LOCATION]
        assert len(loc_anomalies) > 0


class TestPatternAlerts:
    """Test alert rule system."""

    def test_alert_fires_on_anomaly(self):
        detector = PatternDetector()

        alert = PatternAlert(
            alert_id="palert_test",
            pattern_id="pat_test",
            target_id="ble_x",
            name="Test Alert",
            severity="high",
            deviation_threshold=0.5,
            cooldown_seconds=0,
            enabled=True,
        )
        detector.add_alert(alert)

        anomaly = PatternAnomaly(
            anomaly_id="anom_test",
            target_id="ble_x",
            pattern_id="pat_test",
            deviation_type=DeviationType.MISSING,
            deviation_score=0.8,
            expected_behavior="Expected at Zone A",
            actual_behavior="Not seen",
        )

        fired = detector.check_alerts([anomaly])
        assert len(fired) == 1
        assert fired[0]["alert_name"] == "Test Alert"
        assert fired[0]["severity"] == "high"
        assert anomaly.alert_generated

    def test_alert_respects_threshold(self):
        detector = PatternDetector()

        alert = PatternAlert(
            alert_id="palert_strict",
            pattern_id="pat_test",
            enabled=True,
            deviation_threshold=0.9,
            cooldown_seconds=0,
        )
        detector.add_alert(alert)

        anomaly = PatternAnomaly(
            anomaly_id="anom_low",
            target_id="ble_x",
            pattern_id="pat_test",
            deviation_score=0.5,
        )

        fired = detector.check_alerts([anomaly])
        assert len(fired) == 0

    def test_alert_crud(self):
        detector = PatternDetector()

        alert = PatternAlert(
            alert_id="palert_crud",
            pattern_id="pat_test",
            name="CRUD Test",
            enabled=True,
        )
        detector.add_alert(alert)
        assert len(detector.list_alerts()) == 1

        assert detector.remove_alert("palert_crud")
        assert len(detector.list_alerts()) == 0

        assert not detector.remove_alert("nonexistent")


class TestHaversine:
    """Test distance calculation."""

    def test_same_point(self):
        d = PatternDetector._haversine_m(40.0, -74.0, 40.0, -74.0)
        assert d < 0.1

    def test_known_distance(self):
        # NYC to Newark ~15km
        d = PatternDetector._haversine_m(40.7128, -74.0060, 40.7357, -74.1724)
        assert 13000 < d < 17000
