# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for MotorOutput — translates graphling actions to TRITIUM-SC state changes.

TDD: Written before implementation.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, call, patch

import pytest


def _make_mock_target(target_id: str = "npc_001", position: tuple = (100.0, 200.0)) -> MagicMock:
    """Create a mock SimulationTarget."""
    target = MagicMock()
    target.target_id = target_id
    target.position = position
    target.heading = 0.0
    target.status = "active"
    target.waypoints = []
    return target


def _make_mock_event_bus() -> MagicMock:
    """Create a mock EventBus."""
    return MagicMock()


def _make_mock_tracker(targets: dict[str, MagicMock] | None = None) -> MagicMock:
    """Create a mock TargetTracker."""
    tracker = MagicMock()
    targets = targets or {}
    tracker.get_target.side_effect = lambda tid: targets.get(tid)
    return tracker


# ── Say publishes npc_thought event ──────────────────────────────


class TestSayAction:
    """Motor say() publishes an event via EventBus."""

    def test_say_publishes_event(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        result = motor.execute("npc_001", 'say("Hello, traveler!")')

        assert result is True
        event_bus.publish.assert_called_once()
        call_args = event_bus.publish.call_args
        assert call_args[0][0] == "npc_thought"
        assert call_args[0][1]["text"] == "Hello, traveler!"
        assert call_args[0][1]["target_id"] == "npc_001"

    def test_say_includes_duration(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        motor.execute("npc_001", 'say("A longer sentence that takes more time to read.")')

        call_args = event_bus.publish.call_args
        # Duration should be > 0 (based on text length)
        assert call_args[0][1].get("duration", 0) > 0


# ── Move_to sets waypoints ───────────────────────────────────────


class TestMoveToAction:
    """Motor move_to() sets target waypoints."""

    def test_move_to_sets_waypoints(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        result = motor.execute("npc_001", "move_to(50, 75)")

        assert result is True
        assert target.waypoints == [(50.0, 75.0)]

    def test_move_to_validates_coordinates(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        # Non-numeric coordinates should fail
        result = motor.execute("npc_001", 'move_to("invalid", "bad")')
        assert result is False


# ── Flee calculates away-vector ──────────────────────────────────


class TestFleeAction:
    """Motor flee() calculates escape waypoint."""

    def test_flee_sets_away_waypoint(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target(position=(100.0, 100.0))
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        # Flee from a position (threat at 110, 100 -- east of us)
        result = motor.execute("npc_001", "flee(110, 100)")

        assert result is True
        # Waypoint should be away from threat (west, roughly)
        assert len(target.waypoints) == 1
        wx, wy = target.waypoints[0]
        # Should move away from 110,100 -- so x should be < 100
        assert wx < 100.0

    def test_flee_from_unknown_target_handled(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        # Flee with 0,0 coordinates (no specific threat)
        result = motor.execute("npc_001", "flee(0, 0)")
        assert result is True


# ── Observe changes status ───────────────────────────────────────


class TestObserveAction:
    """Motor observe() sets target to observing state."""

    def test_observe_sets_status(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        result = motor.execute("npc_001", "observe()")

        assert result is True
        assert target.status == "idle"


# ── Emote publishes emotion event ────────────────────────────────


class TestEmoteAction:
    """Motor emote() publishes emotion event."""

    def test_emote_publishes_emotion(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        result = motor.execute("npc_001", 'emote("happy")')

        assert result is True
        event_bus.publish.assert_called_once()
        call_args = event_bus.publish.call_args
        assert call_args[0][0] == "npc_emotion"
        assert call_args[0][1]["emotion"] == "happy"


# ── Unknown action returns False ─────────────────────────────────


class TestUnknownAction:
    """Unknown actions are rejected."""

    def test_unknown_action_returns_false(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        result = motor.execute("npc_001", "explode()")
        assert result is False


# ── Missing target returns False ─────────────────────────────────


class TestMissingTarget:
    """Actions on missing targets fail gracefully."""

    def test_missing_target_returns_false(self):
        from graphlings.motor import MotorOutput

        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({})  # empty
        motor = MotorOutput(tracker, event_bus)

        result = motor.execute("nonexistent", 'say("Hello")')
        assert result is False


# ── Parse Lua action string ──────────────────────────────────────


class TestActionParsing:
    """Lua-style action string parsing."""

    def test_parse_simple_action(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        result = motor.execute("npc_001", "observe()")
        assert result is True

    def test_parse_multiple_params(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        result = motor.execute("npc_001", "move_to(42.5, 99.0)")
        assert result is True
        assert target.waypoints == [(42.5, 99.0)]


# ── Remember triggers experience recording ───────────────────────


class TestRememberAction:
    """Motor remember() stores an experience."""

    def test_remember_publishes_experience_event(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        motor = MotorOutput(tracker, event_bus)

        result = motor.execute("npc_001", 'remember("guard_post", "north_gate")')

        assert result is True
        event_bus.publish.assert_called_once()
        call_args = event_bus.publish.call_args
        assert call_args[0][0] == "npc_experience"
        assert call_args[0][1]["subject"] == "guard_post"
        assert call_args[0][1]["value"] == "north_gate"


# ── Action execution is logged ───────────────────────────────────


class TestActionLogging:
    """Actions are logged."""

    def test_action_is_logged(self):
        from graphlings.motor import MotorOutput

        target = _make_mock_target()
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_001": target})
        logger = MagicMock()
        motor = MotorOutput(tracker, event_bus, logger=logger)

        motor.execute("npc_001", "observe()")

        logger.debug.assert_called()


# ── Concurrent actions don't interfere ───────────────────────────


class TestConcurrency:
    """Multiple actions for different targets don't interfere."""

    def test_concurrent_targets_independent(self):
        from graphlings.motor import MotorOutput

        target_a = _make_mock_target("npc_a", (0.0, 0.0))
        target_b = _make_mock_target("npc_b", (50.0, 50.0))
        event_bus = _make_mock_event_bus()
        tracker = _make_mock_tracker({"npc_a": target_a, "npc_b": target_b})
        motor = MotorOutput(tracker, event_bus)

        motor.execute("npc_a", "move_to(10, 10)")
        motor.execute("npc_b", "move_to(60, 60)")

        assert target_a.waypoints == [(10.0, 10.0)]
        assert target_b.waypoints == [(60.0, 60.0)]
