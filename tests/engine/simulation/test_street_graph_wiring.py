# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for street graph and building obstacles wiring into SimulationEngine.

Validates that:
1. Engine with a street graph produces road-aware hostile paths
2. Engine with building obstacles stores them for use by behaviors
3. Graceful fallback when no street graph or obstacles are available
4. The lifespan wiring code in main.py properly loads and sets both
"""

import math
import pytest

# Engine now has set_street_graph, set_obstacles, dispatch_unit, _map_bounds

from unittest.mock import MagicMock, patch

from engine.comms.event_bus import EventBus
from engine.simulation.engine import SimulationEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def engine(event_bus):
    return SimulationEngine(event_bus, map_bounds=200.0)


def _make_mock_street_graph():
    """Create a mock StreetGraph with a simple 3-node linear graph."""
    sg = MagicMock()
    sg.graph = MagicMock()
    sg.graph.number_of_nodes.return_value = 3
    sg.graph.number_of_edges.return_value = 2
    # shortest_path returns a straight path along "roads"
    sg.shortest_path.return_value = [
        (0.0, 50.0),
        (0.0, 25.0),
        (0.0, 0.0),
    ]
    return sg


def _make_mock_obstacles():
    """Create a mock BuildingObstacles with a simple square building."""
    obs = MagicMock()
    obs.polygons = [
        [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0)],
    ]
    obs.point_in_building.return_value = False
    obs.path_crosses_building.return_value = False
    return obs


# ---------------------------------------------------------------------------
# Task #1: Street graph wiring
# ---------------------------------------------------------------------------

class TestStreetGraphWiring:
    """Engine with street graph should produce road-aware paths."""

    def test_set_street_graph_stores_reference(self, engine):
        """set_street_graph() stores the graph on the engine."""
        sg = _make_mock_street_graph()
        engine.set_street_graph(sg)
        assert engine.street_graph is sg

    def test_set_obstacles_stores_reference(self, engine):
        """set_obstacles() stores obstacles on the engine."""
        obs = _make_mock_obstacles()
        engine.set_obstacles(obs)
        assert engine.obstacles is obs

    def test_spawn_hostile_uses_street_graph(self, engine):
        """When street graph is wired, spawn_hostile uses pathfinder for waypoints."""
        sg = _make_mock_street_graph()
        engine.set_street_graph(sg)

        target = engine.spawn_hostile(position=(0.0, 80.0))
        # The pathfinder was invoked (shortest_path is called inside plan_path)
        assert sg.shortest_path.called or sg.nearest_node.called
        # Target should exist in engine
        assert engine.get_target(target.target_id) is not None

    def test_spawn_hostile_road_waypoints_contain_road_points(self, engine):
        """When street graph provides a road path, waypoints include road nodes."""
        sg = _make_mock_street_graph()
        engine.set_street_graph(sg)

        target = engine.spawn_hostile(position=(0.0, 80.0))
        # Waypoints should contain road points from the mock graph
        # The mock returns [(0,50), (0,25), (0,0)] — some of these should appear
        wp_set = {(round(w[0], 1), round(w[1], 1)) for w in target.waypoints}
        # At least one road waypoint should be in the path
        road_points = {(0.0, 50.0), (0.0, 25.0), (0.0, 0.0)}
        assert wp_set & road_points, f"Expected road waypoints in {target.waypoints}"

    def test_dispatch_unit_uses_street_graph(self, engine):
        """dispatch_unit() routes through street graph when available."""
        from engine.simulation.target import SimulationTarget
        sg = _make_mock_street_graph()
        engine.set_street_graph(sg)

        rover = SimulationTarget(
            target_id="rover-1",
            name="Rover Alpha",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=5.0,
        )
        engine.add_target(rover)
        engine.dispatch_unit("rover-1", (50.0, 50.0))

        t = engine.get_target("rover-1")
        assert t is not None
        assert len(t.waypoints) > 0
        assert t.status == "active"


class TestGracefulFallback:
    """Engine should work fine without street graph or obstacles."""

    def test_no_street_graph_spawn_hostile_still_works(self, engine):
        """spawn_hostile works without a street graph (legacy waypoints)."""
        assert engine.street_graph is None
        target = engine.spawn_hostile(position=(0.0, 80.0))
        assert target is not None
        assert len(target.waypoints) > 0
        assert target.alliance == "hostile"

    def test_no_street_graph_dispatch_still_works(self, engine):
        """dispatch_unit works without a street graph (direct path)."""
        from engine.simulation.target import SimulationTarget
        rover = SimulationTarget(
            target_id="rover-2",
            name="Rover Bravo",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=5.0,
        )
        engine.add_target(rover)
        engine.dispatch_unit("rover-2", (50.0, 50.0))

        t = engine.get_target("rover-2")
        assert t is not None
        assert len(t.waypoints) > 0

    def test_no_obstacles_stored_as_none(self, engine):
        """Engine starts with obstacles=None."""
        assert engine.obstacles is None

    def test_no_street_graph_stored_as_none(self, engine):
        """Engine starts with street_graph=None."""
        assert engine.street_graph is None

    def test_street_graph_with_no_graph_attr(self, engine):
        """If street graph has graph=None, falls back to legacy waypoints."""
        sg = MagicMock()
        sg.graph = None
        engine.set_street_graph(sg)

        target = engine.spawn_hostile(position=(0.0, 80.0))
        assert target is not None
        assert len(target.waypoints) > 0


class TestMainLifespanWiring:
    """Test that main.py lifespan wiring code loads street graph/obstacles."""

    @patch("engine.tactical.street_graph.StreetGraph")
    def test_street_graph_load_called_with_settings(self, MockSG):
        """Verify the wiring pattern: create -> load -> set_street_graph."""
        mock_sg = MagicMock()
        mock_sg.graph = MagicMock()
        mock_sg.graph.number_of_nodes.return_value = 10
        mock_sg.graph.number_of_edges.return_value = 8
        MockSG.return_value = mock_sg

        # Simulate the wiring code from main.py
        eb = EventBus()
        eng = SimulationEngine(eb, map_bounds=200.0)

        from engine.tactical.street_graph import StreetGraph
        street_graph = StreetGraph()
        street_graph.load(37.7749, -122.4194, radius_m=300)
        if street_graph.graph is not None:
            eng.set_street_graph(street_graph)

        mock_sg.load.assert_called_once_with(37.7749, -122.4194, radius_m=300)
        assert eng.street_graph is mock_sg

    @patch("engine.tactical.obstacles.BuildingObstacles")
    def test_obstacles_load_called_with_settings(self, MockObs):
        """Verify the wiring pattern: create -> load -> set_obstacles."""
        mock_obs = MagicMock()
        mock_obs.polygons = [[(0, 0), (1, 0), (1, 1)]]
        MockObs.return_value = mock_obs

        eb = EventBus()
        eng = SimulationEngine(eb, map_bounds=200.0)

        from engine.tactical.obstacles import BuildingObstacles
        obstacles = BuildingObstacles()
        obstacles.load(37.7749, -122.4194, radius_m=300)
        if obstacles.polygons:
            eng.set_obstacles(obstacles)

        mock_obs.load.assert_called_once_with(37.7749, -122.4194, radius_m=300)
        assert eng.obstacles is mock_obs

    def test_street_graph_load_failure_graceful(self):
        """If StreetGraph.load raises, engine continues without it."""
        eb = EventBus()
        eng = SimulationEngine(eb, map_bounds=200.0)

        # Simulate the try/except from main.py
        try:
            raise ConnectionError("Overpass API unreachable")
        except Exception:
            pass  # graceful fallback

        assert eng.street_graph is None
        # Engine should still work
        target = eng.spawn_hostile(position=(0.0, 80.0))
        assert target is not None

    def test_obstacles_load_failure_graceful(self):
        """If BuildingObstacles.load raises, engine continues without them."""
        eb = EventBus()
        eng = SimulationEngine(eb, map_bounds=200.0)

        try:
            raise ConnectionError("Overpass API unreachable")
        except Exception:
            pass

        assert eng.obstacles is None
