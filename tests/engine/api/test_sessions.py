# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for session management API endpoints."""

import pytest
from unittest.mock import patch

# Mark all tests as unit tests
pytestmark = pytest.mark.unit


class TestSessionsRouter:
    """Test session management endpoints."""

    @pytest.fixture(autouse=True)
    def _clear_sessions(self):
        """Clear session store between tests."""
        from app.routers.sessions import _sessions, _users
        _sessions.clear()
        _users.clear()
        yield
        _sessions.clear()
        _users.clear()

    @pytest.fixture
    def client(self):
        """Create a test client."""
        from fastapi.testclient import TestClient
        from app.routers.sessions import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_create_session(self, client):
        resp = client.post("/api/sessions", json={
            "username": "commander1",
            "display_name": "Commander Alpha",
            "role": "commander",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"]["username"] == "commander1"
        assert data["session"]["role"] == "commander"
        assert data["user"]["role"] == "commander"
        assert "permissions" in data
        assert len(data["permissions"]) > 0

    def test_create_session_invalid_role(self, client):
        resp = client.post("/api/sessions", json={
            "username": "bad",
            "role": "superadmin",
        })
        assert resp.status_code == 400

    def test_list_sessions(self, client):
        client.post("/api/sessions", json={"username": "a", "role": "observer"})
        client.post("/api/sessions", json={"username": "b", "role": "analyst"})
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_end_session(self, client):
        resp = client.post("/api/sessions", json={"username": "temp", "role": "observer"})
        sid = resp.json()["session"]["session_id"]
        resp2 = client.delete(f"/api/sessions/{sid}")
        assert resp2.status_code == 200
        # Should be gone
        resp3 = client.get(f"/api/sessions/{sid}")
        assert resp3.status_code == 404

    def test_update_cursor(self, client):
        resp = client.post("/api/sessions", json={"username": "cursor_test", "role": "commander"})
        sid = resp.json()["session"]["session_id"]
        resp2 = client.put(f"/api/sessions/{sid}/cursor", json={"lat": 40.7, "lng": -74.0})
        assert resp2.status_code == 200

    def test_get_cursors(self, client):
        resp = client.post("/api/sessions", json={"username": "loc_test", "role": "analyst"})
        sid = resp.json()["session"]["session_id"]
        client.put(f"/api/sessions/{sid}/cursor", json={"lat": 40.7, "lng": -74.0})
        resp2 = client.get("/api/sessions/cursors")
        assert resp2.status_code == 200
        data = resp2.json()
        assert len(data["cursors"]) == 1
        assert data["cursors"][0]["lat"] == pytest.approx(40.7)

    def test_update_layout(self, client):
        resp = client.post("/api/sessions", json={"username": "layout_test", "role": "observer"})
        sid = resp.json()["session"]["session_id"]
        resp2 = client.put(f"/api/sessions/{sid}/layout", json={
            "panel_layout": {"panels": ["targets", "fleet"]},
            "notification_prefs": {"sound": True},
        })
        assert resp2.status_code == 200

    def test_list_roles(self, client):
        resp = client.get("/api/sessions/roles/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["roles"]) == 5
        role_names = [r["role"] for r in data["roles"]]
        assert "admin" in role_names
        assert "commander" in role_names

    def test_default_colors_per_role(self, client):
        resp1 = client.post("/api/sessions", json={"username": "cmd", "role": "commander"})
        resp2 = client.post("/api/sessions", json={"username": "obs", "role": "observer"})
        assert resp1.json()["session"]["color"] == "#ff2a6d"  # magenta
        assert resp2.json()["session"]["color"] == "#8888aa"  # muted

    def test_multiple_sessions_same_user(self, client):
        client.post("/api/sessions", json={"username": "multi", "role": "analyst"})
        client.post("/api/sessions", json={"username": "multi", "role": "analyst"})
        resp = client.get("/api/sessions")
        assert resp.json()["total"] == 2
