# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for configurable escalation thresholds.

Verifies that ThreatClassifier and AutoDispatcher accept custom threshold
parameters and use them instead of the class constants.
"""

from __future__ import annotations

import queue
import time

import pytest

from engine.tactical.escalation import (
    AutoDispatcher,
    ThreatClassifier,
    ThreatRecord,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class MockEventBus:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, data: dict) -> None:
        self.published.append((event_type, data))

    def subscribe(self):
        return queue.Queue()

    def unsubscribe(self, q) -> None:
        pass


class MockTrackedTarget:
    def __init__(
        self,
        target_id: str,
        alliance: str = "hostile",
        position: tuple[float, float] = (5.0, 5.0),
        battery: float = 1.0,
        status: str = "active",
        name: str = "Target",
        asset_type: str = "rover",
    ):
        self.target_id = target_id
        self.alliance = alliance
        self.position = position
        self.battery = battery
        self.status = status
        self.name = name
        self.asset_type = asset_type


class MockTargetTracker:
    def __init__(self, targets: list | None = None):
        self._targets = {t.target_id: t for t in (targets or [])}

    def get_all(self):
        return list(self._targets.values())

    def get(self, target_id: str):
        return self._targets.get(target_id)


# ---------------------------------------------------------------------------
# ThreatClassifier config tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestThreatClassifierConfig:
    """ThreatClassifier accepts custom thresholds via constructor."""

    def test_default_linger_threshold(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker)
        assert tc.LINGER_THRESHOLD == 30.0

    def test_custom_linger_threshold(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker, linger_threshold=10.0)
        assert tc.LINGER_THRESHOLD == 10.0

    def test_default_deescalation_time(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker)
        assert tc.DEESCALATION_TIME == 30.0

    def test_custom_deescalation_time(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(bus, tracker, deescalation_time=60.0)
        assert tc.DEESCALATION_TIME == 60.0

    def test_custom_both_thresholds(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(
            bus, tracker,
            linger_threshold=15.0,
            deescalation_time=45.0,
        )
        assert tc.LINGER_THRESHOLD == 15.0
        assert tc.DEESCALATION_TIME == 45.0

    def test_none_preserves_defaults(self):
        """Passing None explicitly should keep class constants."""
        bus = MockEventBus()
        tracker = MockTargetTracker()
        tc = ThreatClassifier(
            bus, tracker,
            linger_threshold=None,
            deescalation_time=None,
        )
        assert tc.LINGER_THRESHOLD == 30.0
        assert tc.DEESCALATION_TIME == 30.0


# ---------------------------------------------------------------------------
# AutoDispatcher config tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAutoDispatcherConfig:
    """AutoDispatcher accepts custom min_battery via constructor."""

    def test_default_min_battery(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        ad = AutoDispatcher(bus, tracker)
        assert ad.MIN_BATTERY == 0.20

    def test_custom_min_battery(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        ad = AutoDispatcher(bus, tracker, min_battery=0.50)
        assert ad.MIN_BATTERY == 0.50

    def test_none_preserves_default(self):
        bus = MockEventBus()
        tracker = MockTargetTracker()
        ad = AutoDispatcher(bus, tracker, min_battery=None)
        assert ad.MIN_BATTERY == 0.20

    def test_custom_min_battery_filters_low_units(self):
        """A high min_battery should cause low-battery units to be skipped."""
        bus = MockEventBus()
        # Create a low-battery friendly and a hostile
        friendly = MockTrackedTarget(
            target_id="rover-1",
            alliance="friendly",
            battery=0.30,
            asset_type="rover",
        )
        hostile = MockTrackedTarget(
            target_id="threat-1",
            alliance="hostile",
            position=(10.0, 10.0),
        )
        tracker = MockTargetTracker([friendly, hostile])

        # With min_battery=0.50, the 30% rover should be skipped
        ad = AutoDispatcher(bus, tracker, min_battery=0.50)
        assert ad.MIN_BATTERY == 0.50
        # The rover at 0.30 is below the 0.50 threshold
        assert friendly.battery < ad.MIN_BATTERY
