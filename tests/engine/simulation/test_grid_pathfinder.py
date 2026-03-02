# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for grid-based A* pathfinder — per-unit-type routing on TerrainMap.

TDD: These tests are written FIRST, before implementation.
"""

import math
import pytest

from engine.simulation.terrain import TerrainMap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_terrain_with_building_wall(bounds=50.0, res=5.0):
    """Create a terrain map with a building wall blocking the direct path.

    Layout (50m bounds = 100m wide, 5m cells):
        - Building wall from (-25, -5) to (-25, 5) and (25, 5) — a horizontal
          wall across the middle that blocks east-west at y=0.
        - Leaves gaps at the edges for routing around.

    Actually: simpler — put a building block from x=-15 to x=15 at y=0.
    Forces units to go around north or south.
    """
    tm = TerrainMap(map_bounds=bounds, resolution=res)
    # Build a wall of building cells across y=0, from x=-15 to x=15
    for x in range(-15, 16, int(res)):
        tm.set_cell(float(x), 0.0, "building")
    return tm


def _make_terrain_with_roads(bounds=50.0, res=5.0):
    """Create a terrain map with roads and buildings.

    Roads: horizontal road at y=20, vertical road at x=20.
    Buildings: block from (-10, -10) to (10, 10).
    """
    tm = TerrainMap(map_bounds=bounds, resolution=res)
    # Building block in center
    for x in range(-10, 11, int(res)):
        for y in range(-10, 11, int(res)):
            tm.set_cell(float(x), float(y), "building")
    # Road: horizontal at y=20
    for x in range(-50, 51, int(res)):
        tm.set_cell(float(x), 20.0, "road")
    # Road: vertical at x=20
    for y in range(-50, 51, int(res)):
        tm.set_cell(20.0, float(y), "road")
    return tm


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _path_enters_building(path, terrain_map):
    """Check if any waypoint in the path is inside a building cell."""
    for wp in path:
        cell = terrain_map.get_cell(wp[0], wp[1])
        if cell.terrain_type == "building":
            return True
    return False


# ---------------------------------------------------------------------------
# MovementProfile + PROFILES
# ---------------------------------------------------------------------------

class TestMovementProfiles:
    def test_profiles_exist(self):
        from engine.simulation.grid_pathfinder import PROFILES
        assert "pedestrian" in PROFILES
        assert "light_vehicle" in PROFILES
        assert "heavy_vehicle" in PROFILES
        assert "aerial" in PROFILES

    def test_pedestrian_can_enter_buildings_at_high_cost(self):
        from engine.simulation.grid_pathfinder import PROFILES
        p = PROFILES["pedestrian"]
        assert p.building < 999.0  # passable but expensive
        assert p.building > 5.0    # much more costly than open terrain

    def test_light_vehicle_cannot_enter_buildings(self):
        from engine.simulation.grid_pathfinder import PROFILES
        p = PROFILES["light_vehicle"]
        assert p.building >= 999.0  # effectively impassable

    def test_heavy_vehicle_roads_only(self):
        from engine.simulation.grid_pathfinder import PROFILES
        p = PROFILES["heavy_vehicle"]
        assert p.road < 1.0        # fast on roads
        assert p.yard >= 999.0     # cannot go off-road
        assert p.building >= 999.0

    def test_aerial_low_cost_everywhere(self):
        from engine.simulation.grid_pathfinder import PROFILES
        p = PROFILES["aerial"]
        assert p.road <= 1.5
        assert p.yard <= 1.5
        assert p.open_ <= 1.5
        assert p.water <= 1.5
        assert p.building < 999.0  # prefer avoiding but can overfly


# ---------------------------------------------------------------------------
# profile_for_unit()
# ---------------------------------------------------------------------------

class TestProfileForUnit:
    def test_hostile_person_is_pedestrian(self):
        from engine.simulation.grid_pathfinder import profile_for_unit
        assert profile_for_unit("person", "hostile") == "pedestrian"

    def test_rover_is_light_vehicle(self):
        from engine.simulation.grid_pathfinder import profile_for_unit
        assert profile_for_unit("rover", "friendly") == "light_vehicle"

    def test_apc_is_light_vehicle(self):
        from engine.simulation.grid_pathfinder import profile_for_unit
        assert profile_for_unit("apc", "friendly") == "light_vehicle"

    def test_tank_is_heavy_vehicle(self):
        from engine.simulation.grid_pathfinder import profile_for_unit
        assert profile_for_unit("tank", "friendly") == "heavy_vehicle"

    def test_drone_is_aerial(self):
        from engine.simulation.grid_pathfinder import profile_for_unit
        assert profile_for_unit("drone", "friendly") == "aerial"

    def test_scout_drone_is_aerial(self):
        from engine.simulation.grid_pathfinder import profile_for_unit
        assert profile_for_unit("scout_drone", "friendly") == "aerial"

    def test_unknown_type_falls_back_to_pedestrian(self):
        from engine.simulation.grid_pathfinder import profile_for_unit
        result = profile_for_unit("unknown_thing", "neutral")
        assert result == "pedestrian"


# ---------------------------------------------------------------------------
# grid_find_path() — A* core
# ---------------------------------------------------------------------------

class TestGridFindPath:
    def test_trivial_straight_line(self):
        """No obstacles — path goes roughly direct."""
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = TerrainMap(map_bounds=50.0, resolution=5.0)
        path = grid_find_path(tm, (-20.0, -20.0), (20.0, -20.0), "light_vehicle")
        assert path is not None
        assert len(path) >= 2
        # Start and end should be close to requested positions
        assert _dist(path[0], (-20.0, -20.0)) < 6.0
        assert _dist(path[-1], (20.0, -20.0)) < 6.0

    def test_routes_around_building_wall(self):
        """Building wall across middle — path must go around."""
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = _make_terrain_with_building_wall()
        # Go from south to north — direct path blocked by wall at y=0
        path = grid_find_path(tm, (0.0, -20.0), (0.0, 20.0), "light_vehicle")
        assert path is not None
        assert len(path) >= 3  # Must detour
        assert not _path_enters_building(path, tm)

    def test_pedestrian_avoids_buildings_by_default(self):
        """Pedestrians should route around buildings even though they CAN enter."""
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = _make_terrain_with_building_wall()
        path = grid_find_path(tm, (0.0, -20.0), (0.0, 20.0), "pedestrian")
        assert path is not None
        # With high building cost (25.0), pedestrian should still go around
        assert not _path_enters_building(path, tm)

    def test_heavy_vehicle_uses_roads(self):
        """Heavy vehicle (tank) can only travel on roads."""
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = _make_terrain_with_roads()
        # Start and end on roads
        path = grid_find_path(tm, (-40.0, 20.0), (20.0, -40.0), "heavy_vehicle")
        assert path is not None
        # Every waypoint should be on road terrain (or very close)
        for wp in path:
            cell = tm.get_cell(wp[0], wp[1])
            assert cell.terrain_type == "road", f"Tank at non-road cell {wp}: {cell.terrain_type}"

    def test_aerial_takes_short_path(self):
        """Aerial units can fly over buildings — path should be shorter."""
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = _make_terrain_with_building_wall()
        vehicle_path = grid_find_path(tm, (0.0, -20.0), (0.0, 20.0), "light_vehicle")
        aerial_path = grid_find_path(tm, (0.0, -20.0), (0.0, 20.0), "aerial")
        assert vehicle_path is not None
        assert aerial_path is not None
        # Aerial path should be shorter or equal (can overfly buildings)
        aerial_len = sum(_dist(aerial_path[i], aerial_path[i + 1])
                         for i in range(len(aerial_path) - 1))
        vehicle_len = sum(_dist(vehicle_path[i], vehicle_path[i + 1])
                          for i in range(len(vehicle_path) - 1))
        assert aerial_len <= vehicle_len + 1.0

    def test_start_equals_end(self):
        """Start == end should return a single-point path."""
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = TerrainMap(map_bounds=50.0, resolution=5.0)
        path = grid_find_path(tm, (10.0, 10.0), (10.0, 10.0), "pedestrian")
        assert path is not None
        assert len(path) >= 1

    def test_circuit_breaker(self):
        """A* should give up after max_iterations and return None or best-effort."""
        from engine.simulation.grid_pathfinder import grid_find_path
        # Create a large open map with very low max_iterations
        tm = TerrainMap(map_bounds=200.0, resolution=5.0)
        # Very far apart, very low iteration budget
        path = grid_find_path(tm, (-190.0, -190.0), (190.0, 190.0),
                              "pedestrian", max_iterations=5)
        # Should return None when budget exhausted before reaching goal
        assert path is None

    def test_no_path_possible(self):
        """Completely walled-off destination should return None."""
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = TerrainMap(map_bounds=50.0, resolution=5.0)
        # Surround (20, 20) with buildings
        for x in range(15, 26, 5):
            for y in range(15, 26, 5):
                tm.set_cell(float(x), float(y), "building")
        path = grid_find_path(tm, (-20.0, -20.0), (20.0, 20.0), "light_vehicle")
        assert path is None

    def test_returns_world_coordinates(self):
        """Path waypoints should be in world coordinates, not grid indices."""
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = TerrainMap(map_bounds=50.0, resolution=5.0)
        path = grid_find_path(tm, (-20.0, 0.0), (20.0, 0.0), "pedestrian")
        assert path is not None
        for wp in path:
            assert isinstance(wp, tuple)
            assert len(wp) == 2
            # World coordinates should be in range
            assert -55.0 <= wp[0] <= 55.0
            assert -55.0 <= wp[1] <= 55.0

    def test_diagonal_movement(self):
        """Path should use diagonal moves for efficiency."""
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = TerrainMap(map_bounds=50.0, resolution=5.0)
        path = grid_find_path(tm, (-20.0, -20.0), (20.0, 20.0), "pedestrian")
        assert path is not None
        # A diagonal path should be reasonably efficient
        direct_dist = _dist((-20.0, -20.0), (20.0, 20.0))
        path_dist = sum(_dist(path[i], path[i + 1]) for i in range(len(path) - 1))
        # Path should not be more than 1.5x the direct distance (diagonal is sqrt(2)x)
        assert path_dist < direct_dist * 1.5


# ---------------------------------------------------------------------------
# smooth_path()
# ---------------------------------------------------------------------------

class TestSmoothPath:
    def test_removes_collinear_points(self):
        from engine.simulation.grid_pathfinder import smooth_path
        # 5 points all on a straight line
        path = [(0, 0), (5, 0), (10, 0), (15, 0), (20, 0)]
        smoothed = smooth_path(path)
        # Should reduce to just start and end
        assert len(smoothed) == 2
        assert smoothed[0] == (0, 0)
        assert smoothed[-1] == (20, 0)

    def test_preserves_corners(self):
        from engine.simulation.grid_pathfinder import smooth_path
        # L-shaped path: right then up
        path = [(0, 0), (5, 0), (10, 0), (10, 5), (10, 10)]
        smoothed = smooth_path(path)
        # Should keep the corner at (10, 0)
        assert len(smoothed) == 3
        assert smoothed[0] == (0, 0)
        assert smoothed[1] == (10, 0)
        assert smoothed[-1] == (10, 10)

    def test_empty_path(self):
        from engine.simulation.grid_pathfinder import smooth_path
        assert smooth_path([]) == []

    def test_single_point(self):
        from engine.simulation.grid_pathfinder import smooth_path
        assert smooth_path([(5, 5)]) == [(5, 5)]

    def test_two_points(self):
        from engine.simulation.grid_pathfinder import smooth_path
        assert smooth_path([(0, 0), (10, 10)]) == [(0, 0), (10, 10)]


# ---------------------------------------------------------------------------
# terrain.py get_cost() helper
# ---------------------------------------------------------------------------

class TestTerrainGetCost:
    def test_get_cost_open(self):
        tm = TerrainMap(map_bounds=50.0, resolution=5.0)
        col, row = tm._world_to_grid(0.0, 0.0)
        cost = tm.get_cost(col, row)
        assert cost == 1.0  # open terrain default

    def test_get_cost_road(self):
        tm = TerrainMap(map_bounds=50.0, resolution=5.0)
        tm.set_cell(0.0, 0.0, "road")
        col, row = tm._world_to_grid(0.0, 0.0)
        cost = tm.get_cost(col, row)
        assert cost == 0.7

    def test_get_cost_building(self):
        tm = TerrainMap(map_bounds=50.0, resolution=5.0)
        tm.set_cell(0.0, 0.0, "building")
        col, row = tm._world_to_grid(0.0, 0.0)
        cost = tm.get_cost(col, row)
        assert cost == float("inf")

    def test_get_cost_out_of_bounds(self):
        tm = TerrainMap(map_bounds=50.0, resolution=5.0)
        # Grid indices well outside bounds
        cost = tm.get_cost(-1, -1)
        assert cost == float("inf")  # out of bounds = impassable

    def test_grid_size_and_bounds_exposed(self):
        """Pathfinder needs grid_size and bounds for clamp checks."""
        tm = TerrainMap(map_bounds=50.0, resolution=5.0)
        assert tm.grid_size > 0
        assert tm.bounds == 50.0
        assert tm.resolution == 5.0


# ---------------------------------------------------------------------------
# Integration: grid_find_path with realistic terrain
# ---------------------------------------------------------------------------

class TestGridPathfinderIntegration:
    def test_light_vehicle_avoids_center_building(self):
        """Rover routes around a building block in the center."""
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = _make_terrain_with_roads()
        path = grid_find_path(tm, (-30.0, -30.0), (30.0, 30.0), "light_vehicle")
        assert path is not None
        assert not _path_enters_building(path, tm)

    def test_path_performance_budget(self):
        """A* on 81x81 grid should complete in < 5ms for typical paths."""
        import time
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = _make_terrain_with_building_wall()
        start = time.perf_counter()
        for _ in range(10):
            grid_find_path(tm, (0.0, -20.0), (0.0, 20.0), "light_vehicle")
        elapsed = (time.perf_counter() - start) / 10
        assert elapsed < 0.005, f"A* took {elapsed*1000:.1f}ms, budget is 5ms"

    def test_multiple_profiles_same_terrain(self):
        """Different profiles should produce different paths on the same terrain."""
        from engine.simulation.grid_pathfinder import grid_find_path
        tm = _make_terrain_with_roads()
        heavy_path = grid_find_path(tm, (-40.0, 20.0), (20.0, -40.0), "heavy_vehicle")
        light_path = grid_find_path(tm, (-40.0, 20.0), (20.0, -40.0), "light_vehicle")
        aerial_path = grid_find_path(tm, (-40.0, 20.0), (20.0, -40.0), "aerial")
        # Heavy vehicle path exists (roads connect these points)
        assert heavy_path is not None
        # Light vehicle path exists
        assert light_path is not None
        # Aerial path exists
        assert aerial_path is not None
        # Heavy path should be longer (road-only) than light or aerial
        if heavy_path and light_path:
            heavy_len = sum(_dist(heavy_path[i], heavy_path[i+1])
                            for i in range(len(heavy_path) - 1))
            light_len = sum(_dist(light_path[i], light_path[i+1])
                            for i in range(len(light_path) - 1))
            assert heavy_len >= light_len - 1.0
