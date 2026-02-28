"""Tests for CrowdDynamics — panic/curiosity spreading between nearby NPCs."""

import pytest

from engine.simulation.npc_intelligence.brain import NPCBrain, NPCPersonality
from engine.simulation.npc_intelligence.crowd import CrowdDynamics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_brain(
    target_id: str = "npc-0",
    asset_type: str = "person",
    caution: float = 0.5,
    curiosity: float = 0.5,
    sociability: float = 0.5,
) -> NPCBrain:
    personality = NPCPersonality(
        curiosity=curiosity,
        caution=caution,
        sociability=sociability,
        aggression=0.1,
    )
    return NPCBrain(
        target_id=target_id,
        asset_type=asset_type,
        alliance="neutral",
        personality=personality,
    )


# ===========================================================================
# Construction
# ===========================================================================


class TestCrowdConstruction:
    def test_create(self):
        cd = CrowdDynamics()
        assert cd is not None

    def test_update_empty_list(self):
        """Update with empty list should not crash."""
        cd = CrowdDynamics()
        cd.update([])  # no error


# ===========================================================================
# Panic contagion
# ===========================================================================


class TestPanicSpreading:
    def test_fleeing_npc_spreads_panic_within_15m(self):
        """A fleeing NPC should cause nearby NPCs (within 15m) to gain danger."""
        cd = CrowdDynamics()

        fleeing = _make_brain("npc-flee")
        fleeing.set_danger(5.0)
        fleeing.apply_action("FLEE")

        bystander = _make_brain("npc-stand")
        assert bystander._danger_nearby is False

        bwp = [
            (fleeing, (0.0, 0.0)),
            (bystander, (10.0, 0.0)),  # 10m away, within 15m
        ]
        cd.update(bwp)

        assert bystander._danger_nearby is True

    def test_fleeing_npc_does_not_spread_beyond_15m(self):
        """Panic should not spread beyond 15m."""
        cd = CrowdDynamics()

        fleeing = _make_brain("npc-flee")
        fleeing.set_danger(5.0)
        fleeing.apply_action("FLEE")

        far_bystander = _make_brain("npc-far")

        bwp = [
            (fleeing, (0.0, 0.0)),
            (far_bystander, (20.0, 0.0)),  # 20m away, outside 15m
        ]
        cd.update(bwp)

        assert far_bystander._danger_nearby is False

    def test_multiple_fleeing_npcs_compound_panic(self):
        """Multiple fleeing NPCs near a bystander should increase the effect."""
        cd = CrowdDynamics()

        fleeing1 = _make_brain("npc-f1")
        fleeing1.set_danger(5.0)
        fleeing1.apply_action("FLEE")

        fleeing2 = _make_brain("npc-f2")
        fleeing2.set_danger(5.0)
        fleeing2.apply_action("FLEE")

        bystander = _make_brain("npc-b")

        bwp = [
            (fleeing1, (5.0, 0.0)),
            (fleeing2, (-5.0, 0.0)),
            (bystander, (0.0, 0.0)),
        ]
        cd.update(bwp)

        assert bystander._danger_nearby is True

    def test_panicking_npc_also_spreads(self):
        """NPCs in panicking state should also spread panic."""
        cd = CrowdDynamics()

        panicker = _make_brain("npc-panic")
        panicker.set_danger(3.0)
        panicker.force_state("panicking")

        bystander = _make_brain("npc-b")

        bwp = [
            (panicker, (0.0, 0.0)),
            (bystander, (8.0, 0.0)),
        ]
        cd.update(bwp)

        assert bystander._danger_nearby is True


# ===========================================================================
# Curiosity spreading
# ===========================================================================


class TestCuriositySpreading:
    def test_curious_npc_attracts_social_npcs_within_20m(self):
        """A curious NPC should attract nearby social NPCs (within 20m)."""
        cd = CrowdDynamics()

        curious = _make_brain("npc-curious", sociability=0.8, curiosity=0.9)
        curious.set_interest(10.0)
        curious.apply_action("OBSERVE")

        social_bystander = _make_brain("npc-social", sociability=0.8)

        bwp = [
            (curious, (0.0, 0.0)),
            (social_bystander, (15.0, 0.0)),  # 15m, within 20m
        ]
        cd.update(bwp)

        assert social_bystander._interest_nearby is True

    def test_curiosity_does_not_spread_beyond_20m(self):
        """Curiosity should not spread beyond 20m."""
        cd = CrowdDynamics()

        curious = _make_brain("npc-curious", curiosity=0.9)
        curious.set_interest(10.0)
        curious.apply_action("OBSERVE")

        far_bystander = _make_brain("npc-far", sociability=0.8)

        bwp = [
            (curious, (0.0, 0.0)),
            (far_bystander, (25.0, 0.0)),  # 25m, outside 20m
        ]
        cd.update(bwp)

        assert far_bystander._interest_nearby is False

    def test_low_sociability_not_attracted(self):
        """Low sociability NPCs should not be attracted by curious NPCs."""
        cd = CrowdDynamics()

        curious = _make_brain("npc-curious", curiosity=0.9)
        curious.set_interest(10.0)
        curious.apply_action("OBSERVE")

        loner = _make_brain("npc-loner", sociability=0.1)

        bwp = [
            (curious, (0.0, 0.0)),
            (loner, (10.0, 0.0)),
        ]
        cd.update(bwp)

        assert loner._interest_nearby is False


# ===========================================================================
# Exclusions
# ===========================================================================


class TestCrowdExclusions:
    def test_bound_npcs_excluded(self):
        """Bound NPCs should not be affected by crowd dynamics."""
        cd = CrowdDynamics()

        fleeing = _make_brain("npc-flee")
        fleeing.set_danger(5.0)
        fleeing.apply_action("FLEE")

        bound_npc = _make_brain("npc-bound")
        bound_npc.bind()

        bwp = [
            (fleeing, (0.0, 0.0)),
            (bound_npc, (5.0, 0.0)),
        ]
        cd.update(bwp)

        assert bound_npc._danger_nearby is False

    def test_vehicles_excluded_from_panic_spreading(self):
        """Vehicles should not be affected by pedestrian panic spreading."""
        cd = CrowdDynamics()

        fleeing = _make_brain("npc-flee", asset_type="person")
        fleeing.set_danger(5.0)
        fleeing.apply_action("FLEE")

        vehicle = _make_brain("npc-car", asset_type="vehicle")

        bwp = [
            (fleeing, (0.0, 0.0)),
            (vehicle, (5.0, 0.0)),
        ]
        cd.update(bwp)

        assert vehicle._danger_nearby is False

    def test_bound_npcs_do_not_spread_panic(self):
        """Bound NPCs should not act as panic sources."""
        cd = CrowdDynamics()

        bound_fleeing = _make_brain("npc-bound-flee")
        bound_fleeing.set_danger(5.0)
        bound_fleeing.apply_action("FLEE")
        bound_fleeing.bind()  # bound after setting danger

        bystander = _make_brain("npc-b")

        bwp = [
            (bound_fleeing, (0.0, 0.0)),
            (bystander, (5.0, 0.0)),
        ]
        cd.update(bwp)

        assert bystander._danger_nearby is False

    def test_danger_does_not_override_already_fleeing(self):
        """NPCs already fleeing should not have their state re-set redundantly,
        but their danger should remain set."""
        cd = CrowdDynamics()

        fleeing1 = _make_brain("npc-f1")
        fleeing1.set_danger(5.0)
        fleeing1.apply_action("FLEE")

        fleeing2 = _make_brain("npc-f2")
        fleeing2.set_danger(3.0)
        fleeing2.apply_action("FLEE")

        bwp = [
            (fleeing1, (0.0, 0.0)),
            (fleeing2, (5.0, 0.0)),
        ]
        cd.update(bwp)

        # Both should still be in danger
        assert fleeing1._danger_nearby is True
        assert fleeing2._danger_nearby is True
