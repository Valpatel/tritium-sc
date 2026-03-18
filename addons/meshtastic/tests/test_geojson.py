# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Meshtastic GeoJSON endpoints (nodes, links)."""

import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from meshtastic_addon.router import create_router


SAMPLE_NODES = {
    "!aabb1122": {
        "long_name": "Node Alpha",
        "short_name": "NA",
        "lat": 37.8,
        "lng": -122.4,
        "battery": 85,
        "snr": -4.0,
        "role": "CLIENT",
        "neighbors": ["!ccdd3344"],
        "neighbor_snr": {"!ccdd3344": -4.0},
    },
    "!ccdd3344": {
        "long_name": "Node Bravo",
        "short_name": "NB",
        "lat": 37.7,
        "lng": -122.3,
        "battery": 60,
        "snr": -8.0,
        "role": "ROUTER",
        "neighbors": ["!aabb1122"],
        "neighbor_snr": {"!aabb1122": -4.0},
    },
    "!nogps0000": {
        "long_name": "Node No GPS",
        "short_name": "NG",
        "lat": None,
        "lng": None,
        "battery": 50,
        "snr": -12.0,
        "role": "CLIENT",
        "neighbors": [],
    },
    "!zero0000": {
        "long_name": "Node Zero",
        "short_name": "NZ",
        "lat": 0.0,
        "lng": 0.0,
        "battery": 100,
        "snr": 0.0,
        "role": "CLIENT",
        "neighbors": [],
    },
}


def _make_node_manager(nodes=None):
    """Create a mock NodeManager with test nodes."""
    from meshtastic_addon.node_manager import NodeManager
    nm = NodeManager()
    nm.nodes = dict(nodes or SAMPLE_NODES)
    return nm


def _make_app(node_manager=None):
    """Create a FastAPI app with Meshtastic router for testing."""
    connection = MagicMock()
    connection.is_connected = True
    connection.interface = MagicMock()
    connection.transport_type = "serial"
    connection.port = "/dev/ttyACM0"
    connection.device_info = {}

    nm = node_manager or _make_node_manager()
    router = create_router(connection, nm)
    app = FastAPI()
    app.include_router(router, prefix="/api/addons/meshtastic")
    return TestClient(app)


class TestGeoJsonNodes:
    """GET /api/addons/meshtastic/geojson/nodes"""

    def test_returns_feature_collection(self):
        client = _make_app()
        resp = client.get("/api/addons/meshtastic/geojson/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"

    def test_only_nodes_with_gps(self):
        client = _make_app()
        resp = client.get("/api/addons/meshtastic/geojson/nodes")
        data = resp.json()
        # Only aabb1122 and ccdd3344 have valid GPS (nogps has None, zero has 0,0)
        assert len(data["features"]) == 2

    def test_feature_structure(self):
        client = _make_app()
        resp = client.get("/api/addons/meshtastic/geojson/nodes")
        features = resp.json()["features"]

        f0 = features[0]
        assert f0["type"] == "Feature"
        assert f0["geometry"]["type"] == "Point"
        coords = f0["geometry"]["coordinates"]
        assert len(coords) == 2  # [lng, lat]

        props = f0["properties"]
        assert "target_id" in props
        assert props["target_id"].startswith("mesh_")
        assert "long_name" in props
        assert "short_name" in props
        assert props["icon"] == "mesh_node"

    def test_coordinates_are_lng_lat(self):
        """GeoJSON uses [longitude, latitude] order."""
        nm = _make_node_manager({
            "!test0001": {
                "long_name": "Test", "short_name": "T",
                "lat": 37.8, "lng": -122.4,
                "role": "CLIENT",
            }
        })
        client = _make_app(node_manager=nm)
        resp = client.get("/api/addons/meshtastic/geojson/nodes")
        coords = resp.json()["features"][0]["geometry"]["coordinates"]
        assert coords == [-122.4, 37.8]

    def test_empty_when_no_node_manager(self):
        connection = MagicMock()
        connection.is_connected = False
        connection.transport_type = "none"
        connection.port = ""
        connection.device_info = {}

        router = create_router(connection, None)
        app = FastAPI()
        app.include_router(router, prefix="/api/addons/meshtastic")
        client = TestClient(app)

        resp = client.get("/api/addons/meshtastic/geojson/nodes")
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert data["features"] == []


class TestGeoJsonLinks:
    """GET /api/addons/meshtastic/geojson/links"""

    def test_returns_feature_collection(self):
        client = _make_app()
        resp = client.get("/api/addons/meshtastic/geojson/links")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"

    def test_links_as_linestrings(self):
        client = _make_app()
        resp = client.get("/api/addons/meshtastic/geojson/links")
        features = resp.json()["features"]
        # aabb1122 <-> ccdd3344 (deduplicated to 1 link)
        assert len(features) == 1

        f = features[0]
        assert f["type"] == "Feature"
        assert f["geometry"]["type"] == "LineString"
        assert len(f["geometry"]["coordinates"]) == 2
        assert f["properties"]["icon"] == "mesh_link"
        assert "from_node" in f["properties"]
        assert "to_node" in f["properties"]

    def test_skips_links_without_gps(self):
        """Links where either endpoint lacks GPS are excluded."""
        nm = _make_node_manager({
            "!hasgps": {
                "long_name": "Has", "short_name": "H",
                "lat": 37.8, "lng": -122.4,
                "role": "CLIENT",
                "neighbors": ["!nogps"],
                "neighbor_snr": {"!nogps": -5.0},
            },
            "!nogps": {
                "long_name": "No", "short_name": "N",
                "lat": None, "lng": None,
                "role": "CLIENT",
                "neighbors": ["!hasgps"],
                "neighbor_snr": {"!hasgps": -5.0},
            },
        })
        client = _make_app(node_manager=nm)
        resp = client.get("/api/addons/meshtastic/geojson/links")
        features = resp.json()["features"]
        assert len(features) == 0

    def test_empty_when_no_node_manager(self):
        connection = MagicMock()
        connection.is_connected = False
        connection.transport_type = "none"
        connection.port = ""
        connection.device_info = {}

        router = create_router(connection, None)
        app = FastAPI()
        app.include_router(router, prefix="/api/addons/meshtastic")
        client = TestClient(app)

        resp = client.get("/api/addons/meshtastic/geojson/links")
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert data["features"] == []


class TestMeshtasticAddonGeoJsonLayers:
    """MeshtasticAddon.get_geojson_layers() returns correct layer defs."""

    def test_returns_two_layers(self):
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        layers = addon.get_geojson_layers()
        assert len(layers) == 2

        ids = [l.layer_id for l in layers]
        assert "meshtastic-nodes" in ids
        assert "meshtastic-links" in ids

    def test_layers_have_correct_endpoints(self):
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        layers = {l.layer_id: l for l in addon.get_geojson_layers()}

        assert layers["meshtastic-nodes"].geojson_endpoint == "/api/addons/meshtastic/geojson/nodes"
        assert layers["meshtastic-links"].geojson_endpoint == "/api/addons/meshtastic/geojson/links"

    def test_nodes_visible_by_default(self):
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        layers = {l.layer_id: l for l in addon.get_geojson_layers()}
        assert layers["meshtastic-nodes"].visible_by_default is True
        assert layers["meshtastic-links"].visible_by_default is False

    def test_layers_serializable(self):
        from meshtastic_addon import MeshtasticAddon
        addon = MeshtasticAddon()
        for layer in addon.get_geojson_layers():
            d = layer.to_dict()
            assert isinstance(d, dict)
            assert "layer_id" in d
            assert "geojson_endpoint" in d
