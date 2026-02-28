# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the plugin API router.

TDD: Tests written before the router implementation.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_plugin_manager():
    """Create a mock plugin manager with test data."""
    from engine.plugins.manager import PluginManager
    mgr = MagicMock(spec=PluginManager)
    mgr.list_plugins.return_value = [
        {
            "id": "test.bridge",
            "name": "Test Bridge",
            "version": "1.0.0",
            "capabilities": ["bridge", "background"],
            "dependencies": [],
            "status": "running",
            "healthy": True,
        },
        {
            "id": "test.ai",
            "name": "AI Plugin",
            "version": "2.1.0",
            "capabilities": ["ai"],
            "dependencies": ["test.bridge"],
            "status": "failed",
            "healthy": False,
        },
    ]
    mgr.health_check.return_value = {
        "test.bridge": True,
    }

    # Mock get_plugin
    bridge = MagicMock()
    bridge.plugin_id = "test.bridge"
    bridge.name = "Test Bridge"
    bridge.version = "1.0.0"
    bridge.capabilities = {"bridge", "background"}
    bridge.dependencies = []
    bridge.healthy = True

    def _get(pid):
        if pid == "test.bridge":
            return bridge
        return None

    mgr.get_plugin.side_effect = _get
    return mgr


@pytest.fixture
def client(mock_plugin_manager):
    """FastAPI test client with plugin manager on app state."""
    from fastapi import FastAPI
    from app.routers.plugins import router

    app = FastAPI()
    app.include_router(router)
    app.state.plugin_manager = mock_plugin_manager

    return TestClient(app)


class TestPluginListEndpoint:
    """GET /api/plugins — list all plugins."""

    def test_list_plugins(self, client):
        resp = client.get("/api/plugins")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == "test.bridge"
        assert data[1]["id"] == "test.ai"

    def test_list_plugins_has_status(self, client):
        resp = client.get("/api/plugins")
        data = resp.json()
        assert data[0]["status"] == "running"
        assert data[1]["status"] == "failed"

    def test_list_plugins_has_capabilities(self, client):
        resp = client.get("/api/plugins")
        data = resp.json()
        assert "bridge" in data[0]["capabilities"]


class TestPluginDetailEndpoint:
    """GET /api/plugins/{id} — plugin details."""

    def test_get_existing_plugin(self, client):
        resp = client.get("/api/plugins/test.bridge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test.bridge"
        assert data["name"] == "Test Bridge"

    def test_get_nonexistent_plugin(self, client):
        resp = client.get("/api/plugins/nonexistent")
        assert resp.status_code == 404


class TestPluginHealthEndpoint:
    """GET /api/plugins/health — plugin health check."""

    def test_health_check(self, client):
        resp = client.get("/api/plugins/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["test.bridge"] is True


class TestNoPluginManager:
    """Test graceful behavior when no plugin manager is available."""

    def test_list_returns_empty_without_manager(self):
        from fastapi import FastAPI
        from app.routers.plugins import router

        app = FastAPI()
        app.include_router(router)
        # Don't set app.state.plugin_manager

        client = TestClient(app)
        resp = client.get("/api/plugins")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_health_returns_empty_without_manager(self):
        from fastapi import FastAPI
        from app.routers.plugins import router

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)
        resp = client.get("/api/plugins/health")
        assert resp.status_code == 200
        assert resp.json() == {}
