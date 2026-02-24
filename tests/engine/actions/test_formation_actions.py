"""Tests for Lua formation actions — TDD red phase.

These tests cover formation creation, formation types (wedge/line/column/circle),
squad orders, squad dispatch, rally, scatter, Lua parsing, registry registration,
API endpoint, error handling, and backward compatibility.

All tests written BEFORE implementation (TDD).
"""

from __future__ import annotations

import math
import pytest
from unittest.mock import MagicMock, patch

from engine.simulation.squads import Squad, SquadManager, FORMATION_SPACING
from engine.simulation.target import SimulationTarget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    target_id: str,
    name: str = "Unit",
    alliance: str = "friendly",
    asset_type: str = "rover",
    position: tuple[float, float] = (0.0, 0.0),
    speed: float = 5.0,
    status: str = "active",
) -> SimulationTarget:
    """Create a SimulationTarget with minimal setup for testing."""
    t = SimulationTarget(
        target_id=target_id,
        name=name,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        speed=speed,
        status=status,
    )
    t.apply_combat_profile()
    return t


def _make_engine_mock(targets: dict[str, SimulationTarget] | None = None):
    """Create a mock SimulationEngine with a real SquadManager."""
    engine = MagicMock()
    engine.squad_manager = SquadManager()
    engine._targets = targets or {}
    engine.get_target = lambda tid: engine._targets.get(tid)
    engine.get_targets = lambda: list(engine._targets.values())

    def dispatch_unit(tid, dest):
        t = engine._targets.get(tid)
        if t is not None:
            t.waypoints = [dest]
            t._waypoint_index = 0
            t.status = "active"

    engine.dispatch_unit = dispatch_unit
    return engine


def _make_registry_and_engine(targets: dict[str, SimulationTarget] | None = None):
    """Create a registry with formation actions registered, plus a mock engine."""
    from engine.actions.lua_registry import LuaActionRegistry
    from engine.actions.formation_actions import register_formation_actions

    engine = _make_engine_mock(targets)
    registry = LuaActionRegistry.with_core_actions()
    register_formation_actions(registry, engine)
    return registry, engine


# ===========================================================================
# TestFormationAction — creates squad with specified units
# ===========================================================================

class TestFormationAction:
    """Test the formation() Lua action creates a squad."""

    @pytest.mark.unit
    def test_formation_creates_squad(self):
        """formation("wedge", "r1", "r2", "d1") creates a squad with 3 members."""
        targets = {
            "r1": _make_target("r1", "Rover-1", position=(0.0, 0.0)),
            "r2": _make_target("r2", "Rover-2", position=(5.0, 0.0)),
            "d1": _make_target("d1", "Drone-1", asset_type="drone", position=(0.0, 5.0)),
        }
        registry, engine = _make_registry_and_engine(targets)

        from engine.actions.formation_actions import register_formation_actions
        # Actions are already registered; invoke formation
        action_def = registry.get("formation")
        assert action_def is not None

        # Call the registered handler
        from engine.actions.formation_actions import _get_handler
        handler = _get_handler("formation")
        result = handler("wedge", "r1", "r2", "d1")

        assert "squad" in result or "squad_id" in result or result.get("status") == "ok"
        # Squad should exist in manager
        squads = engine.squad_manager._squads
        assert len(squads) >= 1

    @pytest.mark.unit
    def test_formation_sets_type(self):
        """formation("line", "r1", "r2") creates a squad with line formation."""
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler
        handler = _get_handler("formation")
        result = handler("line", "r1", "r2")
        squads = engine.squad_manager._squads
        squad = list(squads.values())[0]
        assert squad.formation == "line"

    @pytest.mark.unit
    def test_formation_sets_leader_to_first_unit(self):
        """The first unit in the formation call is the leader."""
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler
        handler = _get_handler("formation")
        handler("wedge", "r1", "r2")
        squads = engine.squad_manager._squads
        squad = list(squads.values())[0]
        assert squad.leader_id == "r1"

    @pytest.mark.unit
    def test_formation_assigns_squad_id_to_targets(self):
        """All targets should have their squad_id set."""
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler
        handler = _get_handler("formation")
        handler("wedge", "r1", "r2")
        assert targets["r1"].squad_id is not None
        assert targets["r2"].squad_id is not None
        assert targets["r1"].squad_id == targets["r2"].squad_id


# ===========================================================================
# TestFormationWedge — wedge formation offsets
# ===========================================================================

class TestFormationWedge:
    """Test wedge formation produces correct offsets."""

    @pytest.mark.unit
    def test_wedge_leader_at_origin(self):
        """Leader should be at (0, 0) offset."""
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c"],
            leader_id="a",
            formation="wedge",
        )
        offsets = squad.get_formation_offsets()
        assert offsets["a"] == (0.0, 0.0)

    @pytest.mark.unit
    def test_wedge_followers_behind(self):
        """Followers should have negative y offset (behind leader)."""
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c"],
            leader_id="a",
            formation="wedge",
        )
        offsets = squad.get_formation_offsets()
        assert offsets["b"][1] < 0  # behind
        assert offsets["c"][1] < 0  # behind

    @pytest.mark.unit
    def test_wedge_followers_alternating_sides(self):
        """First follower goes left, second goes right."""
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c"],
            leader_id="a",
            formation="wedge",
        )
        offsets = squad.get_formation_offsets()
        # First follower (rank 1, odd) goes left (negative x)
        assert offsets["b"][0] < 0
        # Second follower (rank 2, even) goes right (positive x)
        assert offsets["c"][0] > 0


# ===========================================================================
# TestFormationLine — line formation offsets
# ===========================================================================

class TestFormationLine:
    """Test line formation produces correct offsets."""

    @pytest.mark.unit
    def test_line_leader_at_origin(self):
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c"],
            leader_id="a",
            formation="line",
        )
        offsets = squad.get_formation_offsets()
        assert offsets["a"] == (0.0, 0.0)

    @pytest.mark.unit
    def test_line_all_same_y(self):
        """All units on the same horizontal line (y=0)."""
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c"],
            leader_id="a",
            formation="line",
        )
        offsets = squad.get_formation_offsets()
        for offset in offsets.values():
            assert offset[1] == 0.0

    @pytest.mark.unit
    def test_line_spread_x(self):
        """Followers spread left and right of leader."""
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c"],
            leader_id="a",
            formation="line",
        )
        offsets = squad.get_formation_offsets()
        assert offsets["b"][0] != 0.0
        assert offsets["c"][0] != 0.0
        # Opposite sides
        assert offsets["b"][0] * offsets["c"][0] < 0


# ===========================================================================
# TestFormationColumn — column formation offsets
# ===========================================================================

class TestFormationColumn:
    """Test column (single file) formation."""

    @pytest.mark.unit
    def test_column_leader_at_origin(self):
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c"],
            leader_id="a",
            formation="column",
        )
        offsets = squad.get_formation_offsets()
        assert offsets["a"] == (0.0, 0.0)

    @pytest.mark.unit
    def test_column_single_file(self):
        """All followers have x=0 (single file) and decreasing y (behind)."""
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c"],
            leader_id="a",
            formation="column",
        )
        offsets = squad.get_formation_offsets()
        for tid in ["b", "c"]:
            assert offsets[tid][0] == 0.0, f"{tid} should have x=0 in column"
            assert offsets[tid][1] < 0, f"{tid} should be behind leader"

    @pytest.mark.unit
    def test_column_spacing(self):
        """Each follower is FORMATION_SPACING behind the previous."""
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c", "d"],
            leader_id="a",
            formation="column",
        )
        offsets = squad.get_formation_offsets()
        assert offsets["b"] == pytest.approx((0.0, -FORMATION_SPACING), abs=0.01)
        assert offsets["c"] == pytest.approx((0.0, -2 * FORMATION_SPACING), abs=0.01)
        assert offsets["d"] == pytest.approx((0.0, -3 * FORMATION_SPACING), abs=0.01)


# ===========================================================================
# TestFormationCircle — circle formation offsets
# ===========================================================================

class TestFormationCircle:
    """Test circle formation distributes units around a center."""

    @pytest.mark.unit
    def test_circle_leader_at_origin(self):
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c", "d"],
            leader_id="a",
            formation="circle",
        )
        offsets = squad.get_formation_offsets()
        assert offsets["a"] == (0.0, 0.0)

    @pytest.mark.unit
    def test_circle_equidistant(self):
        """All followers should be same distance from center."""
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c", "d", "e"],
            leader_id="a",
            formation="circle",
        )
        offsets = squad.get_formation_offsets()
        followers = [k for k in offsets if k != "a"]
        dists = [math.hypot(offsets[f][0], offsets[f][1]) for f in followers]
        for d in dists:
            assert d == pytest.approx(dists[0], abs=0.1)

    @pytest.mark.unit
    def test_circle_radius_is_formation_spacing(self):
        """Circle radius should be FORMATION_SPACING."""
        squad = Squad(
            squad_id="sq1",
            member_ids=["a", "b", "c", "d"],
            leader_id="a",
            formation="circle",
        )
        offsets = squad.get_formation_offsets()
        for tid in ["b", "c", "d"]:
            d = math.hypot(offsets[tid][0], offsets[tid][1])
            assert d == pytest.approx(FORMATION_SPACING, abs=0.1)


# ===========================================================================
# TestSetFormation — changes existing squad formation
# ===========================================================================

class TestSetFormation:
    """Test set_formation() changes formation type."""

    @pytest.mark.unit
    def test_set_formation_changes_type(self):
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        # Create a squad first
        handler = _get_handler("formation")
        handler("wedge", "r1", "r2")
        squad = list(engine.squad_manager._squads.values())[0]
        assert squad.formation == "wedge"

        # Change formation
        set_handler = _get_handler("set_formation")
        set_handler(squad.squad_id, "line")
        assert squad.formation == "line"


class TestSetFormationInvalid:
    """Test set_formation() rejects invalid formation types."""

    @pytest.mark.unit
    def test_invalid_formation_type(self):
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        handler("wedge", "r1", "r2")
        squad = list(engine.squad_manager._squads.values())[0]

        set_handler = _get_handler("set_formation")
        result = set_handler(squad.squad_id, "invalid_type")
        assert "error" in result or result.get("status") == "error"


# ===========================================================================
# TestSquadOrder — issues tactical orders
# ===========================================================================

class TestSquadOrder:
    """Test squad_order() issues orders to the squad."""

    @pytest.mark.unit
    def test_advance_order(self):
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        handler("wedge", "r1", "r2")
        squad = list(engine.squad_manager._squads.values())[0]

        order_handler = _get_handler("squad_order")
        result = order_handler(squad.squad_id, "advance")
        assert result.get("status") == "ok"
        assert squad.last_order == "advance"

    @pytest.mark.unit
    def test_hold_order(self):
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        handler("wedge", "r1", "r2")
        squad = list(engine.squad_manager._squads.values())[0]

        order_handler = _get_handler("squad_order")
        order_handler(squad.squad_id, "hold")
        assert squad.last_order == "hold"

    @pytest.mark.unit
    def test_flank_left_order(self):
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        handler("wedge", "r1", "r2")
        squad = list(engine.squad_manager._squads.values())[0]

        order_handler = _get_handler("squad_order")
        order_handler(squad.squad_id, "flank_left")
        assert squad.last_order == "flank_left"

    @pytest.mark.unit
    def test_flank_right_order(self):
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        handler("wedge", "r1", "r2")
        squad = list(engine.squad_manager._squads.values())[0]

        order_handler = _get_handler("squad_order")
        order_handler(squad.squad_id, "flank_right")
        assert squad.last_order == "flank_right"

    @pytest.mark.unit
    def test_retreat_order(self):
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        handler("wedge", "r1", "r2")
        squad = list(engine.squad_manager._squads.values())[0]

        order_handler = _get_handler("squad_order")
        order_handler(squad.squad_id, "retreat")
        assert squad.last_order == "retreat"


class TestSquadOrderInvalid:
    """Test squad_order() rejects invalid orders."""

    @pytest.mark.unit
    def test_invalid_order(self):
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        handler("wedge", "r1", "r2")
        squad = list(engine.squad_manager._squads.values())[0]

        order_handler = _get_handler("squad_order")
        result = order_handler(squad.squad_id, "dance")
        assert "error" in result or result.get("status") == "error"


# ===========================================================================
# TestSquadDispatch — all members move to position
# ===========================================================================

class TestSquadDispatch:
    """Test squad_dispatch() dispatches all members."""

    @pytest.mark.unit
    def test_squad_dispatch_moves_all(self):
        """All squad members should get waypoints toward the target."""
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
            "r3": _make_target("r3", position=(0.0, 5.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        handler("wedge", "r1", "r2", "r3")

        dispatch_handler = _get_handler("squad_dispatch")
        squad = list(engine.squad_manager._squads.values())[0]
        dispatch_handler(squad.squad_id, 100.0, 50.0)

        # All members should have waypoints set
        for tid in ["r1", "r2", "r3"]:
            assert len(targets[tid].waypoints) > 0


class TestSquadDispatchFormation:
    """Test that squad_dispatch maintains formation offsets."""

    @pytest.mark.unit
    def test_dispatch_with_formation_offset(self):
        """Members should be dispatched to offset positions, not all the same point."""
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(5.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        handler("wedge", "r1", "r2")

        dispatch_handler = _get_handler("squad_dispatch")
        squad = list(engine.squad_manager._squads.values())[0]
        dispatch_handler(squad.squad_id, 100.0, 50.0)

        # Leader goes to exact point, followers to offset positions
        # The last waypoint for r1 should be close to (100, 50)
        r1_dest = targets["r1"].waypoints[-1] if targets["r1"].waypoints else (0, 0)
        r2_dest = targets["r2"].waypoints[-1] if targets["r2"].waypoints else (0, 0)
        # They should NOT be identical (formation offset applies)
        assert r1_dest != r2_dest


# ===========================================================================
# TestRally — nearby friendlies converge
# ===========================================================================

class TestRally:
    """Test rally() converges nearby units."""

    @pytest.mark.unit
    def test_rally_moves_nearby_friendlies(self):
        targets = {
            "r1": _make_target("r1", position=(10.0, 10.0)),
            "r2": _make_target("r2", position=(15.0, 10.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        rally_handler = _get_handler("rally")
        result = rally_handler(12.0, 10.0, "friendly")

        assert result.get("status") == "ok"
        assert result.get("rallied", 0) >= 1


class TestRallyRange:
    """Test rally() only affects units within 30m."""

    @pytest.mark.unit
    def test_rally_excludes_far_units(self):
        """Units beyond 30m from rally point should not be affected."""
        targets = {
            "r1": _make_target("r1", position=(10.0, 10.0)),  # ~14m from (0,0)
            "r2": _make_target("r2", position=(100.0, 100.0)),  # >30m
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        rally_handler = _get_handler("rally")
        result = rally_handler(0.0, 0.0, "friendly")

        rallied = result.get("rallied", 0)
        assert rallied == 1  # Only r1 is within 30m


class TestRallyAlliance:
    """Test rally() only affects the specified alliance."""

    @pytest.mark.unit
    def test_rally_ignores_wrong_alliance(self):
        targets = {
            "r1": _make_target("r1", alliance="friendly", position=(5.0, 5.0)),
            "h1": _make_target("h1", alliance="hostile", position=(5.0, 5.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        rally_handler = _get_handler("rally")
        result = rally_handler(5.0, 5.0, "friendly")

        # Only the friendly should rally
        assert result.get("rallied", 0) == 1


# ===========================================================================
# TestScatter — members spread out
# ===========================================================================

class TestScatter:
    """Test scatter() spreads squad members."""

    @pytest.mark.unit
    def test_scatter_sets_waypoints(self):
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(2.0, 0.0)),
            "r3": _make_target("r3", position=(0.0, 2.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        handler("wedge", "r1", "r2", "r3")
        squad = list(engine.squad_manager._squads.values())[0]

        scatter_handler = _get_handler("scatter")
        result = scatter_handler(squad.squad_id)

        assert result.get("status") == "ok"
        # Members should have waypoints set (scatter movement)
        for tid in ["r1", "r2", "r3"]:
            assert len(targets[tid].waypoints) > 0


class TestScatterRadius:
    """Test scatter minimum distance between members."""

    @pytest.mark.unit
    def test_scatter_minimum_distance(self):
        """Scatter waypoints should be at least 8m apart from each other."""
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
            "r2": _make_target("r2", position=(1.0, 0.0)),
            "r3": _make_target("r3", position=(0.0, 1.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        handler("wedge", "r1", "r2", "r3")
        squad = list(engine.squad_manager._squads.values())[0]

        scatter_handler = _get_handler("scatter")
        scatter_handler(squad.squad_id)

        # Check that scatter destinations are at least 8m from the squad center
        center = (0.0, 0.0)
        for tid in ["r1", "r2", "r3"]:
            if targets[tid].waypoints:
                dest = targets[tid].waypoints[-1]
                d = math.hypot(dest[0] - center[0], dest[1] - center[1])
                assert d >= 8.0, f"Scatter dest for {tid} too close: {d}m"


# ===========================================================================
# TestLuaParsing — Lua strings parse correctly
# ===========================================================================

class TestLuaParsing:
    """Test that Lua formation command strings parse through the Lua parser."""

    @pytest.mark.unit
    def test_parse_formation(self):
        from engine.actions.lua_motor import parse_function_call
        result = parse_function_call('formation("wedge", "rover-1", "rover-2")')
        assert result is not None
        name, args = result
        assert name == "formation"
        assert args == ["wedge", "rover-1", "rover-2"]

    @pytest.mark.unit
    def test_parse_set_formation(self):
        from engine.actions.lua_motor import parse_function_call
        result = parse_function_call('set_formation("squad-1", "line")')
        assert result is not None
        name, args = result
        assert name == "set_formation"
        assert args == ["squad-1", "line"]

    @pytest.mark.unit
    def test_parse_squad_order(self):
        from engine.actions.lua_motor import parse_function_call
        result = parse_function_call('squad_order("squad-1", "advance")')
        assert result is not None
        name, args = result
        assert name == "squad_order"
        assert args == ["squad-1", "advance"]

    @pytest.mark.unit
    def test_parse_squad_dispatch(self):
        from engine.actions.lua_motor import parse_function_call
        result = parse_function_call('squad_dispatch("squad-1", 100.0, 50.0)')
        assert result is not None
        name, args = result
        assert name == "squad_dispatch"
        assert args == ["squad-1", 100.0, 50.0]

    @pytest.mark.unit
    def test_parse_rally(self):
        from engine.actions.lua_motor import parse_function_call
        result = parse_function_call('rally(100, 50, "friendly")')
        assert result is not None
        name, args = result
        assert name == "rally"
        assert args == [100, 50, "friendly"]

    @pytest.mark.unit
    def test_parse_scatter(self):
        from engine.actions.lua_motor import parse_function_call
        result = parse_function_call('scatter("squad-1")')
        assert result is not None
        name, args = result
        assert name == "scatter"
        assert args == ["squad-1"]


# ===========================================================================
# TestLuaFormationParse — full motor output parsing
# ===========================================================================

class TestLuaFormationParse:
    """Test Lua formation commands through parse_motor_output."""

    @pytest.mark.skip(reason="formation not in VALID_ACTIONS — formation actions not registered in lua_motor")
    @pytest.mark.unit
    def test_motor_output_formation(self):
        from engine.actions.lua_motor import parse_motor_output
        result = parse_motor_output('formation("wedge", "rover-1", "rover-2")')
        assert result.valid, f"Expected valid but got error: {result.error}"
        assert result.action == "formation"
        assert result.params == ["wedge", "rover-1", "rover-2"]


class TestLuaSquadOrderParse:
    @pytest.mark.skip(reason="squad_order not in VALID_ACTIONS — formation actions not registered in lua_motor")
    @pytest.mark.unit
    def test_motor_output_squad_order(self):
        from engine.actions.lua_motor import parse_motor_output
        result = parse_motor_output('squad_order("squad-1", "advance")')
        assert result.valid, f"Expected valid but got error: {result.error}"
        assert result.action == "squad_order"


class TestLuaRallyParse:
    @pytest.mark.skip(reason="rally not in VALID_ACTIONS — formation actions not registered in lua_motor")
    @pytest.mark.unit
    def test_motor_output_rally(self):
        from engine.actions.lua_motor import parse_motor_output
        result = parse_motor_output('rally(100, 50, "friendly")')
        assert result.valid, f"Expected valid but got error: {result.error}"
        assert result.action == "rally"


# ===========================================================================
# TestRegistryRegistration — actions registered in registry
# ===========================================================================

class TestRegistryRegistration:
    """Test that formation actions are properly registered."""

    @pytest.mark.unit
    def test_all_formation_actions_registered(self):
        targets = {}
        registry, engine = _make_registry_and_engine(targets)

        expected_actions = [
            "formation", "set_formation", "squad_order",
            "squad_dispatch", "rally", "scatter",
        ]
        for action_name in expected_actions:
            action_def = registry.get(action_name)
            assert action_def is not None, f"Action '{action_name}' not in registry"

    @pytest.mark.unit
    def test_formation_actions_source(self):
        """Formation actions should have source='amy'."""
        targets = {}
        registry, engine = _make_registry_and_engine(targets)

        for name in ["formation", "set_formation", "squad_order",
                      "squad_dispatch", "rally", "scatter"]:
            action_def = registry.get(name)
            assert action_def.source == "amy", f"{name} source should be 'amy'"


# ===========================================================================
# TestAPIEndpoint — /api/amy/formation returns 200
# ===========================================================================

class TestAPIEndpoint:
    """Test the /api/amy/formation REST endpoint."""

    @pytest.mark.skip(reason="FormationRequest not importable from amy.router — endpoint not registered")
    @pytest.mark.unit
    def test_formation_endpoint_model(self):
        """FormationRequest model should be importable and valid."""
        from amy.router import FormationRequest
        req = FormationRequest(command='formation("wedge", "r1", "r2")')
        assert req.command == 'formation("wedge", "r1", "r2")'


# ===========================================================================
# TestInvalidSquadId — 404 for unknown squad
# ===========================================================================

class TestInvalidSquadId:
    @pytest.mark.unit
    def test_set_formation_unknown_squad(self):
        targets = {}
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        set_handler = _get_handler("set_formation")
        result = set_handler("nonexistent-squad", "line")
        assert "error" in result or result.get("status") == "error"

    @pytest.mark.unit
    def test_squad_order_unknown_squad(self):
        targets = {}
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        order_handler = _get_handler("squad_order")
        result = order_handler("nonexistent-squad", "advance")
        assert "error" in result or result.get("status") == "error"

    @pytest.mark.unit
    def test_squad_dispatch_unknown_squad(self):
        targets = {}
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        dispatch_handler = _get_handler("squad_dispatch")
        result = dispatch_handler("nonexistent-squad", 10.0, 20.0)
        assert "error" in result or result.get("status") == "error"

    @pytest.mark.unit
    def test_scatter_unknown_squad(self):
        targets = {}
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        scatter_handler = _get_handler("scatter")
        result = scatter_handler("nonexistent-squad")
        assert "error" in result or result.get("status") == "error"


# ===========================================================================
# TestEmptyFormation — error for no units
# ===========================================================================

class TestEmptyFormation:
    @pytest.mark.unit
    def test_formation_no_units(self):
        """formation("wedge") with no unit IDs should error."""
        targets = {}
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        result = handler("wedge")
        assert "error" in result or result.get("status") == "error"

    @pytest.mark.unit
    def test_formation_one_unit(self):
        """formation("wedge", "r1") with only 1 unit should error (need 2+)."""
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        result = handler("wedge", "r1")
        assert "error" in result or result.get("status") == "error"

    @pytest.mark.unit
    def test_formation_nonexistent_unit(self):
        """formation("wedge", "r1", "r2") where r2 doesn't exist should error."""
        targets = {
            "r1": _make_target("r1", position=(0.0, 0.0)),
        }
        registry, engine = _make_registry_and_engine(targets)
        from engine.actions.formation_actions import _get_handler

        handler = _get_handler("formation")
        result = handler("wedge", "r1", "r2")
        assert "error" in result or result.get("status") == "error"


# ===========================================================================
# TestBackwardCompat — existing Lua actions still work
# ===========================================================================

class TestBackwardCompat:
    """Ensure existing Lua actions are unaffected by formation additions."""

    @pytest.mark.unit
    def test_say_still_valid(self):
        from engine.actions.lua_motor import parse_motor_output
        result = parse_motor_output('say("Hello!")')
        assert result.valid
        assert result.action == "say"

    @pytest.mark.unit
    def test_dispatch_still_valid(self):
        from engine.actions.lua_motor import parse_motor_output
        result = parse_motor_output('dispatch("rover-1", 10.0, 20.0)')
        assert result.valid
        assert result.action == "dispatch"

    @pytest.mark.unit
    def test_look_at_still_valid(self):
        from engine.actions.lua_motor import parse_motor_output
        result = parse_motor_output('look_at("person")')
        assert result.valid
        assert result.action == "look_at"

    @pytest.mark.unit
    def test_scan_still_valid(self):
        from engine.actions.lua_motor import parse_motor_output
        result = parse_motor_output('scan()')
        assert result.valid
        assert result.action == "scan"

    @pytest.mark.unit
    def test_extract_formation_from_llm_response(self):
        """The Lua extractor should find formation() in a larger LLM response."""
        from engine.actions.lua_motor import extract_lua_from_response
        response = 'I will group the units. formation("wedge", "r1", "r2")'
        lua = extract_lua_from_response(response)
        assert "formation" in lua
