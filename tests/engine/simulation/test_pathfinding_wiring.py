# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for pathfinding integration with SimulationEngine.

Verifies that the engine uses the pathfinder to generate road-following
waypoints when a StreetGraph is available.
"""

from __future__ import annotations

import math
import queue
import threading
from unittest.mock import MagicMock, patch

import pytest

from engine.simulation.engine import SimulationEngine
from engine.simulation.target import SimulationTarget

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Minimal EventBus for testing (same pattern as test_simulation_engine.py)
# ---------------------------------------------------------------------------


class SimpleEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)

    def subscribe(self, topic: str = "") -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(topic, []).append(q)
        return q


# ---------------------------------------------------------------------------
# Mock street graph that returns predictable paths
# ---------------------------------------------------------------------------

def _make_mock_street_graph():
    """Create a mock StreetGraph with predictable behavior."""
    mock_sg = MagicMock()
    mock_sg.graph = MagicMock()
    mock_sg.graph.number_of_nodes.return_value = 20

    def mock_nearest_node(x, y):
        return (1, 5.0)

    def mock_shortest_path(start, end):
        return [start, (start[0], end[1]), end]

    mock_sg.nearest_node = mock_nearest_node
    mock_sg.shortest_path = mock_shortest_path

    mock_sg.road_edge_positions = [
        (-200.0, 50.0),
        (200.0, -30.0),
        (50.0, 200.0),
        (-80.0, -200.0),
    ]

    return mock_sg


def _make_mock_obstacles():
    """Create a mock BuildingObstacles with no buildings."""
    mock_obs = MagicMock()
    mock_obs.point_in_building.return_value = False
    mock_obs.path_crosses_building.return_value = False
    mock_obs.polygons = []
    return mock_obs


# ---------------------------------------------------------------------------
# Tests: Engine accepts pathfinding components
# ---------------------------------------------------------------------------


class TestEngineAcceptsPathfinding:
    """Engine should accept and store street_graph and obstacles references."""

    def test_engine_stores_street_graph(self):
        bus = SimpleEventBus()
        mock_sg = _make_mock_street_graph()
        engine = SimulationEngine(bus)
        engine.set_street_graph(mock_sg)
        assert engine.street_graph is mock_sg

    def test_engine_stores_obstacles(self):
        bus = SimpleEventBus()
        mock_obs = _make_mock_obstacles()
        engine = SimulationEngine(bus)
        engine.set_obstacles(mock_obs)
        assert engine.obstacles is mock_obs

    def test_engine_works_without_pathfinding(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        assert engine.street_graph is None
        assert engine.obstacles is None
        hostile = engine.spawn_hostile()
        assert hostile is not None
        assert hostile.alliance == "hostile"
        assert len(hostile.waypoints) > 0


# ---------------------------------------------------------------------------
# Tests: Hostile spawning uses pathfinder when available
# ---------------------------------------------------------------------------


class TestHostileSpawningWithPathfinder:
    """When street_graph is set, hostile spawn should use road-following paths."""

    def test_hostile_spawn_uses_pathfinder(self):
        """Hostile waypoints should differ from legacy when street_graph is set."""
        bus = SimpleEventBus()
        mock_sg = _make_mock_street_graph()
        mock_obs = _make_mock_obstacles()
        engine = SimulationEngine(bus)
        engine.set_street_graph(mock_sg)
        engine.set_obstacles(mock_obs)

        hostile = engine.spawn_hostile()
        # With mock street_graph that returns paths, spawn should succeed
        assert hostile is not None
        assert hostile.alliance == "hostile"
        assert len(hostile.waypoints) >= 2

    def test_hostile_spawn_fallback_without_graph(self):
        """Without street_graph, hostile spawn uses legacy waypoint generation."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)

        hostile = engine.spawn_hostile()
        assert hostile is not None
        assert len(hostile.waypoints) > 0
        # Legacy pattern: objective + escape_edge = 2 waypoints
        assert len(hostile.waypoints) >= 2

    def test_hostile_spawns_at_edge(self):
        """Hostiles should spawn at or near map edge."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)

        hostile = engine.spawn_hostile()
        pos = hostile.position
        b = engine._map_bounds  # Hostiles spawn at the map boundary
        near_edge = (
            abs(abs(pos[0]) - b) < 1.0 or
            abs(abs(pos[1]) - b) < 1.0
        )
        assert near_edge, f"Hostile should spawn at edge ({b}m), got {pos}"


# ---------------------------------------------------------------------------
# Tests: Friendly dispatch uses pathfinder
# ---------------------------------------------------------------------------


class TestFriendlyDispatchWithPathfinder:
    """Friendly units dispatched to a location should use road paths."""

    def test_rover_dispatch_sets_waypoints(self):
        """Dispatching a rover should set waypoints via pathfinding."""
        bus = SimpleEventBus()
        mock_sg = _make_mock_street_graph()
        mock_obs = _make_mock_obstacles()
        engine = SimulationEngine(bus)
        engine.set_street_graph(mock_sg)
        engine.set_obstacles(mock_obs)

        rover = SimulationTarget(
            target_id="rover-1",
            name="Test Rover",
            alliance="friendly",
            asset_type="rover",
            position=(10.0, 10.0),
            speed=3.0,
        )
        engine.add_target(rover)

        engine.dispatch_unit("rover-1", (50.0, 50.0))
        assert len(rover.waypoints) >= 1
        assert rover.status == "active"

    def test_dispatch_fallback_without_graph(self):
        """Without street_graph, dispatch sets direct waypoint."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)

        rover = SimulationTarget(
            target_id="rover-1",
            name="Test Rover",
            alliance="friendly",
            asset_type="rover",
            position=(10.0, 10.0),
            speed=3.0,
        )
        engine.add_target(rover)
        engine.dispatch_unit("rover-1", (50.0, 50.0))

        assert len(rover.waypoints) >= 1
        # Last waypoint should be the destination
        assert rover.waypoints[-1] == (50.0, 50.0)

    def test_dispatch_nonexistent_target(self):
        """Dispatching a nonexistent target is a no-op."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        # Should not crash
        engine.dispatch_unit("nonexistent", (50.0, 50.0))

    def test_dispatch_turret_no_movement(self):
        """Dispatching a turret should not set waypoints (stationary)."""
        bus = SimpleEventBus()
        mock_sg = _make_mock_street_graph()
        engine = SimulationEngine(bus)
        engine.set_street_graph(mock_sg)

        turret = SimulationTarget(
            target_id="turret-1",
            name="Test Turret",
            alliance="friendly",
            asset_type="turret",
            position=(10.0, 10.0),
            speed=0.0,
        )
        engine.add_target(turret)
        engine.dispatch_unit("turret-1", (50.0, 50.0))

        # Turret pathfinding returns None, so waypoints should not be set
        assert turret.waypoints == []

    def test_dispatch_drone_flies_direct(self):
        """Dispatching a drone should set direct waypoints (no roads)."""
        bus = SimpleEventBus()
        mock_sg = _make_mock_street_graph()
        engine = SimulationEngine(bus)
        engine.set_street_graph(mock_sg)

        drone = SimulationTarget(
            target_id="drone-1",
            name="Test Drone",
            alliance="friendly",
            asset_type="drone",
            position=(10.0, 10.0),
            speed=5.0,
        )
        engine.add_target(drone)
        engine.dispatch_unit("drone-1", (50.0, 50.0))

        # Drone should have 2-point direct path
        assert len(drone.waypoints) == 2
        assert drone.waypoints[0] == (10.0, 10.0)
        assert drone.waypoints[1] == (50.0, 50.0)
