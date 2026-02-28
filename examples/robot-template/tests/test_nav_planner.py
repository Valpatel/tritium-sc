# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for navigation planner — coordinate transforms and path planning."""

import math
import pytest

# Add parent to path for imports
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain.nav_planner import (
    WorldPosition, GpsPosition, NavWaypoint, NavPath,
    gps_to_world, world_to_gps,
    StraightLinePlanner, WaypointPlanner,
    Nav2Planner, SlamPlanner, GpsNavigator,
)


# ===========================================================================
# WorldPosition
# ===========================================================================

class TestWorldPosition:
    def test_distance_zero(self):
        a = WorldPosition(0, 0)
        b = WorldPosition(0, 0)
        assert a.distance_to(b) == 0.0

    def test_distance_pythagorean(self):
        a = WorldPosition(0, 0)
        b = WorldPosition(3, 4)
        assert abs(a.distance_to(b) - 5.0) < 0.001

    def test_bearing_north(self):
        a = WorldPosition(0, 0)
        b = WorldPosition(0, 10)
        assert abs(a.bearing_to(b) - 0.0) < 0.1

    def test_bearing_east(self):
        a = WorldPosition(0, 0)
        b = WorldPosition(10, 0)
        assert abs(a.bearing_to(b) - 90.0) < 0.1

    def test_bearing_south(self):
        a = WorldPosition(0, 0)
        b = WorldPosition(0, -10)
        assert abs(a.bearing_to(b) - 180.0) < 0.1

    def test_to_dict(self):
        p = WorldPosition(5.0, -3.0, 45.0)
        d = p.to_dict()
        assert d == {"x": 5.0, "y": -3.0, "heading": 45.0}

    def test_from_dict(self):
        p = WorldPosition.from_dict({"x": 1, "y": 2, "heading": 90})
        assert p.x == 1
        assert p.y == 2
        assert p.heading == 90


# ===========================================================================
# GPS <-> World Coordinate Transforms
# ===========================================================================

class TestCoordinateTransforms:
    """gps_to_world and world_to_gps — equirectangular projection."""

    # Approximate: Austin, TX
    ORIGIN_LAT = 30.2672
    ORIGIN_LNG = -97.7431

    def test_origin_maps_to_zero(self):
        gps = GpsPosition(lat=self.ORIGIN_LAT, lng=self.ORIGIN_LNG)
        world = gps_to_world(gps, self.ORIGIN_LAT, self.ORIGIN_LNG)
        assert abs(world.x) < 0.01
        assert abs(world.y) < 0.01

    def test_north_is_positive_y(self):
        """Moving north (higher lat) should increase Y."""
        gps = GpsPosition(lat=self.ORIGIN_LAT + 0.001, lng=self.ORIGIN_LNG)
        world = gps_to_world(gps, self.ORIGIN_LAT, self.ORIGIN_LNG)
        assert world.y > 0
        assert abs(world.x) < 1.0  # Should be near zero X

    def test_east_is_positive_x(self):
        """Moving east (higher lng) should increase X."""
        gps = GpsPosition(lat=self.ORIGIN_LAT, lng=self.ORIGIN_LNG + 0.001)
        world = gps_to_world(gps, self.ORIGIN_LAT, self.ORIGIN_LNG)
        assert world.x > 0
        assert abs(world.y) < 1.0  # Should be near zero Y

    def test_roundtrip_gps_world_gps(self):
        """GPS → world → GPS should be identity (within float precision)."""
        gps_in = GpsPosition(lat=self.ORIGIN_LAT + 0.001, lng=self.ORIGIN_LNG + 0.001)
        world = gps_to_world(gps_in, self.ORIGIN_LAT, self.ORIGIN_LNG)
        gps_out = world_to_gps(world, self.ORIGIN_LAT, self.ORIGIN_LNG)
        assert abs(gps_in.lat - gps_out.lat) < 1e-6
        assert abs(gps_in.lng - gps_out.lng) < 1e-6

    def test_100m_north_approx(self):
        """~100m north should be ~0.0009 degrees latitude."""
        # 1 degree lat ≈ 111km, so 100m ≈ 0.0009 degrees
        gps = GpsPosition(lat=self.ORIGIN_LAT + 0.0009, lng=self.ORIGIN_LNG)
        world = gps_to_world(gps, self.ORIGIN_LAT, self.ORIGIN_LNG)
        assert 90 < world.y < 110  # ~100m with projection error tolerance

    def test_neighborhood_scale(self):
        """A neighborhood block (~200m) should be accurate."""
        # Two corners of a ~200m block
        gps_a = GpsPosition(lat=self.ORIGIN_LAT, lng=self.ORIGIN_LNG)
        gps_b = GpsPosition(lat=self.ORIGIN_LAT + 0.0018, lng=self.ORIGIN_LNG + 0.0018)
        world_a = gps_to_world(gps_a, self.ORIGIN_LAT, self.ORIGIN_LNG)
        world_b = gps_to_world(gps_b, self.ORIGIN_LAT, self.ORIGIN_LNG)
        dist = world_a.distance_to(world_b)
        # ~280m diagonal, should be in ballpark
        assert 200 < dist < 350


# ===========================================================================
# StraightLinePlanner
# ===========================================================================

class TestStraightLinePlanner:
    def test_plan_two_waypoints(self):
        planner = StraightLinePlanner()
        start = WorldPosition(0, 0)
        goal = WorldPosition(10, 5)
        path = planner.plan(start, goal)
        assert len(path.waypoints) == 2
        assert path.waypoints[0].position.x == 0
        assert path.waypoints[1].position.x == 10

    def test_total_distance(self):
        planner = StraightLinePlanner()
        start = WorldPosition(0, 0)
        goal = WorldPosition(3, 4)
        path = planner.plan(start, goal)
        assert abs(path.total_distance - 5.0) < 0.001

    def test_replan_same_as_plan(self):
        planner = StraightLinePlanner()
        current = WorldPosition(2, 3)
        goal = WorldPosition(10, 5)
        path = planner.replan(current, goal)
        assert len(path.waypoints) == 2


# ===========================================================================
# WaypointPlanner
# ===========================================================================

class TestWaypointPlanner:
    def test_predefined_route(self):
        wps = [WorldPosition(0, 0), WorldPosition(10, 0), WorldPosition(10, 10)]
        planner = WaypointPlanner(waypoints=wps)
        path = planner.plan(WorldPosition(0, 0), WorldPosition(10, 10))
        assert len(path.waypoints) == 3

    def test_empty_waypoints_fallback(self):
        planner = WaypointPlanner()
        path = planner.plan(WorldPosition(0, 0), WorldPosition(5, 5))
        assert len(path.waypoints) == 2  # Falls back to straight line


# ===========================================================================
# NavPath
# ===========================================================================

class TestNavPath:
    def test_empty_path_distance(self):
        path = NavPath()
        assert path.total_distance == 0.0

    def test_single_waypoint_distance(self):
        path = NavPath(waypoints=[NavWaypoint(position=WorldPosition(0, 0))])
        assert path.total_distance == 0.0

    def test_loop_flag(self):
        path = NavPath(loop=True)
        assert path.loop is True


# ===========================================================================
# NavWaypoint
# ===========================================================================

class TestNavWaypoint:
    def test_to_dict(self):
        wp = NavWaypoint(position=WorldPosition(5, 10), speed=0.5, action="scan")
        d = wp.to_dict()
        assert d["x"] == 5
        assert d["y"] == 10
        assert d["speed"] == 0.5
        assert d["action"] == "scan"

    def test_to_dict_no_action(self):
        wp = NavWaypoint(position=WorldPosition(0, 0))
        d = wp.to_dict()
        assert "action" not in d


# ===========================================================================
# Real Navigation Stubs — verify they raise NotImplementedError
# ===========================================================================

class TestNavigationStubs:
    """Real navigation stubs raise NotImplementedError with helpful messages."""

    def test_nav2_plan_raises(self):
        planner = Nav2Planner()
        with pytest.raises(NotImplementedError, match="Nav2Planner"):
            planner.plan(WorldPosition(), WorldPosition(10, 10))

    def test_nav2_replan_raises(self):
        planner = Nav2Planner()
        with pytest.raises(NotImplementedError):
            planner.replan(WorldPosition(), WorldPosition(10, 10))

    def test_slam_plan_raises(self):
        planner = SlamPlanner()
        with pytest.raises(NotImplementedError, match="SlamPlanner"):
            planner.plan(WorldPosition(), WorldPosition(10, 10))

    def test_gps_navigator_position_raises(self):
        nav = GpsNavigator()
        with pytest.raises(NotImplementedError, match="GPS"):
            nav.get_position()

    def test_gps_navigator_navigate_raises(self):
        nav = GpsNavigator()
        with pytest.raises(NotImplementedError, match="GPS"):
            nav.navigate_to(WorldPosition(10, 10))
