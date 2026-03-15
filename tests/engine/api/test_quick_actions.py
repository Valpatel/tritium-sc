# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for /api/quick-actions endpoint."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.quick_actions import router


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router)
    app.state.event_bus = None
    return app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


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
