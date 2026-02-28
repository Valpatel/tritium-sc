# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for EventReactor — distributes EventBus events to nearby NPC brains."""

import math
import queue
import time

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.npc_intelligence.brain import NPCBrain, NPCPersonality
from engine.simulation.npc_intelligence.event_reactor import EventReactor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_brain(target_id: str = "npc-1", asset_type: str = "person") -> NPCBrain:
    return NPCBrain(target_id=target_id, asset_type=asset_type, alliance="neutral")


def _make_brains_with_positions(
    positions: list[tuple[float, float]],
    asset_type: str = "person",
) -> list[tuple[NPCBrain, tuple[float, float]]]:
    """Create N brains at the given positions."""
    return [
        (_make_brain(f"npc-{i}", asset_type), pos)
        for i, pos in enumerate(positions)
    ]


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ===========================================================================
# Construction / lifecycle
# ===========================================================================


class TestEventReactorLifecycle:
    def test_create(self):
        bus = EventBus()
        reactor = EventReactor(bus)
        assert reactor is not None

    def test_start_subscribes(self):
        bus = EventBus()
        reactor = EventReactor(bus)
        reactor.start()
        # After start, the reactor should have an active subscription
        assert reactor._queue is not None
        reactor.stop()

    def test_stop_unsubscribes(self):
        bus = EventBus()
        reactor = EventReactor(bus)
        reactor.start()
        reactor.stop()
        # After stop, the queue should be removed from bus subscribers
        assert reactor._queue is None

    def test_double_start_is_safe(self):
        bus = EventBus()
        reactor = EventReactor(bus)
        reactor.start()
        reactor.start()  # no error
        reactor.stop()

    def test_double_stop_is_safe(self):
        bus = EventBus()
        reactor = EventReactor(bus)
        reactor.start()
        reactor.stop()
        reactor.stop()  # no error


# ===========================================================================
# Event radius filtering
# ===========================================================================


class TestEventRadiusFiltering:
    """Events should only affect NPCs within the type-specific radius."""

    def test_weapon_fired_radius_50m(self):
        """weapon_fired should reach NPCs within 50m but not beyond."""
        bus = EventBus()
        reactor = EventReactor(bus)

        event_origin = (100.0, 100.0)
        # One NPC at 30m (within), one at 70m (outside)
        bwp = _make_brains_with_positions([(130.0, 100.0), (170.0, 100.0)])
        near_brain = bwp[0][0]
        far_brain = bwp[1][0]

        event = {
            "type": "weapon_fired",
            "data": {"position": list(event_origin)},
        }
        reactor.process_event(event, bwp)

        assert len(near_brain.memory.events) == 1
        assert len(far_brain.memory.events) == 0

    def test_target_eliminated_radius_80m(self):
        """target_eliminated should reach NPCs within 80m."""
        bus = EventBus()
        reactor = EventReactor(bus)

        event_origin = (0.0, 0.0)
        bwp = _make_brains_with_positions([(60.0, 0.0), (90.0, 0.0)])
        near_brain = bwp[0][0]
        far_brain = bwp[1][0]

        event = {
            "type": "target_eliminated",
            "data": {"position": [0.0, 0.0]},
        }
        reactor.process_event(event, bwp)

        assert len(near_brain.memory.events) == 1
        assert len(far_brain.memory.events) == 0

    def test_wave_start_infinite_radius(self):
        """wave_start should reach ALL NPCs regardless of distance."""
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(0.0, 0.0), (9999.0, 9999.0)])

        event = {"type": "wave_start", "data": {"wave": 1}}
        reactor.process_event(event, bwp)

        assert len(bwp[0][0].memory.events) == 1
        assert len(bwp[1][0].memory.events) == 1

    def test_escalation_change_infinite_radius(self):
        """escalation_change should reach ALL NPCs regardless of distance."""
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(0.0, 0.0), (5000.0, 5000.0)])

        event = {"type": "escalation_change", "data": {"level": "red"}}
        reactor.process_event(event, bwp)

        assert len(bwp[0][0].memory.events) == 1
        assert len(bwp[1][0].memory.events) == 1

    def test_event_at_exact_radius_boundary_included(self):
        """NPCs exactly at the radius boundary should still receive the event."""
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(50.0, 0.0)])
        event = {
            "type": "weapon_fired",
            "data": {"position": [0.0, 0.0]},
        }
        reactor.process_event(event, bwp)
        assert len(bwp[0][0].memory.events) == 1


# ===========================================================================
# Danger / interest setting
# ===========================================================================


class TestDangerAndInterestMapping:
    """Events should set danger and interest levels on affected brains."""

    def test_weapon_fired_sets_danger(self):
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(10.0, 0.0)])
        brain = bwp[0][0]

        event = {"type": "weapon_fired", "data": {"position": [0.0, 0.0]}}
        reactor.process_event(event, bwp)

        assert brain._danger_nearby is True

    def test_target_eliminated_sets_danger(self):
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(10.0, 0.0)])
        brain = bwp[0][0]

        event = {"type": "target_eliminated", "data": {"position": [0.0, 0.0]}}
        reactor.process_event(event, bwp)

        assert brain._danger_nearby is True

    def test_wave_start_sets_interest(self):
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(10.0, 0.0)])
        brain = bwp[0][0]

        event = {"type": "wave_start", "data": {"wave": 1}}
        reactor.process_event(event, bwp)

        assert brain._interest_nearby is True

    def test_danger_distance_set_correctly(self):
        """The danger distance should match the actual distance from event."""
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(30.0, 0.0)])
        brain = bwp[0][0]

        event = {"type": "weapon_fired", "data": {"position": [0.0, 0.0]}}
        reactor.process_event(event, bwp)

        assert abs(brain._danger_distance - 30.0) < 1.0

    def test_memory_event_includes_distance(self):
        """Events stored in memory should include the distance to the NPC."""
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(25.0, 0.0)])
        brain = bwp[0][0]

        event = {"type": "weapon_fired", "data": {"position": [0.0, 0.0]}}
        reactor.process_event(event, bwp)

        assert len(brain.memory.events) == 1
        recorded = brain.memory.events[0]
        assert abs(recorded["data"]["distance"] - 25.0) < 1.0

    def test_escalation_change_sets_interest(self):
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(10.0, 0.0)])
        brain = bwp[0][0]

        event = {"type": "escalation_change", "data": {"level": "yellow"}}
        reactor.process_event(event, bwp)

        assert brain._interest_nearby is True


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEventReactorEdgeCases:
    def test_event_without_position_uses_infinite_radius(self):
        """Events missing position data should be treated as global."""
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(5000.0, 5000.0)])
        event = {"type": "wave_start", "data": {}}
        reactor.process_event(event, bwp)

        assert len(bwp[0][0].memory.events) == 1

    def test_bound_npcs_excluded(self):
        """Bound NPCs should not receive events."""
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(10.0, 0.0)])
        brain = bwp[0][0]
        brain.bind()

        event = {"type": "weapon_fired", "data": {"position": [0.0, 0.0]}}
        reactor.process_event(event, bwp)

        assert len(brain.memory.events) == 0
        assert brain._danger_nearby is False

    def test_unknown_event_type_ignored(self):
        """Unknown event types should not crash."""
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = _make_brains_with_positions([(10.0, 0.0)])
        event = {"type": "some_unknown_event", "data": {"position": [0.0, 0.0]}}
        reactor.process_event(event, bwp)

        # Should not crash; brain memory may or may not record it
        # but should not set danger/interest for unknown types

    def test_empty_brain_list(self):
        """Processing with no brains should not crash."""
        bus = EventBus()
        reactor = EventReactor(bus)

        event = {"type": "weapon_fired", "data": {"position": [0.0, 0.0]}}
        reactor.process_event(event, [])  # no error
