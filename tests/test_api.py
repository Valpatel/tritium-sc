# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Test TRITIUM API endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHealth:
    """Test health endpoints."""

    def test_health(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "operational"
        assert data["system"] == "TRITIUM"

    def test_status(self, client):
        """Test status endpoint."""
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "TRITIUM"
        assert "version" in data


class TestCameras:
    """Test camera endpoints."""

    def test_list_cameras_empty(self, client):
        """Test listing cameras when empty."""
        response = client.get("/api/cameras")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_camera(self, client):
        """Test creating a camera."""
        camera_data = {
            "channel": 1,
            "name": "Test Camera 1",
            "rtsp_url": "rtsp://192.168.1.100/stream",
        }
        response = client.post("/api/cameras", json=camera_data)
        assert response.status_code == 200
        data = response.json()
        assert data["channel"] == 1
        assert data["name"] == "Test Camera 1"


class TestVideos:
    """Test video browsing endpoints."""

    def test_list_channels(self, client):
        """Test listing video channels."""
        response = client.get("/api/videos/channels")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestWebSocket:
    """Test WebSocket endpoints."""

    def test_websocket_connect(self, client):
        """Test WebSocket connection."""
        with client.websocket_connect("/ws/live") as websocket:
            data = websocket.receive_json()
            assert data["type"] == "connected"
            assert "UPLINK" in data["message"]
