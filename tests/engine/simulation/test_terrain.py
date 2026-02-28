# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TerrainMap -- spatial index for terrain features.

TDD RED phase: All tests written before implementation.
Tests cover: TerrainCell defaults, terrain types, movement costs, cover values,
visibility, grid operations, layout loading, terrain queries, speed modifiers,
line of sight (Bresenham), combat LOS integration, telemetry, empty terrain.
"""

import math
import pytest

from engine.simulation.terrain import TerrainCell, TerrainMap


# ---------------------------------------------------------------------------
# TerrainCell defaults
# ---------------------------------------------------------------------------

class TestTerrainCellDefaults:
    """Default TerrainCell values (open terrain)."""

    @pytest.mark.unit
    def test_default_terrain_type(self):
        cell = TerrainCell(x=0.0, y=0.0, terrain_type="open")
        assert cell.terrain_type == "open"

    @pytest.mark.unit
    def test_default_movement_cost(self):
        cell = TerrainCell(x=0.0, y=0.0, terrain_type="open")
        assert cell.movement_cost == 1.0

    @pytest.mark.unit
    def test_default_cover_value(self):
        cell = TerrainCell(x=0.0, y=0.0, terrain_type="open")
        assert cell.cover_value == 0.0

    @pytest.mark.unit
    def test_default_visibility(self):
        cell = TerrainCell(x=0.0, y=0.0, terrain_type="open")
        assert cell.visibility == 1.0

    @pytest.mark.unit
    def test_default_elevation(self):
        cell = TerrainCell(x=0.0, y=0.0, terrain_type="open")
        assert cell.elevation == 0.0

    @pytest.mark.unit
    def test_cell_position(self):
        cell = TerrainCell(x=10.5, y=-20.3, terrain_type="road")
        assert cell.x == 10.5
        assert cell.y == -20.3


# ---------------------------------------------------------------------------
# TerrainCell types -- each terrain type has expected properties
# ---------------------------------------------------------------------------

class TestTerrainCellTypes:
    """Verify terrain types map to correct movement cost, cover, visibility."""

    @pytest.mark.unit
    def test_road_movement_cost(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "road")
        cell = tm.get_cell(0.0, 0.0)
        assert cell.movement_cost == pytest.approx(0.7)

    @pytest.mark.unit
    def test_building_movement_cost(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "building")
        cell = tm.get_cell(0.0, 0.0)
        assert cell.movement_cost == float("inf")

    @pytest.mark.unit
    def test_yard_movement_cost(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "yard")
        cell = tm.get_cell(0.0, 0.0)
        assert cell.movement_cost == 1.0

    @pytest.mark.unit
    def test_open_movement_cost(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "open")
        cell = tm.get_cell(0.0, 0.0)
        assert cell.movement_cost == 1.0

    @pytest.mark.unit
    def test_water_movement_cost(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "water")
        cell = tm.get_cell(0.0, 0.0)
        assert cell.movement_cost == float("inf")


# ---------------------------------------------------------------------------
# Cover values per terrain type
# ---------------------------------------------------------------------------

class TestCoverValue:
    """Natural cover provided by terrain type."""

    @pytest.mark.unit
    def test_building_cover(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "building")
        assert tm.get_cover_value(0.0, 0.0) == pytest.approx(0.5)

    @pytest.mark.unit
    def test_yard_cover(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "yard")
        assert tm.get_cover_value(0.0, 0.0) == pytest.approx(0.1)

    @pytest.mark.unit
    def test_road_cover(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "road")
        assert tm.get_cover_value(0.0, 0.0) == pytest.approx(0.0)

    @pytest.mark.unit
    def test_open_cover(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "open")
        assert tm.get_cover_value(0.0, 0.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Visibility per terrain type
# ---------------------------------------------------------------------------

class TestVisibility:
    """How visible a unit is on this terrain."""

    @pytest.mark.unit
    def test_building_visibility(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "building")
        assert tm.get_visibility(0.0, 0.0) == pytest.approx(0.0)

    @pytest.mark.unit
    def test_yard_visibility(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "yard")
        assert tm.get_visibility(0.0, 0.0) == pytest.approx(0.8)

    @pytest.mark.unit
    def test_road_visibility(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "road")
        assert tm.get_visibility(0.0, 0.0) == pytest.approx(1.0)

    @pytest.mark.unit
    def test_open_visibility(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "open")
        assert tm.get_visibility(0.0, 0.0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Set/Get cell operations
# ---------------------------------------------------------------------------

class TestSetGetCell:
    """Setting and retrieving terrain cells."""

    @pytest.mark.unit
    def test_set_and_get(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(10.0, 20.0, "road")
        cell = tm.get_cell(10.0, 20.0)
        assert cell.terrain_type == "road"

    @pytest.mark.unit
    def test_overwrite_cell(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(10.0, 20.0, "road")
        tm.set_cell(10.0, 20.0, "building")
        cell = tm.get_cell(10.0, 20.0)
        assert cell.terrain_type == "building"

    @pytest.mark.unit
    def test_get_terrain_type_string(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(5.0, 5.0, "yard")
        assert tm.get_terrain_type(5.0, 5.0) == "yard"

    @pytest.mark.unit
    def test_negative_coordinates(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(-50.0, -30.0, "road")
        assert tm.get_terrain_type(-50.0, -30.0) == "road"

    @pytest.mark.unit
    def test_boundary_coordinates(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(99.0, 99.0, "water")
        assert tm.get_terrain_type(99.0, 99.0) == "water"


# ---------------------------------------------------------------------------
# Default cell (unset positions)
# ---------------------------------------------------------------------------

class TestDefaultCell:
    """Unset positions return open terrain."""

    @pytest.mark.unit
    def test_unset_returns_open(self):
        tm = TerrainMap(map_bounds=100.0)
        cell = tm.get_cell(42.0, 42.0)
        assert cell.terrain_type == "open"

    @pytest.mark.unit
    def test_unset_movement_cost(self):
        tm = TerrainMap(map_bounds=100.0)
        assert tm.get_movement_cost(50.0, 50.0) == 1.0

    @pytest.mark.unit
    def test_unset_cover_value(self):
        tm = TerrainMap(map_bounds=100.0)
        assert tm.get_cover_value(50.0, 50.0) == 0.0

    @pytest.mark.unit
    def test_unset_visibility(self):
        tm = TerrainMap(map_bounds=100.0)
        assert tm.get_visibility(50.0, 50.0) == 1.0


# ---------------------------------------------------------------------------
# Grid resolution
# ---------------------------------------------------------------------------

class TestGridResolution:
    """Grid resolution and cell snapping."""

    @pytest.mark.unit
    def test_default_resolution_5m(self):
        tm = TerrainMap(map_bounds=100.0)
        assert tm._resolution == 5.0

    @pytest.mark.unit
    def test_custom_resolution(self):
        tm = TerrainMap(map_bounds=100.0, resolution=10.0)
        assert tm._resolution == 10.0

    @pytest.mark.unit
    def test_nearby_positions_same_cell(self):
        """Two positions within the same grid cell share terrain type."""
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        tm.set_cell(10.0, 10.0, "road")
        # Position 1m away should land in the same cell
        cell = tm.get_cell(11.0, 11.0)
        assert cell.terrain_type == "road"

    @pytest.mark.unit
    def test_grid_size_calculation(self):
        """Grid for 200m bounds at 5m resolution: 2*200/5 + 1 = 81 cells per axis."""
        tm = TerrainMap(map_bounds=200.0, resolution=5.0)
        assert tm._grid_size == 81


# ---------------------------------------------------------------------------
# Load buildings
# ---------------------------------------------------------------------------

class TestLoadBuildings:
    """Building polygons create building cells."""

    @pytest.mark.unit
    def test_building_polygon_creates_cells(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        # Simple 20x20 building
        buildings = [
            {"footprint": [(0, 0), (20, 0), (20, 20), (0, 20)], "position": (10, 10)}
        ]
        tm.load_buildings(buildings)
        # Center of the building should be "building"
        assert tm.get_terrain_type(10.0, 10.0) == "building"

    @pytest.mark.unit
    def test_building_has_infinite_movement_cost(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        buildings = [
            {"footprint": [(0, 0), (20, 0), (20, 20), (0, 20)], "position": (10, 10)}
        ]
        tm.load_buildings(buildings)
        assert tm.get_movement_cost(10.0, 10.0) == float("inf")

    @pytest.mark.unit
    def test_outside_building_stays_open(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        buildings = [
            {"footprint": [(0, 0), (20, 0), (20, 20), (0, 20)], "position": (10, 10)}
        ]
        tm.load_buildings(buildings)
        # Well outside building
        assert tm.get_terrain_type(50.0, 50.0) == "open"

    @pytest.mark.unit
    def test_multiple_buildings(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        buildings = [
            {"footprint": [(0, 0), (10, 0), (10, 10), (0, 10)], "position": (5, 5)},
            {"footprint": [(50, 50), (70, 50), (70, 70), (50, 70)], "position": (60, 60)},
        ]
        tm.load_buildings(buildings)
        assert tm.get_terrain_type(5.0, 5.0) == "building"
        assert tm.get_terrain_type(60.0, 60.0) == "building"


# ---------------------------------------------------------------------------
# Load roads
# ---------------------------------------------------------------------------

class TestLoadRoads:
    """Road segments create road cells."""

    @pytest.mark.unit
    def test_road_segment_creates_cells(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        # Road from (0,0) to (50,0) -- horizontal road
        road_segments = [
            {"start": (0.0, 0.0), "end": (50.0, 0.0), "width": 6.0}
        ]
        tm.load_roads(road_segments)
        # Middle of road
        assert tm.get_terrain_type(25.0, 0.0) == "road"

    @pytest.mark.unit
    def test_road_has_low_movement_cost(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        road_segments = [
            {"start": (0.0, 0.0), "end": (50.0, 0.0), "width": 6.0}
        ]
        tm.load_roads(road_segments)
        assert tm.get_movement_cost(25.0, 0.0) == pytest.approx(0.7)

    @pytest.mark.unit
    def test_road_off_road_is_not_road(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        road_segments = [
            {"start": (0.0, 0.0), "end": (50.0, 0.0), "width": 6.0}
        ]
        tm.load_roads(road_segments)
        # 20m away from road
        assert tm.get_terrain_type(25.0, 20.0) != "road"


# ---------------------------------------------------------------------------
# Load from layout (full TritiumLevelFormat)
# ---------------------------------------------------------------------------

class TestLoadFromLayout:
    """Full layout loading from TritiumLevelFormat data."""

    @pytest.mark.unit
    def test_load_buildings_from_layout(self):
        """Buildings in layout get loaded as terrain."""
        layout = {
            "objects": [
                {
                    "type": "building",
                    "name": "Test House",
                    "position": {"x": 10, "y": 0, "z": 20},
                    "properties": {
                        "footprint": [[0, 10], [0, 30], [20, 30], [20, 10]],
                        "doors": [],
                    },
                }
            ]
        }
        tm = TerrainMap(map_bounds=200.0, resolution=5.0)
        tm.load_from_layout(layout)
        assert tm.get_terrain_type(10.0, 20.0) == "building"

    @pytest.mark.unit
    def test_load_empty_layout(self):
        """Empty layout loads without error."""
        layout = {"objects": []}
        tm = TerrainMap(map_bounds=200.0, resolution=5.0)
        tm.load_from_layout(layout)
        # Everything should remain "open"
        assert tm.get_terrain_type(0.0, 0.0) == "open"

    @pytest.mark.unit
    def test_load_layout_with_non_terrain_objects(self):
        """Non-terrain objects (cameras, turrets) are silently ignored."""
        layout = {
            "objects": [
                {
                    "type": "ptz_camera",
                    "name": "Cam",
                    "position": {"x": 0, "y": 0, "z": 0},
                    "properties": {},
                },
                {
                    "type": "sentry_turret",
                    "name": "Turret",
                    "position": {"x": 10, "y": 0, "z": 10},
                    "properties": {},
                },
            ]
        }
        tm = TerrainMap(map_bounds=200.0, resolution=5.0)
        tm.load_from_layout(layout)
        # No terrain changed
        assert tm.get_terrain_type(0.0, 0.0) == "open"
        assert tm.get_terrain_type(10.0, 10.0) == "open"


# ---------------------------------------------------------------------------
# Find terrain of type
# ---------------------------------------------------------------------------

class TestFindTerrainOfType:
    """Find positions with given terrain type."""

    @pytest.mark.unit
    def test_find_road_positions(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        tm.set_cell(10.0, 10.0, "road")
        tm.set_cell(20.0, 20.0, "road")
        tm.set_cell(30.0, 30.0, "building")
        results = tm.find_terrain_of_type("road")
        assert len(results) == 2

    @pytest.mark.unit
    def test_find_no_matching_type(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        tm.set_cell(10.0, 10.0, "road")
        results = tm.find_terrain_of_type("water")
        assert len(results) == 0


class TestFindNearPosition:
    """Find terrain near specific point."""

    @pytest.mark.unit
    def test_find_near_position(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        tm.set_cell(10.0, 10.0, "road")
        tm.set_cell(90.0, 90.0, "road")
        # Search near (10, 10) with radius 20
        results = tm.find_terrain_of_type("road", near=(10.0, 10.0), radius=20.0)
        assert len(results) == 1

    @pytest.mark.unit
    def test_find_near_returns_positions(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        tm.set_cell(15.0, 15.0, "road")
        results = tm.find_terrain_of_type("road", near=(15.0, 15.0), radius=10.0)
        assert len(results) >= 1
        # Result should be a tuple (x, y)
        assert len(results[0]) == 2


# ---------------------------------------------------------------------------
# Speed modifier per unit type
# ---------------------------------------------------------------------------

class TestSpeedModifier:
    """Unit type affects speed on terrain."""

    @pytest.mark.unit
    def test_road_speed_modifier_for_rover(self):
        """Rover on road gets faster movement (0.7 cost = higher modifier)."""
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "road")
        mod = tm.get_speed_modifier(0.0, 0.0, "rover")
        # Road cost 0.7 means faster, so modifier > 1.0
        assert mod > 1.0

    @pytest.mark.unit
    def test_open_terrain_speed_modifier(self):
        """Open terrain gives base speed (1.0)."""
        tm = TerrainMap(map_bounds=100.0)
        mod = tm.get_speed_modifier(0.0, 0.0, "rover")
        assert mod == pytest.approx(1.0)

    @pytest.mark.unit
    def test_hostile_yard_penalty(self):
        """Hostile gets slight speed penalty in yards."""
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "yard")
        mod = tm.get_speed_modifier(0.0, 0.0, "person")
        assert mod <= 1.0


class TestDroneIgnoresTerrain:
    """Drone speed modifier always 1.0."""

    @pytest.mark.unit
    def test_drone_on_building(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "building")
        assert tm.get_speed_modifier(0.0, 0.0, "drone") == pytest.approx(1.0)

    @pytest.mark.unit
    def test_drone_on_water(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "water")
        assert tm.get_speed_modifier(0.0, 0.0, "drone") == pytest.approx(1.0)

    @pytest.mark.unit
    def test_drone_on_road(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "road")
        assert tm.get_speed_modifier(0.0, 0.0, "drone") == pytest.approx(1.0)

    @pytest.mark.unit
    def test_scout_drone_ignores_terrain(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "building")
        assert tm.get_speed_modifier(0.0, 0.0, "scout_drone") == pytest.approx(1.0)


class TestRoverRoadBonus:
    """Rover faster on roads."""

    @pytest.mark.unit
    def test_rover_road_faster_than_yard(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "road")
        tm.set_cell(10.0, 10.0, "yard")
        road_mod = tm.get_speed_modifier(0.0, 0.0, "rover")
        yard_mod = tm.get_speed_modifier(10.0, 10.0, "rover")
        assert road_mod > yard_mod


# ---------------------------------------------------------------------------
# Line of sight
# ---------------------------------------------------------------------------

class TestLineOfSight:
    """Clear LOS between two points."""

    @pytest.mark.unit
    def test_clear_los_empty_terrain(self):
        """No buildings -> always clear LOS."""
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        assert tm.line_of_sight((0.0, 0.0), (50.0, 50.0)) is True

    @pytest.mark.unit
    def test_clear_los_with_road(self):
        """Roads don't block LOS."""
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        tm.set_cell(25.0, 25.0, "road")
        assert tm.line_of_sight((0.0, 0.0), (50.0, 50.0)) is True

    @pytest.mark.unit
    def test_same_position(self):
        """LOS from a point to itself is always true."""
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        assert tm.line_of_sight((10.0, 10.0), (10.0, 10.0)) is True


class TestLineOfSightBlocked:
    """Building blocks LOS."""

    @pytest.mark.unit
    def test_building_blocks_los(self):
        """Building between two points blocks LOS."""
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        # Place a wall of buildings between (0,0) and (50,0)
        for x in range(20, 35, 5):
            tm.set_cell(float(x), 0.0, "building")
        assert tm.line_of_sight((0.0, 0.0), (50.0, 0.0)) is False

    @pytest.mark.unit
    def test_building_not_in_path(self):
        """Building off to the side doesn't block LOS."""
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        # Building at (50, 50) shouldn't block (0,0) to (50, 0) LOS
        tm.set_cell(50.0, 50.0, "building")
        assert tm.line_of_sight((0.0, 0.0), (50.0, 0.0)) is True


class TestLineOfSightEdge:
    """LOS along building edge."""

    @pytest.mark.unit
    def test_los_diagonal_around_building(self):
        """Diagonal path that misses the building should have LOS."""
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        # Small building at (25, 25)
        tm.set_cell(25.0, 25.0, "building")
        # Path from (0,0) to (50,0) -- horizontal, doesn't cross (25,25)
        assert tm.line_of_sight((0.0, 0.0), (50.0, 0.0)) is True

    @pytest.mark.unit
    def test_vertical_los_blocked(self):
        """Vertical LOS blocked by building in the middle."""
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        tm.set_cell(0.0, 25.0, "building")
        assert tm.line_of_sight((0.0, 0.0), (0.0, 50.0)) is False


# ---------------------------------------------------------------------------
# Combat LOS integration
# ---------------------------------------------------------------------------

class TestCombatLOS:
    """Projectile blocked by building (combat integration concept)."""

    @pytest.mark.unit
    def test_terrain_blocks_combat_los(self):
        """When terrain has a building in path, LOS returns False."""
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        shooter_pos = (0.0, 0.0)
        target_pos = (50.0, 0.0)
        # Wall of buildings blocking the shot
        for x in range(20, 35, 5):
            tm.set_cell(float(x), 0.0, "building")
        assert tm.line_of_sight(shooter_pos, target_pos) is False


class TestCombatClearShot:
    """Projectile passes through open terrain."""

    @pytest.mark.unit
    def test_clear_shot_over_open(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        shooter_pos = (0.0, 0.0)
        target_pos = (30.0, 30.0)
        assert tm.line_of_sight(shooter_pos, target_pos) is True

    @pytest.mark.unit
    def test_clear_shot_over_road(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        for x in range(0, 35, 5):
            tm.set_cell(float(x), 0.0, "road")
        assert tm.line_of_sight((0.0, 0.0), (30.0, 0.0)) is True


# ---------------------------------------------------------------------------
# Telemetry serialization
# ---------------------------------------------------------------------------

class TestToTelemetry:
    """Serialization format."""

    @pytest.mark.unit
    def test_telemetry_is_dict(self):
        tm = TerrainMap(map_bounds=100.0)
        data = tm.to_telemetry()
        assert isinstance(data, dict)

    @pytest.mark.unit
    def test_telemetry_has_bounds(self):
        tm = TerrainMap(map_bounds=100.0)
        data = tm.to_telemetry()
        assert "bounds" in data
        assert data["bounds"] == 100.0

    @pytest.mark.unit
    def test_telemetry_has_resolution(self):
        tm = TerrainMap(map_bounds=100.0, resolution=5.0)
        data = tm.to_telemetry()
        assert "resolution" in data
        assert data["resolution"] == 5.0

    @pytest.mark.unit
    def test_telemetry_has_cells(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "road")
        data = tm.to_telemetry()
        assert "cells" in data
        assert len(data["cells"]) >= 1

    @pytest.mark.unit
    def test_telemetry_cell_format(self):
        """Each cell has x, y, terrain_type, movement_cost, cover_value, visibility."""
        tm = TerrainMap(map_bounds=100.0)
        tm.set_cell(0.0, 0.0, "road")
        data = tm.to_telemetry()
        cell = data["cells"][0]
        assert "x" in cell
        assert "y" in cell
        assert "terrain_type" in cell
        assert "movement_cost" in cell
        assert "cover_value" in cell
        assert "visibility" in cell


# ---------------------------------------------------------------------------
# Empty terrain -- graceful handling of no terrain data
# ---------------------------------------------------------------------------

class TestEmptyTerrain:
    """Graceful handling of no terrain data."""

    @pytest.mark.unit
    def test_empty_terrain_map(self):
        tm = TerrainMap(map_bounds=100.0)
        assert tm.get_terrain_type(0.0, 0.0) == "open"

    @pytest.mark.unit
    def test_empty_line_of_sight(self):
        tm = TerrainMap(map_bounds=100.0)
        assert tm.line_of_sight((0.0, 0.0), (100.0, 100.0)) is True

    @pytest.mark.unit
    def test_empty_find_terrain(self):
        tm = TerrainMap(map_bounds=100.0)
        results = tm.find_terrain_of_type("road")
        assert results == []

    @pytest.mark.unit
    def test_empty_speed_modifier(self):
        tm = TerrainMap(map_bounds=100.0)
        assert tm.get_speed_modifier(0.0, 0.0, "rover") == pytest.approx(1.0)

    @pytest.mark.unit
    def test_empty_telemetry(self):
        tm = TerrainMap(map_bounds=100.0)
        data = tm.to_telemetry()
        assert data["cells"] == []

    @pytest.mark.unit
    def test_load_buildings_empty_list(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.load_buildings([])
        assert tm.get_terrain_type(0.0, 0.0) == "open"

    @pytest.mark.unit
    def test_load_roads_empty_list(self):
        tm = TerrainMap(map_bounds=100.0)
        tm.load_roads([])
        assert tm.get_terrain_type(0.0, 0.0) == "open"
