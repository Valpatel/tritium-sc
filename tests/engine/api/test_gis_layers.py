# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for GIS infrastructure layer endpoints.

Tests the new Overpass-based endpoints:
  - /api/geo/layers/catalog — layer metadata catalog
  - /api/geo/layers/power — power lines and towers
  - /api/geo/layers/traffic — traffic signals and stop signs
  - /api/geo/layers/water — waterways, water towers, pipelines
  - /api/geo/layers/cable — telecom/utility lines
  - /api/geo/layers/building-heights — buildings with height data

All tests use mocked HTTP responses (no external API calls).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.geo import router


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Layer Catalog
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLayerCatalog:
    """GET /api/geo/layers/catalog — returns available GIS layers."""

    def test_catalog_returns_list(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 5  # power, traffic, water, cable, building-heights

    def test_catalog_entries_have_required_fields(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/catalog")
        data = resp.json()
        for entry in data:
            assert "id" in entry
            assert "name" in entry
            assert "type" in entry
            assert "color" in entry
            assert "endpoint" in entry

    def test_catalog_has_power_layer(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/catalog")
        ids = [e["id"] for e in resp.json()]
        assert "power-lines" in ids

    def test_catalog_has_traffic_layer(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/catalog")
        ids = [e["id"] for e in resp.json()]
        assert "traffic-signals" in ids

    def test_catalog_has_water_layer(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/catalog")
        ids = [e["id"] for e in resp.json()]
        assert "waterways" in ids

    def test_catalog_has_cable_layer(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/catalog")
        ids = [e["id"] for e in resp.json()]
        assert "telecom-lines" in ids

    def test_catalog_has_building_heights_layer(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/catalog")
        ids = [e["id"] for e in resp.json()]
        assert "building-heights" in ids

    def test_catalog_color_format(self):
        """All colors should be valid hex codes."""
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/catalog")
        for entry in resp.json():
            color = entry["color"]
            assert color.startswith("#"), f"Color {color} for {entry['id']} must be hex"
            assert len(color) in (4, 7), f"Color {color} for {entry['id']} has invalid length"

    def test_catalog_type_values(self):
        """Layer types must be one of: point, line, polygon."""
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/catalog")
        valid_types = {"point", "line", "polygon"}
        for entry in resp.json():
            assert entry["type"] in valid_types, \
                f"Layer {entry['id']} has invalid type: {entry['type']}"


# ---------------------------------------------------------------------------
# Power Lines
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPowerLinesEndpoint:
    """GET /api/geo/layers/power — power lines and towers."""

    def test_missing_params(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/power")
        assert resp.status_code == 422

    def test_cached_data_served(self):
        """Serve from disk cache if available."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[-121.93, 37.70], [-121.94, 37.71]]},
                    "properties": {"power": "line", "voltage": "115000"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            import hashlib
            cache_key = f"power_37.774900_-121.935800_500"
            cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
            (cache_dir / f"{cache_hash}.json").write_text(json.dumps(geojson))
            with patch("app.routers.geo._GIS_CACHE", cache_dir):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/power?lat=37.7749&lng=-121.9358&radius=500")
                assert resp.status_code == 200
                data = resp.json()
                assert data["type"] == "FeatureCollection"
                assert len(data["features"]) == 1

    def test_radius_validation_low(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/power?lat=37.77&lng=-121.93&radius=5")
        assert resp.status_code == 422

    def test_radius_validation_high(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/power?lat=37.77&lng=-121.93&radius=5000")
        assert resp.status_code == 422

    def test_overpass_query_failure(self):
        """When Overpass is down, return 502."""
        import httpx
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            mock_req = httpx.Request("POST", "https://overpass-api.de/api/interpreter")
            mock_response = httpx.Response(503, request=mock_req)
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
                "503", request=mock_req, response=mock_response,
            ))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._GIS_CACHE", cache_dir), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/power?lat=37.77&lng=-121.93&radius=500")
                assert resp.status_code == 502

    def test_overpass_empty_result(self):
        """Overpass returns no elements: get empty GeoJSON."""
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"elements": []})
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._GIS_CACHE", cache_dir), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/power?lat=37.77&lng=-121.93&radius=500")
                assert resp.status_code == 200
                data = resp.json()
                assert data["type"] == "FeatureCollection"
                assert len(data["features"]) == 0

    def test_overpass_line_element_converted(self):
        """Way elements from Overpass are converted to LineString GeoJSON features."""
        overpass_resp = {
            "elements": [
                {
                    "type": "way",
                    "id": 12345,
                    "tags": {"power": "line", "voltage": "115000"},
                    "geometry": [
                        {"lat": 37.70, "lon": -121.93},
                        {"lat": 37.71, "lon": -121.94},
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=overpass_resp)
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._GIS_CACHE", cache_dir), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/power?lat=37.77&lng=-121.93&radius=500")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["features"]) == 1
                feat = data["features"][0]
                assert feat["geometry"]["type"] == "LineString"
                assert feat["properties"]["power"] == "line"

    def test_overpass_node_element_converted(self):
        """Node elements from Overpass become Point GeoJSON features."""
        overpass_resp = {
            "elements": [
                {
                    "type": "node",
                    "id": 99999,
                    "lat": 37.705,
                    "lon": -121.935,
                    "tags": {"power": "tower"},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=overpass_resp)
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._GIS_CACHE", cache_dir), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/power?lat=37.77&lng=-121.93&radius=500")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["features"]) == 1
                feat = data["features"][0]
                assert feat["geometry"]["type"] == "Point"
                assert feat["properties"]["power"] == "tower"


# ---------------------------------------------------------------------------
# Traffic Signals
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTrafficEndpoint:
    """GET /api/geo/layers/traffic — traffic signals and stop signs."""

    def test_missing_params(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/traffic")
        assert resp.status_code == 422

    def test_cached_data(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-121.93, 37.70]},
                    "properties": {"highway": "traffic_signals"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            import hashlib
            cache_key = f"traffic_37.774900_-121.935800_500"
            cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
            (cache_dir / f"{cache_hash}.json").write_text(json.dumps(geojson))
            with patch("app.routers.geo._GIS_CACHE", cache_dir):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/traffic?lat=37.7749&lng=-121.9358&radius=500")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["features"]) == 1
                assert data["features"][0]["properties"]["highway"] == "traffic_signals"

    def test_traffic_signals_and_stop_signs(self):
        """Both traffic_signals and stop nodes are returned."""
        overpass_resp = {
            "elements": [
                {"type": "node", "id": 1, "lat": 37.70, "lon": -121.93, "tags": {"highway": "traffic_signals"}},
                {"type": "node", "id": 2, "lat": 37.71, "lon": -121.94, "tags": {"highway": "stop"}},
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=overpass_resp)
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._GIS_CACHE", cache_dir), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/traffic?lat=37.77&lng=-121.93&radius=500")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["features"]) == 2


# ---------------------------------------------------------------------------
# Water Infrastructure
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWaterEndpoint:
    """GET /api/geo/layers/water — waterways, water towers, pipelines."""

    def test_missing_params(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/water")
        assert resp.status_code == 422

    def test_waterway_converted(self):
        """Waterway ways become LineString features."""
        overpass_resp = {
            "elements": [
                {
                    "type": "way",
                    "id": 5000,
                    "tags": {"waterway": "stream"},
                    "geometry": [
                        {"lat": 37.70, "lon": -121.93},
                        {"lat": 37.71, "lon": -121.94},
                        {"lat": 37.72, "lon": -121.95},
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=overpass_resp)
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._GIS_CACHE", cache_dir), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/water?lat=37.77&lng=-121.93&radius=500")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["features"]) == 1
                feat = data["features"][0]
                assert feat["geometry"]["type"] == "LineString"
                assert feat["properties"]["waterway"] == "stream"

    def test_water_tower_node(self):
        """Water tower nodes become Point features."""
        overpass_resp = {
            "elements": [
                {"type": "node", "id": 5001, "lat": 37.705, "lon": -121.935, "tags": {"man_made": "water_tower"}},
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=overpass_resp)
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._GIS_CACHE", cache_dir), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/water?lat=37.77&lng=-121.93&radius=500")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["features"]) == 1
                assert data["features"][0]["geometry"]["type"] == "Point"


# ---------------------------------------------------------------------------
# Telecom / Cable Lines
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCableEndpoint:
    """GET /api/geo/layers/cable — telecom and utility lines."""

    def test_missing_params(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/cable")
        assert resp.status_code == 422

    def test_telecom_line_converted(self):
        overpass_resp = {
            "elements": [
                {
                    "type": "way",
                    "id": 8000,
                    "tags": {"utility": "telecom", "communication": "line"},
                    "geometry": [
                        {"lat": 37.70, "lon": -121.93},
                        {"lat": 37.71, "lon": -121.94},
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=overpass_resp)
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._GIS_CACHE", cache_dir), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/cable?lat=37.77&lng=-121.93&radius=500")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["features"]) == 1
                assert data["features"][0]["geometry"]["type"] == "LineString"


# ---------------------------------------------------------------------------
# Building Heights
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuildingHeightsEndpoint:
    """GET /api/geo/layers/building-heights — buildings with height data."""

    def test_missing_params(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/layers/building-heights")
        assert resp.status_code == 422

    def test_building_with_height(self):
        """Buildings with height tags are returned as Polygon features with height property."""
        overpass_resp = {
            "elements": [
                {
                    "type": "way",
                    "id": 9000,
                    "tags": {"building": "yes", "building:height": "12", "building:levels": "3"},
                    "geometry": [
                        {"lat": 37.700, "lon": -121.930},
                        {"lat": 37.700, "lon": -121.931},
                        {"lat": 37.701, "lon": -121.931},
                        {"lat": 37.701, "lon": -121.930},
                        {"lat": 37.700, "lon": -121.930},
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=overpass_resp)
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._GIS_CACHE", cache_dir), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/building-heights?lat=37.77&lng=-121.93&radius=500")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["features"]) == 1
                feat = data["features"][0]
                assert feat["geometry"]["type"] == "Polygon"
                assert feat["properties"]["height"] == 12.0
                assert feat["properties"]["levels"] == 3

    def test_building_without_explicit_height_uses_levels(self):
        """When building:height is missing but levels is present, estimate height."""
        overpass_resp = {
            "elements": [
                {
                    "type": "way",
                    "id": 9001,
                    "tags": {"building": "yes", "building:levels": "2"},
                    "geometry": [
                        {"lat": 37.700, "lon": -121.930},
                        {"lat": 37.700, "lon": -121.931},
                        {"lat": 37.701, "lon": -121.931},
                        {"lat": 37.700, "lon": -121.930},
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "gis"
            cache_dir.mkdir()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=overpass_resp)
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._GIS_CACHE", cache_dir), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/building-heights?lat=37.77&lng=-121.93&radius=500")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["features"]) == 1
                # 2 levels * 3m default = 6m
                assert data["features"][0]["properties"]["height"] == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# GeoJSON Helper Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOverpassToGeojson:
    """Test the _overpass_to_geojson helper function."""

    def test_import(self):
        """The helper function should be importable."""
        from app.routers.geo import _overpass_to_geojson
        assert callable(_overpass_to_geojson)

    def test_empty_elements(self):
        from app.routers.geo import _overpass_to_geojson
        result = _overpass_to_geojson([])
        assert result["type"] == "FeatureCollection"
        assert result["features"] == []

    def test_node_conversion(self):
        from app.routers.geo import _overpass_to_geojson
        elements = [{"type": "node", "id": 1, "lat": 37.7, "lon": -121.9, "tags": {"highway": "stop"}}]
        result = _overpass_to_geojson(elements)
        assert len(result["features"]) == 1
        feat = result["features"][0]
        assert feat["type"] == "Feature"
        assert feat["geometry"]["type"] == "Point"
        assert feat["geometry"]["coordinates"] == [-121.9, 37.7]

    def test_way_conversion_as_line(self):
        from app.routers.geo import _overpass_to_geojson
        elements = [{
            "type": "way", "id": 2,
            "tags": {"power": "line"},
            "geometry": [{"lat": 37.7, "lon": -121.9}, {"lat": 37.8, "lon": -121.8}],
        }]
        result = _overpass_to_geojson(elements)
        assert len(result["features"]) == 1
        assert result["features"][0]["geometry"]["type"] == "LineString"

    def test_way_conversion_as_polygon(self):
        """Closed ways become Polygon when as_polygon=True."""
        from app.routers.geo import _overpass_to_geojson
        elements = [{
            "type": "way", "id": 3,
            "tags": {"building": "yes"},
            "geometry": [
                {"lat": 37.7, "lon": -121.9},
                {"lat": 37.7, "lon": -121.8},
                {"lat": 37.8, "lon": -121.8},
                {"lat": 37.7, "lon": -121.9},
            ],
        }]
        result = _overpass_to_geojson(elements, as_polygon=True)
        assert len(result["features"]) == 1
        assert result["features"][0]["geometry"]["type"] == "Polygon"

    def test_way_without_geometry_skipped(self):
        from app.routers.geo import _overpass_to_geojson
        elements = [{"type": "way", "id": 4, "tags": {}}]
        result = _overpass_to_geojson(elements)
        assert len(result["features"]) == 0

    def test_tags_preserved(self):
        from app.routers.geo import _overpass_to_geojson
        elements = [{"type": "node", "id": 5, "lat": 37.7, "lon": -121.9,
                      "tags": {"power": "tower", "voltage": "69000"}}]
        result = _overpass_to_geojson(elements)
        props = result["features"][0]["properties"]
        assert props["power"] == "tower"
        assert props["voltage"] == "69000"
