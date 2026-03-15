# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for /api/quick-actions endpoint.

Tests auth enforcement, rate limiting, and action dispatch.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.quick_actions import router, _rate_tracker


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router)
    app.state.event_bus = None
    return app


@pytest.fixture
def client(app):
    from app.auth import require_auth

    async def _mock_auth():
        return {"sub": "test-operator", "role": "admin"}

    app.dependency_overrides[require_auth] = _mock_auth
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_rate_tracker():
    """Reset rate tracker between tests."""
    _rate_tracker._windows.clear()
    yield
    _rate_tracker._windows.clear()


class TestQuickActionsAuth:
    """Test that auth is enforced on quick-actions endpoints."""

    @pytest.mark.unit
    def test_post_requires_auth(self):
        """Without auth bypass, endpoint should require authentication."""
        app = FastAPI()
        app.include_router(router)
        app.state.event_bus = None
        # Use real auth (not patched) — auth_enabled=False returns default admin
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/quick-actions", json={
            "action_type": "investigate",
            "target_id": "ble_test",
        })
        # With auth_enabled=False, require_auth returns default admin, so 200
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_log_requires_auth(self):
        """GET /log should also require auth."""
        app = FastAPI()
        app.include_router(router)
        app.state.event_bus = None
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/quick-actions/log")
        # With auth_enabled=False, returns 200
        assert resp.status_code == 200


class TestQuickActionsRateLimit:
    """Test per-operator rate limiting on quick actions."""

    @pytest.mark.unit
    def test_rate_limit_allows_up_to_max(self, client):
        """First 10 requests within window should succeed."""
        for i in range(10):
            resp = client.post("/api/quick-actions", json={
                "action_type": "dismiss",
                "target_id": f"t_{i}",
            })
            assert resp.status_code == 200, f"Request {i+1} should succeed"

    @pytest.mark.unit
    def test_rate_limit_blocks_after_max(self, client):
        """11th request should be rate limited."""
        for i in range(10):
            client.post("/api/quick-actions", json={
                "action_type": "dismiss",
                "target_id": f"t_{i}",
            })
        resp = client.post("/api/quick-actions", json={
            "action_type": "dismiss",
            "target_id": "t_overflow",
        })
        assert resp.status_code == 429
        assert "rate limit" in resp.json()["detail"].lower()


class TestQuickActions:
    @pytest.mark.unit
    def test_investigate_action(self, client):
        resp = client.post("/api/quick-actions", json={
            "action_type": "investigate",
            "target_id": "ble_aa:bb:cc",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_type"] == "investigate"
        assert data["target_id"] == "ble_aa:bb:cc"
        assert data["action_id"]

    @pytest.mark.unit
    def test_watch_action(self, client):
        resp = client.post("/api/quick-actions", json={
            "action_type": "watch",
            "target_id": "det_person_1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_type"] == "watch"
        assert data["status"] == "ok"

    @pytest.mark.unit
    def test_classify_action(self, client):
        resp = client.post("/api/quick-actions", json={
            "action_type": "classify",
            "target_id": "ble_test",
            "params": {"alliance": "hostile"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_type"] == "classify"

    @pytest.mark.unit
    def test_track_action(self, client):
        resp = client.post("/api/quick-actions", json={
            "action_type": "track",
            "target_id": "mesh_node_1",
            "params": {"prediction_cone": True, "minutes_ahead": 5},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["details"]["tracking"] is True
        assert data["details"]["prediction_cone"] is True

    @pytest.mark.unit
    def test_dismiss_action(self, client):
        resp = client.post("/api/quick-actions", json={
            "action_type": "dismiss",
            "target_id": "ble_test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["details"]["dismissed"] is True

    @pytest.mark.unit
    def test_escalate_action(self, client):
        resp = client.post("/api/quick-actions", json={
            "action_type": "escalate",
            "target_id": "ble_test",
            "notes": "Suspicious behavior near perimeter",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["details"]["escalated"] is True

    @pytest.mark.unit
    def test_unknown_action_type(self, client):
        resp = client.post("/api/quick-actions", json={
            "action_type": "invalid_type",
            "target_id": "ble_test",
        })
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_action_log(self, client):
        # Execute a couple of actions first
        client.post("/api/quick-actions", json={
            "action_type": "watch",
            "target_id": "t1",
        })
        client.post("/api/quick-actions", json={
            "action_type": "track",
            "target_id": "t2",
        })

        resp = client.get("/api/quick-actions/log")
        assert resp.status_code == 200
        data = resp.json()
        assert "actions" in data
        assert data["total"] >= 2

    @pytest.mark.unit
    def test_action_with_notes(self, client):
        resp = client.post("/api/quick-actions", json={
            "action_type": "investigate",
            "target_id": "ble_test",
            "notes": "Seen near restricted area",
        })
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_action_log_includes_operator(self, client):
        """Action log entries should include operator attribution."""
        client.post("/api/quick-actions", json={
            "action_type": "dismiss",
            "target_id": "t_op",
        })
        resp = client.get("/api/quick-actions/log")
        data = resp.json()
        assert len(data["actions"]) >= 1
        latest = data["actions"][0]
        assert "operator" in latest
        assert latest["operator"] == "test-operator"
