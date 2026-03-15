# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the system-wide threat level calculator."""

import time
import pytest

from engine.tactical.threat_level_calculator import (
    ThreatLevelCalculator,
    score_to_level,
    HOSTILE_TARGET_WEIGHT,
    GEOFENCE_BREACH_WEIGHT,
    THREAT_FEED_MATCH_WEIGHT,
)


class FakeEventBus:
    """Minimal EventBus stub for testing."""

    def __init__(self):
        self.published = []

    def subscribe(self):
        import queue
        return queue.Queue()

    def publish(self, event_type, data=None):
        self.published.append({"type": event_type, "data": data})


class FakeTarget:
    def __init__(self, alliance="unknown", threat_level="none", threat_score=0.0):
        self.alliance = alliance
        self.threat_level = threat_level
        self.threat_score = threat_score


class FakeTracker:
    def __init__(self, targets=None):
        self._targets = targets or []

    def all_targets(self):
        return self._targets


class FakeEscalation:
    def __init__(self, threats=None):
        self._threats = threats or []

    def get_active_threats(self):
        return self._threats


class TestScoreToLevel:
    def test_green(self):
        assert score_to_level(0) == "green"
        assert score_to_level(9) == "green"

    def test_yellow(self):
        assert score_to_level(10) == "yellow"
        assert score_to_level(29) == "yellow"

    def test_orange(self):
        assert score_to_level(30) == "orange"
        assert score_to_level(59) == "orange"

    def test_red(self):
        assert score_to_level(60) == "red"
        assert score_to_level(89) == "red"

    def test_black(self):
        assert score_to_level(90) == "black"
        assert score_to_level(100) == "black"


class TestThreatLevelCalculator:
    def test_green_when_no_threats(self):
        bus = FakeEventBus()
        tracker = FakeTracker()
        escalation = FakeEscalation()
        calc = ThreatLevelCalculator(bus, tracker, escalation)
        calc._calculate()
        assert calc.current_level == "green"
        assert calc.current_score == 0.0

    def test_hostile_targets_raise_level(self):
        bus = FakeEventBus()
        targets = [FakeTarget(alliance="hostile") for _ in range(3)]
        tracker = FakeTracker(targets)
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        expected_score = 3 * HOSTILE_TARGET_WEIGHT
        assert calc.current_score == expected_score
        assert calc.current_level == "orange"

    def test_single_hostile_yellow(self):
        bus = FakeEventBus()
        tracker = FakeTracker([FakeTarget(alliance="hostile")])
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        assert calc.current_level == "yellow"

    def test_geofence_breaches(self):
        bus = FakeEventBus()
        tracker = FakeTracker()
        threats = [object() for _ in range(3)]
        escalation = FakeEscalation(threats)
        calc = ThreatLevelCalculator(bus, tracker, escalation)
        calc._calculate()
        expected = 3 * GEOFENCE_BREACH_WEIGHT
        assert calc.current_score == expected
        assert calc.current_level == "orange"

    def test_behavioral_anomalies(self):
        bus = FakeEventBus()
        targets = [FakeTarget(threat_score=0.8) for _ in range(2)]
        tracker = FakeTracker(targets)
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        assert calc.current_score > 0
        assert calc.current_level == "yellow"

    def test_combined_signals(self):
        bus = FakeEventBus()
        targets = [
            FakeTarget(alliance="hostile"),
            FakeTarget(alliance="hostile"),
            FakeTarget(threat_score=0.9),
        ]
        threats = [object(), object()]
        tracker = FakeTracker(targets)
        escalation = FakeEscalation(threats)
        calc = ThreatLevelCalculator(bus, tracker, escalation)
        calc._calculate()
        # 2 hostile * 10 + 2 geofence * 15 + 1 anomaly * 8 = 58
        assert calc.current_level == "orange"

    def test_publishes_on_level_change(self):
        bus = FakeEventBus()
        tracker = FakeTracker([FakeTarget(alliance="hostile")])
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        assert len(bus.published) == 1
        assert bus.published[0]["type"] == "system:threat_level"
        assert bus.published[0]["data"]["level"] == "yellow"

    def test_no_publish_when_level_unchanged(self):
        bus = FakeEventBus()
        tracker = FakeTracker([FakeTarget(alliance="hostile")])
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        bus.published.clear()
        calc._calculate()
        assert len(bus.published) == 0

    def test_get_status(self):
        bus = FakeEventBus()
        calc = ThreatLevelCalculator(bus)
        status = calc.get_status()
        assert "level" in status
        assert "score" in status
        assert status["level"] == "green"

    def test_score_clamped_to_100(self):
        bus = FakeEventBus()
        targets = [FakeTarget(alliance="hostile") for _ in range(20)]
        tracker = FakeTracker(targets)
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        assert calc.current_score == 100.0

    def test_set_tracker(self):
        bus = FakeEventBus()
        calc = ThreatLevelCalculator(bus)
        calc._calculate()
        assert calc.current_level == "green"

        tracker = FakeTracker([FakeTarget(alliance="hostile")])
        calc.set_tracker(tracker)
        calc._calculate()
        assert calc.current_level == "yellow"

    def test_threat_feed_match_increment(self):
        bus = FakeEventBus()
        calc = ThreatLevelCalculator(bus)
        calc._threat_feed_matches = 2
        calc._threat_feed_match_time = time.monotonic()
        calc._calculate()
        expected = 2 * THREAT_FEED_MATCH_WEIGHT
        assert calc.current_score == expected

    def test_history_recorded(self):
        bus = FakeEventBus()
        tracker = FakeTracker([FakeTarget(alliance="hostile")])
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        calc._calculate()
        history = calc.get_history(hours=1.0)
        assert len(history) == 2
        assert history[0]["level"] == "yellow"
        assert history[0]["score"] == 10.0
        assert "timestamp" in history[0]

    def test_history_time_filter(self):
        bus = FakeEventBus()
        calc = ThreatLevelCalculator(bus)
        # Add old entries by manipulating the history directly
        old_ts = time.time() - 7200  # 2 hours ago
        calc._history.append((old_ts, "yellow", 15.0))
        calc._history.append((time.time(), "green", 0.0))
        # Request only 1 hour of history
        history = calc.get_history(hours=1.0)
        assert len(history) == 1
        assert history[0]["level"] == "green"

    def test_history_max_24_hours(self):
        bus = FakeEventBus()
        calc = ThreatLevelCalculator(bus)
        # Even if requesting 48 hours, max is clamped to 24
        old_ts = time.time() - (25 * 3600)
        calc._history.append((old_ts, "red", 60.0))
        calc._history.append((time.time(), "green", 0.0))
        history = calc.get_history(hours=48.0)
        # Only the recent entry should be returned (25h old > 24h max)
        assert len(history) == 1


class TestThreatLevelSecurity:
    """Security audit tests for threat level calculator.

    Verifies that the threat level cannot be trivially manipulated
    by flooding targets or exploiting edge cases.
    """

    def test_score_capped_at_100(self):
        """Score is capped at 100 even with extreme hostile counts."""
        bus = FakeEventBus()
        targets = [FakeTarget(alliance="hostile") for _ in range(100)]
        tracker = FakeTracker(targets)
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        assert calc.current_score == 100.0  # Capped
        assert calc.current_level == "black"

    def test_only_valid_alliances_counted(self):
        """Targets with non-hostile alliance do not contribute hostile score."""
        bus = FakeEventBus()
        targets = [
            FakeTarget(alliance="friendly"),
            FakeTarget(alliance="neutral"),
            FakeTarget(alliance="unknown"),
            FakeTarget(alliance=""),
            FakeTarget(alliance=None),
        ]
        tracker = FakeTracker(targets)
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        assert calc.current_score == 0.0
        assert calc.current_level == "green"

    def test_threat_feed_decay(self):
        """Threat feed matches decay after 5 minutes."""
        bus = FakeEventBus()
        calc = ThreatLevelCalculator(bus)
        calc._threat_feed_matches = 5
        calc._threat_feed_match_time = time.monotonic() - 301  # 5+ min ago
        calc._calculate()
        # One match should have been decremented (decay)
        assert calc._threat_feed_matches == 4

    def test_tracker_exception_handled(self):
        """Calculator handles tracker exceptions gracefully."""
        bus = FakeEventBus()

        class BrokenTracker:
            def all_targets(self):
                raise RuntimeError("Database error")

        calc = ThreatLevelCalculator(bus, BrokenTracker())
        calc._calculate()  # Should not raise
        assert calc.current_level == "green"

    def test_escalation_exception_handled(self):
        """Calculator handles escalation exceptions gracefully."""
        bus = FakeEventBus()

        class BrokenEscalation:
            def get_active_threats(self):
                raise RuntimeError("Connection lost")

        calc = ThreatLevelCalculator(bus, escalation=BrokenEscalation())
        calc._calculate()
        assert calc.current_level == "green"

    def test_none_alliance_not_counted_as_hostile(self):
        """A target with alliance=None must NOT be treated as hostile."""
        bus = FakeEventBus()
        tracker = FakeTracker([FakeTarget(alliance=None)])
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        assert calc.current_score == 0.0
