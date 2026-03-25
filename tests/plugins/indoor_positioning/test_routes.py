# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for indoor positioning API routes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.indoor_positioning.fusion import IndoorPositionFusion
from plugins.indoor_positioning.routes import create_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FINGERPRINTS = [
    {
        "fingerprint_id": "fp_1",
        "plan_id": "plan_a",
        "room_id": "room_lobby",
        "lat": 37.3352,
        "lon": -121.8811,
        "rssi_map": {"bssid_a": -45, "bssid_b": -65, "bssid_c": -80},
    },
    {
        "fingerprint_id": "fp_2",
        "plan_id": "plan_a",
        "room_id": "room_conference",
        "lat": 37.3354,
        "lon": -121.8809,
        "rssi_map": {"bssid_a": -70, "bssid_b": -40, "bssid_c": -55},
    },
]


class MockFloorPlanStore:
    def __init__(self, fingerprints=None, plans=None):
        self._fingerprints = fingerprints or []
        self._plans = plans or []

    def get_fingerprints(self, plan_id=None, room_id=None):
        return self._fingerprints

    def list_plans(self, status=None, building=None, floor_level=None):
        return self._plans


class MockTrilat:
    def __init__(self):
        self._results = {}

    def set_result(self, mac, lat, lon, confidence, anchors_used=3):
        from tritium_lib.tracking.trilateration import PositionResult
        self._results[mac.upper()] = PositionResult(
            lat=lat, lon=lon, confidence=confidence,
            anchors_used=anchors_used,
        )

    def estimate_position(self, mac):
        return self._results.get(mac.upper())


@pytest.fixture
def client():
    store = MockFloorPlanStore(fingerprints=FINGERPRINTS)
    trilat = MockTrilat()
    trilat.set_result("AA:BB:CC:DD:EE:FF", 37.3354, -121.8809, 0.7, 3)

    fusion = IndoorPositionFusion(
        trilateration_engine=trilat,
        floorplan_store=store,
    )
    # Seed a WiFi observation
    fusion.update_wifi_observation(
        "ble_AA:BB:CC:DD:EE:FF",
        {"bssid_a": -45, "bssid_b": -65, "bssid_c": -80},
    )

    app = FastAPI()
    router = create_router(fusion)
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def empty_client():
    fusion = IndoorPositionFusion()
    app = FastAPI()
    router = create_router(fusion)
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetPosition:
    def test_get_fused_position(self, client):
        resp = client.get("/api/indoor/position/ble_AA:BB:CC:DD:EE:FF")
        assert resp.status_code == 200
        data = resp.json()["position"]
        assert "lat" in data
        assert "lon" in data
        assert "confidence" in data
        assert "uncertainty_m" in data
        assert data["method"] in ("fused", "fingerprint", "trilateration")

    def test_not_found(self, empty_client):
        resp = empty_client.get("/api/indoor/position/unknown_target")
        assert resp.status_code == 404


class TestGetAllPositions:
    def test_returns_list(self, client):
        # Trigger estimation to populate cache
        client.get("/api/indoor/position/ble_AA:BB:CC:DD:EE:FF")
        resp = client.get("/api/indoor/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data
        assert "count" in data
        assert data["count"] >= 1

    def test_empty(self, empty_client):
        resp = empty_client.get("/api/indoor/positions")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestWifiObservation:
    def test_submit_observation(self, client):
        resp = client.post("/api/indoor/wifi-observation", json={
            "target_id": "test_device",
            "rssi_map": {"bssid_x": -55, "bssid_y": -70},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["stored"] is True
        assert data["bssid_count"] == 2

    def test_empty_rssi_map_rejected(self, client):
        resp = client.post("/api/indoor/wifi-observation", json={
            "target_id": "test_device",
            "rssi_map": {},
        })
        assert resp.status_code == 400


class TestStatus:
    def test_status(self, client):
        resp = client.get("/api/indoor/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine"] == "wifi_ble_fusion"
        assert "fingerprint_knn" in data["methods"]
        assert "ble_trilateration" in data["methods"]
