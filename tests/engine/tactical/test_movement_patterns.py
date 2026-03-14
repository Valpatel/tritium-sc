# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for MovementPatternAnalyzer — loitering, routes, deviations."""

import math
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_sc_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_sc_root / "src"))

from engine.tactical.movement_patterns import (
    MovementPatternAnalyzer,
    MovementPattern,
    LOITER_RADIUS,
    LOITER_MIN_DURATION,
    SPEED_THRESHOLD,
    DEVIATION_SIGMA,
)


class FakeHistory:
    """Minimal TargetHistory mock that stores trails."""

    def __init__(self):
        self._trails: dict[str, list[tuple[float, float, float]]] = {}

    def add_trail(self, target_id: str, trail: list[tuple[float, float, float]]):
        self._trails[target_id] = trail

    def get_trail(self, target_id: str, max_points: int = 500):
        return self._trails.get(target_id, [])[:max_points]


@pytest.fixture
def history():
    return FakeHistory()


@pytest.fixture
def analyzer(history):
    return MovementPatternAnalyzer(history=history)


# -- Loitering detection tests (>5 min in small area) ----------------------

class TestLoitering:
    def test_detect_loitering(self, analyzer, history):
        """Target staying in a small area for >5 minutes = loitering."""
        t0 = 1000.0
        # Generate points within 2m radius over 6 minutes (360 seconds)
        trail = []
        for i in range(60):
            x = 10.0 + math.sin(i * 0.1) * 1.5
            y = 20.0 + math.cos(i * 0.1) * 1.5
            trail.append((x, y, t0 + i * 6.0))  # 6s apart = 360s total

        history.add_trail("tgt_1", trail)
        patterns = analyzer.analyze("tgt_1")

        loitering = [p for p in patterns if p["pattern_type"] == "loitering"]
        assert len(loitering) >= 1
        assert loitering[0]["duration_s"] >= LOITER_MIN_DURATION

    def test_no_loitering_if_moving(self, analyzer, history):
        """Target moving steadily should not trigger loitering."""
        t0 = 1000.0
        trail = [(i * 10.0, 0.0, t0 + i * 10.0) for i in range(50)]
        history.add_trail("tgt_2", trail)
        patterns = analyzer.analyze("tgt_2")
        loitering = [p for p in patterns if p["pattern_type"] == "loitering"]
        assert len(loitering) == 0

    def test_no_loitering_if_too_short(self, analyzer, history):
        """Staying in an area for <5 min should not be loitering."""
        t0 = 1000.0
        # 2 minutes in the same spot (below 5-min threshold)
        trail = [(10.0, 20.0, t0 + i * 6.0) for i in range(20)]
        history.add_trail("tgt_3", trail)
        patterns = analyzer.analyze("tgt_3")
        loitering = [p for p in patterns if p["pattern_type"] == "loitering"]
        assert len(loitering) == 0

    def test_loitering_center_computed(self, analyzer, history):
        """Loitering pattern should have a center near the actual position."""
        t0 = 1000.0
        trail = [(10.0 + i * 0.01, 20.0, t0 + i * 6.0) for i in range(60)]
        history.add_trail("tgt_4", trail)
        patterns = analyzer.analyze("tgt_4")
        loitering = [p for p in patterns if p["pattern_type"] == "loitering"]
        if loitering:
            center = loitering[0]["center"]
            assert abs(center["x"] - 10.0) < 2.0
            assert abs(center["y"] - 20.0) < 2.0

    def test_custom_loiter_params(self, history):
        """Custom loiter radius and duration."""
        analyzer = MovementPatternAnalyzer(
            history=history,
            loiter_radius=3.0,
            loiter_min_duration=60.0,  # 1 min
        )
        t0 = 1000.0
        trail = [(10.0, 20.0, t0 + i * 5.0) for i in range(20)]
        history.add_trail("tgt_5", trail)
        patterns = analyzer.analyze("tgt_5")
        loitering = [p for p in patterns if p["pattern_type"] == "loitering"]
        assert len(loitering) >= 1


# -- Regular route detection tests -----------------------------------------

class TestRegularRoutes:
    def test_detect_repeated_route(self, analyzer, history):
        """Two similar path segments should be detected as regular route."""
        t0 = 1000.0
        trail = []
        # First segment: walk from (0,0) to (100,0) over 5 min
        for i in range(10):
            trail.append((i * 10.0, 0.0, t0 + i * 30.0))
        # Second segment: same path, 10 min later
        t1 = t0 + 600.0
        for i in range(10):
            trail.append((i * 10.0, 0.0, t1 + i * 30.0))

        history.add_trail("tgt_route", trail)
        patterns = analyzer.analyze("tgt_route")
        routes = [p for p in patterns if p["pattern_type"] == "regular_route"]
        assert len(routes) >= 1

    def test_no_route_with_few_points(self, analyzer, history):
        """Too few points should not trigger route detection."""
        trail = [(0.0, 0.0, 1000.0), (10.0, 0.0, 1010.0)]
        history.add_trail("tgt_few", trail)
        patterns = analyzer.analyze("tgt_few")
        assert len(patterns) == 0


# -- Deviation detection tests ---------------------------------------------

class TestDeviations:
    def test_detect_deviation(self, analyzer, history):
        """A point far from the mean path should be flagged."""
        t0 = 1000.0
        # Normal path near (10, 10)
        trail = [(10.0 + i * 0.1, 10.0, t0 + i * 10.0) for i in range(15)]
        # Add one outlier far away
        trail.append((100.0, 100.0, t0 + 150.0))
        history.add_trail("tgt_dev", trail)
        patterns = analyzer.analyze("tgt_dev")
        deviations = [p for p in patterns if p["pattern_type"] == "deviation"]
        assert len(deviations) >= 1

    def test_no_deviation_on_straight_line(self, analyzer, history):
        """A straight line should not have deviations."""
        t0 = 1000.0
        trail = [(i * 1.0, 0.0, t0 + i * 10.0) for i in range(20)]
        history.add_trail("tgt_line", trail)
        patterns = analyzer.analyze("tgt_line")
        deviations = [p for p in patterns if p["pattern_type"] == "deviation"]
        assert len(deviations) == 0


# -- Stationary detection tests --------------------------------------------

class TestStationary:
    def test_detect_stationary(self, analyzer, history):
        """Target at same position for >30s should be stationary."""
        t0 = 1000.0
        trail = [(10.0, 20.0, t0 + i * 5.0) for i in range(20)]
        history.add_trail("tgt_stat", trail)
        patterns = analyzer.analyze("tgt_stat")
        stationary = [p for p in patterns if p["pattern_type"] == "stationary"]
        assert len(stationary) >= 1

    def test_no_stationary_if_moving(self, analyzer, history):
        """Fast-moving target should not be stationary."""
        t0 = 1000.0
        trail = [(i * 100.0, 0.0, t0 + i * 1.0) for i in range(20)]
        history.add_trail("tgt_fast", trail)
        patterns = analyzer.analyze("tgt_fast")
        stationary = [p for p in patterns if p["pattern_type"] == "stationary"]
        assert len(stationary) == 0


# -- Analyze all & summary tests -------------------------------------------

class TestAnalyzeAll:
    def test_analyze_all(self, analyzer, history):
        """Analyze multiple targets at once."""
        t0 = 1000.0
        history.add_trail("a", [(10.0, 20.0, t0 + i * 5.0) for i in range(20)])
        history.add_trail("b", [(i * 100.0, 0.0, t0 + i * 1.0) for i in range(20)])
        results = analyzer.analyze_all(["a", "b"])
        assert "a" in results
        assert "b" in results

    def test_get_summary(self, analyzer, history):
        """Summary should count patterns and list loitering targets."""
        t0 = 1000.0
        trail = [(10.0, 20.0, t0 + i * 6.0) for i in range(60)]
        history.add_trail("loiterer", trail)
        analyzer.analyze("loiterer")
        summary = analyzer.get_summary()
        assert "total_patterns" in summary
        assert "counts" in summary
        assert summary["targets_analyzed"] >= 1


# -- Caching tests ---------------------------------------------------------

class TestCaching:
    def test_cached_patterns(self, analyzer, history):
        """After analysis, cached patterns should be available."""
        t0 = 1000.0
        trail = [(10.0, 20.0, t0 + i * 5.0) for i in range(20)]
        history.add_trail("cached", trail)
        analyzer.analyze("cached")
        cached = analyzer.get_cached_patterns("cached")
        assert isinstance(cached, list)

    def test_cached_empty_before_analysis(self, analyzer):
        """No cached patterns before analysis."""
        cached = analyzer.get_cached_patterns("nonexistent")
        assert cached == []


# -- Edge cases ------------------------------------------------------------

class TestEdgeCases:
    def test_empty_trail(self, analyzer, history):
        history.add_trail("empty", [])
        patterns = analyzer.analyze("empty")
        assert patterns == []

    def test_single_point(self, analyzer, history):
        history.add_trail("single", [(0.0, 0.0, 1000.0)])
        patterns = analyzer.analyze("single")
        assert patterns == []

    def test_two_points(self, analyzer, history):
        history.add_trail("two", [(0.0, 0.0, 1000.0), (1.0, 0.0, 1001.0)])
        patterns = analyzer.analyze("two")
        assert patterns == []

    def test_no_history(self):
        analyzer = MovementPatternAnalyzer(history=None)
        assert analyzer.analyze("test") == []

    def test_set_history(self, analyzer, history):
        new_history = FakeHistory()
        analyzer.set_history(new_history)
        assert analyzer._history is new_history


# -- MovementPattern dataclass tests ---------------------------------------

class TestMovementPattern:
    def test_to_dict(self):
        p = MovementPattern(
            pattern_type="loitering",
            target_id="tgt_1",
            timestamp=1000.0,
            duration_s=360.0,
            center=(10.0, 20.0),
            radius=3.0,
            confidence=0.8,
        )
        d = p.to_dict()
        assert d["pattern_type"] == "loitering"
        assert d["target_id"] == "tgt_1"
        assert d["center"] == {"x": 10.0, "y": 20.0}
        assert d["duration_s"] == 360.0
        assert d["confidence"] == 0.8
