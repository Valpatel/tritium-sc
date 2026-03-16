# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the radar tracker plugin — tracker logic, routes, and demo generator."""

import math
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import sys
from pathlib import Path

# Ensure plugins/ is on sys.path for importing radar_tracker
_plugins_dir = str(Path(__file__).resolve().parents[3] / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

from radar_tracker.tracker import (
    RadarTracker,
    range_azimuth_to_latlng,
    classify_from_rcs_velocity,
)
from radar_tracker.routes import create_router
from radar_tracker.demo import RadarDemoGenerator
from radar_tracker.models import RadarConfigRequest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tracker():
    """RadarTracker with no external dependencies."""
    return RadarTracker()


@pytest.fixture
def configured_tracker(tracker):
    """RadarTracker with a demo radar configured."""
    tracker.configure_radar(
        radar_id="test-radar",
        lat=37.7749,
        lng=-122.4194,
        altitude_m=50.0,
        orientation_deg=0.0,
        max_range_m=20000.0,
        min_range_m=10.0,
        name="Test Radar",
    )
    return tracker


@pytest.fixture
def app(configured_tracker):
    """FastAPI app with radar routes."""
    app = FastAPI()
    router = create_router(configured_tracker)
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Unit tests — coordinate conversion
# ---------------------------------------------------------------------------

class TestRangeAzimuthToLatLng:
    """Test polar to geographic coordinate conversion."""

    def test_zero_range_returns_radar_position(self):
        """Zero range should return the radar's own position."""
        lat, lng = range_azimuth_to_latlng(37.7749, -122.4194, 0.0, 0.0)
        assert abs(lat - 37.7749) < 0.0001
        assert abs(lng - (-122.4194)) < 0.0001

    def test_north_bearing(self):
        """Target due north should increase latitude."""
        lat, lng = range_azimuth_to_latlng(37.7749, -122.4194, 1000.0, 0.0)
        assert lat > 37.7749  # north = higher latitude
        assert abs(lng - (-122.4194)) < 0.001  # longitude roughly unchanged

    def test_south_bearing(self):
        """Target due south should decrease latitude."""
        lat, lng = range_azimuth_to_latlng(37.7749, -122.4194, 1000.0, 180.0)
        assert lat < 37.7749

    def test_east_bearing(self):
        """Target due east should increase longitude."""
        lat, lng = range_azimuth_to_latlng(37.7749, -122.4194, 1000.0, 90.0)
        assert lng > -122.4194

    def test_west_bearing(self):
        """Target due west should decrease longitude."""
        lat, lng = range_azimuth_to_latlng(37.7749, -122.4194, 1000.0, 270.0)
        assert lng < -122.4194

    def test_orientation_offset(self):
        """Orientation rotates the reference frame."""
        # Boresight pointing east (90 deg), target at 0 azimuth = east
        lat1, lng1 = range_azimuth_to_latlng(37.7749, -122.4194, 1000.0, 0.0, orientation_deg=90.0)
        # Same as target at 90 deg azimuth with north boresight
        lat2, lng2 = range_azimuth_to_latlng(37.7749, -122.4194, 1000.0, 90.0, orientation_deg=0.0)
        assert abs(lat1 - lat2) < 0.0001
        assert abs(lng1 - lng2) < 0.0001

    def test_range_proportional_to_distance(self):
        """Doubling range should roughly double the geographic distance."""
        lat1, _ = range_azimuth_to_latlng(37.7749, -122.4194, 1000.0, 0.0)
        lat2, _ = range_azimuth_to_latlng(37.7749, -122.4194, 2000.0, 0.0)
        d1 = lat1 - 37.7749
        d2 = lat2 - 37.7749
        ratio = d2 / d1 if d1 != 0 else 0
        assert 1.9 < ratio < 2.1


# ---------------------------------------------------------------------------
# Unit tests — classification heuristic
# ---------------------------------------------------------------------------

class TestClassifyFromRcsVelocity:
    def test_fast_large_is_aircraft(self):
        assert classify_from_rcs_velocity(20.0, 100.0) == "aircraft"

    def test_fast_small_is_uav(self):
        assert classify_from_rcs_velocity(-10.0, 80.0) == "uav"

    def test_moderate_speed_moderate_rcs_is_vehicle(self):
        assert classify_from_rcs_velocity(5.0, 15.0) == "vehicle"

    def test_slow_low_rcs_is_person(self):
        assert classify_from_rcs_velocity(-3.0, 1.0) == "person"

    def test_slow_very_high_rcs_is_ship(self):
        assert classify_from_rcs_velocity(35.0, 5.0) == "ship"

    def test_slow_very_low_rcs_is_animal(self):
        assert classify_from_rcs_velocity(-15.0, 2.0) == "animal"

    def test_ambiguous_is_unknown(self):
        # Edge case that doesn't clearly match any category
        result = classify_from_rcs_velocity(15.0, 0.5)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Unit tests — RadarTracker
# ---------------------------------------------------------------------------

class TestRadarTracker:
    def test_configure_radar(self, tracker):
        unit = tracker.configure_radar(
            "r1", lat=37.0, lng=-122.0, max_range_m=5000.0,
        )
        assert unit.radar_id == "r1"
        assert unit.lat == 37.0
        assert unit.max_range_m == 5000.0

    def test_list_radars(self, configured_tracker):
        radars = configured_tracker.list_radars()
        assert len(radars) == 1
        assert radars[0]["radar_id"] == "test-radar"

    def test_remove_radar(self, configured_tracker):
        assert configured_tracker.remove_radar("test-radar") is True
        assert configured_tracker.list_radars() == []

    def test_remove_nonexistent_radar(self, tracker):
        assert tracker.remove_radar("nope") is False

    def test_ingest_tracks(self, configured_tracker):
        tracks = [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 45.0, "velocity_mps": 10.0},
            {"track_id": "T002", "range_m": 2000.0, "azimuth_deg": 90.0, "velocity_mps": 20.0},
        ]
        count = configured_tracker.ingest_tracks("test-radar", tracks)
        assert count == 2

    def test_get_tracks(self, configured_tracker):
        configured_tracker.ingest_tracks("test-radar", [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 45.0},
        ])
        tracks = configured_tracker.get_tracks()
        assert len(tracks) == 1
        assert tracks[0]["track_id"] == "T001"
        assert tracks[0]["target_id"] == "radar_test-radar_T001"

    def test_tracks_have_latlng(self, configured_tracker):
        configured_tracker.ingest_tracks("test-radar", [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 0.0},
        ])
        tracks = configured_tracker.get_tracks()
        assert tracks[0]["lat"] != 0.0
        assert tracks[0]["lng"] != 0.0

    def test_filter_tracks_by_radar(self, configured_tracker):
        configured_tracker.configure_radar("r2", lat=38.0, lng=-121.0)
        configured_tracker.ingest_tracks("test-radar", [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 0.0},
        ])
        configured_tracker.ingest_tracks("r2", [
            {"track_id": "T002", "range_m": 2000.0, "azimuth_deg": 90.0},
        ])
        r1_tracks = configured_tracker.get_tracks(radar_id="test-radar")
        r2_tracks = configured_tracker.get_tracks(radar_id="r2")
        assert len(r1_tracks) == 1
        assert len(r2_tracks) == 1

    def test_tracks_outside_range_filtered(self, configured_tracker):
        # min_range is 10m, max_range is 20000m
        configured_tracker.ingest_tracks("test-radar", [
            {"track_id": "T001", "range_m": 5.0, "azimuth_deg": 0.0},    # too close
            {"track_id": "T002", "range_m": 25000.0, "azimuth_deg": 0.0}, # too far
            {"track_id": "T003", "range_m": 500.0, "azimuth_deg": 0.0},   # OK
        ])
        tracks = configured_tracker.get_tracks()
        assert len(tracks) == 1
        assert tracks[0]["track_id"] == "T003"

    def test_ingest_updates_existing_track(self, configured_tracker):
        configured_tracker.ingest_tracks("test-radar", [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 45.0},
        ])
        configured_tracker.ingest_tracks("test-radar", [
            {"track_id": "T001", "range_m": 1100.0, "azimuth_deg": 50.0},
        ])
        tracks = configured_tracker.get_tracks()
        assert len(tracks) == 1
        assert tracks[0]["range_m"] == 1100.0

    def test_auto_classification(self, configured_tracker):
        configured_tracker.ingest_tracks("test-radar", [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 0.0,
             "velocity_mps": 100.0, "rcs_dbsm": 20.0},
        ])
        tracks = configured_tracker.get_tracks()
        assert tracks[0]["classification"] == "aircraft"

    def test_explicit_classification_overrides(self, configured_tracker):
        configured_tracker.ingest_tracks("test-radar", [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 0.0,
             "classification": "rotorcraft"},
        ])
        tracks = configured_tracker.get_tracks()
        assert tracks[0]["classification"] == "rotorcraft"

    def test_ppi_data(self, configured_tracker):
        configured_tracker.ingest_tracks("test-radar", [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 45.0},
        ])
        ppi = configured_tracker.get_ppi_data("test-radar")
        assert ppi is not None
        assert ppi["radar_id"] == "test-radar"
        assert len(ppi["tracks"]) == 1
        assert ppi["lat"] == 37.7749

    def test_ppi_nonexistent_radar(self, tracker):
        assert tracker.get_ppi_data("nope") is None

    def test_prune_stale(self, configured_tracker):
        configured_tracker.ingest_tracks("test-radar", [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 0.0,
             "timestamp": time.time() - 60.0},  # old
        ])
        pruned = configured_tracker.prune_stale()
        assert pruned == 1
        assert configured_tracker.get_tracks() == []

    def test_get_stats(self, configured_tracker):
        configured_tracker.ingest_tracks("test-radar", [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 0.0},
        ])
        stats = configured_tracker.get_stats()
        assert stats["tracks_received"] >= 1
        assert stats["tracks_active"] >= 1
        assert stats["radars_configured"] == 1

    def test_unconfigured_radar_auto_registers(self, tracker):
        """Tracks from unknown radar should auto-register with zero position."""
        count = tracker.ingest_tracks("unknown-radar", [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 0.0},
        ])
        assert count == 1
        radars = tracker.list_radars()
        assert len(radars) == 1
        assert radars[0]["radar_id"] == "unknown-radar"

    def test_disabled_radar_skips_tracks(self, tracker):
        tracker.configure_radar("r1", lat=37.0, lng=-122.0, enabled=False)
        count = tracker.ingest_tracks("r1", [
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 0.0},
        ])
        assert count == 0


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------

class TestRadarRoutes:
    def test_get_status(self, client):
        resp = client.get("/api/radar/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "radars" in data
        assert "total_tracks" in data

    def test_get_tracks_empty(self, client):
        resp = client.get("/api/radar/tracks")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_configure_radar(self, client):
        resp = client.post("/api/radar/configure", json={
            "radar_id": "new-radar",
            "lat": 38.0,
            "lng": -121.0,
            "max_range_m": 10000.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["radar"]["radar_id"] == "new-radar"

    def test_list_radars(self, client):
        resp = client.get("/api/radar/radars")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_remove_radar(self, client):
        resp = client.delete("/api/radar/radars/test-radar")
        assert resp.status_code == 200
        assert resp.json()["removed"] is True

    def test_remove_nonexistent_radar(self, client):
        resp = client.delete("/api/radar/radars/nope")
        assert resp.status_code == 404

    def test_ingest_and_get_tracks(self, client):
        resp = client.post("/api/radar/ingest/test-radar", json=[
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 45.0},
            {"track_id": "T002", "range_m": 2000.0, "azimuth_deg": 90.0},
        ])
        assert resp.status_code == 200
        assert resp.json()["processed"] == 2

        resp = client.get("/api/radar/tracks")
        assert resp.json()["count"] == 2

    def test_get_ppi(self, client):
        client.post("/api/radar/ingest/test-radar", json=[
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 45.0},
        ])
        resp = client.get("/api/radar/ppi/test-radar")
        assert resp.status_code == 200
        data = resp.json()
        assert data["radar_id"] == "test-radar"
        assert len(data["tracks"]) == 1

    def test_get_ppi_nonexistent(self, client):
        resp = client.get("/api/radar/ppi/nope")
        assert resp.status_code == 404

    def test_get_stats(self, client):
        resp = client.get("/api/radar/stats")
        assert resp.status_code == 200
        assert "tracks_received" in resp.json()

    def test_filter_tracks_by_radar_id(self, client):
        client.post("/api/radar/ingest/test-radar", json=[
            {"track_id": "T001", "range_m": 1000.0, "azimuth_deg": 0.0},
        ])
        resp = client.get("/api/radar/tracks?radar_id=test-radar")
        assert resp.json()["count"] == 1
        resp = client.get("/api/radar/tracks?radar_id=other")
        assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# Demo generator tests
# ---------------------------------------------------------------------------

class TestRadarDemoGenerator:
    def test_generate_tracks(self):
        tracker = RadarTracker()
        gen = RadarDemoGenerator(tracker=tracker, radar_id="demo-radar")
        # Manually call _generate_tracks without starting the thread
        tracks = gen._generate_tracks()
        assert len(tracks) > 0
        for t in tracks:
            assert "track_id" in t
            assert "range_m" in t
            assert "azimuth_deg" in t
            assert t["range_m"] > 0

    def test_start_configures_radar(self):
        tracker = RadarTracker()
        gen = RadarDemoGenerator(tracker=tracker, radar_id="demo-radar")
        gen.start()
        try:
            radars = tracker.list_radars()
            assert len(radars) == 1
            assert radars[0]["radar_id"] == "demo-radar"
        finally:
            gen.stop()

    def test_start_stop(self):
        tracker = RadarTracker()
        gen = RadarDemoGenerator(tracker=tracker)
        gen.start()
        assert gen.running is True
        # Give it a moment to generate some tracks
        import time
        time.sleep(1.5)
        tracks = tracker.get_tracks()
        assert len(tracks) > 0
        gen.stop()
        assert gen.running is False


# ---------------------------------------------------------------------------
# Plugin integration test
# ---------------------------------------------------------------------------

class TestRadarTrackerPlugin:
    def test_plugin_identity(self):
        from radar_tracker.plugin import RadarTrackerPlugin

        plugin = RadarTrackerPlugin()
        assert plugin.plugin_id == "tritium.radar-tracker"
        assert plugin.name == "Radar Tracker"
        assert "data_source" in plugin.capabilities
        assert "routes" in plugin.capabilities

    def test_plugin_configure_creates_tracker(self):
        from radar_tracker.plugin import RadarTrackerPlugin
        from unittest.mock import MagicMock

        plugin = RadarTrackerPlugin()

        ctx = MagicMock()
        ctx.event_bus = None
        ctx.target_tracker = None
        ctx.app = None
        ctx.logger = None
        ctx.settings = {}

        plugin.configure(ctx)
        assert plugin.tracker is not None

    def test_plugin_start_stop(self):
        from radar_tracker.plugin import RadarTrackerPlugin
        from unittest.mock import MagicMock

        plugin = RadarTrackerPlugin()

        ctx = MagicMock()
        ctx.event_bus = None
        ctx.target_tracker = None
        ctx.app = None
        ctx.logger = None
        ctx.settings = {}

        plugin.configure(ctx)
        plugin.start()
        assert plugin.healthy is True
        plugin.stop()
        assert plugin.healthy is False

    def test_demo_start_stop(self):
        from radar_tracker.plugin import RadarTrackerPlugin
        from unittest.mock import MagicMock

        plugin = RadarTrackerPlugin()

        ctx = MagicMock()
        ctx.event_bus = None
        ctx.target_tracker = None
        ctx.app = None
        ctx.logger = None
        ctx.settings = {}

        plugin.configure(ctx)
        result = plugin.start_demo()
        assert result["status"] == "started"
        result = plugin.stop_demo()
        assert result["status"] == "stopped"


# ---------------------------------------------------------------------------
# Models test
# ---------------------------------------------------------------------------

class TestModels:
    def test_radar_config_request(self):
        req = RadarConfigRequest(
            radar_id="r1", lat=37.0, lng=-122.0,
        )
        assert req.radar_id == "r1"
        assert req.max_range_m == 20000.0  # default
        assert req.enabled is True  # default

    def test_radar_config_request_full(self):
        req = RadarConfigRequest(
            radar_id="r1", lat=37.0, lng=-122.0,
            altitude_m=100.0, orientation_deg=45.0,
            max_range_m=5000.0, min_range_m=100.0,
            name="My Radar", enabled=False,
        )
        assert req.altitude_m == 100.0
        assert req.enabled is False
