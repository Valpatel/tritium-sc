# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for street graph extraction from OpenStreetMap Overpass API.

TDD: These tests are written FIRST, before the implementation.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# The module under test — will fail until implementation exists
from engine.tactical.street_graph import StreetGraph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Realistic Overpass response for a small area with roads.
# Three roads forming an intersection network:
#   Oak Street: runs north-south at lng -122.4195
#   Elm Avenue: runs east-west at lat 37.7752
#   Main Road: runs east-west at lat 37.7754
# Intersection at (37.7752, -122.4195) connects Oak and Elm.
# Intersection at (37.7754, -122.4195) connects Oak and Main.
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


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Provide a temporary cache directory."""
    return str(tmp_path / "street_cache")


# Reference point matching config.py defaults
REF_LAT = 37.7749
REF_LNG = -122.4194


def _make_loaded_graph(temp_cache_dir: str) -> StreetGraph:
    """Helper: create and load a StreetGraph with mock data."""
    with patch("engine.tactical.street_graph._fetch_roads") as mock_fetch:
        mock_fetch.return_value = _MOCK_OVERPASS_ROADS["elements"]
        sg = StreetGraph()
        sg.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=temp_cache_dir)
    return sg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStreetGraphHasNodesAndEdges:
    """test_street_graph_has_nodes_and_edges -- graph loads with mock data."""

    def test_graph_has_nodes(self, temp_cache_dir):
        """After loading, the graph should contain nodes (intersections/endpoints)."""
        sg = _make_loaded_graph(temp_cache_dir)
        assert sg.graph is not None
        assert len(sg.graph.nodes) > 0, "Graph should have at least one node"

    def test_graph_has_edges(self, temp_cache_dir):
        """After loading, the graph should contain edges (road segments)."""
        sg = _make_loaded_graph(temp_cache_dir)
        assert sg.graph is not None
        assert len(sg.graph.edges) > 0, "Graph should have at least one edge"

    def test_edge_weights_are_distances(self, temp_cache_dir):
        """Edge weights should represent distance in meters."""
        sg = _make_loaded_graph(temp_cache_dir)
        for u, v, data in sg.graph.edges(data=True):
            assert "weight" in data, f"Edge ({u}, {v}) should have a weight"
            assert data["weight"] > 0, f"Edge ({u}, {v}) weight should be positive"
            # Road segments in a 300m radius should be < 600m
            assert data["weight"] < 600, f"Edge ({u}, {v}) weight unreasonably large"

    def test_shared_points_create_intersections(self, temp_cache_dir):
        """Roads that share a lat/lng point should create connected graph nodes."""
        sg = _make_loaded_graph(temp_cache_dir)
        # Oak Street and Elm Avenue share (37.7752, -122.4195).
        # Oak Street and Main Road share (37.7754, -122.4195).
        # Graph should be connected (all three roads linked).
        import networkx as nx
        assert nx.is_connected(sg.graph), "Graph should be connected via shared intersections"


@pytest.mark.unit
class TestNearestNodeWithinRange:
    """test_nearest_node_within_range -- given a road point, nearest node is close."""

    def test_nearest_node_on_road(self, temp_cache_dir):
        """A point on a known road should have a nearest node within a few meters."""
        sg = _make_loaded_graph(temp_cache_dir)
        # The mock roads are near the reference point.
        # Oak Street at lat 37.7750 is about y=+11m from center (37.7749).
        # That road is at lng -122.4195, about x=-8.9m from center (-122.4194).
        node_id, dist = sg.nearest_node(-8.9, 11.0)
        assert node_id is not None, "Should find a nearest node"
        assert dist < 20.0, f"Nearest node should be < 20m from a road point, got {dist:.1f}m"

    def test_nearest_node_returns_none_for_empty_graph(self):
        """If graph is not loaded, nearest_node returns (None, inf)."""
        sg = StreetGraph()
        node_id, dist = sg.nearest_node(0.0, 0.0)
        assert node_id is None
        assert dist == float("inf")


@pytest.mark.unit
class TestShortestPathReturnsWaypoints:
    """test_shortest_path_returns_waypoints -- A* path has multiple segments."""

    def test_path_has_waypoints(self, temp_cache_dir):
        """A path between two distant points should have multiple intermediate waypoints."""
        sg = _make_loaded_graph(temp_cache_dir)
        # Start near Oak Street south end, end near Main Road east end.
        # These require traversing Oak + Main = at least 3 waypoints.
        start = (-8.9, 11.0)   # near Oak Street at 37.7750
        end = (70.0, 55.0)     # near Main Road at 37.7754, -122.4185

        path = sg.shortest_path(start, end)
        assert path is not None, "Should find a path"
        assert len(path) >= 2, f"Path should have at least 2 waypoints, got {len(path)}"

    def test_path_returns_none_when_no_graph(self):
        """If graph is not loaded, shortest_path returns None."""
        sg = StreetGraph()
        path = sg.shortest_path((0, 0), (10, 10))
        assert path is None

    def test_path_start_and_end_near_requested(self, temp_cache_dir):
        """Path endpoints should be near the requested start and end."""
        sg = _make_loaded_graph(temp_cache_dir)
        start = (-8.9, 11.0)
        end = (70.0, 55.0)
        path = sg.shortest_path(start, end)
        if path is not None and len(path) >= 2:
            d_start = math.hypot(path[0][0] - start[0], path[0][1] - start[1])
            d_end = math.hypot(path[-1][0] - end[0], path[-1][1] - end[1])
            assert d_start < 50.0, f"Path start too far from requested: {d_start:.1f}m"
            assert d_end < 50.0, f"Path end too far from requested: {d_end:.1f}m"


@pytest.mark.unit
class TestPathStaysNearRoads:
    """test_path_stays_near_roads -- all waypoints within 5m of a road."""

    def test_waypoints_near_road_nodes(self, temp_cache_dir):
        """Every waypoint on the path should be at or very near a graph node."""
        sg = _make_loaded_graph(temp_cache_dir)
        start = (-8.9, 11.0)
        end = (70.0, 55.0)
        path = sg.shortest_path(start, end)
        if path is None:
            pytest.skip("No path found with mock data")

        for wp in path:
            _, dist = sg.nearest_node(wp[0], wp[1])
            assert dist < 5.0, (
                f"Waypoint ({wp[0]:.1f}, {wp[1]:.1f}) is {dist:.1f}m from nearest road node"
            )


@pytest.mark.unit
class TestCachingWorks:
    """test_caching_works -- second load is fast and uses cache."""

    def test_cache_saves_and_loads(self, temp_cache_dir):
        """After first load, cache file exists. Second load should not call API."""
        call_count = 0

        def counting_fetch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _MOCK_OVERPASS_ROADS["elements"]

        with patch("engine.tactical.street_graph._fetch_roads", side_effect=counting_fetch):
            sg1 = StreetGraph()
            sg1.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=temp_cache_dir)
            assert call_count == 1, "First load should call API"

            sg2 = StreetGraph()
            sg2.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=temp_cache_dir)
            assert call_count == 1, "Second load should use cache, not call API"
            assert sg2.graph is not None
            assert len(sg2.graph.nodes) > 0

    def test_expired_cache_refetches(self, temp_cache_dir):
        """Expired cache (>24h) should trigger a re-fetch."""
        call_count = 0

        def counting_fetch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _MOCK_OVERPASS_ROADS["elements"]

        with patch("engine.tactical.street_graph._fetch_roads", side_effect=counting_fetch):
            sg = StreetGraph()
            sg.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=temp_cache_dir)
            assert call_count == 1

            # Manually age the cache file
            cache_dir = Path(temp_cache_dir)
            pkl_files = list(cache_dir.glob("*.pkl"))
            assert len(pkl_files) > 0, "Cache file should exist"
            for f in pkl_files:
                old_time = time.time() - 25 * 3600
                os.utime(f, (old_time, old_time))

            sg2 = StreetGraph()
            sg2.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=temp_cache_dir)
            assert call_count == 2, "Expired cache should trigger re-fetch"


@pytest.mark.unit
class TestOfflineFallback:
    """test_offline_fallback -- returns None when API unreachable."""

    def test_returns_none_on_api_failure(self, temp_cache_dir):
        """When Overpass API is unreachable, load should return gracefully."""
        def failing_fetch(*args, **kwargs):
            raise ConnectionError("Overpass API unreachable")

        with patch("engine.tactical.street_graph._fetch_roads", side_effect=failing_fetch):
            sg = StreetGraph()
            sg.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=temp_cache_dir)

        assert sg.graph is None
        node_id, dist = sg.nearest_node(0.0, 0.0)
        assert node_id is None
        path = sg.shortest_path((0, 0), (10, 10))
        assert path is None

    def test_returns_none_on_empty_response(self, temp_cache_dir):
        """When Overpass returns no elements, graph is None."""
        def empty_fetch(*args, **kwargs):
            return []

        with patch("engine.tactical.street_graph._fetch_roads", side_effect=empty_fetch):
            sg = StreetGraph()
            sg.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=temp_cache_dir)

        assert sg.graph is None
