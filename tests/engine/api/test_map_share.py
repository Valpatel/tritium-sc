# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for map sharing API."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def app():
    """Create a minimal FastAPI test app with the map_share router."""
    from fastapi import FastAPI
    from app.routers.map_share import router, _shared_views
    _shared_views.clear()
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.mark.unit
class TestMapShare:
    def test_create_share(self, client):
        resp = client.post("/api/map-share/create", json={
            "center_lat": 40.7128,
            "center_lng": -74.006,
            "zoom": 15.0,
            "bearing": 45.0,
            "pitch": 30.0,
            "active_layers": ["showSatellite", "showBuildings"],
            "selected_targets": ["ble_aa:bb:cc"],
            "mode": "tactical",
            "operator": "op1",
            "message": "Check this area",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "share_id" in data
        assert data["url_fragment"].startswith("#share=")
        assert len(data["share_id"]) == 12

    def test_get_shared_view(self, client):
        # Create first
        resp = client.post("/api/map-share/create", json={
            "center_lat": 51.5,
            "center_lng": -0.12,
            "zoom": 12.0,
        })
        share_id = resp.json()["share_id"]

        # Retrieve
        resp = client.get(f"/api/map-share/{share_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["view"]["center_lat"] == 51.5
        assert data["view"]["zoom"] == 12.0

    def test_get_nonexistent_share(self, client):
        resp = client.get("/api/map-share/doesnotexist")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_list_shared_views(self, client):
        # Create two shares
        client.post("/api/map-share/create", json={"center_lat": 1.0, "center_lng": 2.0, "zoom": 5.0})
        client.post("/api/map-share/create", json={"center_lat": 3.0, "center_lng": 4.0, "zoom": 10.0})

        resp = client.get("/api/map-share")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["shares"]) == 2


@pytest.mark.unit
class TestClassificationOverride:
    def test_valid_alliances(self):
        from app.routers.classification_override import VALID_ALLIANCES
        assert "friendly" in VALID_ALLIANCES
        assert "hostile" in VALID_ALLIANCES
        assert "neutral" in VALID_ALLIANCES
        assert "unknown" in VALID_ALLIANCES

    def test_valid_device_types(self):
        from app.routers.classification_override import VALID_DEVICE_TYPES
        assert "person" in VALID_DEVICE_TYPES
        assert "vehicle" in VALID_DEVICE_TYPES
        assert "drone" in VALID_DEVICE_TYPES
