# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for PatrolManager — route CRUD, assignment, tick movement."""

import math
import pytest

from tritium_lib.tracking.patrol import PatrolManager, PatrolRoute
from engine.comms.event_bus import EventBus


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mgr(bus):
    return PatrolManager(event_bus=bus)


SQUARE_WAYPOINTS = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


# ------------------------------------------------------------------
# Route CRUD
# ------------------------------------------------------------------

class TestRouteCRUD:
    def test_create_route(self, mgr):
        rid = mgr.create_route("Perimeter", SQUARE_WAYPOINTS)
        assert rid is not None
        route = mgr.get_route(rid)
        assert route.name == "Perimeter"
        assert len(route.waypoints) == 4
        assert route.loop is True
        assert route.speed == 1.0

    def test_create_route_custom_params(self, mgr):
        rid = mgr.create_route("Fast", [(0, 0), (1, 1)], loop=False, speed=5.0)
        route = mgr.get_route(rid)
        assert route.loop is False
        assert route.speed == 5.0

    def test_list_routes(self, mgr):
        mgr.create_route("A", [(0, 0), (1, 1)])
        mgr.create_route("B", [(2, 2), (3, 3)])
        routes = mgr.list_routes()
        assert len(routes) == 2
        names = {r.name for r in routes}
        assert names == {"A", "B"}

    def test_remove_route(self, mgr):
        rid = mgr.create_route("Gone", [(0, 0), (1, 1)])
        assert mgr.remove_route(rid) is True
        assert mgr.get_route(rid) is None
        assert mgr.remove_route(rid) is False

    def test_remove_route_unassigns_assets(self, mgr):
        rid = mgr.create_route("Temp", [(0, 0), (10, 0)])
        mgr.assign_asset(rid, "asset-1")
        assert len(mgr.get_active_patrols()) == 1
        mgr.remove_route(rid)
        assert len(mgr.get_active_patrols()) == 0

    def test_route_to_dict(self):
        route = PatrolRoute(
            route_id="abc",
            name="Test",
            waypoints=[(1.0, 2.0), (3.0, 4.0)],
            loop=False,
            speed=2.5,
        )
        d = route.to_dict()
        assert d["route_id"] == "abc"
        assert d["waypoints"] == [[1.0, 2.0], [3.0, 4.0]]
        assert d["loop"] is False
        assert d["speed"] == 2.5


# ------------------------------------------------------------------
# Assignment
# ------------------------------------------------------------------

class TestAssignment:
    def test_assign_asset(self, mgr):
        rid = mgr.create_route("Route", SQUARE_WAYPOINTS)
        assert mgr.assign_asset(rid, "drone-1") is True
        patrols = mgr.get_active_patrols()
        assert len(patrols) == 1
        assert patrols[0].asset_id == "drone-1"
        assert patrols[0].route_id == rid

    def test_assign_invalid_route(self, mgr):
        assert mgr.assign_asset("nonexistent", "drone-1") is False

    def test_assign_empty_waypoints(self, mgr):
        rid = mgr.create_route("Empty", [])
        assert mgr.assign_asset(rid, "drone-1") is False

    def test_unassign_asset(self, mgr):
        rid = mgr.create_route("Route", SQUARE_WAYPOINTS)
        mgr.assign_asset(rid, "drone-1")
        assert mgr.unassign_asset("drone-1") is True
        assert len(mgr.get_active_patrols()) == 0

    def test_unassign_not_patrolling(self, mgr):
        assert mgr.unassign_asset("ghost") is False

    def test_reassign_asset(self, mgr):
        r1 = mgr.create_route("A", [(0, 0), (1, 1)])
        r2 = mgr.create_route("B", [(5, 5), (6, 6)])
        mgr.assign_asset(r1, "drone-1")
        mgr.assign_asset(r2, "drone-1")
        assignment = mgr.get_assignment("drone-1")
        assert assignment.route_id == r2

    def test_initial_position_at_first_waypoint(self, mgr):
        rid = mgr.create_route("Route", [(5.0, 3.0), (10.0, 0.0)])
        mgr.assign_asset(rid, "drone-1")
        assignment = mgr.get_assignment("drone-1")
        assert assignment.position == (5.0, 3.0)

    def test_assignment_to_dict(self, mgr):
        rid = mgr.create_route("Route", SQUARE_WAYPOINTS)
        mgr.assign_asset(rid, "drone-1")
        d = mgr.get_assignment("drone-1").to_dict()
        assert d["asset_id"] == "drone-1"
        assert d["completed"] is False
        assert isinstance(d["position"], list)


# ------------------------------------------------------------------
# Tick — movement
# ------------------------------------------------------------------

class TestTick:
    def test_tick_moves_toward_waypoint(self, mgr):
        rid = mgr.create_route("Line", [(0.0, 0.0), (10.0, 0.0)], speed=5.0)
        mgr.assign_asset(rid, "a1")
        mgr.tick(1.0)  # move 5 units at speed 5
        pos = mgr.get_assignment("a1").position
        # Should have moved toward (10, 0) — still short of arrival
        assert pos[0] > 0.0
        assert pos[0] < 10.0
        assert abs(pos[1]) < 0.001

    def test_tick_arrives_at_waypoint(self, mgr):
        rid = mgr.create_route("Short", [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)], speed=10.0)
        mgr.assign_asset(rid, "a1")
        mgr.tick(1.0)  # speed 10 >> distance, should blow past all waypoints
        a = mgr.get_assignment("a1")
        # With loop=True (default), should keep going
        assert a.completed is False

    def test_tick_loop_wraps(self, mgr):
        wp = [(0.0, 0.0), (1.0, 0.0)]
        rid = mgr.create_route("Loop", wp, loop=True, speed=100.0)
        mgr.assign_asset(rid, "a1")
        # Tick several times — should keep looping, never complete
        for _ in range(10):
            mgr.tick(1.0)
        a = mgr.get_assignment("a1")
        assert a.completed is False

    def test_tick_no_loop_completes(self, mgr):
        wp = [(0.0, 0.0), (1.0, 0.0)]
        rid = mgr.create_route("OneWay", wp, loop=False, speed=100.0)
        mgr.assign_asset(rid, "a1")
        mgr.tick(1.0)
        a = mgr.get_assignment("a1")
        assert a.completed is True
        # Completed assets should not appear in active patrols
        assert len(mgr.get_active_patrols()) == 0

    def test_tick_diagonal_movement(self, mgr):
        wp = [(0.0, 0.0), (3.0, 4.0)]  # distance = 5
        rid = mgr.create_route("Diag", wp, speed=5.0)
        mgr.assign_asset(rid, "a1")
        mgr.tick(0.5)  # move 2.5 units
        pos = mgr.get_assignment("a1").position
        # Should be roughly at (1.5, 2.0) — halfway to (3, 4) in 0.5s at speed 5
        assert 1.0 < pos[0] < 2.0
        assert 1.5 < pos[1] < 2.5

    def test_tick_multiple_assets(self, mgr):
        r1 = mgr.create_route("R1", [(0, 0), (10, 0)], speed=1.0)
        r2 = mgr.create_route("R2", [(0, 0), (0, 10)], speed=2.0)
        mgr.assign_asset(r1, "a1")
        mgr.assign_asset(r2, "a2")
        mgr.tick(1.0)
        p1 = mgr.get_assignment("a1").position
        p2 = mgr.get_assignment("a2").position
        assert abs(p1[0] - 1.0) < 0.01  # moved 1 unit in x
        assert abs(p2[1] - 2.0) < 0.01  # moved 2 units in y

    def test_tick_zero_dt(self, mgr):
        rid = mgr.create_route("R", [(0, 0), (10, 0)], speed=5.0)
        mgr.assign_asset(rid, "a1")
        mgr.tick(0.0)
        pos = mgr.get_assignment("a1").position
        assert pos == (0.0, 0.0)


# ------------------------------------------------------------------
# EventBus integration
# ------------------------------------------------------------------

class TestEventBus:
    def test_position_events_published(self, mgr, bus):
        q = bus.subscribe()
        rid = mgr.create_route("R", [(0, 0), (10, 0)], speed=1.0)
        mgr.assign_asset(rid, "a1")
        mgr.tick(1.0)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        types = [e["type"] for e in events]
        assert "patrol:position" in types

    def test_waypoint_event_on_arrival(self, mgr, bus):
        q = bus.subscribe()
        rid = mgr.create_route("R", [(0, 0), (1, 0)], speed=100.0)
        mgr.assign_asset(rid, "a1")
        mgr.tick(1.0)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        types = [e["type"] for e in events]
        assert "patrol:waypoint" in types

    def test_complete_event_on_finish(self, mgr, bus):
        q = bus.subscribe()
        rid = mgr.create_route("R", [(0, 0), (1, 0)], loop=False, speed=100.0)
        mgr.assign_asset(rid, "a1")
        mgr.tick(1.0)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        types = [e["type"] for e in events]
        assert "patrol:complete" in types

    def test_no_events_without_bus(self):
        mgr = PatrolManager(event_bus=None)
        rid = mgr.create_route("R", [(0, 0), (10, 0)])
        mgr.assign_asset(rid, "a1")
        # Should not raise
        mgr.tick(1.0)
