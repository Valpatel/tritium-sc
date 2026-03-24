# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for city simulation pipeline.

Tests the full data flow: geo reference → city data → city sim plugin.
No external API calls — uses mocked Overpass responses and cached data.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.geo import (
    _estimate_building_height,
    _classify_building,
    _BUILDING_TYPE_HEIGHTS,
    _BUILDING_CATEGORIES,
    _ROAD_WIDTHS,
    router as geo_router,
)


def _make_app():
    app = FastAPI()
    app.include_router(geo_router)
    return app


# ---------------------------------------------------------------------------
# City Data Pipeline Integration
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCityDataPipeline:
    """Full pipeline: city-data endpoint → validation → response shape."""

    def test_city_data_returns_all_feature_types(self):
        """Verify city-data response has all expected fields."""
        with tempfile.TemporaryDirectory() as td:
            gis_cache = Path(td)
            import hashlib
            cache_key = "city_37.780000_-122.410000_200_v2"
            cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()[:16]

            city_data = {
                "center": {"lat": 37.78, "lng": -122.41},
                "radius": 200,
                "schema_version": 1,
                "buildings": [
                    {"id": 1, "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
                     "height": 15.0, "type": "apartments", "category": "residential",
                     "name": "Test Apts", "levels": 5, "roof_shape": "flat", "colour": ""}
                ],
                "roads": [
                    {"id": 2, "points": [[0, 0], [100, 0]], "class": "residential",
                     "name": "Main St", "width": 6.0, "lanes": 2, "surface": "asphalt",
                     "oneway": False, "bridge": False, "tunnel": False, "maxspeed": ""}
                ],
                "trees": [
                    {"pos": [5, 5], "species": "oak", "height": 8.0, "leaf_type": "broadleaved"}
                ],
                "landuse": [
                    {"id": 3, "polygon": [[0, 0], [50, 0], [50, 50], [0, 50]], "type": "park", "name": ""}
                ],
                "barriers": [
                    {"id": 4, "points": [[0, 0], [20, 0]], "type": "fence", "height": 1.2}
                ],
                "water": [
                    {"id": 5, "polygon": [[0, 0], [10, 0], [10, 10]], "points": None,
                     "type": "water", "name": "Pond"}
                ],
                "entrances": [
                    {"pos": [5, 0], "type": "main", "wheelchair": "yes", "name": "Front Door"}
                ],
                "pois": [
                    {"pos": [7, 7], "type": "restaurant", "name": "Joe's", "cuisine": "italian"}
                ],
                "stats": {
                    "buildings": 1, "roads": 1, "trees": 1, "landuse": 1,
                    "barriers": 1, "water": 1, "entrances": 1, "pois": 1,
                },
            }

            (gis_cache / f"{cache_hash}.json").write_text(json.dumps(city_data))

            with patch("app.routers.geo._GIS_CACHE", gis_cache):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/city-data?lat=37.78&lng=-122.41&radius=200")
                assert resp.status_code == 200
                data = resp.json()

                # Verify all feature types present
                assert len(data["buildings"]) == 1
                assert len(data["roads"]) == 1
                assert len(data["trees"]) == 1
                assert len(data["landuse"]) == 1
                assert len(data["barriers"]) == 1
                assert len(data["water"]) == 1
                assert len(data["entrances"]) == 1
                assert len(data["pois"]) == 1

                # Verify building detail
                b = data["buildings"][0]
                assert b["height"] == 15.0
                assert b["category"] == "residential"
                assert b["type"] == "apartments"
                assert b["name"] == "Test Apts"
                assert len(b["polygon"]) == 4

                # Verify road detail
                r = data["roads"][0]
                assert r["width"] == 6.0
                assert r["name"] == "Main St"
                assert len(r["points"]) == 2

                # Verify tree
                t = data["trees"][0]
                assert t["height"] == 8.0
                assert t["species"] == "oak"

                # Verify entrance
                e = data["entrances"][0]
                assert e["type"] == "main"
                assert e["wheelchair"] == "yes"

                # Verify POI
                p = data["pois"][0]
                assert p["type"] == "restaurant"
                assert p["cuisine"] == "italian"

    def test_city_data_status_for_cached(self):
        """Verify status endpoint reports cache state."""
        with tempfile.TemporaryDirectory() as td:
            gis_cache = Path(td)
            import hashlib
            cache_key = "city_37.780000_-122.410000_300_v2"
            cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()[:16]

            city_data = {
                "center": {"lat": 37.78, "lng": -122.41},
                "radius": 300,
                "schema_version": 1,
                "buildings": [],
                "roads": [],
                "trees": [],
                "landuse": [],
                "barriers": [],
                "water": [],
                "entrances": [],
                "pois": [],
                "stats": {"buildings": 0, "roads": 0, "trees": 0,
                          "landuse": 0, "barriers": 0, "water": 0,
                          "entrances": 0, "pois": 0},
            }

            (gis_cache / f"{cache_hash}.json").write_text(json.dumps(city_data))

            with patch("app.routers.geo._GIS_CACHE", gis_cache):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/city-data/status?lat=37.78&lng=-122.41&radius=300")
                assert resp.status_code == 200
                data = resp.json()
                assert data["cached"] is True
                assert "cache_age_s" in data
                assert data["schema_version"] == 1


# ---------------------------------------------------------------------------
# Building Classification Coverage
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuildingClassificationCoverage:
    """Verify all building types are properly classified."""

    def test_every_osm_type_has_height(self):
        """Every building type in our lookup should have a height default."""
        for btype, height in _BUILDING_TYPE_HEIGHTS.items():
            assert isinstance(height, (int, float)), f"{btype} height is not numeric"
            assert 1.0 <= height <= 200.0, f"{btype} height {height} out of range"

    def test_every_category_type_has_height(self):
        """Every categorized type should have a corresponding height."""
        missing = []
        for btype in _BUILDING_CATEGORIES:
            if btype not in _BUILDING_TYPE_HEIGHTS:
                missing.append(btype)
        assert missing == [], f"Types in categories but missing from heights: {missing}"

    def test_categories_are_valid(self):
        """All category values are from the expected set."""
        valid = {"residential", "commercial", "industrial", "civic", "religious", "utility"}
        for btype, cat in _BUILDING_CATEGORIES.items():
            assert cat in valid, f"{btype} has invalid category '{cat}'"

    def test_road_widths_positive(self):
        """All road widths are positive and reasonable."""
        for rtype, width in _ROAD_WIDTHS.items():
            assert 0.5 <= width <= 50.0, f"{rtype} width {width} out of range"

    def test_height_estimation_hierarchy(self):
        """Height tag > levels tag > type default > global default."""
        # Height tag wins
        assert _estimate_building_height({"height": "50", "building:levels": "3", "building": "garage"}) == 50.0
        # Levels tag wins over type
        assert _estimate_building_height({"building:levels": "10", "building": "garage"}) == pytest.approx(31.0)
        # Type default wins over global
        assert _estimate_building_height({"building": "cathedral"}) == 25.0
        # Global default
        assert _estimate_building_height({"building": "some_unknown_type"}) == 8.0


# ---------------------------------------------------------------------------
# City Sim Plugin
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCitySimPlugin:
    """Test the city sim plugin backend."""

    def test_plugin_import(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "plugins"))
        from city_sim.plugin import CitySimPlugin
        p = CitySimPlugin()
        assert p.plugin_id == "tritium.city-sim"
        assert p.name == "City Simulation"
        assert "routes" in p.capabilities
        assert "data_source" in p.capabilities

    def test_plugin_config_defaults(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "plugins"))
        from city_sim.plugin import CitySimPlugin
        p = CitySimPlugin()
        assert p._config["max_vehicles"] == 200
        assert p._config["max_pedestrians"] == 100
        assert p._config["radius"] == 300

    def test_plugin_lifecycle(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "plugins"))
        from city_sim.plugin import CitySimPlugin
        p = CitySimPlugin()
        assert p.healthy is False
        p.start()
        assert p.healthy is True
        p.stop()
        assert p.healthy is False


# ---------------------------------------------------------------------------
# City Sim Telemetry Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCitySimTelemetry:
    """Test the POST /api/city-sim/telemetry endpoint."""

    def _make_app(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "plugins"))
        from city_sim.routes import create_router
        from city_sim.plugin import CitySimPlugin
        app = FastAPI()
        plugin = CitySimPlugin()
        router = create_router(plugin)
        app.include_router(router)
        return app

    def test_telemetry_empty_body(self):
        client = TestClient(self._make_app())
        resp = client.post("/api/city-sim/telemetry", json={"vehicles": [], "pedestrians": []})
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 0

    def test_telemetry_vehicles_broadcast(self):
        """Vehicles are accepted and converted to target format."""
        captured = []

        async def fake_broadcast(event_type, data):
            captured.append((event_type, data))

        with patch("app.routers.ws.broadcast_amy_event", fake_broadcast):
            client = TestClient(self._make_app())
            resp = client.post("/api/city-sim/telemetry", json={
                "vehicles": [
                    {"id": "v1", "x": 10.5, "z": 20.3, "speed": 5.0, "heading": 90.0},
                    {"id": "v2", "x": -5.0, "z": 15.0, "speed": 3.0, "heading": 180.0},
                ],
                "pedestrians": [
                    {"id": "p1", "x": 1.0, "z": 2.0, "speed": 1.2, "heading": 45.0},
                ],
            })
            assert resp.status_code == 200
            assert resp.json()["accepted"] == 3
            assert len(captured) == 1
            assert captured[0][0] == "sim_telemetry_batch"
            batch = captured[0][1]
            assert len(batch) == 3
            assert batch[0]["target_id"] == "csim_vehicle_v1"
            assert batch[2]["target_id"] == "csim_pedestrian_p1"

    def test_telemetry_entity_to_target_format(self):
        """Verify _entity_to_target produces correct target dict shape."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "plugins"))
        from city_sim.routes import _entity_to_target

        entity = {"id": "v42", "x": 100.0, "z": -50.0, "speed": 12.5, "heading": 270.0}
        target = _entity_to_target(entity, "vehicle")

        assert target["target_id"] == "csim_vehicle_v42"
        assert target["position"] == [100.0, -50.0]
        assert target["heading"] == 270.0
        assert target["speed"] == 12.5
        assert target["health"] == 100.0
        assert target["status"] == "active"
        assert target["alliance"] == "neutral"
        assert target["source"] == "city_sim"
        assert target["classification"] == "vehicle"

    def test_telemetry_pedestrian_target_id(self):
        """Pedestrians get csim_pedestrian_ prefix."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "plugins"))
        from city_sim.routes import _entity_to_target

        target = _entity_to_target({"id": "p7", "x": 0, "z": 0}, "pedestrian")
        assert target["target_id"] == "csim_pedestrian_p7"
        assert target["classification"] == "pedestrian"

    def test_telemetry_defaults_for_missing_fields(self):
        """Missing optional fields default gracefully."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "plugins"))
        from city_sim.routes import _entity_to_target

        target = _entity_to_target({"id": "x1"}, "vehicle")
        assert target["position"] == [0.0, 0.0]
        assert target["heading"] == 0.0
        assert target["speed"] == 0.0


# ---------------------------------------------------------------------------
# City Sim API Routes (GET config, status, scenarios, demo-city, PUT config)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCitySimRoutes:
    """Test all city sim REST endpoints."""

    def _make_app(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "plugins"))
        from city_sim.routes import create_router
        from city_sim.plugin import CitySimPlugin
        app = FastAPI()
        plugin = CitySimPlugin()
        router = create_router(plugin)
        app.include_router(router)
        return app, plugin

    def test_get_config(self):
        app, plugin = self._make_app()
        client = TestClient(app)
        resp = client.get("/api/city-sim/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_vehicles"] == 200
        assert data["max_pedestrians"] == 100
        assert data["radius"] == 300

    def test_put_config_valid(self):
        app, plugin = self._make_app()
        client = TestClient(app)
        resp = client.put("/api/city-sim/config", json={"max_vehicles": 50, "radius": 500})
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_vehicles"] == 50
        assert data["radius"] == 500
        # Unchanged values persist
        assert data["max_pedestrians"] == 100

    def test_put_config_rejects_wrong_type(self):
        app, plugin = self._make_app()
        client = TestClient(app)
        resp = client.put("/api/city-sim/config", json={"max_vehicles": "not_a_number"})
        assert resp.status_code == 200
        data = resp.json()
        # Value should NOT have changed
        assert data["max_vehicles"] == 200
        assert "_rejected" in data
        assert "max_vehicles" in data["_rejected"]

    def test_put_config_ignores_unknown_keys(self):
        app, plugin = self._make_app()
        client = TestClient(app)
        resp = client.put("/api/city-sim/config", json={"unknown_key": 42})
        assert resp.status_code == 200
        data = resp.json()
        assert "unknown_key" not in data

    def test_get_status(self):
        app, plugin = self._make_app()
        client = TestClient(app)
        resp = client.get("/api/city-sim/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data
        assert "config" in data
        assert data["running"] is False  # not started

    def test_get_status_after_start(self):
        app, plugin = self._make_app()
        plugin.start()
        client = TestClient(app)
        resp = client.get("/api/city-sim/status")
        data = resp.json()
        assert data["running"] is True
        plugin.stop()

    def test_get_scenarios(self):
        app, _ = self._make_app()
        client = TestClient(app)
        resp = client.get("/api/city-sim/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert "scenarios" in data
        assert len(data["scenarios"]) == 5
        ids = {s["id"] for s in data["scenarios"]}
        assert "rush_hour" in ids
        assert "night_patrol" in ids
        assert "emergency" in ids

    def test_demo_city_returns_valid_schema(self):
        app, _ = self._make_app()
        client = TestClient(app)
        resp = client.get("/api/city-sim/demo-city?radius=200&seed=42")
        assert resp.status_code == 200
        data = resp.json()
        assert data["_procedural"] is True
        assert data["schema_version"] == 2
        assert len(data["buildings"]) > 0
        assert len(data["roads"]) > 0
        assert all(len(b["polygon"]) >= 3 for b in data["buildings"])

    def test_protest_endpoint(self):
        app, plugin = self._make_app()
        client = TestClient(app)
        # Mock broadcast
        from unittest.mock import patch, AsyncMock
        with patch("app.routers.ws.broadcast_amy_event", AsyncMock()):
            resp = client.post("/api/city-sim/protest", json={
                "plazaCenter": {"x": 10, "z": 20},
                "participantCount": 30,
                "legitimacy": 0.4,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["triggered"] == "protest"
        assert data["participants"] == 30
        assert data["legitimacy"] == 0.4

    def test_demo_city_different_seeds(self):
        app, _ = self._make_app()
        client = TestClient(app)
        r1 = client.get("/api/city-sim/demo-city?radius=200&seed=1").json()
        r2 = client.get("/api/city-sim/demo-city?radius=200&seed=99").json()
        # Different seeds should produce different building counts or layouts
        assert r1["buildings"] != r2["buildings"]
