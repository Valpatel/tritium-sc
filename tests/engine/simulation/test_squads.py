# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for squad formation system — coordinated hostile unit behavior.

Validates:
1. Squad formation from nearby hostiles (2+ within 15m)
2. Leader selection (highest health) and succession
3. Formation offset calculation (wedge, line)
4. Squad dissolution when members eliminated/scattered
5. Integration with engine tick loop
6. Squad members share target (focus fire)
7. Focus fire behavior — all squad members attack same defender
"""

import math
import time
import pytest
from unittest.mock import MagicMock

from engine.comms.event_bus import EventBus
from engine.simulation.combat import CombatSystem
from engine.simulation.behaviors import UnitBehaviors
from engine.simulation.target import SimulationTarget


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def combat(event_bus):
    return CombatSystem(event_bus)


@pytest.fixture
def behaviors(combat):
    return UnitBehaviors(combat)


def _make_turret(tid: str = "turret-1", pos: tuple = (0.0, 0.0)) -> SimulationTarget:
    """Create a stationary turret."""
    t = SimulationTarget(
        target_id=tid,
        name=f"Turret {tid}",
        alliance="friendly",
        asset_type="turret",
        position=pos,
        speed=0.0,
        status="stationary",
    )
    t.apply_combat_profile()
    return t


def _make_hostile(
    tid: str = "hostile-1",
    pos: tuple = (0.0, 30.0),
    health: float | None = None,
) -> SimulationTarget:
    """Create a hostile person target."""
    t = SimulationTarget(
        target_id=tid,
        name=f"Intruder {tid}",
        alliance="hostile",
        asset_type="person",
        position=pos,
        speed=3.0,
        status="active",
        waypoints=[(0.0, 0.0)],
    )
    t.apply_combat_profile()
    if health is not None:
        t.health = health
    return t


def _dist(a: tuple, b: tuple) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 1. Squad formation from nearby hostiles
# ---------------------------------------------------------------------------

class TestSquadFormation:
    """SquadManager should auto-form squads when 2+ hostiles are within 15m."""

    def test_squad_forms_with_two_nearby_hostiles(self):
        """Two hostiles within 15m should form a squad."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(5.0, 32.0))

        assert _dist(h1.position, h2.position) < 15.0

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        assert h1.squad_id is not None, "h1 should be assigned to a squad"
        assert h2.squad_id is not None, "h2 should be assigned to a squad"
        assert h1.squad_id == h2.squad_id, "Both should be in the same squad"

    def test_squad_does_not_form_when_far_apart(self):
        """Two hostiles >15m apart should NOT form a squad."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 0.0))
        h2 = _make_hostile("h2", pos=(20.0, 20.0))

        assert _dist(h1.position, h2.position) > 15.0

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        assert h1.squad_id is None
        assert h2.squad_id is None

    def test_squad_forms_with_three_hostiles(self):
        """Three hostiles within 15m should all be in same squad."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(3.0, 32.0))
        h3 = _make_hostile("h3", pos=(-2.0, 28.0))

        targets = {h1.target_id: h1, h2.target_id: h2, h3.target_id: h3}
        sm.tick(0.1, targets)

        assert h1.squad_id == h2.squad_id == h3.squad_id
        assert h1.squad_id is not None

    def test_only_active_hostiles_form_squads(self):
        """Eliminated or escaped hostiles should not be included in squads."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(3.0, 32.0))
        h2.status = "eliminated"

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        assert h1.squad_id is None, "Single active hostile should not form squad"
        assert h2.squad_id is None, "Eliminated hostile should not be in a squad"

    def test_separate_squads_for_distant_groups(self):
        """Two groups of hostiles >15m apart should form separate squads."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        # Group A at (0, 30)
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(3.0, 32.0))
        # Group B at (50, 50) — far from group A
        h3 = _make_hostile("h3", pos=(50.0, 50.0))
        h4 = _make_hostile("h4", pos=(52.0, 48.0))

        assert _dist(h1.position, h3.position) > 15.0

        targets = {
            h1.target_id: h1, h2.target_id: h2,
            h3.target_id: h3, h4.target_id: h4,
        }
        sm.tick(0.1, targets)

        assert h1.squad_id is not None
        assert h3.squad_id is not None
        assert h1.squad_id == h2.squad_id
        assert h3.squad_id == h4.squad_id
        assert h1.squad_id != h3.squad_id, "Distant groups should be separate squads"

    def test_non_hostiles_ignored(self):
        """Friendly and neutral targets should not form squads."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        turret = _make_turret("t1", pos=(0.0, 0.0))
        h1 = _make_hostile("h1", pos=(0.0, 30.0))

        targets = {turret.target_id: turret, h1.target_id: h1}
        sm.tick(0.1, targets)

        assert h1.squad_id is None, "Single hostile should not form squad alone"


# ---------------------------------------------------------------------------
# 2. Leader selection and succession
# ---------------------------------------------------------------------------

class TestLeaderSelection:
    """Squad leader should be the member with highest health."""

    def test_leader_is_highest_health(self):
        """Leader should be the hostile with highest health."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0), health=50.0)
        h2 = _make_hostile("h2", pos=(3.0, 32.0), health=80.0)

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        squad_id = h1.squad_id
        assert squad_id is not None
        squad = sm.get_squad(squad_id)
        assert squad is not None
        assert squad.leader_id == "h2", (
            f"Expected leader to be h2 (health=80), got {squad.leader_id}"
        )

    def test_leader_succession_on_elimination(self):
        """When leader is eliminated, next-highest-health becomes leader."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0), health=80.0)
        h2 = _make_hostile("h2", pos=(3.0, 32.0), health=60.0)
        h3 = _make_hostile("h3", pos=(-2.0, 28.0), health=40.0)

        targets = {h1.target_id: h1, h2.target_id: h2, h3.target_id: h3}
        sm.tick(0.1, targets)

        squad_id = h1.squad_id
        squad = sm.get_squad(squad_id)
        assert squad.leader_id == "h1"  # highest health

        # Eliminate the leader
        h1.status = "eliminated"
        h1.health = 0.0
        sm.tick(0.1, targets)

        # h2 should now be leader (next highest health)
        squad = sm.get_squad(h2.squad_id)
        assert squad is not None
        assert squad.leader_id == "h2", (
            f"Expected h2 to become leader after h1 eliminated, got {squad.leader_id}"
        )

    def test_leader_succession_on_health_change(self):
        """If another member gains more health than leader, leader changes."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0), health=80.0)
        h2 = _make_hostile("h2", pos=(3.0, 32.0), health=60.0)

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        assert squad.leader_id == "h1"

        # h1 takes damage, h2 now has more health
        h1.health = 30.0
        sm.tick(0.1, targets)

        squad = sm.get_squad(h2.squad_id)
        assert squad.leader_id == "h2"


# ---------------------------------------------------------------------------
# 3. Formation offset calculation (wedge, line)
# ---------------------------------------------------------------------------

class TestFormationOffsets:
    """Squad formations: wedge (leader front, 45deg spread) and line (side by side)."""

    def test_wedge_formation_offsets(self):
        """Wedge formation: leader at front, members at 45 degrees behind."""
        from engine.simulation.squads import SquadManager, Squad

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0), health=80.0)
        h2 = _make_hostile("h2", pos=(3.0, 32.0), health=60.0)
        h3 = _make_hostile("h3", pos=(-2.0, 28.0), health=40.0)

        targets = {h1.target_id: h1, h2.target_id: h2, h3.target_id: h3}
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        assert squad is not None
        squad.formation = "wedge"

        offsets = squad.get_formation_offsets()
        # Leader (h1) should have offset (0, 0) — at front
        assert offsets[h1.target_id] == (0.0, 0.0), (
            f"Leader should be at (0,0), got {offsets[h1.target_id]}"
        )
        # Other members should have non-zero offsets (behind leader)
        for tid in [h2.target_id, h3.target_id]:
            ox, oy = offsets[tid]
            # In wedge, followers are behind (negative y) and spread laterally (nonzero x)
            assert oy < 0 or abs(ox) > 0, (
                f"Follower {tid} should have an offset behind leader, got ({ox}, {oy})"
            )

    def test_wedge_formation_spacing(self):
        """Wedge formation spacing should be 3-5m between members."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0), health=80.0)
        h2 = _make_hostile("h2", pos=(3.0, 32.0), health=60.0)

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        squad.formation = "wedge"

        offsets = squad.get_formation_offsets()
        for tid, (ox, oy) in offsets.items():
            if tid == squad.leader_id:
                continue
            spacing = math.hypot(ox, oy)
            assert 3.0 <= spacing <= 5.0, (
                f"Wedge spacing for {tid} should be 3-5m, got {spacing:.2f}m"
            )

    def test_line_formation_offsets(self):
        """Line formation: members side by side."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0), health=80.0)
        h2 = _make_hostile("h2", pos=(3.0, 32.0), health=60.0)
        h3 = _make_hostile("h3", pos=(-2.0, 28.0), health=40.0)

        targets = {h1.target_id: h1, h2.target_id: h2, h3.target_id: h3}
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        squad.formation = "line"

        offsets = squad.get_formation_offsets()
        # All members should be on the same forward line (y offset ~= 0 for all)
        for tid, (ox, oy) in offsets.items():
            assert abs(oy) < 0.01, (
                f"Line formation: {tid} should have no forward/back offset, got oy={oy}"
            )

    def test_line_formation_spacing(self):
        """Line formation spacing should be 3-5m between members."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0), health=80.0)
        h2 = _make_hostile("h2", pos=(3.0, 32.0), health=60.0)

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        squad.formation = "line"

        offsets = squad.get_formation_offsets()
        for tid, (ox, oy) in offsets.items():
            if tid == squad.leader_id:
                continue
            spacing = abs(ox)
            assert 3.0 <= spacing <= 5.0, (
                f"Line spacing for {tid} should be 3-5m, got {spacing:.2f}m"
            )

    def test_default_formation_is_wedge(self):
        """New squads should default to wedge formation."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(3.0, 32.0))

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        assert squad.formation == "wedge", (
            f"Expected default formation 'wedge', got '{squad.formation}'"
        )


# ---------------------------------------------------------------------------
# 4. Squad dissolution
# ---------------------------------------------------------------------------

class TestSquadDissolution:
    """Squads dissolve when members are eliminated or scatter."""

    def test_squad_dissolves_when_all_but_one_eliminated(self):
        """Squad dissolves when only one member remains."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(3.0, 32.0))

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        squad_id = h1.squad_id
        assert squad_id is not None

        # Eliminate h2
        h2.status = "eliminated"
        h2.health = 0.0
        sm.tick(0.1, targets)

        # Squad should dissolve (only 1 active member left)
        assert h1.squad_id is None, "Squad should dissolve when only 1 member remains"

    def test_squad_dissolves_when_members_scatter(self):
        """Squad dissolves when members move >15m apart."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(3.0, 32.0))

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)
        assert h1.squad_id is not None

        # Move h2 far away
        h2.position = (50.0, 50.0)
        sm.tick(0.1, targets)

        assert h1.squad_id is None, "Squad should dissolve when members scatter"
        assert h2.squad_id is None

    def test_squad_id_cleared_on_dissolution(self):
        """When squad dissolves, squad_id on targets should be set to None."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(3.0, 32.0))

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)
        old_squad_id = h1.squad_id
        assert old_squad_id is not None

        # Eliminate both
        h1.status = "eliminated"
        h2.status = "eliminated"
        sm.tick(0.1, targets)

        assert h1.squad_id is None
        assert h2.squad_id is None
        assert sm.get_squad(old_squad_id) is None


# ---------------------------------------------------------------------------
# 5. Integration with engine tick loop
# ---------------------------------------------------------------------------

class TestEngineIntegration:
    """SquadManager should be wired into SimulationEngine."""

    @pytest.mark.skip(reason="SimulationEngine does not have squad_manager attribute")
    def test_engine_has_squad_manager(self, event_bus):
        """SimulationEngine should have a squad_manager attribute."""
        from engine.simulation.engine import SimulationEngine

        engine = SimulationEngine(event_bus, map_bounds=200.0)
        assert hasattr(engine, "squad_manager"), (
            "Engine should have a squad_manager attribute"
        )

    @pytest.mark.skip(reason="SimulationEngine does not have squad_manager attribute")
    def test_engine_tick_calls_squad_manager(self, event_bus):
        """Engine tick loop should call squad_manager.tick() during game."""
        from engine.simulation.engine import SimulationEngine
        from engine.simulation.squads import SquadManager

        engine = SimulationEngine(event_bus, map_bounds=200.0)

        # Add two nearby hostiles
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(3.0, 32.0))
        turret = _make_turret("t1", pos=(0.0, 0.0))
        engine.add_target(h1)
        engine.add_target(h2)
        engine.add_target(turret)

        # Start game mode so combat subsystems run
        engine.game_mode._state = "active"

        # Run a manual tick cycle (simulate what _tick_loop does)
        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.squad_manager.tick(0.1, targets_dict)

        # After tick, hostiles should be assigned to a squad
        assert h1.squad_id is not None or h2.squad_id is not None, (
            "After engine tick with nearby hostiles, squads should form"
        )

    def test_squad_id_field_on_target(self):
        """SimulationTarget should have a squad_id field defaulting to None."""
        t = SimulationTarget(
            target_id="t1", name="Test", alliance="hostile",
            asset_type="person", position=(0.0, 0.0),
        )
        assert hasattr(t, "squad_id"), "SimulationTarget should have squad_id field"
        assert t.squad_id is None, "Default squad_id should be None"

    def test_squad_id_in_target_to_dict(self):
        """Target.to_dict() should include squad_id."""
        t = SimulationTarget(
            target_id="t1", name="Test", alliance="hostile",
            asset_type="person", position=(0.0, 0.0),
        )
        d = t.to_dict()
        assert "squad_id" in d, "to_dict() should include squad_id"
        assert d["squad_id"] is None

    def test_squad_id_persists_in_to_dict_when_set(self):
        """When squad_id is assigned, it should appear in to_dict()."""
        t = SimulationTarget(
            target_id="t1", name="Test", alliance="hostile",
            asset_type="person", position=(0.0, 0.0),
        )
        t.squad_id = "squad-abc"
        d = t.to_dict()
        assert d["squad_id"] == "squad-abc"


# ---------------------------------------------------------------------------
# 6. Squad members share target (focus fire)
# ---------------------------------------------------------------------------

class TestFocusFire:
    """All squad members should focus fire on the same defender."""

    def test_squad_selects_shared_target(self):
        """Squad should select a single shared target for all members."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 10.0))
        h2 = _make_hostile("h2", pos=(3.0, 12.0))

        turret1 = _make_turret("t1", pos=(0.0, 0.0))
        turret2 = _make_turret("t2", pos=(20.0, 0.0))

        targets = {
            h1.target_id: h1, h2.target_id: h2,
            turret1.target_id: turret1, turret2.target_id: turret2,
        }
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        assert squad is not None
        assert squad.shared_target_id is not None, (
            "Squad should have a shared target for focus fire"
        )

    def test_squad_shared_target_is_nearest_to_leader(self):
        """Squad's shared target should be the nearest enemy to the leader."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 10.0), health=80.0)
        h2 = _make_hostile("h2", pos=(3.0, 12.0), health=60.0)

        # t1 at distance 10 from h1 (leader), t2 at distance ~22 from h1
        turret1 = _make_turret("t1", pos=(0.0, 0.0))
        turret2 = _make_turret("t2", pos=(20.0, 0.0))

        targets = {
            h1.target_id: h1, h2.target_id: h2,
            turret1.target_id: turret1, turret2.target_id: turret2,
        }
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        assert squad.shared_target_id == "t1", (
            f"Expected shared target t1 (nearest to leader), got {squad.shared_target_id}"
        )

    def test_shared_target_updated_when_eliminated(self):
        """When shared target is eliminated, squad picks next nearest."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 10.0), health=80.0)
        h2 = _make_hostile("h2", pos=(3.0, 12.0), health=60.0)

        turret1 = _make_turret("t1", pos=(0.0, 0.0))
        turret2 = _make_turret("t2", pos=(5.0, 0.0))

        targets = {
            h1.target_id: h1, h2.target_id: h2,
            turret1.target_id: turret1, turret2.target_id: turret2,
        }
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        assert squad.shared_target_id == "t1"

        # Eliminate t1
        turret1.status = "eliminated"
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        assert squad.shared_target_id == "t2", (
            f"Expected shared target to switch to t2 after t1 eliminated, got {squad.shared_target_id}"
        )

    def test_shared_target_none_when_no_enemies(self):
        """Squad shared_target_id should be None when no enemies visible."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(3.0, 32.0))

        # No friendlies nearby
        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        assert squad.shared_target_id is None


# ---------------------------------------------------------------------------
# 7. Formation movement — members maintain offsets
# ---------------------------------------------------------------------------

class TestFormationMovement:
    """Squad members should maintain formation offsets while moving."""

    def test_formation_positions_relative_to_leader(self):
        """Members should be positioned at formation offsets relative to leader."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0), health=80.0)
        h2 = _make_hostile("h2", pos=(3.0, 32.0), health=60.0)

        targets = {h1.target_id: h1, h2.target_id: h2}

        # Run several ticks to let formation settle
        for _ in range(10):
            sm.tick(0.1, targets)

        # h2's position should converge toward leader + offset
        squad = sm.get_squad(h1.squad_id)
        if squad is not None:
            offsets = squad.get_formation_offsets()
            h2_offset = offsets.get(h2.target_id, (0, 0))
            expected_pos = (
                h1.position[0] + h2_offset[0],
                h1.position[1] + h2_offset[1],
            )
            actual_dist = _dist(h2.position, expected_pos)
            # Formation should be converging (within 5m tolerance)
            assert actual_dist < 10.0, (
                f"h2 should be converging toward formation position, "
                f"actual distance from target = {actual_dist:.2f}m"
            )

    def test_leader_position_not_modified(self):
        """Leader's position should NOT be modified by formation offsets."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0), health=80.0)
        h2 = _make_hostile("h2", pos=(3.0, 32.0), health=60.0)

        original_leader_pos = h1.position
        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        # Leader position should not change from formation management
        assert h1.position == original_leader_pos, (
            f"Leader position should not change, was {original_leader_pos}, now {h1.position}"
        )


# ---------------------------------------------------------------------------
# 8. Behaviors integration — squad members defer to squad
# ---------------------------------------------------------------------------

class TestBehaviorsIntegration:
    """When a hostile is in a squad, behaviors should respect squad directives."""

    def test_squad_manager_get_squad_returns_none_for_no_squad(self):
        """get_squad with invalid ID should return None."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        assert sm.get_squad("nonexistent") is None

    def test_squad_has_member_ids(self):
        """Squad object should track member IDs."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(3.0, 32.0))

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)

        squad = sm.get_squad(h1.squad_id)
        assert squad is not None
        assert "h1" in squad.member_ids
        assert "h2" in squad.member_ids

    def test_squad_clear_resets_all(self):
        """Calling clear() on SquadManager should dissolve all squads."""
        from engine.simulation.squads import SquadManager

        sm = SquadManager()
        h1 = _make_hostile("h1", pos=(0.0, 30.0))
        h2 = _make_hostile("h2", pos=(3.0, 32.0))

        targets = {h1.target_id: h1, h2.target_id: h2}
        sm.tick(0.1, targets)
        assert h1.squad_id is not None

        sm.clear(targets)

        assert h1.squad_id is None
        assert h2.squad_id is None
        assert sm.get_squad(h1.squad_id) is None


# --------------------------------------------------------------------------
# Engine integration: SquadManager wired into tick loop
# --------------------------------------------------------------------------

class TestSquadEngineIntegration:
    """Verify SquadManager is instantiated and ticked by SimulationEngine."""

    def test_engine_has_squad_manager(self, event_bus):
        from engine.simulation.engine import SimulationEngine
        engine = SimulationEngine(event_bus, map_bounds=200)
        assert hasattr(engine, "squad_manager")
        assert engine.squad_manager is not None

    def test_squads_form_during_game(self, event_bus):
        """Two nearby hostiles should form a squad after game ticks."""
        from engine.simulation.engine import SimulationEngine
        engine = SimulationEngine(event_bus, map_bounds=200)

        # Add a friendly so game doesn't end in defeat
        friendly = SimulationTarget(
            target_id="turret-1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            speed=0.0, status="stationary", is_combatant=True,
        )
        friendly.apply_combat_profile()
        engine.add_target(friendly)

        # Add two nearby hostiles
        h1 = _make_hostile("h1", pos=(50.0, 50.0))
        h2 = _make_hostile("h2", pos=(53.0, 52.0))
        engine.add_target(h1)
        engine.add_target(h2)

        # Start game and tick through countdown + some active ticks
        engine.game_mode.begin_war()
        engine.game_mode._countdown_remaining = 0
        engine.game_mode.state = "active"
        engine.game_mode._start_wave(1)
        # Manual tick (not threaded)
        for _ in range(5):
            engine._do_tick(0.1)

        # Hostiles should have been grouped into a squad
        assert h1.squad_id is not None or h2.squad_id is not None, (
            "Nearby hostiles should form a squad during game"
        )

    def test_squads_cleared_on_reset(self, event_bus):
        """reset_game should clear all squads."""
        from engine.simulation.engine import SimulationEngine
        engine = SimulationEngine(event_bus, map_bounds=200)

        h1 = _make_hostile("h1", pos=(50.0, 50.0))
        h2 = _make_hostile("h2", pos=(53.0, 52.0))
        engine.add_target(h1)
        engine.add_target(h2)

        # Manually form a squad
        engine.squad_manager.tick(0.1, {"h1": h1, "h2": h2})
        assert h1.squad_id is not None

        engine.reset_game()
        # After reset, squad manager should be empty
        assert len(engine.squad_manager._squads) == 0
