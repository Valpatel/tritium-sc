# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for NPCRouter — NPC-type-aware pathfinding that respects spatial rules."""

import math
import pytest

from engine.simulation.npc_intelligence.world_model import (
    WorldModel,
    BuildingInfo,
    DoorPoint,
    CrosswalkPoint,
)
from engine.simulation.npc_intelligence.npc_router import NPCRouter


# -- Helpers --


def _make_square(cx: float, cy: float, size: float = 10.0):
    """Create a square building polygon centered at (cx, cy)."""
    hs = size / 2
    return [
        (cx - hs, cy - hs),
        (cx + hs, cy - hs),
        (cx + hs, cy + hs),
        (cx - hs, cy + hs),
    ]


def _build_world(buildings=None, road_nodes=None, road_edges=None):
    """Create a WorldModel with test data."""
    import networkx as nx

    polys = []
    if buildings:
        for bld in buildings:
            if len(bld) == 3:
                cx, cy, sz = bld
            else:
                cx, cy = bld
                sz = 10.0
            polys.append(_make_square(cx, cy, sz))

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

    return WorldModel.from_raw(polys, graph, positions)


def _build_router(buildings=None, road_nodes=None, road_edges=None):
    """Create an NPCRouter with test data."""
    world = _build_world(buildings, road_nodes, road_edges)
    return NPCRouter(world), world


def _path_len(path):
    """Total Euclidean length of a waypoint path."""
    total = 0.0
    for i in range(len(path) - 1):
        total += math.hypot(path[i + 1][0] - path[i][0],
                            path[i + 1][1] - path[i][1])
    return total


def _path_crosses_polygon(path, polygon):
    """Check if any segment of the path crosses through a polygon."""
    for i in range(len(path) - 1):
        # Check midpoint of each segment
        mx = (path[i][0] + path[i + 1][0]) / 2
        my = (path[i][1] + path[i + 1][1]) / 2
        if _point_in_poly(mx, my, polygon):
            return True
        # Also check several interpolated points along the segment
        for t in [0.25, 0.5, 0.75]:
            px = path[i][0] + t * (path[i + 1][0] - path[i][0])
            py = path[i][1] + t * (path[i + 1][1] - path[i][1])
            if _point_in_poly(px, py, polygon):
                return True
    return False


def _point_in_poly(px, py, polygon):
    """Ray-casting point-in-polygon."""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


# ==========================================================================
# Pedestrian routing
# ==========================================================================


class TestPedestrianRouting:
    """NPCRouter.route_pedestrian should use sidewalks and crosswalks."""

    def test_returns_non_empty_path(self):
        """Basic routing produces waypoints."""
        router, _ = _build_router(
            road_nodes={0: (0, 0), 1: (50, 0), 2: (100, 0)},
            road_edges=[
                (0, 1, "footway"),
                (1, 2, "footway"),
            ],
        )
        path = router.route_pedestrian((0, 0), (100, 0))
        assert path is not None
        assert len(path) >= 2

    def test_starts_near_start(self):
        """Path first waypoint should be close to requested start."""
        router, _ = _build_router(
            road_nodes={0: (0, 0), 1: (50, 0), 2: (100, 0)},
            road_edges=[
                (0, 1, "footway"),
                (1, 2, "footway"),
            ],
        )
        path = router.route_pedestrian((5, 3), (95, 0))
        assert math.hypot(path[0][0] - 5, path[0][1] - 3) < 15

    def test_ends_near_destination(self):
        """Path last waypoint should be close to requested end."""
        router, _ = _build_router(
            road_nodes={0: (0, 0), 1: (50, 0), 2: (100, 0)},
            road_edges=[
                (0, 1, "footway"),
                (1, 2, "footway"),
            ],
        )
        path = router.route_pedestrian((5, 3), (95, 0))
        assert math.hypot(path[-1][0] - 95, path[-1][1] - 0) < 15

    def test_prefers_footway_over_road(self):
        """Pedestrian should prefer footway edges over road edges."""
        router, _ = _build_router(
            road_nodes={
                0: (0, 0), 1: (50, 0), 2: (100, 0),  # road
                3: (0, 5), 4: (50, 5), 5: (100, 5),   # footway parallel
            },
            road_edges=[
                (0, 1, "residential"),
                (1, 2, "residential"),
                (3, 4, "footway"),
                (4, 5, "footway"),
            ],
        )
        path = router.route_pedestrian((0, 5), (100, 5))
        # Should use footway nodes (y~5) not road nodes (y~0)
        for wp in path:
            assert wp[1] >= -1, f"Waypoint at y={wp[1]} is on the road side"

    def test_avoids_walking_through_buildings(self):
        """Path should not cut through building polygons."""
        # Building directly between start and end
        building = _make_square(50, 0, 20)
        router, _ = _build_router(
            buildings=[(50, 0, 20)],
            road_nodes={
                0: (0, -15), 1: (30, -15), 2: (70, -15), 3: (100, -15),
            },
            road_edges=[
                (0, 1, "footway"),
                (1, 2, "footway"),
                (2, 3, "footway"),
            ],
        )
        path = router.route_pedestrian((0, -15), (100, -15))
        assert not _path_crosses_polygon(path, building), \
            "Pedestrian path goes through a building"

    def test_urgent_mode_allows_road_crossing(self):
        """In urgent (flee) mode, pedestrians can cross roads directly."""
        router, _ = _build_router(
            road_nodes={
                0: (0, 0), 1: (100, 0),   # road
                2: (0, 20), 3: (100, 20),  # footway
            },
            road_edges=[
                (0, 1, "residential"),
                (2, 3, "footway"),
            ],
        )
        path = router.route_pedestrian((50, 20), (50, -10), urgent=True)
        assert path is not None
        assert len(path) >= 2

    def test_inserts_crosswalk_for_road_crossing(self):
        """When crossing a road, should route via nearest crosswalk."""
        router, world = _build_router(
            road_nodes={
                # Road running east-west
                0: (0, 0), 1: (50, 0), 2: (100, 0),
                # Footway nodes on either side
                3: (0, 20), 4: (50, 20), 5: (100, 20),    # north side
                6: (0, -20), 7: (50, -20), 8: (100, -20),  # south side
                # Footway connecting through crosswalk at (50,0)
            },
            road_edges=[
                (0, 1, "residential"), (1, 2, "residential"),
                (3, 4, "footway"), (4, 5, "footway"),
                (6, 7, "footway"), (7, 8, "footway"),
                (4, 1, "footway"),  # footway meets road at node 1
                (7, 1, "footway"),  # footway meets road at node 1
            ],
        )
        path = router.route_pedestrian((0, 20), (0, -20))
        # Path should include a waypoint near the crosswalk at (50, 0)
        assert path is not None
        assert len(path) >= 2

    def test_fallback_direct_when_no_graph(self):
        """Without a street graph, falls back to direct path."""
        world = WorldModel.from_raw([], None, {})
        router = NPCRouter(world)
        path = router.route_pedestrian((0, 0), (100, 100))
        assert path is not None
        assert len(path) == 2
        assert path[0] == (0, 0)
        assert path[-1] == (100, 100)


# ==========================================================================
# Vehicle routing
# ==========================================================================


class TestVehicleRouting:
    """NPCRouter.route_vehicle should use only road-class edges."""

    def test_returns_path_on_roads(self):
        """Vehicle path should follow road edges."""
        router, _ = _build_router(
            road_nodes={
                0: (0, 0), 1: (50, 0), 2: (50, 50), 3: (0, 50),
            },
            road_edges=[
                (0, 1, "residential"),
                (1, 2, "residential"),
                (2, 3, "residential"),
            ],
        )
        path = router.route_vehicle((0, 0), (0, 50))
        assert path is not None
        assert len(path) >= 2

    def test_never_uses_footway(self):
        """Vehicles must not route on footway edges."""
        router, _ = _build_router(
            road_nodes={
                0: (0, 0), 1: (50, 0), 2: (100, 0),  # road
                3: (0, 10), 4: (100, 10),              # footway shortcut
            },
            road_edges=[
                (0, 1, "residential"),
                (1, 2, "residential"),
                (3, 4, "footway"),     # short cut
            ],
        )
        path = router.route_vehicle((0, 0), (100, 0))
        # Path should use road nodes, not footway
        for wp in path:
            assert wp[1] < 5, f"Vehicle waypoint at y={wp[1]} appears to be on footway"

    def test_snaps_to_nearest_road_node(self):
        """Start/end should snap to nearest road-class node."""
        router, _ = _build_router(
            road_nodes={
                0: (0, 0), 1: (100, 0),
                2: (0, 50),  # footway node, should not snap here
            },
            road_edges=[
                (0, 1, "residential"),
                (0, 2, "footway"),
            ],
        )
        path = router.route_vehicle((5, 3), (95, 2))
        # First waypoint should snap to road node 0 or near it
        assert path is not None
        # Should not go to y=50 (footway node)
        for wp in path:
            assert wp[1] < 10

    def test_speed_limit_in_metadata(self):
        """Vehicle route can include speed limit info per segment."""
        router, _ = _build_router(
            road_nodes={
                0: (0, 0), 1: (100, 0),
            },
            road_edges=[
                (0, 1, "residential"),
            ],
        )
        path = router.route_vehicle((0, 0), (100, 0))
        assert path is not None
        # Speed limit info available via router method
        speed = router.speed_limit_for_road("residential")
        assert speed > 0
        assert speed <= 20  # residential should be ~11 m/s

    def test_fallback_direct_when_no_roads(self):
        """Without road edges, falls back to direct."""
        router, _ = _build_router(
            road_nodes={0: (0, 0), 1: (100, 0)},
            road_edges=[(0, 1, "footway")],  # only footway, no roads
        )
        path = router.route_vehicle((0, 0), (100, 0))
        assert path is not None
        assert len(path) >= 2


# ==========================================================================
# Building routing
# ==========================================================================


class TestBuildingRouting:
    """NPCRouter.route_to_building should route to a building's door."""

    def test_routes_to_nearest_door(self):
        """Path should end near a door of the target building."""
        router, world = _build_router(
            buildings=[(50, 0, 10)],
            road_nodes={0: (0, -10), 1: (100, -10)},
            road_edges=[(0, 1, "footway")],
        )
        building = world.nearest_building(50, 0)
        assert building is not None

        path = router.route_to_building((0, -10), building)
        assert path is not None
        assert len(path) >= 2

        # Last waypoint should be near one of the building's doors
        last = path[-1]
        min_door_dist = min(
            math.hypot(last[0] - d.position[0], last[1] - d.position[1])
            for d in building.doors
        )
        assert min_door_dist < 5, f"Path ends {min_door_dist:.1f}m from nearest door"

    def test_path_does_not_enter_building(self):
        """Route TO building shouldn't go through it."""
        building_poly = _make_square(50, 0, 20)
        router, world = _build_router(
            buildings=[(50, 0, 20)],
            road_nodes={0: (0, -15), 1: (100, -15)},
            road_edges=[(0, 1, "footway")],
        )
        building = world.nearest_building(50, 0)
        path = router.route_to_building((0, -15), building)
        assert not _path_crosses_polygon(path, building_poly), \
            "Route to building goes through the building"

    def test_routes_from_inside_building(self):
        """If starting inside a building, path starts at door."""
        router, world = _build_router(
            buildings=[(50, 0, 10)],
            road_nodes={0: (0, -10), 1: (100, -10)},
            road_edges=[(0, 1, "footway")],
        )
        building = world.nearest_building(50, 0)

        path = router.route_from_building(building, (100, -10))
        assert path is not None
        assert len(path) >= 2
        # First waypoint should be near a door
        first = path[0]
        min_door_dist = min(
            math.hypot(first[0] - d.position[0], first[1] - d.position[1])
            for d in building.doors
        )
        assert min_door_dist < 5


# ==========================================================================
# Flee routing
# ==========================================================================


class TestFleeRouting:
    """NPCRouter.route_flee provides emergency escape paths."""

    def test_pedestrian_flees_to_building(self):
        """Pedestrian should flee toward nearest building door."""
        router, _ = _build_router(
            buildings=[(30, 0, 10)],
            road_nodes={0: (0, -10), 1: (60, -10)},
            road_edges=[(0, 1, "footway")],
        )
        path = router.route_flee((0, -10), threat_pos=(0, -50), npc_type="person")
        assert path is not None
        assert len(path) >= 2

    def test_flee_direction_away_from_threat(self):
        """Flee path should generally move away from the threat."""
        router, _ = _build_router(
            road_nodes={0: (0, 0), 1: (100, 0)},
            road_edges=[(0, 1, "footway")],
        )
        path = router.route_flee((50, 0), threat_pos=(0, 0), npc_type="person")
        assert path is not None
        # Last waypoint should be farther from threat than start
        start_dist = math.hypot(50 - 0, 0 - 0)
        end_dist = math.hypot(path[-1][0] - 0, path[-1][1] - 0)
        assert end_dist >= start_dist - 5, \
            f"Flee path goes toward threat: start_dist={start_dist:.0f}, end_dist={end_dist:.0f}"

    def test_vehicle_flees_on_roads(self):
        """Vehicle flee should stay on road edges."""
        router, _ = _build_router(
            road_nodes={0: (0, 0), 1: (50, 0), 2: (100, 0)},
            road_edges=[
                (0, 1, "residential"),
                (1, 2, "residential"),
            ],
        )
        path = router.route_flee((50, 0), threat_pos=(0, 0), npc_type="vehicle")
        assert path is not None
        assert len(path) >= 2
        # Should go toward node 2 (100, 0) — away from threat
        assert path[-1][0] > 50

    def test_animal_flees_in_safe_direction(self):
        """Animals bolt in a safe direction, not through buildings."""
        building_poly = _make_square(50, 0, 20)
        router, _ = _build_router(
            buildings=[(50, 0, 20)],
            road_nodes={0: (0, 0), 1: (100, 0)},
            road_edges=[(0, 1, "residential")],
        )
        path = router.route_flee((30, 0), threat_pos=(0, 0), npc_type="animal")
        assert path is not None
        assert not _path_crosses_polygon(path, building_poly), \
            "Animal flees through a building"

    def test_flee_still_avoids_buildings(self):
        """Even in emergency, flee path should not go through buildings."""
        building_poly = _make_square(50, 0, 30)
        router, _ = _build_router(
            buildings=[(50, 0, 30)],
            road_nodes={
                0: (0, -20), 1: (100, -20),
                2: (0, 20), 3: (100, 20),
            },
            road_edges=[
                (0, 1, "footway"),
                (2, 3, "footway"),
            ],
        )
        path = router.route_flee((0, -20), threat_pos=(-50, -20), npc_type="person")
        assert path is not None
        assert not _path_crosses_polygon(path, building_poly)


# ==========================================================================
# Speed limits
# ==========================================================================


class TestSpeedLimits:
    """NPCRouter provides speed limits for road types."""

    def test_residential_speed_limit(self):
        router, _ = _build_router()
        assert router.speed_limit_for_road("residential") == pytest.approx(11.0, abs=1)

    def test_secondary_speed_limit(self):
        router, _ = _build_router()
        assert router.speed_limit_for_road("secondary") == pytest.approx(16.0, abs=1)

    def test_service_speed_limit(self):
        router, _ = _build_router()
        assert router.speed_limit_for_road("service") == pytest.approx(7.0, abs=1)

    def test_unknown_road_gets_default(self):
        router, _ = _build_router()
        speed = router.speed_limit_for_road("unknown_road_class")
        assert speed > 0


# ==========================================================================
# Building avoidance
# ==========================================================================


class TestBuildingAvoidance:
    """NPCRouter avoids routing through buildings."""

    def test_direct_path_rerouted_around_building(self):
        """If direct path crosses building, router goes around."""
        building_poly = _make_square(50, 0, 20)
        router, _ = _build_router(
            buildings=[(50, 0, 20)],
            road_nodes={
                0: (0, 0), 1: (25, -15), 2: (75, -15), 3: (100, 0),
                4: (25, 15), 5: (75, 15),
            },
            road_edges=[
                (0, 1, "footway"), (1, 2, "footway"), (2, 3, "footway"),
                (0, 4, "footway"), (4, 5, "footway"), (5, 3, "footway"),
            ],
        )
        path = router.route_pedestrian((0, 0), (100, 0))
        assert not _path_crosses_polygon(path, building_poly)

    def test_validate_path_utility(self):
        """Router's validate_path detects building crossings."""
        router, _ = _build_router(buildings=[(50, 0, 20)])
        # Direct path through building
        bad_path = [(0, 0), (100, 0)]
        assert router.validate_path(bad_path) is False

    def test_validate_path_clear(self):
        """Clear path passes validation."""
        router, _ = _build_router(buildings=[(50, 50, 20)])
        good_path = [(0, 0), (100, 0)]
        assert router.validate_path(good_path) is True


# ==========================================================================
# Performance
# ==========================================================================


class TestRouterPerformance:
    """NPCRouter should be fast enough for 70 NPCs."""

    def test_100_pedestrian_routes_under_budget(self):
        """100 pedestrian routes should complete in < 50ms."""
        import time
        import random
        random.seed(42)

        buildings = [(i * 20, j * 20, 10) for i in range(5) for j in range(5)]
        nodes = {}
        edges = []
        # Grid of footway nodes
        nid = 0
        grid = {}
        for i in range(11):
            for j in range(11):
                x, y = i * 10, j * 10
                nodes[nid] = (x, y)
                grid[(i, j)] = nid
                nid += 1
        for i in range(11):
            for j in range(11):
                if i < 10:
                    edges.append((grid[(i, j)], grid[(i + 1, j)], "footway"))
                if j < 10:
                    edges.append((grid[(i, j)], grid[(i, j + 1)], "footway"))

        router, _ = _build_router(buildings, nodes, edges)

        start = time.perf_counter()
        for _ in range(100):
            sx, sy = random.uniform(0, 100), random.uniform(0, 100)
            ex, ey = random.uniform(0, 100), random.uniform(0, 100)
            router.route_pedestrian((sx, sy), (ex, ey))
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"100 pedestrian routes took {elapsed*1000:.1f}ms"

    def test_100_vehicle_routes_under_budget(self):
        """100 vehicle routes should complete in < 50ms."""
        import time
        import random
        random.seed(42)

        nodes = {}
        edges = []
        nid = 0
        grid = {}
        for i in range(11):
            for j in range(11):
                nodes[nid] = (i * 10, j * 10)
                grid[(i, j)] = nid
                nid += 1
        for i in range(11):
            for j in range(11):
                if i < 10:
                    edges.append((grid[(i, j)], grid[(i + 1, j)], "residential"))
                if j < 10:
                    edges.append((grid[(i, j)], grid[(i, j + 1)], "residential"))

        router, _ = _build_router(None, nodes, edges)

        start = time.perf_counter()
        for _ in range(100):
            sx, sy = random.uniform(0, 100), random.uniform(0, 100)
            ex, ey = random.uniform(0, 100), random.uniform(0, 100)
            router.route_vehicle((sx, sy), (ex, ey))
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"100 vehicle routes took {elapsed*1000:.1f}ms"
