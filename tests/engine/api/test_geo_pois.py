"""Unit tests for GET /api/geo/pois -- POI endpoint on the geo router.

Tests the endpoint with fully mocked ``fetch_pois`` (no real network calls).
Validates query parameter validation, response structure, default values,
and caching behavior.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.geo import router

# The endpoint does a deferred import:
#   from engine.simulation.poi_data import fetch_pois
# so we mock at the source module level.
_FETCH_POIS_PATH = "engine.simulation.poi_data.fetch_pois"


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _make_poi(**overrides):
    """Create a fake POI object with sensible defaults."""
    defaults = {
        "name": "Dublin Library",
        "poi_type": "library",
        "category": "amenity",
        "address": "200 Civic Plaza",
        "lat": 37.7161,
        "lng": -121.9357,
        "local_x": 12.5,
        "local_y": -8.3,
        "osm_id": 123456,
    }
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPoisEndpointReturnsList:
    """GET /api/geo/pois?lat=...&lng=...&radius=400 returns a list."""

    def test_pois_endpoint_returns_list(self):
        pois = [_make_poi(), _make_poi(name="Circle K", poi_type="convenience", osm_id=789)]
        with patch(_FETCH_POIS_PATH, return_value=pois) as mock_fetch:
            client = TestClient(_make_app())
            resp = client.get("/api/geo/pois?lat=37.7161&lng=-121.9357&radius=400")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) == 2
            mock_fetch.assert_called_once_with(37.7161, -121.9357, 400.0)


# ---------------------------------------------------------------------------
# Missing / invalid parameters
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPoisMissingParams:
    """Missing lat/lng returns 422."""

    def test_missing_lat(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/pois?lng=-121.9357")
        assert resp.status_code == 422

    def test_missing_lng(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/pois?lat=37.7161")
        assert resp.status_code == 422

    def test_missing_both(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/pois")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Radius bounds
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPoisRadiusBounds:
    """radius < 50 or > 2000 returns 422."""

    def test_radius_too_small(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/pois?lat=37.71&lng=-121.93&radius=10")
        assert resp.status_code == 422

    def test_radius_too_large(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/pois?lat=37.71&lng=-121.93&radius=5000")
        assert resp.status_code == 422

    def test_radius_at_lower_bound(self):
        with patch(_FETCH_POIS_PATH, return_value=[]):
            client = TestClient(_make_app())
            resp = client.get("/api/geo/pois?lat=37.71&lng=-121.93&radius=50")
            assert resp.status_code == 200

    def test_radius_at_upper_bound(self):
        with patch(_FETCH_POIS_PATH, return_value=[]):
            client = TestClient(_make_app())
            resp = client.get("/api/geo/pois?lat=37.71&lng=-121.93&radius=2000")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPoisResponseStructure:
    """Each POI dict has the expected keys."""

    def test_pois_response_structure(self):
        poi = _make_poi()
        with patch(_FETCH_POIS_PATH, return_value=[poi]):
            client = TestClient(_make_app())
            resp = client.get("/api/geo/pois?lat=37.7161&lng=-121.9357")
            data = resp.json()
            assert len(data) == 1
            item = data[0]
            assert item["name"] == "Dublin Library"
            assert item["poi_type"] == "library"
            assert item["category"] == "amenity"
            assert item["address"] == "200 Civic Plaza"
            assert item["lat"] == pytest.approx(37.7161)
            assert item["lng"] == pytest.approx(-121.9357)
            assert item["local_x"] == pytest.approx(12.5)
            assert item["local_y"] == pytest.approx(-8.3)
            assert item["osm_id"] == 123456

    def test_response_keys_are_complete(self):
        """Every expected key is present in the response."""
        poi = _make_poi()
        expected_keys = {"name", "poi_type", "category", "address", "lat", "lng",
                         "local_x", "local_y", "osm_id"}
        with patch(_FETCH_POIS_PATH, return_value=[poi]):
            client = TestClient(_make_app())
            resp = client.get("/api/geo/pois?lat=37.71&lng=-121.93")
            item = resp.json()[0]
            assert set(item.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Empty results
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPoisEmptyArea:
    """Returns empty list for coords with no POIs."""

    def test_pois_empty_area(self):
        with patch(_FETCH_POIS_PATH, return_value=[]):
            client = TestClient(_make_app())
            resp = client.get("/api/geo/pois?lat=0.0&lng=0.0&radius=400")
            assert resp.status_code == 200
            assert resp.json() == []


# ---------------------------------------------------------------------------
# Default radius
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPoisDefaultRadius:
    """Omitting radius defaults to 400."""

    def test_pois_default_radius(self):
        with patch(_FETCH_POIS_PATH, return_value=[]) as mock_fetch:
            client = TestClient(_make_app())
            resp = client.get("/api/geo/pois?lat=37.71&lng=-121.93")
            assert resp.status_code == 200
            mock_fetch.assert_called_once_with(37.71, -121.93, 400.0)


# ---------------------------------------------------------------------------
# Valid coordinate types
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPoisValidCoordinates:
    """Returned lat/lng are floats in valid range."""

    def test_pois_valid_coordinates(self):
        poi = _make_poi(lat=37.7161, lng=-121.9357)
        with patch(_FETCH_POIS_PATH, return_value=[poi]):
            client = TestClient(_make_app())
            resp = client.get("/api/geo/pois?lat=37.7161&lng=-121.9357")
            item = resp.json()[0]
            assert isinstance(item["lat"], float)
            assert isinstance(item["lng"], float)
            assert -90 <= item["lat"] <= 90
            assert -180 <= item["lng"] <= 180


# ---------------------------------------------------------------------------
# Caching: mock verifies fetch_pois called each time
# (caching is internal to fetch_pois, not the endpoint)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPoisCachedResponse:
    """The endpoint delegates to fetch_pois which handles caching internally."""

    def test_pois_calls_fetch_pois_each_time(self):
        """Endpoint always calls fetch_pois -- caching is within fetch_pois."""
        poi = _make_poi()
        with patch(_FETCH_POIS_PATH, return_value=[poi]) as mock_fetch:
            client = TestClient(_make_app())
            # First call
            resp1 = client.get("/api/geo/pois?lat=37.71&lng=-121.93&radius=400")
            assert resp1.status_code == 200
            # Second call
            resp2 = client.get("/api/geo/pois?lat=37.71&lng=-121.93&radius=400")
            assert resp2.status_code == 200
            assert mock_fetch.call_count == 2
