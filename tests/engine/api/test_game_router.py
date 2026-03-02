# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the game API router (/api/game/*).

Tests all endpoints: state, begin, reset, place, projectiles.
Uses FastAPI TestClient with a mocked simulation engine — no real server needed.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.game import router, PlaceUnit, UnitPosition


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
    engine._map_bounds = 500.0
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
        unit = PlaceUnit(name="T-1", asset_type="turret", position=UnitPosition(x=0, y=0))
        assert unit.name == "T-1"
        assert unit.asset_type == "turret"
        assert unit.position.x == 0
        assert unit.position.y == 0

    def test_position_from_dict(self):
        """Position can be constructed from a dict (JSON deserialization path)."""
        unit = PlaceUnit(name="T-1", asset_type="turret", position={"x": 0, "y": 0})
        assert unit.position.x == 0

    def test_missing_required_field(self):
        with pytest.raises(Exception):
            PlaceUnit(asset_type="turret", position={"x": 0, "y": 0})


@pytest.mark.unit
class TestPlaceUnitValidation:
    """Validation tests for POST /api/game/place asset_type and position."""

    def test_400_invalid_asset_type(self):
        """Unknown asset_type should be rejected with 400, not silently accepted."""
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Bad Unit",
            "asset_type": "banana",
            "position": {"x": 0, "y": 0},
        })
        assert resp.status_code == 400
        assert "asset_type" in resp.json()["detail"].lower()
        engine.add_target.assert_not_called()

    def test_400_empty_asset_type(self):
        """Empty string asset_type should be rejected."""
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Empty Type",
            "asset_type": "",
            "position": {"x": 0, "y": 0},
        })
        assert resp.status_code == 400
        engine.add_target.assert_not_called()

    def test_400_hostile_type_as_friendly(self):
        """Hostile-only types (person_hostile, hostile_vehicle) should not be placeable."""
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Sneaky",
            "asset_type": "person_hostile",
            "position": {"x": 0, "y": 0},
        })
        assert resp.status_code == 400
        engine.add_target.assert_not_called()

    def test_valid_types_accepted(self):
        """All legitimate friendly unit types should be accepted."""
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        for asset_type in ("turret", "drone", "rover", "tank", "apc",
                           "heavy_turret", "missile_turret", "scout_drone"):
            resp = client.post("/api/game/place", json={
                "name": f"{asset_type}-1",
                "asset_type": asset_type,
                "position": {"x": 0, "y": 0},
            })
            assert resp.status_code == 200, f"{asset_type} should be valid"

    def test_422_position_missing_x(self):
        """Position dict without 'x' key should return 422, not 500."""
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Bad Pos",
            "asset_type": "turret",
            "position": {"y": 5.0},
        })
        # Should be a clean validation error, not a 500 KeyError
        assert resp.status_code in (400, 422)
        engine.add_target.assert_not_called()

    def test_422_position_missing_y(self):
        """Position dict without 'y' key should return 422, not 500."""
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Bad Pos",
            "asset_type": "turret",
            "position": {"x": 5.0},
        })
        assert resp.status_code in (400, 422)
        engine.add_target.assert_not_called()

    def test_422_position_empty_dict(self):
        """Empty position dict should return 422, not 500."""
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "No Coords",
            "asset_type": "turret",
            "position": {},
        })
        assert resp.status_code in (400, 422)
        engine.add_target.assert_not_called()

    def test_400_position_outside_bounds(self):
        """Position outside map bounds should be rejected."""
        engine = _mock_engine(state="setup")
        engine._map_bounds = 500.0
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Far Away",
            "asset_type": "turret",
            "position": {"x": 9999.0, "y": 0.0},
        })
        assert resp.status_code == 400
        assert "outside" in resp.json()["detail"].lower()
        engine.add_target.assert_not_called()

    def test_400_position_negative_outside_bounds(self):
        """Negative position outside bounds should also be rejected."""
        engine = _mock_engine(state="setup")
        engine._map_bounds = 500.0
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Way South",
            "asset_type": "rover",
            "position": {"x": -100.0, "y": -600.0},
        })
        assert resp.status_code == 400
        engine.add_target.assert_not_called()

    def test_position_at_bounds_edge_accepted(self):
        """Position exactly at bounds edge should be accepted."""
        engine = _mock_engine(state="setup")
        engine._map_bounds = 500.0
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Edge Turret",
            "asset_type": "turret",
            "position": {"x": 500.0, "y": -500.0},
        })
        assert resp.status_code == 200

    def test_position_within_bounds_accepted(self):
        """Position well within bounds should be accepted."""
        engine = _mock_engine(state="setup")
        engine._map_bounds = 500.0
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/place", json={
            "name": "Center Turret",
            "asset_type": "turret",
            "position": {"x": 0.0, "y": 0.0},
        })
        assert resp.status_code == 200


@pytest.mark.unit
class TestListBattleScenarios:
    """GET /api/game/scenarios"""

    def test_lists_scenarios(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        names = [s["name"] for s in data]
        assert "street_combat" in names
        assert "riot" in names

    def test_scenario_fields(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/scenarios")
        for s in resp.json():
            assert "name" in s
            assert "description" in s
            assert "map_bounds" in s
            assert "wave_count" in s
            assert s["wave_count"] > 0


@pytest.mark.unit
class TestStartBattleScenario:
    """POST /api/game/battle/{scenario_name}"""

    def test_start_street_combat(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/battle/street_combat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scenario"] == "street_combat"
        assert data["status"] == "scenario_started"
        assert data["defender_count"] >= 1
        assert data["wave_count"] >= 5
        engine.reset_game.assert_called_once()
        engine.begin_war.assert_called_once()

    def test_start_riot(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/battle/riot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scenario"] == "riot"
        assert data["max_hostiles"] >= 100
        assert data["wave_count"] >= 7

    def test_404_unknown_scenario(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/battle/nonexistent")
        assert resp.status_code == 404

    def test_places_defenders(self):
        engine = _mock_engine(state="setup")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/battle/street_combat")
        assert resp.status_code == 200
        # Should have called add_target for each defender
        assert engine.add_target.call_count == resp.json()["defender_count"]

    def test_scenario_resets_first(self):
        """Starting a scenario resets any existing game state."""
        engine = _mock_engine(state="active")
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/battle/street_combat")
        assert resp.status_code == 200
        engine.reset_game.assert_called_once()


@pytest.mark.unit
class TestHostileIntel:
    """GET /api/game/hostile-intel — enemy commander tactical assessment."""

    def test_returns_assessment(self):
        """Returns the hostile commander's last tactical assessment."""
        engine = _mock_engine()
        engine.hostile_commander._last_assessment = {
            "threat_level": "moderate",
            "force_ratio": 1.5,
            "hostile_count": 6,
            "friendly_count": 4,
            "priority_targets": [
                {"id": "t1", "type": "turret", "priority": 5,
                 "position": (10, 20)},
            ],
            "recommended_action": "assault",
        }
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/hostile-intel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["threat_level"] == "moderate"
        assert data["force_ratio"] == 1.5
        assert data["recommended_action"] == "assault"
        assert len(data["priority_targets"]) == 1

    def test_returns_empty_before_assessment(self):
        """Returns empty dict when no assessment has been made yet."""
        engine = _mock_engine()
        engine.hostile_commander._last_assessment = {}
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/hostile-intel")
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_returns_503_no_engine(self):
        """Returns 503 when no simulation engine is running."""
        client = TestClient(_make_app(engine=None))
        resp = client.get("/api/game/hostile-intel")
        assert resp.status_code == 503

    def test_includes_objectives(self):
        """Includes per-unit objectives assigned by the commander."""
        engine = _mock_engine()
        engine.hostile_commander._last_assessment = {
            "threat_level": "high",
            "force_ratio": 0.8,
            "hostile_count": 3,
            "friendly_count": 4,
            "priority_targets": [],
            "recommended_action": "flank",
        }
        engine.hostile_commander._objectives = {
            "h1": MagicMock(to_dict=MagicMock(return_value={
                "type": "flank", "target_position": (50, 60),
                "priority": 3, "target_id": "t1",
            })),
        }
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/hostile-intel")
        assert resp.status_code == 200
        data = resp.json()
        assert "objectives" in data
        assert "h1" in data["objectives"]
        assert data["objectives"]["h1"]["type"] == "flank"


# ---------------------------------------------------------------------------
# Replay frame endpoint — playhead advancement
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestReplayFrameAdvance:
    """GET /api/game/replay/frame — verifies tick() is called when playing."""

    def _make_spectator_engine(self, playing=False, frame_index=0, total_frames=20):
        """Create a mock engine with a real-ish spectator."""
        engine = _mock_engine(state="active")
        # Build a mock spectator that tracks tick calls
        spectator = MagicMock()
        spectator._playing = playing
        spectator.current_frame = frame_index
        spectator.get_frame.return_value = {
            "targets": [{"target_id": "t1", "position": {"x": 10, "y": 20}}],
            "timestamp": 1000.0,
        }
        spectator.get_state.return_value = {
            "playing": playing,
            "speed": 1.0,
            "current_frame": frame_index,
            "total_frames": total_frames,
            "duration": 9.5,
            "current_time": frame_index / 2.0,
            "progress": frame_index / max(1, total_frames - 1),
        }
        engine.spectator = spectator
        return engine, spectator

    def test_frame_endpoint_does_not_tick(self):
        """The /replay/frame endpoint reads state but does not call tick().

        Playback advancement is now handled by the engine tick loop
        (SimulationEngine._do_tick calls spectator.tick(dt) at 10Hz).
        The HTTP endpoint is purely a read-only state accessor.
        """
        engine, spectator = self._make_spectator_engine(playing=True)
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/replay/frame")
        assert resp.status_code == 200
        spectator.tick.assert_not_called()

    def test_frame_endpoint_returns_frame_and_state(self):
        """Response should contain both 'frame' and 'state' keys."""
        engine, spectator = self._make_spectator_engine(playing=False)
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/replay/frame")
        assert resp.status_code == 200
        data = resp.json()
        assert "frame" in data
        assert "state" in data
        assert data["frame"]["targets"][0]["target_id"] == "t1"
        assert data["state"]["total_frames"] == 20

    def test_frame_endpoint_returns_current_state(self):
        """The returned state reflects the spectator's current position."""
        engine, spectator = self._make_spectator_engine(playing=True, frame_index=5)
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/replay/frame")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"]["current_frame"] == 5
