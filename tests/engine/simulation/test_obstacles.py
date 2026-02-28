# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for building obstacle detection from OpenStreetMap Overpass API.

TDD: These tests are written FIRST, before the implementation.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from engine.tactical.obstacles import BuildingObstacles


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Reference point matching config.py defaults
REF_LAT = 37.7749
REF_LNG = -122.4194

# Mock Overpass response with building footprints.
# Two buildings: a small house near origin and a larger building offset east.
# Building 1: roughly 10x10m square centered at about (5, 20) local coords.
# Building 2: roughly 20x10m rectangle centered at about (50, 30) local coords.
_MOCK_OVERPASS_BUILDINGS = {
    "elements": [
        {
            "type": "way",
            "id": 200001,
            "tags": {"building": "house", "name": "Small House"},
            "geometry": [
                {"lat": 37.77504, "lon": -122.41934},   # SW corner
                {"lat": 37.77504, "lon": -122.41928},   # SE corner
                {"lat": 37.77513, "lon": -122.41928},   # NE corner
                {"lat": 37.77513, "lon": -122.41934},   # NW corner
                {"lat": 37.77504, "lon": -122.41934},   # close polygon
            ],
        },
        {
            "type": "way",
            "id": 200002,
            "tags": {"building": "commercial"},
            "geometry": [
                {"lat": 37.77510, "lon": -122.41880},   # SW corner
                {"lat": 37.77510, "lon": -122.41858},   # SE corner
                {"lat": 37.77520, "lon": -122.41858},   # NE corner
                {"lat": 37.77520, "lon": -122.41880},   # NW corner
                {"lat": 37.77510, "lon": -122.41880},   # close polygon
            ],
        },
    ]
}


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Provide a temporary cache directory."""
    return str(tmp_path / "building_cache")


def _make_loaded_obstacles(temp_cache_dir: str) -> BuildingObstacles:
    """Helper: create and load obstacles with mock data."""
    with patch("engine.tactical.obstacles._fetch_buildings") as mock_fetch:
        mock_fetch.return_value = _MOCK_OVERPASS_BUILDINGS["elements"]
        obs = BuildingObstacles()
        obs.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=temp_cache_dir)
    return obs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildingObstaclesLoad:
    """Building footprints load and are stored as polygons."""

    def test_loads_polygons(self, temp_cache_dir):
        """After loading, should have polygons from mock data."""
        obs = _make_loaded_obstacles(temp_cache_dir)
        assert obs.polygons is not None
        assert len(obs.polygons) == 2, f"Expected 2 buildings, got {len(obs.polygons)}"

    def test_polygons_are_local_coords(self, temp_cache_dir):
        """Polygon vertices should be in local (x, z) meters, not lat/lng."""
        obs = _make_loaded_obstacles(temp_cache_dir)
        for poly in obs.polygons:
            for x, z in poly:
                # Local coords should be within the 300m radius
                assert abs(x) < 400, f"X={x} too large for local coords"
                assert abs(z) < 400, f"Z={z} too large for local coords"

    def test_offline_returns_empty(self, temp_cache_dir):
        """When API fails, polygons should be empty list, not None."""
        def failing_fetch(*args, **kwargs):
            raise ConnectionError("Overpass unreachable")

        with patch("engine.tactical.obstacles._fetch_buildings", side_effect=failing_fetch):
            obs = BuildingObstacles()
            obs.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=temp_cache_dir)

        assert obs.polygons == []

    def test_empty_response(self, temp_cache_dir):
        """Empty Overpass response produces empty polygon list."""
        with patch("engine.tactical.obstacles._fetch_buildings") as mock_fetch:
            mock_fetch.return_value = []
            obs = BuildingObstacles()
            obs.load(REF_LAT, REF_LNG, radius_m=300, cache_dir=temp_cache_dir)

        assert obs.polygons == []


@pytest.mark.unit
class TestPointInBuilding:
    """Ray-casting point-in-polygon test."""

    def test_point_inside_building(self, temp_cache_dir):
        """A point at the center of a known building should be detected."""
        obs = _make_loaded_obstacles(temp_cache_dir)
        # Building 1 center is roughly at local (5.3, 19) based on lat/lng offsets
        # Compute approximate center from the geometry:
        # lat center: (37.77504 + 37.77513)/2 = 37.775085 → y = (37.775085 - 37.7749) * 111320 = ~2.06m
        # lng center: (-122.41934 + -122.41928)/2 = -122.41931 → x = (-122.41931 - (-122.4194)) * 111320 * cos(37.7749) ≈ 0.79m
        # Actually let me compute more carefully:
        # y = (37.775085 - 37.7749) * 111320 = 0.001985 * 111320 = 220.97... nope
        # That gives ~2m, which seems small. Let me recalculate:
        # 37.77504 - 37.7749 = 0.00014, * 111320 = 15.6m
        # 37.77513 - 37.7749 = 0.00023, * 111320 = 25.6m
        # center y ≈ 20.6m
        # -122.41934 - (-122.4194) = -0.00006 → won't matter for sign
        # Actually: x = (lng - ref_lng) * meters_per_deg_lng
        # lng = -122.41931, ref = -122.4194
        # diff = -122.41931 - (-122.4194) = 0.00009
        # meters_per_deg_lng = 111320 * cos(37.7749°) ≈ 111320 * 0.7903 ≈ 87974
        # x ≈ 0.00009 * 87974 ≈ 7.9m
        # So center is roughly (7.9, 20.6) — let's test a point inside
        assert obs.point_in_building(7.9, 20.6) is True

    def test_point_outside_building(self, temp_cache_dir):
        """A point far from any building should not be detected."""
        obs = _make_loaded_obstacles(temp_cache_dir)
        # Point at origin (0, 0) — no buildings there
        assert obs.point_in_building(0.0, 0.0) is False

    def test_point_far_outside(self, temp_cache_dir):
        """A point far from any building is definitely outside."""
        obs = _make_loaded_obstacles(temp_cache_dir)
        assert obs.point_in_building(200.0, 200.0) is False

    def test_no_buildings_loaded(self):
        """If no buildings loaded, point_in_building always returns False."""
        obs = BuildingObstacles()
        assert obs.point_in_building(0.0, 0.0) is False


@pytest.mark.unit
class TestPathCrossesBuilding:
    """Line segment intersection with building polygons."""

    def test_path_through_building(self, temp_cache_dir):
        """A path that passes through a building should be detected."""
        obs = _make_loaded_obstacles(temp_cache_dir)
        # Path from west to east through building 1 (center at ~7.9, 20.6)
        waypoints = [(0.0, 20.6), (20.0, 20.6)]
        assert obs.path_crosses_building(waypoints) is True

    def test_path_around_building(self, temp_cache_dir):
        """A path that avoids all buildings should not be detected."""
        obs = _make_loaded_obstacles(temp_cache_dir)
        # Path along y=0, far south of both buildings
        waypoints = [(-50.0, 0.0), (50.0, 0.0)]
        assert obs.path_crosses_building(waypoints) is False

    def test_single_point_path(self, temp_cache_dir):
        """A single-point path can't cross a building (no segments)."""
        obs = _make_loaded_obstacles(temp_cache_dir)
        assert obs.path_crosses_building([(0.0, 0.0)]) is False

    def test_empty_path(self, temp_cache_dir):
        """An empty path can't cross anything."""
        obs = _make_loaded_obstacles(temp_cache_dir)
        assert obs.path_crosses_building([]) is False

    def test_no_buildings_loaded(self):
        """If no buildings loaded, path never crosses."""
        obs = BuildingObstacles()
        assert obs.path_crosses_building([(0.0, 0.0), (100.0, 100.0)]) is False
