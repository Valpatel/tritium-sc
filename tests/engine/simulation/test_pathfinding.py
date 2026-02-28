# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for A* pathfinding with street graph and building obstacle awareness.

TDD: These tests are written FIRST, before the implementation.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

from engine.simulation.pathfinding import plan_path
from engine.tactical.obstacles import BuildingObstacles
from engine.tactical.street_graph import StreetGraph


# ---------------------------------------------------------------------------
# Fixtures: pre-built street graph and obstacles
# ---------------------------------------------------------------------------

# Reference point matching config.py defaults
REF_LAT = 37.7749
REF_LNG = -122.4194

# Mock Overpass roads (same as test_street_graph.py)
_MOCK_OVERPASS_ROADS = {
    "elements": [
        {
            "type": "way",
            "id": 100001,
            "tags": {"highway": "residential", "name": "Oak Street"},
            "geometry": [
                {"lat": 37.7750, "lon": -122.4195},
                {"lat": 37.7752, "lon": -122.4195},
                {"lat": 37.7754, "lon": -122.4195},
            ],
        },
        {
            "type": "way",
            "id": 100002,
            "tags": {"highway": "residential", "name": "Elm Avenue"},
            "geometry": [
                {"lat": 37.7752, "lon": -122.4195},
                {"lat": 37.7752, "lon": -122.4190},
                {"lat": 37.7752, "lon": -122.4185},
            ],
        },
        {
            "type": "way",
            "id": 100003,
            "tags": {"highway": "tertiary", "name": "Main Road"},
            "geometry": [
                {"lat": 37.7754, "lon": -122.4195},
                {"lat": 37.7754, "lon": -122.4190},
                {"lat": 37.7754, "lon": -122.4185},
            ],
        },
    ]
}

_MOCK_OVERPASS_BUILDINGS = {
    "elements": [
        {
            "type": "way",
            "id": 200001,
            "tags": {"building": "house"},
            "geometry": [
                {"lat": 37.77504, "lon": -122.41934},
                {"lat": 37.77504, "lon": -122.41928},
                {"lat": 37.77513, "lon": -122.41928},
                {"lat": 37.77513, "lon": -122.41934},
                {"lat": 37.77504, "lon": -122.41934},
            ],
        },
    ]
}


@pytest.fixture
def street_graph(tmp_path):
    """Pre-loaded street graph with mock data."""
    cache_dir = str(tmp_path / "sg_cache")
    with patch("engine.tactical.street_graph._fetch_roads") as mock_fetch:
        mock_fetch.return_value = _MOCK_OVERPASS_ROADS["elements"]
        sg = StreetGraph()
        sg.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=cache_dir)
    return sg


@pytest.fixture
def obstacles(tmp_path):
    """Pre-loaded building obstacles with mock data."""
    cache_dir = str(tmp_path / "obs_cache")
    with patch("engine.tactical.obstacles._fetch_buildings") as mock_fetch:
        mock_fetch.return_value = _MOCK_OVERPASS_BUILDINGS["elements"]
        obs = BuildingObstacles()
        obs.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=cache_dir)
    return obs


@pytest.fixture
def empty_obstacles():
    """Obstacles with no buildings loaded."""
    return BuildingObstacles()


# ---------------------------------------------------------------------------
# Tests: Rover (road-following)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRoverPathfinding:
    """Rovers should snap to roads and follow the street graph."""

    def test_rover_follows_roads(self, street_graph, obstacles):
        """Rover path should follow road segments via A* on street graph."""
        start = (-8.9, 11.0)  # near Oak Street south
        end = (70.0, 55.0)    # near Main Road east
        path = plan_path(start, end, "rover", street_graph, obstacles)
        assert path is not None, "Rover should find a path"
        assert len(path) >= 2, "Path should have at least 2 waypoints"

    def test_rover_waypoints_near_roads(self, street_graph, obstacles):
        """All rover waypoints should be near road nodes."""
        start = (-8.9, 11.0)
        end = (70.0, 55.0)
        path = plan_path(start, end, "rover", street_graph, obstacles)
        if path is None:
            pytest.skip("No path found")
        for wp in path:
            _, dist = street_graph.nearest_node(wp[0], wp[1])
            assert dist < 5.0, f"Rover waypoint ({wp[0]:.1f}, {wp[1]:.1f}) is {dist:.1f}m from road"

    def test_rover_fallback_when_no_graph(self, obstacles):
        """With no street graph, rover gets a direct path."""
        start = (0.0, 0.0)
        end = (50.0, 50.0)
        path = plan_path(start, end, "rover", None, obstacles)
        assert path is not None
        assert len(path) == 2, "Fallback path should be start + end"
        assert path[0] == start
        assert path[1] == end


# ---------------------------------------------------------------------------
# Tests: Drone (straight line)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDronePathfinding:
    """Drones ignore roads and buildings — straight line."""

    def test_drone_straight_line(self, street_graph, obstacles):
        """Drone should get a direct 2-point path."""
        start = (0.0, 0.0)
        end = (100.0, 100.0)
        path = plan_path(start, end, "drone", street_graph, obstacles)
        assert path is not None
        assert len(path) == 2
        assert path[0] == start
        assert path[1] == end

    def test_scout_drone_straight_line(self, street_graph, obstacles):
        """Scout drone also gets straight line."""
        path = plan_path((0, 0), (50, 50), "scout_drone", street_graph, obstacles)
        assert path is not None
        assert len(path) == 2


# ---------------------------------------------------------------------------
# Tests: Hostile (road approach then direct last 30m)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHostilePathfinding:
    """Hostile units: road-following approach, then direct for last 30m."""

    def test_hostile_uses_roads_then_direct(self, street_graph, obstacles):
        """Hostile path should start on roads then cut through for the last stretch."""
        start = (-8.9, 11.0)   # near a road
        end = (0.0, 0.0)       # objective near center
        path = plan_path(start, end, "person", street_graph, obstacles, alliance="hostile")
        assert path is not None
        assert len(path) >= 2, "Hostile path should have multiple waypoints"
        # Last waypoint should be near the objective
        d_end = math.hypot(path[-1][0] - end[0], path[-1][1] - end[1])
        assert d_end < 5.0, f"Last waypoint should be near objective, got {d_end:.1f}m"

    def test_hostile_fallback_no_graph(self, obstacles):
        """Without street graph, hostile gets direct path."""
        path = plan_path((-100, 0), (0, 0), "person", None, obstacles, alliance="hostile")
        assert path is not None
        assert len(path) == 2


# ---------------------------------------------------------------------------
# Tests: Turret (stationary)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTurretPathfinding:
    """Turrets don't move — no path."""

    def test_turret_no_path(self, street_graph, obstacles):
        """Turret should return None (stationary)."""
        path = plan_path((0, 0), (10, 10), "turret", street_graph, obstacles)
        assert path is None

    def test_heavy_turret_no_path(self, street_graph, obstacles):
        """Heavy turret also stationary."""
        path = plan_path((0, 0), (10, 10), "heavy_turret", street_graph, obstacles)
        assert path is None

    def test_missile_turret_no_path(self, street_graph, obstacles):
        """Missile turret also stationary."""
        path = plan_path((0, 0), (10, 10), "missile_turret", street_graph, obstacles)
        assert path is None


# ---------------------------------------------------------------------------
# Tests: Integration with SimulationEngine (future wiring)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPathfindingEdgeCases:
    """Edge cases and fallbacks."""

    def test_same_start_end(self, street_graph, obstacles):
        """Start == end should return a single-point path for non-turrets."""
        path = plan_path((10, 10), (10, 10), "rover", street_graph, obstacles)
        assert path is not None
        assert len(path) >= 1

    def test_unknown_unit_type_gets_direct(self, street_graph, obstacles):
        """Unknown unit types fall back to direct path."""
        path = plan_path((0, 0), (50, 50), "unknown_type", street_graph, obstacles)
        assert path is not None
        assert len(path) == 2
