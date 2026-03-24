# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for GIS Layers plugin — providers, plugin lifecycle, and API routes."""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import MagicMock

from plugins.gis_layers.providers import (
    BBox,
    BuildingFootprintProvider,
    OSMTileProvider,
    SatelliteProvider,
    TerrainProvider,
)
from plugins.gis_layers.plugin import GISLayersPlugin


# ---------------------------------------------------------------------------
# BBox
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBBox:
    def test_from_string_valid(self):
        bbox = BBox.from_string("10.0,48.0,10.1,48.1")
        assert bbox.west == 10.0
        assert bbox.south == 48.0
        assert bbox.east == 10.1
        assert bbox.north == 48.1

    def test_from_string_invalid_count(self):
        with pytest.raises(ValueError, match="exactly 4"):
            BBox.from_string("10.0,48.0,10.1")

    def test_from_string_not_numbers(self):
        with pytest.raises(ValueError):
            BBox.from_string("a,b,c,d")

    def test_from_string_negative_coords(self):
        bbox = BBox.from_string("-122.42,37.77,-122.41,37.78")
        assert bbox.west == -122.42
        assert bbox.north == 37.78


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOSMTileProvider:
    def test_identity(self):
        p = OSMTileProvider()
        assert p.layer_id == "osm"
        assert p.layer_type == "tile"

    def test_tile_url(self):
        p = OSMTileProvider()
        url = p.tile_url(10, 512, 340)
        assert "tile.openstreetmap.org/10/512/340.png" in url

    def test_attribution(self):
        p = OSMTileProvider()
        assert "OpenStreetMap" in p.attribution

    def test_to_dict(self):
        p = OSMTileProvider()
        d = p.to_dict()
        assert d["id"] == "osm"
        assert d["type"] == "tile"
        assert "name" in d
        assert "attribution" in d
        assert "description" in d

    def test_query_returns_empty_collection(self):
        p = OSMTileProvider()
        bbox = BBox(west=10.0, south=48.0, east=10.1, north=48.1)
        result = p.query(bbox)
        assert result["type"] == "FeatureCollection"
        assert result["features"] == []


@pytest.mark.unit
class TestSatelliteProvider:
    def test_default_url(self):
        p = SatelliteProvider()
        url = p.tile_url(5, 16, 11)
        assert "arcgisonline.com" in url

    def test_custom_url(self):
        p = SatelliteProvider(url_template="https://custom/{z}/{x}/{y}.jpg")
        url = p.tile_url(3, 4, 5)
        assert url == "https://custom/3/4/5.jpg"

    def test_layer_type(self):
        p = SatelliteProvider()
        assert p.layer_type == "tile"

    def test_max_zoom(self):
        p = SatelliteProvider()
        assert p.max_zoom == 18


@pytest.mark.unit
class TestBuildingFootprintProvider:
    def test_query_returns_feature_collection(self):
        p = BuildingFootprintProvider()
        bbox = BBox(west=-122.42, south=37.77, east=-122.41, north=37.78)
        result = p.query(bbox)
        assert result["type"] == "FeatureCollection"
        assert isinstance(result["features"], list)
        assert len(result["features"]) >= 5

    def test_query_deterministic(self):
        p = BuildingFootprintProvider()
        bbox = BBox(west=-122.42, south=37.77, east=-122.41, north=37.78)
        # Use stub directly (OSM availability varies, making query() non-deterministic)
        r1 = p._query_stub(bbox)
        r2 = p._query_stub(bbox)
        assert r1 == r2

    def test_features_are_polygons(self):
        p = BuildingFootprintProvider()
        bbox = BBox(west=10.0, south=48.0, east=10.1, north=48.1)
        result = p.query(bbox)
        for f in result["features"]:
            assert f["type"] == "Feature"
            assert f["geometry"]["type"] == "Polygon"
            assert "height" in f["properties"]
            assert "levels" in f["properties"]

    def test_layer_type_is_feature(self):
        p = BuildingFootprintProvider()
        assert p.layer_type == "feature"

    def test_tile_url_returns_none(self):
        p = BuildingFootprintProvider()
        assert p.tile_url(1, 2, 3) is None

    def test_buildings_within_bounds(self):
        p = BuildingFootprintProvider()
        bbox = BBox(west=10.0, south=48.0, east=10.1, north=48.1)
        result = p.query(bbox)
        for f in result["features"]:
            coords = f["geometry"]["coordinates"][0]
            for lon, lat in coords:
                # Buildings can extend slightly beyond bounds due to polygon width
                assert bbox.west - 0.001 <= lon <= bbox.east + 0.001
                assert bbox.south - 0.001 <= lat <= bbox.north + 0.001


@pytest.mark.unit
class TestTerrainProvider:
    def test_query_returns_points(self):
        p = TerrainProvider()
        bbox = BBox(west=10.0, south=48.0, east=10.1, north=48.1)
        result = p.query(bbox)
        assert result["type"] == "FeatureCollection"
        assert len(result["features"]) == 25  # 5x5 grid

    def test_features_have_elevation(self):
        p = TerrainProvider()
        bbox = BBox(west=10.0, south=48.0, east=10.1, north=48.1)
        result = p.query(bbox)
        for f in result["features"]:
            assert f["geometry"]["type"] == "Point"
            assert "elevation_m" in f["properties"]
            assert isinstance(f["properties"]["elevation_m"], float)

    def test_attribution(self):
        p = TerrainProvider()
        assert "Mapzen" in p.attribution or "USGS" in p.attribution


# ---------------------------------------------------------------------------
# Plugin lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGISLayersPlugin:
    def _make_plugin(self, with_app=False):
        plugin = GISLayersPlugin()
        ctx = MagicMock()
        ctx.event_bus = MagicMock()
        ctx.logger = None
        if with_app:
            from fastapi import FastAPI
            ctx.app = FastAPI()
        else:
            ctx.app = None
        plugin.configure(ctx)
        return plugin

    def test_identity(self):
        p = GISLayersPlugin()
        assert p.plugin_id == "tritium.gis-layers"
        assert p.name == "GIS Layers"
        assert p.version == "1.0.0"

    def test_capabilities(self):
        p = GISLayersPlugin()
        caps = p.capabilities
        assert "data_source" in caps
        assert "routes" in caps
        assert "ui" in caps

    def test_configure_registers_builtin_providers(self):
        plugin = self._make_plugin()
        layers = plugin.list_layers()
        ids = {layer["id"] for layer in layers}
        assert "osm" in ids
        assert "satellite" in ids
        assert "buildings" in ids
        assert "terrain" in ids

    def test_list_layers_returns_five(self):
        plugin = self._make_plugin()
        assert len(plugin.list_layers()) == 5  # osm, satellite, buildings, terrain, segmented_terrain

    def test_start_stop(self):
        plugin = self._make_plugin()
        assert not plugin.healthy
        plugin.start()
        assert plugin.healthy
        plugin.stop()
        assert not plugin.healthy

    def test_double_start_idempotent(self):
        plugin = self._make_plugin()
        plugin.start()
        plugin.start()
        assert plugin.healthy

    def test_double_stop_idempotent(self):
        plugin = self._make_plugin()
        plugin.start()
        plugin.stop()
        plugin.stop()
        assert not plugin.healthy

    def test_register_duplicate_raises(self):
        plugin = self._make_plugin()
        with pytest.raises(ValueError, match="already registered"):
            plugin.register_provider(OSMTileProvider())

    def test_remove_provider(self):
        plugin = self._make_plugin()
        plugin.remove_provider("terrain")
        ids = {layer["id"] for layer in plugin.list_layers()}
        assert "terrain" not in ids

    def test_remove_nonexistent_raises(self):
        plugin = self._make_plugin()
        with pytest.raises(KeyError):
            plugin.remove_provider("nonexistent")

    def test_get_provider(self):
        plugin = self._make_plugin()
        p = plugin.get_provider("osm")
        assert p is not None
        assert p.layer_id == "osm"

    def test_get_provider_none(self):
        plugin = self._make_plugin()
        assert plugin.get_provider("nonexistent") is None

    def test_get_tile_url(self):
        plugin = self._make_plugin()
        url = plugin.get_tile_url("osm", 10, 512, 340)
        assert url is not None
        assert "10/512/340" in url

    def test_get_tile_url_unknown(self):
        plugin = self._make_plugin()
        assert plugin.get_tile_url("nonexistent", 1, 2, 3) is None

    def test_query_features(self):
        plugin = self._make_plugin()
        bbox = BBox(west=10.0, south=48.0, east=10.1, north=48.1)
        result = plugin.query_features("buildings", bbox)
        assert result is not None
        assert result["type"] == "FeatureCollection"

    def test_query_features_unknown(self):
        plugin = self._make_plugin()
        bbox = BBox(west=10.0, south=48.0, east=10.1, north=48.1)
        assert plugin.query_features("nonexistent", bbox) is None


# ---------------------------------------------------------------------------
# API routes (via TestClient)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGISLayersRoutes:
    def _make_app(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        plugin = GISLayersPlugin()
        ctx = MagicMock()
        ctx.event_bus = MagicMock()
        ctx.app = app
        ctx.logger = None
        plugin.configure(ctx)
        plugin.start()
        return TestClient(app), plugin

    def test_list_layers(self):
        client, _ = self._make_app()
        resp = client.get("/api/gis/layers")
        assert resp.status_code == 200
        data = resp.json()
        assert "layers" in data
        assert data["count"] == 5  # osm, satellite, buildings, terrain, segmented_terrain
        ids = {layer["id"] for layer in data["layers"]}
        assert "osm" in ids
        assert "satellite" in ids

    def test_layers_have_metadata(self):
        client, _ = self._make_app()
        resp = client.get("/api/gis/layers")
        for layer in resp.json()["layers"]:
            assert "id" in layer
            assert "name" in layer
            assert "type" in layer
            assert "attribution" in layer
            assert "description" in layer

    def test_tile_redirect_osm(self):
        client, _ = self._make_app()
        resp = client.get("/api/gis/layers/osm/tiles/10/512/340", follow_redirects=False)
        assert resp.status_code == 302
        assert "tile.openstreetmap.org/10/512/340" in resp.headers["location"]

    def test_tile_redirect_satellite(self):
        client, _ = self._make_app()
        resp = client.get("/api/gis/layers/satellite/tiles/5/16/11", follow_redirects=False)
        assert resp.status_code == 302
        assert "arcgisonline.com" in resp.headers["location"]

    def test_tile_not_found(self):
        client, _ = self._make_app()
        resp = client.get("/api/gis/layers/nope/tiles/1/2/3")
        assert resp.status_code == 404

    def test_tile_non_tile_layer(self):
        client, _ = self._make_app()
        resp = client.get("/api/gis/layers/buildings/tiles/1/2/3")
        assert resp.status_code == 400

    def test_features_buildings(self):
        client, _ = self._make_app()
        resp = client.get("/api/gis/layers/buildings/features?bbox=10.0,48.0,10.1,48.1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) >= 5

    def test_features_terrain(self):
        client, _ = self._make_app()
        resp = client.get("/api/gis/layers/terrain/features?bbox=10.0,48.0,10.1,48.1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["features"]) == 25
        assert "elevation_m" in data["features"][0]["properties"]

    def test_features_bad_bbox(self):
        client, _ = self._make_app()
        resp = client.get("/api/gis/layers/buildings/features?bbox=bad")
        assert resp.status_code == 400

    def test_features_missing_bbox(self):
        client, _ = self._make_app()
        resp = client.get("/api/gis/layers/buildings/features")
        assert resp.status_code == 422

    def test_features_not_found(self):
        client, _ = self._make_app()
        resp = client.get("/api/gis/layers/nope/features?bbox=10.0,48.0,10.1,48.1")
        assert resp.status_code == 404
