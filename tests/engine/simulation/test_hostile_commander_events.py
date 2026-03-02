# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for hostile commander event publishing via EventBus.

The HostileCommander should publish a hostile_intel event on the EventBus
after each assessment cycle so the frontend receives it in real time via
the WebSocket bridge instead of polling.
"""

import time
import queue
import pytest

from engine.simulation.target import SimulationTarget
from engine.simulation.hostile_commander import HostileCommander
from engine.comms.event_bus import EventBus


def _make_target(tid, x, y, alliance="hostile", asset_type="person",
                 speed=1.5, health=100, status="active"):
    t = SimulationTarget(
        target_id=tid, name=f"Unit-{tid}", alliance=alliance,
        asset_type=asset_type, position=(x, y), speed=speed,
    )
    t.health = health
    t.max_health = health
    t.status = status
    return t


def _make_battlefield(n_hostiles=4, n_friendlies=3):
    """Create a standard battlefield with given force counts."""
    targets = {}
    for i in range(n_hostiles):
        t = _make_target(f"h{i}", 50 + i * 5, 50, "hostile")
        targets[t.target_id] = t
    for i in range(n_friendlies):
        t = _make_target(f"f{i}", -20 - i * 5, -20, "friendly", "turret", speed=0)
        targets[t.target_id] = t
    return targets


class TestHostileIntelEventPublished:
    """Test that hostile_intel event is published after assessment."""

    def test_event_published_after_assessment(self):
        """hostile_intel event should appear on the EventBus after tick triggers assessment."""
        bus = EventBus()
        sub = bus.subscribe()
        cmd = HostileCommander(event_bus=bus)
        targets = _make_battlefield(4, 3)

        # Force assessment by resetting last_assess
        cmd._last_assess = 0.0
        cmd.tick(0.1, targets)

        # Drain the queue looking for hostile_intel
        found = None
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "hostile_intel":
                found = msg
                break

        assert found is not None, "hostile_intel event not published"

    def test_no_event_without_event_bus(self):
        """Commander without event_bus should not crash (backward compat)."""
        cmd = HostileCommander()
        targets = _make_battlefield(4, 3)
        cmd._last_assess = 0.0
        # Should not raise
        cmd.tick(0.1, targets)

    def test_event_not_published_before_interval(self):
        """No event if the assessment interval has not elapsed."""
        bus = EventBus()
        sub = bus.subscribe()
        cmd = HostileCommander(event_bus=bus)
        targets = _make_battlefield(4, 3)

        # Set last_assess to now so interval hasn't elapsed
        cmd._last_assess = time.monotonic()
        cmd.tick(0.01, targets)

        found = False
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "hostile_intel":
                found = True
        assert not found, "hostile_intel should NOT be published before interval"


class TestHostileIntelEventData:
    """Test that the event data includes the expected fields."""

    def _get_intel_event(self, n_hostiles=4, n_friendlies=3):
        bus = EventBus()
        sub = bus.subscribe()
        cmd = HostileCommander(event_bus=bus)
        targets = _make_battlefield(n_hostiles, n_friendlies)
        cmd._last_assess = 0.0
        cmd.tick(0.1, targets)

        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "hostile_intel":
                return msg.get("data", {})
        pytest.fail("hostile_intel event not found")

    def test_includes_threat_level(self):
        data = self._get_intel_event()
        assert "threat_level" in data
        assert data["threat_level"] in ("low", "moderate", "high", "critical")

    def test_includes_force_ratio(self):
        data = self._get_intel_event()
        assert "force_ratio" in data
        assert isinstance(data["force_ratio"], (int, float))

    def test_includes_recommended_action(self):
        data = self._get_intel_event()
        assert "recommended_action" in data
        assert data["recommended_action"] in ("retreat", "flank", "assault", "advance")

    def test_includes_hostile_count(self):
        data = self._get_intel_event(n_hostiles=6, n_friendlies=2)
        assert "hostile_count" in data
        assert data["hostile_count"] == 6

    def test_includes_friendly_count(self):
        data = self._get_intel_event(n_hostiles=6, n_friendlies=2)
        assert "friendly_count" in data
        assert data["friendly_count"] == 2

    def test_includes_priority_targets(self):
        data = self._get_intel_event()
        assert "priority_targets" in data
        assert isinstance(data["priority_targets"], list)

    def test_force_ratio_is_correct(self):
        data = self._get_intel_event(n_hostiles=6, n_friendlies=3)
        assert abs(data["force_ratio"] - 2.0) < 0.01


class TestHostileIntelPublishCycle:
    """Test that hostile_intel publishes on each 1Hz assessment cycle."""

    def test_publishes_on_each_tick_cycle(self):
        """Multiple ticks that cross the ASSESS_INTERVAL should each produce an event."""
        bus = EventBus()
        sub = bus.subscribe()
        cmd = HostileCommander(event_bus=bus)
        targets = _make_battlefield(4, 3)

        intel_count = 0
        # First tick — force assess
        cmd._last_assess = 0.0
        cmd.tick(0.1, targets)

        # Count events
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "hostile_intel":
                intel_count += 1

        assert intel_count == 1, f"Expected 1 intel event from first tick, got {intel_count}"

        # Second tick — force another assess by resetting
        cmd._last_assess = 0.0
        cmd.tick(0.1, targets)

        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "hostile_intel":
                intel_count += 1

        assert intel_count == 2, f"Expected 2 total intel events, got {intel_count}"

    def test_empty_battlefield_still_publishes(self):
        """Even with no units, assessment should publish (all zeros)."""
        bus = EventBus()
        sub = bus.subscribe()
        cmd = HostileCommander(event_bus=bus)

        cmd._last_assess = 0.0
        cmd.tick(0.1, {})

        found = False
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "hostile_intel":
                found = True
        assert found, "hostile_intel should publish even on empty battlefield"

    def test_event_does_not_include_objectives(self):
        """Event payload should be lightweight — no per-unit objectives.

        Objectives are available via GET /api/game/hostile-intel for
        detailed view, but the 1Hz event should only send summary fields.
        """
        bus = EventBus()
        sub = bus.subscribe()
        cmd = HostileCommander(event_bus=bus)
        targets = _make_battlefield(4, 3)

        cmd._last_assess = 0.0
        cmd.tick(0.1, targets)

        data = None
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "hostile_intel":
                data = msg.get("data", {})

        assert data is not None
        # Objectives should NOT be in the event (kept lightweight)
        assert "objectives" not in data
