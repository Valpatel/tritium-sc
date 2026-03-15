# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the collaboration API — workspaces, drawings, chat."""

import pytest
from unittest.mock import AsyncMock, patch

# Mark all tests as unit tests
pytestmark = pytest.mark.unit


@pytest.fixture
def client():
    """Create a test client with collaboration router."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.collaboration import router, _workspaces, _chat_history, _drawings

    # Clear state between tests
    _workspaces.clear()
    _chat_history.clear()
    _drawings.clear()

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestWorkspaces:
    def test_create_workspace(self, client):
        resp = client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-001",
            "title": "Test Workspace",
            "operator_id": "op1",
            "operator_name": "Alice",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["investigation_id"] == "inv-001"
        assert data["title"] == "Test Workspace"
        assert "workspace_id" in data
        assert data["active_operators"] == ["op1"]

    def test_list_workspaces(self, client):
        # Create two workspaces
        client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-001",
            "operator_id": "op1",
        })
        client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-002",
            "operator_id": "op2",
        })

        resp = client.get("/api/collaboration/workspaces")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_filter_workspaces_by_investigation(self, client):
        client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-001",
            "operator_id": "op1",
        })
        client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-002",
            "operator_id": "op2",
        })

        resp = client.get("/api/collaboration/workspaces?investigation_id=inv-001")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_join_workspace(self, client):
        resp = client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-001",
            "operator_id": "op1",
        })
        ws_id = resp.json()["workspace_id"]

        resp = client.post(f"/api/collaboration/workspaces/{ws_id}/join", json={
            "operator_id": "op2",
            "operator_name": "Bob",
        })
        assert resp.status_code == 200
        assert "op2" in resp.json()["active_operators"]

    def test_leave_workspace(self, client):
        resp = client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-001",
            "operator_id": "op1",
        })
        ws_id = resp.json()["workspace_id"]

        resp = client.post(f"/api/collaboration/workspaces/{ws_id}/leave", json={
            "operator_id": "op1",
        })
        assert resp.status_code == 200
        assert "op1" not in resp.json()["active_operators"]

    def test_add_entity(self, client):
        resp = client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-001",
            "operator_id": "op1",
        })
        ws_id = resp.json()["workspace_id"]

        resp = client.post(f"/api/collaboration/workspaces/{ws_id}/entity", json={
            "entity_id": "ble_aa:bb:cc",
            "operator_id": "op1",
        })
        assert resp.status_code == 200
        assert resp.json()["entity_id"] == "ble_aa:bb:cc"
        assert resp.json()["version"] == 1

    def test_annotate_in_workspace(self, client):
        resp = client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-001",
            "operator_id": "op1",
        })
        ws_id = resp.json()["workspace_id"]

        resp = client.post(f"/api/collaboration/workspaces/{ws_id}/annotate", json={
            "entity_id": "ble_aa:bb:cc",
            "note": "Suspicious device near entrance",
            "operator_id": "op1",
        })
        assert resp.status_code == 200
        assert resp.json()["version"] == 1

    def test_annotate_empty_note_rejected(self, client):
        resp = client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-001",
            "operator_id": "op1",
        })
        ws_id = resp.json()["workspace_id"]

        resp = client.post(f"/api/collaboration/workspaces/{ws_id}/annotate", json={
            "entity_id": "ble_aa:bb:cc",
            "note": "   ",
            "operator_id": "op1",
        })
        assert resp.status_code == 400

    def test_change_status(self, client):
        resp = client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-001",
            "operator_id": "op1",
        })
        ws_id = resp.json()["workspace_id"]

        resp = client.post(f"/api/collaboration/workspaces/{ws_id}/status", json={
            "new_status": "in_progress",
            "operator_id": "op1",
        })
        assert resp.status_code == 200
        assert resp.json()["new_status"] == "in_progress"

    def test_invalid_status_rejected(self, client):
        resp = client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-001",
            "operator_id": "op1",
        })
        ws_id = resp.json()["workspace_id"]

        resp = client.post(f"/api/collaboration/workspaces/{ws_id}/status", json={
            "new_status": "invalid_status",
            "operator_id": "op1",
        })
        assert resp.status_code == 400

    def test_delete_workspace(self, client):
        resp = client.post("/api/collaboration/workspaces", json={
            "investigation_id": "inv-001",
            "operator_id": "op1",
        })
        ws_id = resp.json()["workspace_id"]

        resp = client.delete(f"/api/collaboration/workspaces/{ws_id}")
        assert resp.status_code == 200

        resp = client.get(f"/api/collaboration/workspaces/{ws_id}")
        assert resp.status_code == 404

    def test_workspace_not_found(self, client):
        resp = client.get("/api/collaboration/workspaces/nonexistent")
        assert resp.status_code == 404


class TestMapDrawings:
    def test_create_drawing(self, client):
        resp = client.post("/api/collaboration/drawings", json={
            "drawing_type": "freehand",
            "operator_id": "op1",
            "operator_name": "Alice",
            "color": "#00f0ff",
            "coordinates": [[-74.006, 40.7128], [-74.005, 40.7130]],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["drawing_type"] == "freehand"
        assert "drawing_id" in data

    def test_create_circle_drawing(self, client):
        resp = client.post("/api/collaboration/drawings", json={
            "drawing_type": "circle",
            "operator_id": "op1",
            "coordinates": [[-74.006, 40.7128]],
            "radius": 50.0,
            "label": "Perimeter",
        })
        assert resp.status_code == 200
        assert resp.json()["radius"] == 50.0

    def test_invalid_drawing_type(self, client):
        resp = client.post("/api/collaboration/drawings", json={
            "drawing_type": "invalid",
            "operator_id": "op1",
        })
        assert resp.status_code == 400

    def test_list_drawings(self, client):
        client.post("/api/collaboration/drawings", json={
            "drawing_type": "line",
            "operator_id": "op1",
            "layer": "tactical",
        })
        client.post("/api/collaboration/drawings", json={
            "drawing_type": "circle",
            "operator_id": "op2",
            "layer": "planning",
        })

        resp = client.get("/api/collaboration/drawings")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_filter_drawings_by_layer(self, client):
        client.post("/api/collaboration/drawings", json={
            "drawing_type": "line",
            "operator_id": "op1",
            "layer": "tactical",
        })
        client.post("/api/collaboration/drawings", json={
            "drawing_type": "circle",
            "operator_id": "op2",
            "layer": "planning",
        })

        resp = client.get("/api/collaboration/drawings?layer=tactical")
        assert resp.json()["total"] == 1

    def test_update_drawing(self, client):
        resp = client.post("/api/collaboration/drawings", json={
            "drawing_type": "line",
            "operator_id": "op1",
            "color": "#00f0ff",
        })
        did = resp.json()["drawing_id"]

        resp = client.put(f"/api/collaboration/drawings/{did}", json={
            "color": "#ff2a6d",
            "label": "Updated label",
        })
        assert resp.status_code == 200
        assert resp.json()["color"] == "#ff2a6d"

    def test_delete_drawing(self, client):
        resp = client.post("/api/collaboration/drawings", json={
            "drawing_type": "line",
            "operator_id": "op1",
        })
        did = resp.json()["drawing_id"]

        resp = client.delete(f"/api/collaboration/drawings/{did}")
        assert resp.status_code == 200

    def test_clear_drawings(self, client):
        client.post("/api/collaboration/drawings", json={
            "drawing_type": "line",
            "operator_id": "op1",
        })
        client.post("/api/collaboration/drawings", json={
            "drawing_type": "circle",
            "operator_id": "op1",
        })

        resp = client.delete("/api/collaboration/drawings")
        assert resp.status_code == 200
        assert resp.json()["removed"] == 2


class TestOperatorChat:
    def test_send_message(self, client):
        resp = client.post("/api/collaboration/chat", json={
            "operator_id": "op1",
            "operator_name": "Alice",
            "content": "Target moving south",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"].startswith("Target moving")
        assert data["channel"] == "general"

    def test_empty_message_rejected(self, client):
        resp = client.post("/api/collaboration/chat", json={
            "operator_id": "op1",
            "content": "",
        })
        assert resp.status_code == 400

    def test_chat_history(self, client):
        client.post("/api/collaboration/chat", json={
            "operator_id": "op1",
            "content": "Message 1",
        })
        client.post("/api/collaboration/chat", json={
            "operator_id": "op2",
            "content": "Message 2",
        })

        resp = client.get("/api/collaboration/chat?channel=general")
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 2

    def test_chat_channels(self, client):
        client.post("/api/collaboration/chat", json={
            "operator_id": "op1",
            "content": "Hello",
            "channel": "general",
        })
        client.post("/api/collaboration/chat", json={
            "operator_id": "op1",
            "content": "Contact!",
            "channel": "tactical",
        })

        resp = client.get("/api/collaboration/chat/channels")
        assert resp.status_code == 200
        assert len(resp.json()["channels"]) == 2

    def test_invalid_message_type(self, client):
        resp = client.post("/api/collaboration/chat", json={
            "operator_id": "op1",
            "content": "Test",
            "message_type": "invalid",
        })
        assert resp.status_code == 400

    def test_html_sanitization(self, client):
        resp = client.post("/api/collaboration/chat", json={
            "operator_id": "op1",
            "content": "<script>alert('xss')</script>Hello",
        })
        assert resp.status_code == 200
        assert "<script>" not in resp.json()["content"]
