# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for convoy detector."""

import math
import time
import pytest
from unittest.mock import MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'src'))

from tritium_lib.tracking.convoy_detector import ConvoyDetector


class MockHistory:
    """Mock TargetHistory for testing."""

    def __init__(self):
        self._trails = {}

    def set_trail(self, target_id, trail):
        self._trails[target_id] = trail

    def get_trail(self, target_id, max_points=500):
        return self._trails.get(target_id, [])

    def get_target_ids(self):
        return list(self._trails.keys())


class MockEventBus:
    """Mock EventBus that records published events."""

    def __init__(self):
        self.events = []

    def publish(self, event_type, data=None):
        self.events.append({"type": event_type, "data": data})


def make_trail(x0, y0, speed_mps, heading_deg, points=5, t0=None):
    """Generate a trail of positions moving at constant speed and heading."""
    if t0 is None:
        t0 = time.time() - points
    trail = []
    rad = math.radians(heading_deg)
    dx = speed_mps * math.sin(rad)
    dy = speed_mps * math.cos(rad)
    for i in range(points):
        trail.append((x0 + dx * i, y0 + dy * i, t0 + i))
    return trail


class TestConvoyDetector:
    """Tests for ConvoyDetector."""

    def test_no_history_returns_empty(self):
        detector = ConvoyDetector()
        assert detector.analyze() == []

    def test_too_few_targets(self):
        history = MockHistory()
        history.set_trail("a", make_trail(0, 0, 2.0, 90))
        history.set_trail("b", make_trail(5, 0, 2.0, 90))
        detector = ConvoyDetector(history=history)
        result = detector.analyze()
        assert len(result) == 0

    def test_detect_three_target_convoy(self):
        history = MockHistory()
        bus = MockEventBus()

        # Three targets moving east at ~2 m/s, close together
        history.set_trail("a", make_trail(0, 0, 2.0, 90))
        history.set_trail("b", make_trail(0, 5, 2.0, 90))
        history.set_trail("c", make_trail(0, 10, 2.0, 90))

        detector = ConvoyDetector(history=history, event_bus=bus)
        result = detector.analyze()

        assert len(result) == 1
        convoy = result[0]
        assert len(convoy["member_target_ids"]) == 3
        assert convoy["status"] == "active"
        assert convoy["suspicious_score"] > 0

        # Event bus should have received convoy_detected
        assert len(bus.events) == 1
        assert bus.events[0]["type"] == "convoy_detected"

    def test_no_convoy_different_headings(self):
        history = MockHistory()
        # Three targets moving in different directions
        history.set_trail("a", make_trail(0, 0, 2.0, 0))
        history.set_trail("b", make_trail(0, 5, 2.0, 90))
        history.set_trail("c", make_trail(0, 10, 2.0, 180))

        detector = ConvoyDetector(history=history)
        result = detector.analyze()
        assert len(result) == 0

    def test_no_convoy_different_speeds(self):
        history = MockHistory()
        # Same direction but very different speeds
        history.set_trail("a", make_trail(0, 0, 1.0, 90))
        history.set_trail("b", make_trail(0, 5, 5.0, 90))
        history.set_trail("c", make_trail(0, 10, 10.0, 90))

        detector = ConvoyDetector(history=history)
        result = detector.analyze()
        assert len(result) == 0

    def test_no_convoy_too_far_apart(self):
        history = MockHistory()
        # Same direction and speed but 500m apart
        history.set_trail("a", make_trail(0, 0, 2.0, 90))
        history.set_trail("b", make_trail(0, 250, 2.0, 90))
        history.set_trail("c", make_trail(0, 500, 2.0, 90))

        detector = ConvoyDetector(history=history)
        result = detector.analyze()
        assert len(result) == 0

    def test_stationary_targets_not_convoy(self):
        history = MockHistory()
        # Targets barely moving
        t0 = time.time() - 5
        for tid in ["a", "b", "c"]:
            trail = [(0, 0, t0 + i) for i in range(5)]
            history.set_trail(tid, trail)

        detector = ConvoyDetector(history=history)
        result = detector.analyze()
        assert len(result) == 0

    def test_convoy_update_on_reanalysis(self):
        history = MockHistory()
        bus = MockEventBus()

        history.set_trail("a", make_trail(0, 0, 2.0, 90))
        history.set_trail("b", make_trail(0, 5, 2.0, 90))
        history.set_trail("c", make_trail(0, 10, 2.0, 90))

        detector = ConvoyDetector(history=history, event_bus=bus)

        # First analysis
        result1 = detector.analyze()
        assert len(result1) == 1
        convoy_id = result1[0]["convoy_id"]

        # Second analysis — should update, not create new
        result2 = detector.analyze()
        assert len(result2) == 1
        assert result2[0]["convoy_id"] == convoy_id

        # Only one convoy_detected event (not two)
        detected_events = [e for e in bus.events if e["type"] == "convoy_detected"]
        assert len(detected_events) == 1

    def test_get_summary(self):
        history = MockHistory()
        history.set_trail("a", make_trail(0, 0, 2.0, 90))
        history.set_trail("b", make_trail(0, 5, 2.0, 90))
        history.set_trail("c", make_trail(0, 10, 2.0, 90))

        detector = ConvoyDetector(history=history)
        detector.analyze()

        summary = detector.get_summary()
        # get_summary may return a dataclass or dict
        if hasattr(summary, "active_convoys"):
            assert summary.active_convoys == 1
            assert summary.total_members == 3
            assert summary.highest_suspicious_score > 0
        else:
            assert summary["active_convoys"] == 1
            assert summary["total_members"] == 3
            assert summary["highest_suspicious_score"] > 0

    def test_circular_mean(self):
        # North (0) and slightly east — should average to ~10
        result = ConvoyDetector._circular_mean([5.0, 15.0])
        assert 5.0 <= result <= 15.0

    def test_circular_mean_wrapping(self):
        # 350 and 10 should average to ~0 (north)
        result = ConvoyDetector._circular_mean([350.0, 10.0])
        assert result > 340 or result < 20

    def test_five_target_convoy(self):
        history = MockHistory()
        bus = MockEventBus()

        for i, tid in enumerate(["a", "b", "c", "d", "e"]):
            history.set_trail(tid, make_trail(0, i * 5, 3.0, 45))

        detector = ConvoyDetector(history=history, event_bus=bus)
        result = detector.analyze()

        assert len(result) == 1
        assert len(result[0]["member_target_ids"]) == 5
