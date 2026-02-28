# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for AllianceManager — NPC radicalization logic.

Radicalization conditions (ALL must be true):
1. 3+ target_eliminated events in NPC memory within 60s
2. Global escalation level is "amber" or "red"
3. No friendly units within 30m of the NPC
4. NPC aggression trait > 0.7
5. Global cooldown: 120s since last radicalization

On radicalization the target becomes hostile, gains combat stats,
gets a hostile FSM, and a MovementController.
"""

import math
import time

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.npc_intelligence.alliance import AllianceManager
from engine.simulation.npc_intelligence.brain import NPCBrain, NPCPersonality
from engine.simulation.target import SimulationTarget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    target_id: str = "npc-1",
    alliance: str = "neutral",
    position: tuple[float, float] = (50.0, 50.0),
    is_combatant: bool = False,
) -> SimulationTarget:
    """Create a minimal SimulationTarget for testing."""
    return SimulationTarget(
        target_id=target_id,
        name=f"Test NPC {target_id}",
        alliance=alliance,
        asset_type="person",
        position=position,
        speed=1.5,
        is_combatant=is_combatant,
    )


def _make_brain(
    target_id: str = "npc-1",
    aggression: float = 0.8,
    num_eliminations: int = 4,
) -> NPCBrain:
    """Create a brain with high aggression and enough combat memory."""
    personality = NPCPersonality(
        curiosity=0.5,
        caution=0.5,
        sociability=0.5,
        aggression=aggression,
    )
    brain = NPCBrain(
        target_id=target_id,
        asset_type="person",
        alliance="neutral",
        personality=personality,
    )
    for i in range(num_eliminations):
        brain.memory.add_event("target_eliminated", {"distance": 15.0})
    return brain


def _setup_all_conditions():
    """Return (manager, brain, target, escalation, friendly_positions) with all
    radicalization conditions satisfied."""
    bus = EventBus()
    manager = AllianceManager(event_bus=bus)
    brain = _make_brain(aggression=0.85, num_eliminations=4)
    target = _make_target()
    escalation = "amber"
    friendly_positions = [(200.0, 200.0)]  # far away (>30m)
    return manager, brain, target, escalation, friendly_positions, bus


# ===========================================================================
# Test class
# ===========================================================================


class TestAllianceManager:
    """Tests for AllianceManager radicalization logic."""

    # -----------------------------------------------------------------------
    # Happy path: all conditions met
    # -----------------------------------------------------------------------

    def test_all_conditions_met_radicalizes(self):
        """When every condition is satisfied, check_radicalization returns target_id."""
        mgr, brain, target, esc, fps, _ = _setup_all_conditions()
        result = mgr.check_radicalization(brain, target, esc, fps)
        assert result == "npc-1"

    def test_radicalization_changes_alliance_to_hostile(self):
        mgr, brain, target, esc, fps, _ = _setup_all_conditions()
        mgr.check_radicalization(brain, target, esc, fps)
        assert target.alliance == "hostile"

    def test_radicalization_sets_is_combatant(self):
        mgr, brain, target, esc, fps, _ = _setup_all_conditions()
        mgr.check_radicalization(brain, target, esc, fps)
        assert target.is_combatant is True

    def test_radicalization_applies_hostile_combat_profile(self):
        mgr, brain, target, esc, fps, _ = _setup_all_conditions()
        mgr.check_radicalization(brain, target, esc, fps)
        assert target.health == 80.0
        assert target.weapon_range == 40.0
        assert target.weapon_cooldown == 2.5
        assert target.weapon_damage == 10.0

    def test_radicalization_swaps_fsm_to_hostile(self):
        mgr, brain, target, esc, fps, _ = _setup_all_conditions()
        mgr.check_radicalization(brain, target, esc, fps)
        assert target.fsm_state is not None
        # Hostile FSM starts in "spawning"
        assert target.fsm_state == "spawning"

    def test_radicalization_creates_movement_controller(self):
        mgr, brain, target, esc, fps, _ = _setup_all_conditions()
        mgr.check_radicalization(brain, target, esc, fps)
        assert target.movement is not None

    def test_radicalization_publishes_event(self):
        mgr, brain, target, esc, fps, bus = _setup_all_conditions()
        q = bus.subscribe()
        mgr.check_radicalization(brain, target, esc, fps)
        # Drain the queue to find our event
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        alliance_events = [e for e in events if e["type"] == "npc_alliance_change"]
        assert len(alliance_events) == 1
        data = alliance_events[0]["data"]
        assert data["target_id"] == "npc-1"
        assert data["old_alliance"] == "neutral"
        assert data["new_alliance"] == "hostile"

    # -----------------------------------------------------------------------
    # Missing single conditions -- each should prevent radicalization
    # -----------------------------------------------------------------------

    def test_too_few_eliminations_no_radicalization(self):
        """Fewer than 3 target_eliminated events -> no radicalization."""
        bus = EventBus()
        mgr = AllianceManager(event_bus=bus)
        brain = _make_brain(aggression=0.85, num_eliminations=2)  # only 2
        target = _make_target()
        result = mgr.check_radicalization(brain, target, "amber", [(200.0, 200.0)])
        assert result is None
        assert target.alliance == "neutral"

    def test_escalation_green_no_radicalization(self):
        """Escalation 'green' does not satisfy condition 2."""
        mgr, brain, target, _, fps, _ = _setup_all_conditions()
        result = mgr.check_radicalization(brain, target, "green", fps)
        assert result is None
        assert target.alliance == "neutral"

    def test_escalation_yellow_no_radicalization(self):
        """Escalation 'yellow' does not satisfy condition 2."""
        mgr, brain, target, _, fps, _ = _setup_all_conditions()
        result = mgr.check_radicalization(brain, target, "yellow", fps)
        assert result is None
        assert target.alliance == "neutral"

    def test_friendly_too_close_no_radicalization(self):
        """A friendly within 30m prevents radicalization."""
        mgr, brain, target, esc, _, _ = _setup_all_conditions()
        # Place a friendly at (55, 50) = 5m away from NPC at (50, 50)
        result = mgr.check_radicalization(brain, target, esc, [(55.0, 50.0)])
        assert result is None
        assert target.alliance == "neutral"

    def test_friendly_exactly_30m_no_radicalization(self):
        """A friendly at exactly 30m is still within range (<=30m)."""
        mgr, brain, target, esc, _, _ = _setup_all_conditions()
        # NPC at (50, 50), friendly at (80, 50) = exactly 30m
        result = mgr.check_radicalization(brain, target, esc, [(80.0, 50.0)])
        assert result is None
        assert target.alliance == "neutral"

    def test_low_aggression_no_radicalization(self):
        """NPC with aggression <= 0.7 never radicalizes."""
        bus = EventBus()
        mgr = AllianceManager(event_bus=bus)
        brain = _make_brain(aggression=0.7, num_eliminations=5)
        target = _make_target()
        result = mgr.check_radicalization(brain, target, "red", [(200.0, 200.0)])
        assert result is None
        assert target.alliance == "neutral"

    def test_aggression_exactly_0_7_no_radicalization(self):
        """Aggression must be STRICTLY greater than 0.7."""
        bus = EventBus()
        mgr = AllianceManager(event_bus=bus)
        brain = _make_brain(aggression=0.7, num_eliminations=5)
        target = _make_target()
        result = mgr.check_radicalization(brain, target, "amber", [(200.0, 200.0)])
        assert result is None

    def test_aggression_just_above_threshold(self):
        """Aggression 0.71 satisfies the >0.7 check."""
        bus = EventBus()
        mgr = AllianceManager(event_bus=bus)
        brain = _make_brain(aggression=0.71, num_eliminations=4)
        target = _make_target()
        result = mgr.check_radicalization(brain, target, "amber", [(200.0, 200.0)])
        assert result == "npc-1"

    # -----------------------------------------------------------------------
    # Cooldown
    # -----------------------------------------------------------------------

    def test_cooldown_prevents_rapid_radicalization(self):
        """After one radicalization, the next is blocked for 120s."""
        bus = EventBus()
        mgr = AllianceManager(event_bus=bus)

        # First radicalization succeeds
        brain1 = _make_brain(target_id="npc-1", aggression=0.85, num_eliminations=4)
        target1 = _make_target(target_id="npc-1")
        result1 = mgr.check_radicalization(brain1, target1, "amber", [(200.0, 200.0)])
        assert result1 == "npc-1"

        # Second immediately after fails
        brain2 = _make_brain(target_id="npc-2", aggression=0.85, num_eliminations=4)
        target2 = _make_target(target_id="npc-2")
        result2 = mgr.check_radicalization(brain2, target2, "amber", [(200.0, 200.0)])
        assert result2 is None
        assert target2.alliance == "neutral"

    def test_cooldown_expires_allows_next(self):
        """After cooldown expires, radicalization is allowed again."""
        bus = EventBus()
        mgr = AllianceManager(event_bus=bus)

        brain1 = _make_brain(target_id="npc-1", aggression=0.85, num_eliminations=4)
        target1 = _make_target(target_id="npc-1")
        mgr.check_radicalization(brain1, target1, "amber", [(200.0, 200.0)])

        # Simulate cooldown expiry by backdating the last radicalization time
        mgr._last_radicalization_time = time.time() - 121.0

        brain2 = _make_brain(target_id="npc-2", aggression=0.85, num_eliminations=4)
        target2 = _make_target(target_id="npc-2")
        result = mgr.check_radicalization(brain2, target2, "amber", [(200.0, 200.0)])
        assert result == "npc-2"

    # -----------------------------------------------------------------------
    # Edge cases
    # -----------------------------------------------------------------------

    def test_already_hostile_skipped(self):
        """An already-hostile NPC is skipped entirely."""
        mgr, brain, _, esc, fps, _ = _setup_all_conditions()
        target = _make_target(alliance="hostile", is_combatant=True)
        result = mgr.check_radicalization(brain, target, esc, fps)
        assert result is None

    def test_bound_npc_never_radicalizes(self):
        """A bound NPC (live tracking) should not radicalize."""
        mgr, brain, target, esc, fps, _ = _setup_all_conditions()
        brain.bind()
        result = mgr.check_radicalization(brain, target, esc, fps)
        assert result is None
        assert target.alliance == "neutral"

    def test_returns_target_id_on_success(self):
        """check_radicalization returns the target_id string on success."""
        mgr, brain, target, esc, fps, _ = _setup_all_conditions()
        result = mgr.check_radicalization(brain, target, esc, fps)
        assert isinstance(result, str)
        assert result == target.target_id

    def test_returns_none_on_failure(self):
        """check_radicalization returns None when conditions not met."""
        mgr, brain, target, _, fps, _ = _setup_all_conditions()
        result = mgr.check_radicalization(brain, target, "green", fps)
        assert result is None

    def test_no_event_bus_still_works(self):
        """AllianceManager with no event_bus should radicalize without crashing."""
        mgr = AllianceManager(event_bus=None)
        brain = _make_brain(aggression=0.85, num_eliminations=4)
        target = _make_target()
        result = mgr.check_radicalization(brain, target, "amber", [(200.0, 200.0)])
        assert result == "npc-1"
        assert target.alliance == "hostile"

    def test_escalation_red_allows_radicalization(self):
        """Escalation 'red' satisfies condition 2."""
        mgr, brain, target, _, fps, _ = _setup_all_conditions()
        result = mgr.check_radicalization(brain, target, "red", fps)
        assert result == "npc-1"

    def test_empty_friendly_positions_allows_radicalization(self):
        """No friendlies at all means condition 3 is satisfied."""
        mgr, brain, target, esc, _, _ = _setup_all_conditions()
        result = mgr.check_radicalization(brain, target, esc, [])
        assert result == "npc-1"

    def test_friendly_just_outside_30m(self):
        """A friendly at 30.1m is outside the exclusion zone."""
        mgr, brain, target, esc, _, _ = _setup_all_conditions()
        # NPC at (50, 50), friendly at (80.1, 50) = 30.1m
        result = mgr.check_radicalization(brain, target, esc, [(80.1, 50.0)])
        assert result == "npc-1"

    def test_multiple_npcs_cooldown_global(self):
        """Multiple NPCs radicalize one at a time due to global cooldown."""
        bus = EventBus()
        mgr = AllianceManager(event_bus=bus)

        results = []
        for i in range(3):
            brain = _make_brain(target_id=f"npc-{i}", aggression=0.85, num_eliminations=4)
            target = _make_target(target_id=f"npc-{i}")
            r = mgr.check_radicalization(brain, target, "amber", [(200.0, 200.0)])
            results.append(r)

        # Only the first should succeed
        assert results[0] == "npc-0"
        assert results[1] is None
        assert results[2] is None

    def test_only_target_eliminated_events_count(self):
        """Only target_eliminated events count toward the 3-event threshold,
        not other combat events like weapon_fired."""
        bus = EventBus()
        mgr = AllianceManager(event_bus=bus)
        personality = NPCPersonality(
            curiosity=0.5, caution=0.5, sociability=0.5, aggression=0.85,
        )
        brain = NPCBrain(
            target_id="npc-1", asset_type="person",
            alliance="neutral", personality=personality,
        )
        # Add 5 weapon_fired events but only 2 target_eliminated
        for _ in range(5):
            brain.memory.add_event("weapon_fired", {"distance": 10.0})
        for _ in range(2):
            brain.memory.add_event("target_eliminated", {"distance": 10.0})

        target = _make_target()
        result = mgr.check_radicalization(brain, target, "amber", [(200.0, 200.0)])
        assert result is None
        assert target.alliance == "neutral"
