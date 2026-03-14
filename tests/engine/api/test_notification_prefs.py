# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for notification preferences API."""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _reset_prefs():
    """Reset notification preferences before each test."""
    from app.routers import notifications
    notifications._prefs = {}
    notifications._prefs_file = None
    yield
    notifications._prefs = {}


def _make_client():
    """Create a minimal test client with notification routes."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.notifications import router

    app = FastAPI()
    app.include_router(router)

    return TestClient(app)


@pytest.mark.unit
def test_get_preferences():
    client = _make_client()
    resp = client.get("/api/notifications/preferences")
    assert resp.status_code == 200
    data = resp.json()
    assert "geofence_enter" in data
    assert "ble_new_device" in data
    assert data["geofence_enter"]["enabled"] is True
    assert data["geofence_enter"]["severity"] == "warning"


@pytest.mark.unit
def test_update_preference_enabled():
    client = _make_client()
    resp = client.put(
        "/api/notifications/preferences",
        json={"ble_new_device": {"enabled": False}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["preferences"]["ble_new_device"]["enabled"] is False


@pytest.mark.unit
def test_update_preference_severity():
    client = _make_client()
    resp = client.put(
        "/api/notifications/preferences",
        json={"node_online": {"severity": "warning"}},
    )
    assert resp.status_code == 200
    assert resp.json()["preferences"]["node_online"]["severity"] == "warning"


@pytest.mark.unit
def test_update_invalid_severity():
    client = _make_client()
    resp = client.put(
        "/api/notifications/preferences",
        json={"ble_new_device": {"severity": "banana"}},
    )
    assert resp.status_code == 400


@pytest.mark.unit
def test_reset_preferences():
    client = _make_client()
    # First disable something
    resp1 = client.put(
        "/api/notifications/preferences",
        json={"ble_new_device": {"enabled": False}},
    )
    assert resp1.status_code == 200
    assert resp1.json()["preferences"]["ble_new_device"]["enabled"] is False
    # Then reset (same client, same server state)
    resp = client.post("/api/notifications/preferences/reset")
    assert resp.status_code == 200
    data = resp.json()
    assert data["preferences"]["ble_new_device"]["enabled"] is True


@pytest.mark.unit
def test_add_custom_type():
    client = _make_client()
    resp = client.put(
        "/api/notifications/preferences",
        json={"custom_event": {"enabled": True, "severity": "critical"}},
    )
    assert resp.status_code == 200
    assert "custom_event" in resp.json()["preferences"]
    assert resp.json()["preferences"]["custom_event"]["severity"] == "critical"
