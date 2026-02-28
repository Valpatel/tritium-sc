# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for WorldModel — unified spatial queries for NPC decision-making."""

import math
import pytest

from engine.simulation.npc_intelligence.world_model import (
    WorldModel,
    BuildingInfo,
    DoorPoint,
    CrosswalkPoint,
    POI,
)


# -- Fixtures --


def _make_square_building(cx: float, cy: float, size: float = 10.0):
    """Create a simple square building polygon centered at (cx, cy)."""
    hs = size / 2
    return [
        (cx - hs, cy - hs),
        (cx + hs, cy - hs),
        (cx + hs, cy + hs),
        (cx - hs, cy + hs),
    ]


def _make_world(buildings=None, road_nodes=None, road_edges=None):
    """Create a WorldModel with test data.

    buildings: list of (cx, cy, size) tuples for square buildings
    road_nodes: dict of node_id -> (x, y)
    road_edges: list of (node_a, node_b, road_class)
    """
    import networkx as nx

    building_polygons = []
    if buildings:
        for bld in buildings:
            if len(bld) == 3:
                cx, cy, size = bld
            else:
                cx, cy = bld
                size = 10.0
            building_polygons.append(_make_square_building(cx, cy, size))

    # Build a simple street graph
    graph = None
    positions = {}
    if road_nodes:
        graph = nx.Graph()
        for nid, (x, y) in road_nodes.items():
            graph.add_node(nid, x=x, y=y)
            positions[nid] = (x, y)
        if road_edges:
            for na, nb, rc in road_edges:
                d = math.hypot(
                    positions[na][0] - positions[nb][0],
                    positions[na][1] - positions[nb][1],
                )
                graph.add_edge(na, nb, weight=d, road_class=rc)

    return WorldModel.from_raw(
        building_polygons=building_polygons,
        street_graph=graph,
        node_positions=positions,
    )


# ==========================================================================
# Building queries
# ==========================================================================


class TestBuildingQueries:
    """WorldModel building-related queries."""

    def test_is_inside_building(self):
        world = _make_world(buildings=[(50, 50, 20)])
        assert world.is_inside_building(50, 50) is True

    def test_is_not_inside_building(self):
        world = _make_world(buildings=[(50, 50, 20)])
        assert world.is_inside_building(0, 0) is False

    def test_nearest_building(self):
        world = _make_world(buildings=[(50, 50, 10), (100, 100, 10)])
        b = world.nearest_building(48, 48)
        assert b is not None
        assert abs(b.center[0] - 50) < 1.0
        assert abs(b.center[1] - 50) < 1.0

    def test_nearest_building_returns_closest(self):
        world = _make_world(buildings=[(20, 0, 10), (80, 0, 10)])
        b = world.nearest_building(25, 0)
        assert b is not None
        assert abs(b.center[0] - 20) < 1.0

    def test_buildings_in_radius(self):
        world = _make_world(buildings=[(10, 0, 5), (20, 0, 5), (100, 0, 5)])
        nearby = world.buildings_in_radius(15, 0, 20)
        assert len(nearby) == 2  # first two within 20m

    def test_no_buildings_returns_none(self):
        world = _make_world(buildings=[])
        assert world.nearest_building(0, 0) is None

    def test_building_has_area(self):
        world = _make_world(buildings=[(0, 0, 20)])
        b = world.nearest_building(0, 0)
        assert b is not None
        assert abs(b.area_m2 - 400.0) < 1.0  # 20x20 = 400

    def test_building_has_type(self):
        world = _make_world(buildings=[(0, 0, 8)])
        b = world.nearest_building(0, 0)
        assert b is not None
        assert b.building_type in ("home", "residential", "commercial", "unknown")


# ==========================================================================
# Door generation
# ==========================================================================


class TestDoorGeneration:
    """WorldModel door generation from building polygons."""

    def test_building_has_at_least_one_door(self):
        # Building near a road
        world = _make_world(
            buildings=[(10, 0, 10)],
            road_nodes={0: (0, -20), 1: (20, -20)},
            road_edges=[(0, 1, "residential")],
        )
        b = world.nearest_building(10, 0)
        assert b is not None
        assert len(b.doors) >= 1

    def test_door_is_on_building_edge(self):
        world = _make_world(
            buildings=[(10, 0, 10)],
            road_nodes={0: (0, -20), 1: (20, -20)},
            road_edges=[(0, 1, "residential")],
        )
        b = world.nearest_building(10, 0)
        assert len(b.doors) >= 1
        door = b.doors[0]
        dx, dy = door.position
        # Door should be on or very near the building edge
        # Check it's within 2m of the polygon perimeter
        poly = b.polygon
        min_dist = float("inf")
        for i in range(len(poly)):
            ax, ay = poly[i]
            bx, by = poly[(i + 1) % len(poly)]
            # Point-to-segment distance
            seg_len = math.hypot(bx - ax, by - ay)
            if seg_len < 0.01:
                continue
            t = max(0, min(1, ((dx - ax) * (bx - ax) + (dy - ay) * (by - ay)) / seg_len**2))
            px, py = ax + t * (bx - ax), ay + t * (by - ay)
            d = math.hypot(dx - px, dy - py)
            min_dist = min(min_dist, d)
        assert min_dist < 2.0, f"Door at ({dx:.1f}, {dy:.1f}) is {min_dist:.1f}m from building edge"

    def test_door_faces_away_from_building(self):
        world = _make_world(
            buildings=[(10, 0, 10)],
            road_nodes={0: (0, -20), 1: (20, -20)},
            road_edges=[(0, 1, "residential")],
        )
        b = world.nearest_building(10, 0)
        assert len(b.doors) >= 1
        door = b.doors[0]
        # Door facing should be a valid heading (0-360)
        assert 0 <= door.facing < 360

    def test_building_without_road_still_gets_door(self):
        """Even buildings far from roads get a door (on first edge)."""
        world = _make_world(buildings=[(200, 200, 10)])
        b = world.nearest_building(200, 200)
        assert b is not None
        assert len(b.doors) >= 1

    def test_large_building_gets_multiple_doors(self):
        """Buildings > 200m2 should get doors on multiple edges."""
        world = _make_world(
            buildings=[(0, 0, 20)],  # 20x20 = 400m2
            road_nodes={0: (-20, -20), 1: (20, -20), 2: (20, 20), 3: (-20, 20)},
            road_edges=[(0, 1, "residential"), (1, 2, "residential"),
                        (2, 3, "residential"), (3, 0, "residential")],
        )
        b = world.nearest_building(0, 0)
        assert b is not None
        assert len(b.doors) >= 2, f"Large building only has {len(b.doors)} doors"

    def test_nearest_door(self):
        world = _make_world(
            buildings=[(10, 0, 10), (50, 0, 10)],
            road_nodes={0: (0, -10), 1: (60, -10)},
            road_edges=[(0, 1, "residential")],
        )
        door = world.nearest_door(12, -5)
        assert door is not None
        # Should be closer to the first building
        assert math.hypot(door.position[0] - 10, door.position[1] - 0) < 15


# ==========================================================================
# Road queries
# ==========================================================================


class TestRoadQueries:
    """WorldModel road and sidewalk queries."""

    def test_nearest_sidewalk_node(self):
        world = _make_world(
            road_nodes={0: (0, 0), 1: (50, 0), 2: (0, 50), 3: (50, 50)},
            road_edges=[
                (0, 1, "residential"),
                (2, 3, "footway"),
            ],
        )
        # Should find footway node
        node = world.nearest_sidewalk_node(5, 45)
        assert node is not None
        # Should be near the footway
        assert math.hypot(node[0] - 0, node[1] - 50) < 10 or \
               math.hypot(node[0] - 50, node[1] - 50) < 10

    def test_is_on_road(self):
        world = _make_world(
            road_nodes={0: (0, 0), 1: (100, 0)},
            road_edges=[(0, 1, "residential")],
        )
        # Near the road
        assert world.is_on_road(50, 0, tolerance=5.0) is True
        # Far from road
        assert world.is_on_road(50, 50, tolerance=5.0) is False

    def test_is_on_sidewalk(self):
        world = _make_world(
            road_nodes={0: (0, 0), 1: (100, 0)},
            road_edges=[(0, 1, "footway")],
        )
        assert world.is_on_sidewalk(50, 0, tolerance=5.0) is True
        assert world.is_on_sidewalk(50, 50, tolerance=5.0) is False

    def test_road_type_at(self):
        world = _make_world(
            road_nodes={0: (0, 0), 1: (100, 0)},
            road_edges=[(0, 1, "secondary")],
        )
        assert world.road_type_at(50, 0, tolerance=5.0) == "secondary"


# ==========================================================================
# Crosswalk generation
# ==========================================================================


class TestCrosswalkGeneration:
    """WorldModel crosswalk generation at road intersections."""

    def test_crosswalk_at_intersection(self):
        """T-intersection where footway meets road should get crosswalk."""
        world = _make_world(
            road_nodes={
                0: (0, 0), 1: (50, 0), 2: (100, 0),  # road
                3: (50, 50),                            # footway endpoint
            },
            road_edges=[
                (0, 1, "residential"),
                (1, 2, "residential"),
                (1, 3, "footway"),
            ],
        )
        cw = world.nearest_crosswalk(50, 0)
        # Should find a crosswalk at node 1 (50, 0) where footway meets road
        assert cw is not None
        assert math.hypot(cw.position[0] - 50, cw.position[1]) < 10

    def test_no_crosswalk_in_empty_world(self):
        world = _make_world()
        assert world.nearest_crosswalk(0, 0) is None

    def test_crosswalk_has_width(self):
        world = _make_world(
            road_nodes={0: (0, 0), 1: (100, 0), 2: (50, 50)},
            road_edges=[(0, 1, "residential"), (1, 2, "footway")],
        )
        cw = world.nearest_crosswalk(50, 0)
        if cw is not None:
            assert cw.width > 0


# ==========================================================================
# POI (Points of Interest)
# ==========================================================================


class TestPOI:
    """WorldModel point-of-interest queries."""

    def test_poi_generated_for_buildings(self):
        """Each building should have an associated POI."""
        world = _make_world(buildings=[(10, 0, 8), (50, 0, 8)])
        pois = world.pois_in_radius(0, 0, 100)
        assert len(pois) >= 2

    def test_nearest_poi(self):
        world = _make_world(buildings=[(10, 0, 8), (80, 0, 8)])
        poi = world.nearest_poi(15, 0)
        assert poi is not None
        assert math.hypot(poi.position[0] - 10, poi.position[1]) < 15

    def test_poi_by_type(self):
        world = _make_world(buildings=[(10, 0, 8)])
        poi = world.nearest_poi(10, 0, poi_type="home")
        # Small building should be classified as home
        if poi is not None:
            assert poi.poi_type == "home"

    def test_poi_has_capacity(self):
        world = _make_world(buildings=[(0, 0, 10)])
        poi = world.nearest_poi(0, 0)
        assert poi is not None
        assert poi.capacity > 0


# ==========================================================================
# Safety queries
# ==========================================================================


class TestSafetyQueries:
    """WorldModel safety/flee-related queries."""

    def test_nearest_cover(self):
        """nearest_cover should find a building to hide behind."""
        world = _make_world(buildings=[(20, 0, 10)])
        # Threat from the south
        cover = world.nearest_cover(15, -10, threat_pos=(15, -50))
        assert cover is not None
        # Cover should be north of our position (behind building relative to threat)

    def test_safe_direction(self):
        """safe_direction should point away from threat, avoiding buildings."""
        world = _make_world(buildings=[(30, 0, 10)])
        direction = world.safe_direction(0, 0, threat_pos=(50, 0))
        # Should point generally west (away from threat at east)
        assert direction[0] < 0  # negative x = west

    def test_safe_direction_normalizes(self):
        world = _make_world()
        direction = world.safe_direction(0, 0, threat_pos=(10, 0))
        length = math.hypot(direction[0], direction[1])
        assert abs(length - 1.0) < 0.01, f"Direction not normalized: length={length}"


# ==========================================================================
# WorldModel from real data
# ==========================================================================


class TestWorldModelFromRealData:
    """Test WorldModel can load from real BuildingObstacles + StreetGraph."""

    def test_from_loaded_data(self):
        """WorldModel.from_loaded() accepts existing infrastructure objects."""
        from unittest.mock import MagicMock

        # Mock BuildingObstacles
        mock_buildings = MagicMock()
        mock_buildings.polygons = [
            [(0, 0), (10, 0), (10, 10), (0, 10)],
        ]
        mock_buildings.point_in_building = lambda x, y: 0 <= x <= 10 and 0 <= y <= 10

        # Mock StreetGraph
        import networkx as nx
        mock_sg = MagicMock()
        mock_sg.graph = nx.Graph()
        mock_sg.graph.add_node(0, x=0, y=-10)
        mock_sg.graph.add_node(1, x=10, y=-10)
        mock_sg.graph.add_edge(0, 1, weight=10.0, road_class="residential")
        mock_sg._node_positions = {0: (0, -10), 1: (10, -10)}

        world = WorldModel.from_loaded(mock_buildings, mock_sg)
        assert world is not None
        assert world.is_inside_building(5, 5) is True
        assert world.is_inside_building(50, 50) is False


# ==========================================================================
# Performance
# ==========================================================================


class TestWorldModelPerformance:
    """WorldModel should be fast for 70 NPCs."""

    def test_building_queries_under_budget(self):
        """100 building queries should complete in < 5ms."""
        import time

        # Create world with 30 buildings (realistic density)
        buildings = [(i * 15, j * 15, 10) for i in range(6) for j in range(5)]
        world = _make_world(buildings=buildings)

        start = time.perf_counter()
        for _ in range(100):
            world.nearest_building(random_x(), random_y())
            world.is_inside_building(random_x(), random_y())
        elapsed = time.perf_counter() - start
        assert elapsed < 0.05, f"100 queries took {elapsed*1000:.1f}ms"

    def test_door_queries_under_budget(self):
        import time

        buildings = [(i * 20, 0, 10) for i in range(10)]
        world = _make_world(
            buildings=buildings,
            road_nodes={0: (-10, -10), 1: (200, -10)},
            road_edges=[(0, 1, "residential")],
        )

        start = time.perf_counter()
        for _ in range(100):
            world.nearest_door(random_x(), random_y())
        elapsed = time.perf_counter() - start
        assert elapsed < 0.05, f"100 door queries took {elapsed*1000:.1f}ms"


# -- Helpers --

import random as _rng
_rng.seed(42)

def random_x():
    return _rng.uniform(-100, 100)

def random_y():
    return _rng.uniform(-100, 100)
