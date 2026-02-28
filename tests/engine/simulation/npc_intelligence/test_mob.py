"""Tests for MobManager — riot/mob formation and behavior."""

import math
import pytest
from unittest.mock import MagicMock

from engine.simulation.npc_intelligence.mob import (
    MobFormation,
    MobManager,
    RiotLevel,
)
from engine.simulation.npc_intelligence.brain import NPCPersonality


# -- Helpers --


def _make_personality(aggression=0.5, sociability=0.5, curiosity=0.5, caution=0.3):
    return NPCPersonality(
        curiosity=curiosity, caution=caution,
        sociability=sociability, aggression=aggression,
    )


def _make_npc_info(npc_id, x=0.0, y=0.0, fsm_state="observing",
                   aggression=0.6, alliance="neutral"):
    """Create a dict matching what MobManager expects for NPC data."""
    return {
        "id": npc_id,
        "x": x, "y": y,
        "fsm_state": fsm_state,
        "alliance": alliance,
        "personality": _make_personality(aggression=aggression),
    }


# ==========================================================================
# MobFormation data structure
# ==========================================================================


class TestMobFormation:
    """MobFormation tracks a group of radicalized NPCs."""

    def test_creation(self):
        mob = MobFormation(
            leader_id="npc-1",
            rally_point=(50, 50),
        )
        assert mob.leader_id == "npc-1"
        assert mob.rally_point == (50, 50)
        assert len(mob.member_ids) == 0

    def test_add_member(self):
        mob = MobFormation(leader_id="npc-1", rally_point=(50, 50))
        mob.member_ids.add("npc-2")
        mob.member_ids.add("npc-3")
        assert len(mob.member_ids) == 2

    def test_size_includes_leader(self):
        mob = MobFormation(leader_id="npc-1", rally_point=(50, 50))
        mob.member_ids.add("npc-2")
        assert mob.size == 2  # leader + 1 member

    def test_default_aggression(self):
        mob = MobFormation(leader_id="npc-1", rally_point=(0, 0))
        assert mob.aggression_level == 0.5

    def test_riot_level_by_size(self):
        mob = MobFormation(leader_id="npc-1", rally_point=(0, 0))
        # 1 member (solo) -> no riot
        assert mob.riot_level == RiotLevel.NONE

        # Add to 4 total
        for i in range(3):
            mob.member_ids.add(f"npc-{i+2}")
        assert mob.riot_level == RiotLevel.SHOUTING

        # Add to 8 total
        for i in range(4):
            mob.member_ids.add(f"npc-{i+10}")
        assert mob.riot_level == RiotLevel.AGGRESSIVE

        # Add to 12 total
        for i in range(4):
            mob.member_ids.add(f"npc-{i+20}")
        assert mob.riot_level == RiotLevel.ASSAULT

    def test_has_target(self):
        mob = MobFormation(leader_id="npc-1", rally_point=(0, 0))
        assert mob.target_point is None
        mob.target_point = (100, 100)
        assert mob.target_point == (100, 100)

    def test_scatter_threshold(self):
        """Mob scatters if below 3 total members."""
        mob = MobFormation(leader_id="npc-1", rally_point=(0, 0))
        mob.member_ids.add("npc-2")
        assert mob.should_scatter is True  # only 2 (leader + 1)
        mob.member_ids.add("npc-3")
        assert mob.should_scatter is False  # 3 total


# ==========================================================================
# MobManager
# ==========================================================================


class TestMobManager:
    """MobManager handles mob formation and lifecycle."""

    def test_create_manager(self):
        mgr = MobManager()
        assert mgr is not None
        assert mgr.mob_count == 0

    def test_form_mob(self):
        """Radicalized NPC forms a mob."""
        mgr = MobManager()
        mob = mgr.form_mob("npc-1", rally_point=(50, 50))
        assert mob is not None
        assert mob.leader_id == "npc-1"
        assert mgr.mob_count == 1

    def test_recruit_nearby_npcs(self):
        """MobManager recruits eligible nearby NPCs into a mob."""
        mgr = MobManager()
        mob = mgr.form_mob("npc-1", rally_point=(50, 50))

        # Nearby NPC with high aggression, in observing state
        nearby = [
            _make_npc_info("npc-2", x=55, y=50, aggression=0.8, fsm_state="observing"),
            _make_npc_info("npc-3", x=60, y=50, aggression=0.7, fsm_state="curious"),
            _make_npc_info("npc-4", x=200, y=200, aggression=0.9, fsm_state="observing"),  # too far
            _make_npc_info("npc-5", x=55, y=50, aggression=0.2, fsm_state="observing"),  # too peaceful
            _make_npc_info("npc-6", x=55, y=50, aggression=0.8, fsm_state="fleeing"),  # wrong state
        ]

        recruited = mgr.recruit(mob, nearby, radius=50.0)
        # npc-2 and npc-3 should be recruited
        # npc-4 is too far, npc-5 is too peaceful, npc-6 is fleeing
        assert "npc-2" in recruited
        assert "npc-3" in recruited
        assert "npc-4" not in recruited
        assert "npc-5" not in recruited
        assert "npc-6" not in recruited

    def test_recruit_minimum_aggression(self):
        """Only NPCs with aggression > 0.5 can be recruited."""
        mgr = MobManager()
        mob = mgr.form_mob("npc-1", rally_point=(50, 50))

        low_aggression = [
            _make_npc_info("npc-2", x=55, y=50, aggression=0.3, fsm_state="observing"),
        ]
        recruited = mgr.recruit(mob, low_aggression, radius=50.0)
        assert len(recruited) == 0

    def test_recruit_eligible_states(self):
        """Only NPCs in observing/curious/walking state can be recruited."""
        mgr = MobManager()
        mob = mgr.form_mob("npc-1", rally_point=(50, 50))

        npcs = [
            _make_npc_info("ped-1", x=55, y=50, aggression=0.8, fsm_state="observing"),
            _make_npc_info("ped-2", x=55, y=50, aggression=0.8, fsm_state="curious"),
            _make_npc_info("ped-3", x=55, y=50, aggression=0.8, fsm_state="walking"),
            _make_npc_info("ped-4", x=55, y=50, aggression=0.8, fsm_state="fleeing"),
            _make_npc_info("ped-5", x=55, y=50, aggression=0.8, fsm_state="hiding"),
            _make_npc_info("ped-6", x=55, y=50, aggression=0.8, fsm_state="panicking"),
        ]

        recruited = mgr.recruit(mob, npcs, radius=50.0)
        # Only first 3 should be recruited
        assert "ped-1" in recruited
        assert "ped-2" in recruited
        assert "ped-3" in recruited
        assert "ped-4" not in recruited
        assert "ped-5" not in recruited
        assert "ped-6" not in recruited

    def test_set_target(self):
        """Mob can be directed at a target."""
        mgr = MobManager()
        mob = mgr.form_mob("npc-1", rally_point=(50, 50))
        mgr.set_target(mob, target_point=(200, 100))
        assert mob.target_point == (200, 100)

    def test_disband_mob(self):
        mgr = MobManager()
        mob = mgr.form_mob("npc-1", rally_point=(50, 50))
        mgr.disband_mob(mob)
        assert mgr.mob_count == 0

    def test_get_mob_for_npc(self):
        """Can find which mob an NPC belongs to."""
        mgr = MobManager()
        mob = mgr.form_mob("npc-1", rally_point=(50, 50))
        mob.member_ids.add("npc-2")

        assert mgr.get_mob_for_npc("npc-1") is mob
        assert mgr.get_mob_for_npc("npc-2") is mob
        assert mgr.get_mob_for_npc("npc-99") is None

    def test_tick_disbands_small_mobs(self):
        """Mobs with fewer than 3 total members scatter on tick."""
        mgr = MobManager()
        mob = mgr.form_mob("npc-1", rally_point=(50, 50))
        mob.member_ids.add("npc-2")
        # 2 members total — should scatter
        disbanded = mgr.tick(dt=0.1)
        assert "npc-1" in disbanded or mgr.mob_count == 0

    def test_tick_keeps_large_mobs(self):
        """Mobs with 3+ members are not disbanded."""
        mgr = MobManager()
        mob = mgr.form_mob("npc-1", rally_point=(50, 50))
        mob.member_ids.update({"npc-2", "npc-3"})
        disbanded = mgr.tick(dt=0.1)
        assert mgr.mob_count == 1

    def test_already_in_mob_not_recruited(self):
        """NPCs already in a mob should not be recruited again."""
        mgr = MobManager()
        mob1 = mgr.form_mob("npc-1", rally_point=(50, 50))
        mob1.member_ids.add("npc-2")

        mob2 = mgr.form_mob("npc-10", rally_point=(100, 100))
        npcs = [
            _make_npc_info("npc-2", x=100, y=100, aggression=0.9, fsm_state="observing"),
        ]
        recruited = mgr.recruit(mob2, npcs, radius=50.0)
        assert "npc-2" not in recruited

    def test_hostile_not_recruited(self):
        """NPCs that are already hostile should not be recruited."""
        mgr = MobManager()
        mob = mgr.form_mob("npc-1", rally_point=(50, 50))
        npcs = [
            _make_npc_info("npc-2", x=55, y=50, aggression=0.9,
                           fsm_state="observing", alliance="hostile"),
        ]
        recruited = mgr.recruit(mob, npcs, radius=50.0)
        assert "npc-2" not in recruited

    def test_mob_advance_waypoints(self):
        """Mob generates advance waypoints toward target."""
        mgr = MobManager()
        mob = mgr.form_mob("npc-1", rally_point=(0, 0))
        mob.member_ids.update({"npc-2", "npc-3"})
        mob.target_point = (100, 0)

        waypoints = mgr.advance_waypoints(mob, "npc-2", npc_pos=(0, 0))
        assert waypoints is not None
        assert len(waypoints) >= 2
        # Should generally move toward target
        assert waypoints[-1][0] > 0


# ==========================================================================
# Riot levels
# ==========================================================================


class TestRiotLevels:
    """RiotLevel enum represents escalation stages."""

    def test_none_level(self):
        assert RiotLevel.NONE.value == 0

    def test_shouting_level(self):
        assert RiotLevel.SHOUTING.value == 1

    def test_aggressive_level(self):
        assert RiotLevel.AGGRESSIVE.value == 2

    def test_assault_level(self):
        assert RiotLevel.ASSAULT.value == 3
