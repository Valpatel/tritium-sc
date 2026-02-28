"""Tests for BehaviorTreeFallback — weighted-random NPC decision making."""

import random

import pytest

from engine.simulation.npc_intelligence.brain import NPCBrain, NPCPersonality
from engine.simulation.npc_intelligence.fallback import BehaviorTreeFallback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_brain(
    asset_type: str = "person",
    curiosity: float = 0.5,
    caution: float = 0.5,
    sociability: float = 0.5,
    aggression: float = 0.1,
) -> NPCBrain:
    personality = NPCPersonality(
        curiosity=curiosity,
        caution=caution,
        sociability=sociability,
        aggression=aggression,
    )
    return NPCBrain(
        target_id="test-npc",
        asset_type=asset_type,
        alliance="neutral",
        personality=personality,
    )


# ===========================================================================
# Basic construction
# ===========================================================================


class TestFallbackConstruction:
    def test_create(self):
        fb = BehaviorTreeFallback()
        assert fb is not None

    def test_decide_returns_string(self):
        fb = BehaviorTreeFallback()
        brain = _make_brain()
        result = fb.decide(brain, danger_level=0.0, interest_level=0.0)
        assert isinstance(result, str)


# ===========================================================================
# High danger scenarios
# ===========================================================================


class TestHighDangerDecisions:
    def test_high_caution_high_danger_flees_or_hides(self):
        """High caution + close danger should produce FLEE or HIDE."""
        fb = BehaviorTreeFallback()
        brain = _make_brain(caution=0.9)

        # Run many times to check distribution
        results = set()
        random.seed(42)
        for _ in range(100):
            results.add(fb.decide(brain, danger_level=0.9, interest_level=0.0))

        assert results <= {"FLEE", "HIDE"}
        assert "FLEE" in results  # should appear at least once

    def test_low_caution_high_danger_still_flees(self):
        """Even low-caution NPCs should flee/hide at very high danger."""
        fb = BehaviorTreeFallback()
        brain = _make_brain(caution=0.2)

        random.seed(42)
        results = set()
        for _ in range(100):
            results.add(fb.decide(brain, danger_level=0.95, interest_level=0.0))

        # At extreme danger, even low caution should flee
        assert "FLEE" in results or "HIDE" in results


# ===========================================================================
# High interest scenarios
# ===========================================================================


class TestHighInterestDecisions:
    def test_high_curiosity_high_interest_approaches_or_observes(self):
        """High curiosity + interesting event should produce APPROACH or OBSERVE."""
        fb = BehaviorTreeFallback()
        brain = _make_brain(curiosity=0.9)

        random.seed(42)
        results = set()
        for _ in range(100):
            results.add(fb.decide(brain, danger_level=0.0, interest_level=0.8))

        assert results <= {"APPROACH", "OBSERVE", "WALK", "PAUSE"}
        assert "APPROACH" in results or "OBSERVE" in results

    def test_low_curiosity_high_interest_mostly_ignores(self):
        """Low curiosity NPCs should mostly ignore interesting events."""
        fb = BehaviorTreeFallback()
        brain = _make_brain(curiosity=0.1)

        random.seed(42)
        results = set()
        for _ in range(200):
            results.add(fb.decide(brain, danger_level=0.0, interest_level=0.7))

        # Low-curiosity NPCs should mostly walk/pause, not approach
        # They may rarely approach but it should not dominate
        assert "WALK" in results or "PAUSE" in results


# ===========================================================================
# Normal conditions (no danger, no interest)
# ===========================================================================


class TestNormalDecisions:
    def test_pedestrian_normal_walks_or_pauses(self):
        """Pedestrians under normal conditions should WALK or PAUSE."""
        fb = BehaviorTreeFallback()
        brain = _make_brain(asset_type="person")

        random.seed(42)
        results = set()
        for _ in range(100):
            results.add(fb.decide(brain, danger_level=0.0, interest_level=0.0))

        assert "WALK" in results or "PAUSE" in results
        # Should NOT produce FLEE or HIDE under normal conditions
        assert "FLEE" not in results
        assert "HIDE" not in results

    def test_vehicle_normal_drives(self):
        """Vehicles under normal conditions should DRIVE."""
        fb = BehaviorTreeFallback()
        brain = _make_brain(asset_type="vehicle")

        random.seed(42)
        results = set()
        for _ in range(100):
            results.add(fb.decide(brain, danger_level=0.0, interest_level=0.0))

        assert "DRIVE" in results

    def test_animal_normal_wanders(self):
        """Animals under normal conditions should WANDER."""
        fb = BehaviorTreeFallback()
        brain = _make_brain(asset_type="animal")

        random.seed(42)
        results = set()
        for _ in range(100):
            results.add(fb.decide(brain, danger_level=0.0, interest_level=0.0))

        assert "WANDER" in results


# ===========================================================================
# Action validity
# ===========================================================================


class TestActionValidity:
    VALID_ACTIONS = {"WALK", "FLEE", "HIDE", "OBSERVE", "APPROACH", "PAUSE", "IGNORE",
                     "DRIVE", "WANDER"}

    def test_all_actions_are_valid_strings(self):
        """Every returned action must be in the valid set."""
        fb = BehaviorTreeFallback()

        random.seed(42)
        for asset_type in ("person", "vehicle", "animal"):
            brain = _make_brain(asset_type=asset_type)
            for danger in (0.0, 0.3, 0.6, 0.9):
                for interest in (0.0, 0.3, 0.6, 0.9):
                    result = fb.decide(brain, danger_level=danger, interest_level=interest)
                    assert result in self.VALID_ACTIONS, (
                        f"Invalid action '{result}' for {asset_type}, "
                        f"danger={danger}, interest={interest}"
                    )

    def test_danger_overrides_interest(self):
        """When both danger and interest are high, danger should take priority."""
        fb = BehaviorTreeFallback()
        brain = _make_brain(caution=0.9, curiosity=0.9)

        random.seed(42)
        flee_count = 0
        approach_count = 0
        for _ in range(100):
            result = fb.decide(brain, danger_level=0.9, interest_level=0.9)
            if result in ("FLEE", "HIDE"):
                flee_count += 1
            if result in ("APPROACH", "OBSERVE"):
                approach_count += 1

        # Danger should dominate
        assert flee_count > approach_count


# ===========================================================================
# Edge cases
# ===========================================================================


class TestFallbackEdgeCases:
    def test_zero_everything(self):
        """Zero danger, zero interest should still return a valid action."""
        fb = BehaviorTreeFallback()
        brain = _make_brain()
        result = fb.decide(brain, danger_level=0.0, interest_level=0.0)
        assert result in TestActionValidity.VALID_ACTIONS

    def test_max_everything(self):
        """Max danger and interest should still return a valid action."""
        fb = BehaviorTreeFallback()
        brain = _make_brain()
        result = fb.decide(brain, danger_level=1.0, interest_level=1.0)
        assert result in TestActionValidity.VALID_ACTIONS
