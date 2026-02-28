# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for NPCBrain, NPCPersonality, NPCMemory."""

import time
import pytest
from engine.simulation.npc_intelligence.brain import (
    NPCPersonality,
    NPCMemory,
    NPCBrain,
)


# ============================================================================
# NPCPersonality
# ============================================================================

class TestNPCPersonality:
    """Tests for personality trait generation and access."""

    def test_random_creates_valid_traits(self):
        p = NPCPersonality.random()
        assert 0.0 <= p.curiosity <= 1.0
        assert 0.0 <= p.caution <= 1.0
        assert 0.0 <= p.sociability <= 1.0
        assert 0.0 <= p.aggression <= 1.0

    def test_for_person(self):
        p = NPCPersonality.for_asset_type("person")
        assert 0.0 <= p.curiosity <= 1.0
        assert 0.0 <= p.caution <= 1.0
        assert p.aggression <= 0.4  # pedestrians have low max aggression

    def test_for_vehicle(self):
        p = NPCPersonality.for_asset_type("vehicle")
        assert p.curiosity <= 0.4  # vehicles less curious
        assert p.caution >= 0.3    # vehicles cautious
        assert p.aggression <= 0.2

    def test_for_animal(self):
        p = NPCPersonality.for_asset_type("animal")
        assert p.caution >= 0.4    # animals cautious
        assert p.aggression <= 0.2

    def test_explicit_values(self):
        p = NPCPersonality(curiosity=0.5, caution=0.6, sociability=0.7, aggression=0.1)
        assert p.curiosity == 0.5
        assert p.caution == 0.6
        assert p.sociability == 0.7
        assert p.aggression == 0.1

    def test_unknown_type_uses_random(self):
        p = NPCPersonality.for_asset_type("unknown_type")
        assert 0.0 <= p.curiosity <= 1.0

    def test_to_dict(self):
        p = NPCPersonality(curiosity=0.5, caution=0.6, sociability=0.7, aggression=0.1)
        d = p.to_dict()
        assert d["curiosity"] == 0.5
        assert d["caution"] == 0.6
        assert d["sociability"] == 0.7
        assert d["aggression"] == 0.1


# ============================================================================
# NPCMemory
# ============================================================================

class TestNPCMemory:
    """Tests for short-term event memory."""

    def test_add_event(self):
        m = NPCMemory()
        m.add_event("explosion", {"distance": 10.0})
        assert len(m.events) == 1

    def test_recent_events(self):
        m = NPCMemory()
        m.add_event("explosion", {"distance": 10.0})
        m.add_event("gunfire", {"distance": 20.0})
        recent = m.recent(5)
        assert len(recent) == 2

    def test_max_events_trimmed(self):
        m = NPCMemory(max_events=5)
        for i in range(10):
            m.add_event(f"event_{i}", {})
        assert len(m.events) == 5
        # Should keep newest
        assert m.events[-1]["type"] == "event_9"

    def test_danger_level_from_events(self):
        m = NPCMemory()
        m.add_event("weapon_fired", {"distance": 5.0})
        m.add_event("target_eliminated", {"distance": 10.0})
        danger = m.danger_level()
        assert danger > 0.0

    def test_danger_level_zero_no_events(self):
        m = NPCMemory()
        assert m.danger_level() == 0.0

    def test_danger_decays_with_age(self):
        m = NPCMemory()
        m.add_event("weapon_fired", {"distance": 5.0})
        d1 = m.danger_level()
        # Manually age the event
        m.events[0]["timestamp"] -= 60.0
        d2 = m.danger_level()
        assert d2 < d1

    def test_interest_level(self):
        m = NPCMemory()
        m.add_event("wave_start", {"wave": 1})
        interest = m.interest_level()
        assert interest > 0.0

    def test_interest_level_zero_no_events(self):
        m = NPCMemory()
        assert m.interest_level() == 0.0

    def test_format_for_prompt(self):
        m = NPCMemory()
        m.add_event("explosion", {"distance": 10.0})
        m.add_event("gunfire", {"distance": 20.0})
        text = m.format_for_prompt()
        assert "explosion" in text
        assert "gunfire" in text

    def test_format_empty(self):
        m = NPCMemory()
        text = m.format_for_prompt()
        assert "none" in text.lower() or text == ""

    def test_combat_events_in_window(self):
        m = NPCMemory()
        now = time.time()
        m.add_event("target_eliminated", {"distance": 10.0})
        m.add_event("target_eliminated", {"distance": 15.0})
        m.add_event("target_eliminated", {"distance": 20.0})
        count = m.combat_events_in_window(60.0)
        assert count == 3

    def test_combat_events_exclude_old(self):
        m = NPCMemory()
        m.add_event("target_eliminated", {"distance": 10.0})
        # Age the event beyond window
        m.events[0]["timestamp"] -= 120.0
        count = m.combat_events_in_window(60.0)
        assert count == 0

    def test_clear(self):
        m = NPCMemory()
        m.add_event("test", {})
        m.clear()
        assert len(m.events) == 0


# ============================================================================
# NPCBrain
# ============================================================================

class TestNPCBrain:
    """Tests for the per-NPC brain controller."""

    def test_create_with_id(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        assert brain.target_id == "npc-1"

    def test_has_personality(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        assert brain.personality is not None
        assert 0.0 <= brain.personality.curiosity <= 1.0

    def test_has_memory(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        assert brain.memory is not None

    def test_has_fsm(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        assert brain.fsm is not None
        assert brain.fsm.current_state == "walking"

    def test_vehicle_brain_has_vehicle_fsm(self):
        brain = NPCBrain("npc-2", "vehicle", "neutral")
        assert brain.fsm is not None
        assert brain.fsm.current_state == "driving"

    def test_animal_brain_has_animal_fsm(self):
        brain = NPCBrain("npc-3", "animal", "neutral")
        assert brain.fsm is not None
        assert brain.fsm.current_state == "wandering"

    def test_tick_updates_fsm(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.tick(0.1)
        # Should still be walking (no events)
        assert brain.fsm_state == "walking"

    def test_fsm_state_property(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        assert brain.fsm_state == "walking"

    def test_needs_think_initially_true(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        # After enough time, should need thinking
        brain._last_think_time = 0.0
        assert brain.needs_think()

    def test_needs_think_false_after_recent_think(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain._last_think_time = time.monotonic()
        assert not brain.needs_think()

    def test_apply_action_flee(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.apply_action("FLEE")
        assert brain.fsm_state == "fleeing"

    def test_apply_action_walk(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.force_state("fleeing")
        brain.apply_action("WALK")
        assert brain.fsm_state == "walking"

    def test_apply_action_observe(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.apply_action("OBSERVE")
        assert brain.fsm_state == "observing"

    def test_apply_action_hide(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.apply_action("HIDE")
        assert brain.fsm_state == "hiding"

    def test_apply_action_approach(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.apply_action("APPROACH")
        assert brain.fsm_state == "curious"

    def test_apply_action_ignore(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.apply_action("IGNORE")
        assert brain.fsm_state == "walking"

    def test_apply_action_pause(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.apply_action("PAUSE")
        assert brain.fsm_state == "pausing"

    def test_bind_suspends_ai(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.bind()
        assert brain.is_bound
        assert not brain.needs_think()

    def test_unbind_resumes_ai(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.bind()
        brain.unbind()
        assert not brain.is_bound

    def test_build_context(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        ctx = brain.build_fsm_context(
            danger_nearby=True,
            danger_distance=10.0,
            interest_nearby=False,
        )
        assert ctx["danger_nearby"] is True
        assert ctx["danger_distance"] == 10.0

    def test_force_state(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.force_state("hiding")
        assert brain.fsm_state == "hiding"

    def test_get_state_returns_dict(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        state = brain.get_state()
        assert "fsm_state" in state
        assert "personality" in state
        assert state["target_id"] == "npc-1"

    def test_set_danger_context(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.set_danger(distance=5.0)
        brain.tick(0.1)
        assert brain.fsm_state == "fleeing"

    def test_set_interest_context(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.personality = NPCPersonality(curiosity=0.9, caution=0.1, sociability=0.5, aggression=0.0)
        brain.set_interest(distance=8.0)
        brain.tick(0.1)
        assert brain.fsm_state == "curious"

    def test_clear_danger(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.set_danger(distance=5.0)
        brain.tick(0.1)
        assert brain.fsm_state == "fleeing"
        brain.clear_danger()
        # After enough time the max_duration should return to walking
        for _ in range(200):
            brain.tick(0.1)
        assert brain.fsm_state != "fleeing"
