"""Integration tests: pathfinding wired into SimulationEngine.

Verifies that the engine uses the pathfinder for hostile spawns,
unit dispatches, and rover patrol routes when a street graph is available.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.engine import SimulationEngine
from engine.simulation.target import SimulationTarget
from engine.tactical.obstacles import BuildingObstacles
from engine.tactical.street_graph import StreetGraph


# Reference point matching config.py defaults
REF_LAT = 37.7749
REF_LNG = -122.4194

# Mock Overpass roads
_MOCK_ROADS = {
    "elements": [
        {
            "type": "way",
            "id": 100001,
            "tags": {"highway": "residential", "name": "Oak Street"},
            "geometry": [
                {"lat": 37.7740, "lon": -122.4200},
                {"lat": 37.7749, "lon": -122.4200},
                {"lat": 37.7758, "lon": -122.4200},
            ],
        },
        {
            "type": "way",
            "id": 100002,
            "tags": {"highway": "residential", "name": "Elm Avenue"},
            "geometry": [
                {"lat": 37.7749, "lon": -122.4200},
                {"lat": 37.7749, "lon": -122.4194},
                {"lat": 37.7749, "lon": -122.4188},
            ],
        },
        {
            "type": "way",
            "id": 100003,
            "tags": {"highway": "residential", "name": "North Road"},
            "geometry": [
                {"lat": 37.7758, "lon": -122.4200},
                {"lat": 37.7758, "lon": -122.4194},
                {"lat": 37.7758, "lon": -122.4188},
            ],
        },
    ]
}


@pytest.fixture
def street_graph(tmp_path):
    """Pre-loaded street graph."""
    cache_dir = str(tmp_path / "sg_cache")
    with patch("engine.tactical.street_graph._fetch_roads") as mock_fetch:
        mock_fetch.return_value = _MOCK_ROADS["elements"]
        sg = StreetGraph()
        sg.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=cache_dir)
    return sg


@pytest.fixture
def obstacles():
    """Empty obstacles (no buildings)."""
    return BuildingObstacles()


@pytest.fixture
def engine():
    """SimulationEngine with a mock EventBus."""
    bus = EventBus()
    eng = SimulationEngine(bus, map_bounds=200.0)
    return eng


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEngineUsesPathfinder:
    """Engine should use pathfinder when street graph is available."""

    def test_engine_accepts_street_graph(self, engine, street_graph, obstacles):
        """Engine should accept and store a street graph."""
        engine.set_street_graph(street_graph)
        engine.set_obstacles(obstacles)
        assert engine._street_graph is street_graph
        assert engine._obstacles is obstacles

    def test_spawn_hostile_with_street_graph(self, engine, street_graph, obstacles):
        """When street graph is set, hostile spawn should use pathfinder for waypoints."""
        engine.set_street_graph(street_graph)
        engine.set_obstacles(obstacles)

        hostile = engine.spawn_hostile()
        assert hostile is not None
        assert hostile.alliance == "hostile"
        # Hostile should have waypoints
        assert len(hostile.waypoints) >= 1, "Hostile should have at least 1 waypoint"

    def test_spawn_hostile_without_street_graph(self, engine):
        """Without street graph, hostile spawn falls back to legacy waypoints."""
        hostile = engine.spawn_hostile()
        assert hostile is not None
        assert len(hostile.waypoints) >= 1


@pytest.mark.unit
class TestHostileSpawnsNearRoad:
    """Hostile spawn position should be at the map edge (road or not)."""

    def test_hostile_spawn_at_edge(self, engine, street_graph, obstacles):
        """Hostile should spawn near the map boundary."""
        engine.set_street_graph(street_graph)
        engine.set_obstacles(obstacles)

        hostile = engine.spawn_hostile()
        x, y = hostile.position
        # Should be near one of the edges (within 10m of +-200 boundary)
        at_edge = (
            abs(abs(x) - 200.0) < 10.0 or
            abs(abs(y) - 200.0) < 10.0
        )
        assert at_edge, f"Hostile spawned at ({x:.1f}, {y:.1f}), not near edge"


@pytest.mark.unit
class TestDispatchGeneratesRoadPath:
    """When a unit is dispatched, it should get a road-following path."""

    def test_rover_dispatch_with_graph(self, engine, street_graph, obstacles):
        """Dispatched rover should get road-following waypoints."""
        engine.set_street_graph(street_graph)
        engine.set_obstacles(obstacles)

        # Add a rover
        rover = SimulationTarget(
            target_id="test-rover-1",
            name="Test Rover",
            alliance="friendly",
            asset_type="rover",
            position=(-50.0, 0.0),
            speed=2.0,
        )
        engine.add_target(rover)

        # Dispatch to a position
        dest = (50.0, 0.0)
        engine.dispatch_unit("test-rover-1", dest)

        # Rover should now have waypoints
        assert len(rover.waypoints) >= 1, "Dispatched rover should have waypoints"

    def test_dispatch_nonexistent_unit(self, engine, street_graph, obstacles):
        """Dispatching a nonexistent unit should not crash."""
        engine.set_street_graph(street_graph)
        engine.set_obstacles(obstacles)
        # Should not raise
        engine.dispatch_unit("nonexistent-id", (50.0, 50.0))

    def test_dispatch_drone_direct(self, engine, street_graph, obstacles):
        """Dispatched drone should get direct path (no road following)."""
        engine.set_street_graph(street_graph)
        engine.set_obstacles(obstacles)

        drone = SimulationTarget(
            target_id="test-drone-1",
            name="Test Drone",
            alliance="friendly",
            asset_type="drone",
            position=(0.0, 0.0),
            speed=5.0,
        )
        engine.add_target(drone)
        engine.dispatch_unit("test-drone-1", (100.0, 100.0))

        # Drone should have a simple path
        assert len(drone.waypoints) >= 1


@pytest.mark.unit
class TestSimTickMovesRoverAlongRoad:
    """Ticking the engine should move a rover along its road path."""

    def test_rover_moves_toward_waypoint(self, engine, street_graph, obstacles):
        """After dispatch and several ticks, rover should move closer to destination."""
        engine.set_street_graph(street_graph)
        engine.set_obstacles(obstacles)

        rover = SimulationTarget(
            target_id="test-rover-2",
            name="Test Rover 2",
            alliance="friendly",
            asset_type="rover",
            position=(-50.0, 0.0),
            speed=2.0,
        )
        engine.add_target(rover)
        engine.dispatch_unit("test-rover-2", (50.0, 0.0))

        initial_pos = rover.position
        # Tick 10 times (1 second of sim time)
        for _ in range(10):
            rover.tick(0.1)

        # Rover should have moved
        moved_dist = math.hypot(
            rover.position[0] - initial_pos[0],
            rover.position[1] - initial_pos[1],
        )
        assert moved_dist > 0.5, f"Rover should have moved, but only moved {moved_dist:.2f}m"
