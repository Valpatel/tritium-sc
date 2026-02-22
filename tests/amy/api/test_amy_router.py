"""Unit tests for the Amy router (/api/amy/*).

Tests simulation endpoints (work in headless mode), 503 error responses
when Amy is disabled, layout management, and SpawnRequest validation.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amy.router import router, SpawnRequest, LayoutSaveRequest


def _make_app(amy=None, engine=None):
    """Create a minimal FastAPI app with Amy router."""
    app = FastAPI()
    app.include_router(router)
    app.state.amy = amy
    app.state.simulation_engine = engine
    return app


def _mock_engine(targets=None):
    """Create a mock SimulationEngine."""
    engine = MagicMock()
    engine.get_targets.return_value = targets or []
    engine.remove_target.return_value = True
    return engine


def _mock_target(target_id: str, alliance: str = "hostile", asset_type: str = "rover"):
    """Create a mock SimulationTarget."""
    t = MagicMock()
    t.target_id = target_id
    t.alliance = alliance
    t.asset_type = asset_type
    t.to_dict.return_value = {
        "target_id": target_id,
        "alliance": alliance,
        "asset_type": asset_type,
        "position": {"x": 0, "y": 0},
    }
    return t


# --- 503 responses when Amy is not running ---

@pytest.mark.unit
class TestAmyNotRunning:
    """All Amy-only endpoints return 503 when Amy is disabled."""

    def _client(self):
        return TestClient(_make_app())

    def test_status_503(self):
        resp = self._client().get("/api/amy/status")
        assert resp.status_code == 503

    def test_mode_get_503(self):
        resp = self._client().get("/api/amy/mode")
        assert resp.status_code == 503

    def test_mode_set_503(self):
        resp = self._client().post("/api/amy/mode", json={"mode": "sim"})
        assert resp.status_code == 503

    def test_thoughts_503(self):
        resp = self._client().get("/api/amy/thoughts")
        assert resp.status_code == 503

    def test_speak_503(self):
        resp = self._client().post("/api/amy/speak", json={"text": "hello"})
        assert resp.status_code == 503

    def test_chat_503(self):
        resp = self._client().post("/api/amy/chat", json={"text": "hello"})
        assert resp.status_code == 503

    def test_nodes_503(self):
        resp = self._client().get("/api/amy/nodes")
        assert resp.status_code == 503

    def test_memory_503(self):
        resp = self._client().get("/api/amy/memory")
        assert resp.status_code == 503

    def test_sensorium_503(self):
        resp = self._client().get("/api/amy/sensorium")
        assert resp.status_code == 503

    def test_auto_chat_503(self):
        resp = self._client().post("/api/amy/auto-chat")
        assert resp.status_code == 503

    def test_command_503(self):
        resp = self._client().post("/api/amy/command", json={"action": "look_at", "params": ["left"]})
        assert resp.status_code == 503

    def test_escalation_503(self):
        resp = self._client().get("/api/amy/escalation/status")
        assert resp.status_code == 503

    def test_war_state_503(self):
        resp = self._client().get("/api/amy/war/state")
        assert resp.status_code == 503


# --- Simulation endpoints (work in headless mode) ---

@pytest.mark.unit
class TestSimTargets:
    """GET /api/amy/simulation/targets"""

    def test_returns_targets(self):
        t1 = _mock_target("turret-1", "friendly", "turret")
        t2 = _mock_target("hostile-1", "hostile", "rover")
        engine = _mock_engine(targets=[t1, t2])
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/amy/simulation/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 2

    def test_empty_when_no_targets(self):
        engine = _mock_engine(targets=[])
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/amy/simulation/targets")
        data = resp.json()
        assert data["targets"] == []

    def test_returns_message_without_engine(self):
        client = TestClient(_make_app())
        resp = client.get("/api/amy/simulation/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["targets"] == []
        assert "not active" in data.get("message", "").lower()

    def test_prefers_amy_engine(self):
        """When Amy is running, uses Amy's simulation engine."""
        amy = MagicMock()
        amy_target = _mock_target("amy-t1", "friendly")
        amy.simulation_engine = _mock_engine(targets=[amy_target])

        headless_target = _mock_target("headless-t1", "hostile")
        headless_engine = _mock_engine(targets=[headless_target])

        client = TestClient(_make_app(amy=amy, engine=headless_engine))
        resp = client.get("/api/amy/simulation/targets")
        data = resp.json()
        assert data["targets"][0]["target_id"] == "amy-t1"


@pytest.mark.unit
class TestSimSpawn:
    """POST /api/amy/simulation/spawn"""

    def test_spawn_hostile(self):
        engine = _mock_engine()
        hostile = _mock_target("spawned-1", "hostile")
        engine.spawn_hostile.return_value = hostile
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/amy/simulation/spawn", json={
            "alliance": "hostile",
            "asset_type": "rover",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        engine.spawn_hostile.assert_called_once()

    def test_spawn_with_position(self):
        engine = _mock_engine()
        hostile = _mock_target("spawned-1", "hostile")
        engine.spawn_hostile.return_value = hostile
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/amy/simulation/spawn", json={
            "alliance": "hostile",
            "position": {"x": 10, "y": -5},
        })
        assert resp.status_code == 200
        call_kwargs = engine.spawn_hostile.call_args
        assert call_kwargs.kwargs.get("position") == (10, -5)

    def test_spawn_friendly(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/amy/simulation/spawn", json={
            "name": "My Turret",
            "alliance": "friendly",
            "asset_type": "turret",
            "position": {"x": 0, "y": 0},
        })
        assert resp.status_code == 200
        engine.add_target.assert_called_once()

    def test_503_without_engine(self):
        client = TestClient(_make_app())
        resp = client.post("/api/amy/simulation/spawn", json={
            "alliance": "hostile",
        })
        assert resp.status_code == 503


@pytest.mark.unit
class TestSimRemove:
    """DELETE /api/amy/simulation/targets/{target_id}"""

    def test_remove_existing(self):
        engine = _mock_engine()
        engine.remove_target.return_value = True
        client = TestClient(_make_app(engine=engine))
        resp = client.delete("/api/amy/simulation/targets/turret-1")
        assert resp.status_code == 200
        engine.remove_target.assert_called_once_with("turret-1")

    def test_remove_nonexistent(self):
        engine = _mock_engine()
        engine.remove_target.return_value = False
        client = TestClient(_make_app(engine=engine))
        resp = client.delete("/api/amy/simulation/targets/fake-id")
        assert resp.status_code == 404

    def test_503_without_engine(self):
        client = TestClient(_make_app())
        resp = client.delete("/api/amy/simulation/targets/any-id")
        assert resp.status_code == 503


# --- Layout management ---

@pytest.mark.unit
class TestLayouts:
    """Layout save/list/load endpoints."""

    def test_list_layouts_empty(self):
        client = TestClient(_make_app())
        resp = client.get("/api/amy/layouts")
        assert resp.status_code == 200
        assert resp.json()["layouts"] == [] or isinstance(resp.json()["layouts"], list)

    def test_save_and_list_layout(self):
        client = TestClient(_make_app())
        resp = client.post("/api/amy/layouts", json={
            "name": "test-layout",
            "data": {"format": "TritiumLevel", "objects": []},
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-layout"

    def test_get_nonexistent_layout(self):
        client = TestClient(_make_app())
        resp = client.get("/api/amy/layouts/nonexistent")
        assert resp.status_code == 404

    def test_layout_name_sanitized(self):
        client = TestClient(_make_app())
        resp = client.post("/api/amy/layouts", json={
            "name": "../../etc/passwd",
            "data": {"test": True},
        })
        assert resp.status_code == 200
        # Name should be sanitized
        assert ".." not in resp.json()["name"]


# --- Photos endpoint ---

@pytest.mark.unit
class TestPhotos:
    """Photo listing and serving."""

    def test_photos_empty_dir(self):
        """Photos endpoint returns empty list when directory doesn't exist."""
        original_isdir = os.path.isdir
        def fake_isdir(path):
            if "photos" in path:
                return False
            return original_isdir(path)
        with patch("os.path.isdir", side_effect=fake_isdir):
            client = TestClient(_make_app())
            resp = client.get("/api/amy/photos")
            assert resp.status_code == 200
            assert resp.json()["photos"] == []

    def test_photo_not_found(self):
        client = TestClient(_make_app())
        resp = client.get("/api/amy/photos/nonexistent.jpg")
        assert resp.status_code == 404

    def test_path_traversal_blocked(self):
        """Filename with ../ should be rejected."""
        client = TestClient(_make_app())
        resp = client.get("/api/amy/photos/../../../etc/passwd")
        # FastAPI might normalize the path; the handler checks normpath
        assert resp.status_code in (400, 404)


# --- Model validation ---

@pytest.mark.unit
class TestSpawnRequestModel:
    """SpawnRequest Pydantic model validation."""

    def test_defaults(self):
        req = SpawnRequest()
        assert req.alliance == "hostile"
        assert req.asset_type == "rover"
        assert req.name is None
        assert req.position is None

    def test_with_position(self):
        req = SpawnRequest(position={"x": 5, "y": -3})
        assert req.position["x"] == 5

    def test_with_latlng(self):
        req = SpawnRequest(lat=37.7, lng=-122.4)
        assert req.lat == 37.7
        assert req.lng == -122.4
