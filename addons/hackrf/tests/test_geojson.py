# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for HackRF GeoJSON endpoints (ADS-B aircraft, RF signals)."""

import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hackrf_addon.router import create_router


def _make_app(adsb_decoder=None, signal_db=None):
    """Create a minimal FastAPI app with the HackRF router."""
    device = MagicMock()
    device.is_available = True
    device.get_info.return_value = {"serial": "test123"}

    spectrum = MagicMock()
    spectrum.get_status.return_value = {}

    receiver = MagicMock()

    router = create_router(
        device, spectrum, receiver,
        adsb_decoder=adsb_decoder,
        signal_db=signal_db,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/addons/hackrf")
    return TestClient(app)


class TestGeoJsonAdsb:
    """GET /api/addons/hackrf/geojson/adsb"""

    def test_empty_when_no_decoder(self):
        client = _make_app(adsb_decoder=None)
        resp = client.get("/api/addons/hackrf/geojson/adsb")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert data["features"] == []

    def test_empty_when_no_aircraft(self):
        decoder = MagicMock()
        decoder.get_aircraft.return_value = []
        client = _make_app(adsb_decoder=decoder)
        resp = client.get("/api/addons/hackrf/geojson/adsb")
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert data["features"] == []

    def test_aircraft_as_geojson_points(self):
        decoder = MagicMock()
        decoder.get_aircraft.return_value = [
            {
                "icao": "abc123",
                "callsign": "UAL456",
                "latitude": 37.8,
                "longitude": -122.4,
                "altitude_ft": 35000,
                "heading": 270,
                "velocity_kt": 450,
                "squawk": "1200",
            },
            {
                "icao": "def789",
                "callsign": "",
                "latitude": 38.0,
                "longitude": -121.0,
                "altitude_ft": 10000,
                "heading": 90,
                "velocity_kt": 200,
                "squawk": "7700",
            },
        ]
        client = _make_app(adsb_decoder=decoder)
        resp = client.get("/api/addons/hackrf/geojson/adsb")
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 2

        f0 = data["features"][0]
        assert f0["type"] == "Feature"
        assert f0["geometry"]["type"] == "Point"
        assert f0["geometry"]["coordinates"] == [-122.4, 37.8]
        assert f0["properties"]["target_id"] == "adsb_abc123"
        assert f0["properties"]["callsign"] == "UAL456"
        assert f0["properties"]["altitude_ft"] == 35000
        assert f0["properties"]["icon"] == "aircraft"

    def test_skips_aircraft_without_position(self):
        decoder = MagicMock()
        decoder.get_aircraft.return_value = [
            {"icao": "nopos1", "callsign": "X", "latitude": None, "longitude": None},
            {"icao": "haspos", "callsign": "Y", "latitude": 40.0, "longitude": -74.0},
        ]
        client = _make_app(adsb_decoder=decoder)
        resp = client.get("/api/addons/hackrf/geojson/adsb")
        data = resp.json()
        assert len(data["features"]) == 1
        assert data["features"][0]["properties"]["target_id"] == "adsb_haspos"


class TestGeoJsonSignals:
    """GET /api/addons/hackrf/geojson/signals"""

    def test_empty_when_no_signal_db(self):
        client = _make_app(signal_db=None)
        resp = client.get("/api/addons/hackrf/geojson/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert data["features"] == []

    def test_empty_when_no_peaks(self):
        db = MagicMock()
        db.get_peaks.return_value = []
        client = _make_app(signal_db=db)
        resp = client.get("/api/addons/hackrf/geojson/signals")
        data = resp.json()
        assert data["features"] == []

    def test_signal_peaks_as_geojson(self):
        db = MagicMock()
        db.get_peaks.return_value = [
            {"freq_hz": 433920000, "power_dbm": -25.3, "timestamp": 1700000000},
            {"freq_hz": 915000000, "power_dbm": -18.7, "timestamp": 1700000001},
        ]
        client = _make_app(signal_db=db)
        resp = client.get("/api/addons/hackrf/geojson/signals")
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 2

        f0 = data["features"][0]
        assert f0["type"] == "Feature"
        assert f0["geometry"] is None
        assert f0["properties"]["freq_mhz"] == 433.92
        assert f0["properties"]["power_dbm"] == -25.3
        assert f0["properties"]["icon"] == "rf_signal"


class TestHackRFAddonGeoJsonLayers:
    """HackRFAddon.get_geojson_layers() returns correct layer defs."""

    def test_returns_two_layers(self):
        from hackrf_addon import HackRFAddon
        addon = HackRFAddon()
        layers = addon.get_geojson_layers()
        assert len(layers) == 2

        ids = [l.layer_id for l in layers]
        assert "hackrf-adsb" in ids
        assert "hackrf-signals" in ids

    def test_layers_have_correct_endpoints(self):
        from hackrf_addon import HackRFAddon
        addon = HackRFAddon()
        layers = {l.layer_id: l for l in addon.get_geojson_layers()}

        assert layers["hackrf-adsb"].geojson_endpoint == "/api/addons/hackrf/geojson/adsb"
        assert layers["hackrf-signals"].geojson_endpoint == "/api/addons/hackrf/geojson/signals"

    def test_layers_serializable(self):
        from hackrf_addon import HackRFAddon
        addon = HackRFAddon()
        for layer in addon.get_geojson_layers():
            d = layer.to_dict()
            assert isinstance(d, dict)
            assert "layer_id" in d
            assert "geojson_endpoint" in d
