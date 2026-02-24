"""Unit tests for the game API router (/api/game/*).

Tests all endpoints: state, begin, reset, place, projectiles.
Uses FastAPI TestClient with a mocked simulation engine — no real server needed.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.game import router, PlaceUnit


def _make_app(engine=None, amy=None):
    """Create a minimal FastAPI app with game router and optional engine/amy."""
    app = FastAPI()
    app.include_router(router)
    app.state.simulation_engine = engine
    app.state.amy = amy
    return app


def _mock_engine(state="setup", wave=1, total_eliminations=0, targets=None):
    """Create a mock SimulationEngine with game_mode and combat."""
    engine = MagicMock()
    engine.game_mode.state = state
    engine.get_game_state.return_value = {
        "state": state,
        "wave": wave,
        "total_eliminations": total_eliminations,
    }
    engine.combat.get_active_projectiles.return_value = []
    engine.get_targets.return_value = targets or []
    return engine


@pytest.mark.unit
class TestGetGameState:
    """GET /api/game/state"""

    def test_returns_state(self):
        engine = _mock_engine(state="active", wave=3, total_eliminations=5)
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "active"
        assert data["wave"] == 3
        assert data["total_eliminations"] == 5

    def test_503_without_engine(self):
        client = TestClient(_make_app(engine=None))
        resp = client.get("/api/game/state")
        assert resp.status_code == 503

    def test_prefers_amy_engine(self):
        """When both Amy and headless engine exist, Amy's engine wins."""
        amy = MagicMock()
        amy_engine = _mock_engine(state="active", wave=5)
        amy.simulation_engine = amy_engine
        headless_engine = _mock_engine(state="setup", wave=1)

        client = TestClient(_make_app(engine=headless_engine, amy=amy))
        resp = client.get("/api/game/state")
        assert resp.status_code == 200
        assert resp.json()["wave"] == 5  # Amy's engine, not headless

    def test_falls_back_to_headless(self):
        """When Amy has no sim engine, falls back to headless."""
        amy = MagicMock()
        amy.simulation_engine = None
        headless_engine = _mock_engine(state="setup", wave=1)

        client = TestClient(_make_app(engine=headless_engine, amy=amy))
        resp = client.get("/api/game/state")
        assert resp.status_code == 200
        assert resp.json()["state"] == "setup"


@pytest.mark.unit
class TestBeginWar:
    """POST /api/game/begin"""

    def test_begin_from_setup(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/begin")
        assert resp.status_code == 200
        assert resp.json()["status"] == "countdown_started"
        engine.begin_war.assert_called_once()

    def test_400_if_not_setup(self):
        engine = _mock_engine(state="active")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/begin")
        assert resp.status_code == 400
        assert "Cannot begin war" in resp.json()["detail"]

    def test_400_during_countdown(self):
        engine = _mock_engine(state="countdown")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/begin")
        assert resp.status_code == 400

    def test_400_after_victory(self):
        engine = _mock_engine(state="victory")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/begin")
        assert resp.status_code == 400


@pytest.mark.unit
class TestResetGame:
    """POST /api/game/reset"""

    def test_reset_returns_setup(self):
        engine = _mock_engine(state="active")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/reset")
        assert resp.status_code == 200
        assert resp.json()["state"] == "setup"
        engine.reset_game.assert_called_once()

    def test_reset_from_any_state(self):
        for state in ("setup", "countdown", "active", "victory", "defeat"):
            engine = _mock_engine(state=state)
            client = TestClient(_make_app(engine=engine))
            resp = client.post("/api/game/reset")
            assert resp.status_code == 200


@pytest.mark.unit
class TestPlaceUnit:
    """POST /api/game/place"""

    def test_place_turret(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Turret-1",
            "asset_type": "turret",
            "position": {"x": 5.0, "y": 10.0},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "target_id" in data
        assert data["status"] == "placed"
        engine.add_target.assert_called_once()

    def test_place_drone(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Drone-1",
            "asset_type": "drone",
            "position": {"x": 0, "y": 0},
        })
        assert resp.status_code == 200
        # Drone should have speed > 0
        placed = engine.add_target.call_args[0][0]
        assert placed.speed > 0

    def test_place_rover(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Rover-1",
            "asset_type": "rover",
            "position": {"x": -3, "y": 7},
        })
        assert resp.status_code == 200

    def test_400_during_active(self):
        engine = _mock_engine(state="active")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Turret-X",
            "asset_type": "turret",
            "position": {"x": 0, "y": 0},
        })
        assert resp.status_code == 400
        assert "setup" in resp.json()["detail"].lower()

    def test_422_missing_name(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "asset_type": "turret",
            "position": {"x": 0, "y": 0},
        })
        assert resp.status_code == 422  # Pydantic validation

    def test_422_missing_position(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Turret-1",
            "asset_type": "turret",
        })
        assert resp.status_code == 422

    def test_422_flat_xy_rejected(self):
        """Old payload format {x, y} without nested position is rejected."""
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Turret-1",
            "asset_type": "turret",
            "x": 0,
            "y": 0,
        })
        assert resp.status_code == 422

    def test_turret_is_stationary(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        client.post("/api/game/place", json={
            "name": "Turret-1",
            "asset_type": "turret",
            "position": {"x": 0, "y": 0},
        })
        placed = engine.add_target.call_args[0][0]
        assert placed.speed == 0.0
        assert placed.status == "stationary"

    def test_placed_target_has_combat_profile(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        client.post("/api/game/place", json={
            "name": "Turret-1",
            "asset_type": "turret",
            "position": {"x": 0, "y": 0},
        })
        placed = engine.add_target.call_args[0][0]
        # apply_combat_profile should have been called before add_target
        assert placed.is_combatant is True
        assert placed.health > 0
        assert placed.weapon_range > 0

    def test_position_stored_correctly(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        client.post("/api/game/place", json={
            "name": "Turret-1",
            "asset_type": "turret",
            "position": {"x": 12.5, "y": -7.3},
        })
        placed = engine.add_target.call_args[0][0]
        assert placed.position == (12.5, -7.3)


@pytest.mark.unit
class TestGetProjectiles:
    """GET /api/game/projectiles"""

    def test_returns_empty_list(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/projectiles")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_active_projectiles(self):
        engine = _mock_engine()
        engine.combat.get_active_projectiles.return_value = [
            {"from": "turret-a", "to": "hostile-1", "progress": 0.5}
        ]
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/projectiles")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["from"] == "turret-a"


@pytest.mark.unit
class TestPlaceUnitModel:
    """Pydantic model validation for PlaceUnit."""

    def test_valid_input(self):
        unit = PlaceUnit(name="T-1", asset_type="turret", position={"x": 0, "y": 0})
        assert unit.name == "T-1"
        assert unit.asset_type == "turret"
        assert unit.position == {"x": 0, "y": 0}

    def test_extra_fields_ignored(self):
        """Extra fields in position dict are allowed (dict, not strict model)."""
        unit = PlaceUnit(name="T-1", asset_type="turret", position={"x": 0, "y": 0, "z": 5})
        assert unit.position["z"] == 5

    def test_missing_required_field(self):
        with pytest.raises(Exception):
            PlaceUnit(asset_type="turret", position={"x": 0, "y": 0})
