# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for game stats + replay transport API routes.

Tests:
  - GET /api/game/stats
  - GET /api/game/stats/summary
  - GET /api/game/stats/mvp
  - GET /api/game/replay
  - GET /api/game/replay/heatmap
  - GET /api/game/replay/timeline
  - POST /api/game/replay/play
  - POST /api/game/replay/pause
  - POST /api/game/replay/stop
  - POST /api/game/replay/seek
  - POST /api/game/replay/speed
  - POST /api/game/replay/step-forward
  - POST /api/game/replay/step-backward
  - POST /api/game/replay/seek-wave
  - GET /api/game/replay/state
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.game import router


def _make_app(engine=None, amy=None):
    """Create a minimal FastAPI app with game router and optional engine/amy."""
    app = FastAPI()
    app.include_router(router)
    app.state.simulation_engine = engine
    app.state.amy = amy
    return app


def _mock_engine(state="active"):
    """Create a mock SimulationEngine with stats_tracker and replay_recorder."""
    engine = MagicMock()
    engine.game_mode.state = state
    engine._map_bounds = 500.0
    engine.combat.get_active_projectiles.return_value = []
    engine.get_targets.return_value = []
    return engine


# ---------------------------------------------------------------------------
# Stats endpoints
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetBattleStats:
    """GET /api/game/stats"""

    def test_returns_full_stats(self):
        engine = _mock_engine()
        engine.stats_tracker.to_dict.return_value = {
            "units": [
                {"target_id": "turret-01", "kills": 5, "deaths": 0, "accuracy": 0.8},
            ],
            "waves": [
                {"wave_number": 1, "hostiles_spawned": 10, "hostiles_eliminated": 8},
            ],
            "summary": {"total_kills": 5, "total_deaths": 0},
        }
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "units" in data
        assert "waves" in data
        assert "summary" in data
        assert data["units"][0]["target_id"] == "turret-01"

    def test_503_without_engine(self):
        client = TestClient(_make_app(engine=None))
        resp = client.get("/api/game/stats")
        assert resp.status_code == 503

    def test_empty_stats_before_battle(self):
        engine = _mock_engine(state="setup")
        engine.stats_tracker.to_dict.return_value = {
            "units": [],
            "waves": [],
            "summary": {"total_kills": 0, "total_deaths": 0},
        }
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["units"] == []
        assert data["waves"] == []


@pytest.mark.unit
class TestGetStatsSummary:
    """GET /api/game/stats/summary"""

    def test_returns_summary(self):
        engine = _mock_engine()
        engine.stats_tracker.get_summary.return_value = {
            "total_kills": 12,
            "total_deaths": 2,
            "total_shots_fired": 50,
            "total_shots_hit": 40,
            "overall_accuracy": 0.8,
            "total_damage_dealt": 1200.5,
            "total_damage_taken": 300.0,
            "waves_completed": 5,
            "battle_duration": 120.0,
        }
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/stats/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_kills"] == 12
        assert data["overall_accuracy"] == 0.8
        assert data["waves_completed"] == 5

    def test_503_without_engine(self):
        client = TestClient(_make_app(engine=None))
        resp = client.get("/api/game/stats/summary")
        assert resp.status_code == 503


@pytest.mark.unit
class TestGetMVP:
    """GET /api/game/stats/mvp"""

    def test_returns_mvp(self):
        engine = _mock_engine()
        mvp_mock = MagicMock()
        mvp_mock.to_dict.return_value = {
            "target_id": "turret-01",
            "name": "Alpha Turret",
            "kills": 8,
            "deaths": 0,
            "accuracy": 0.85,
            "damage_dealt": 800.0,
        }
        engine.stats_tracker.get_mvp.return_value = mvp_mock
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/stats/mvp")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["mvp"]["target_id"] == "turret-01"
        assert data["mvp"]["kills"] == 8

    def test_returns_no_data_when_empty(self):
        engine = _mock_engine()
        engine.stats_tracker.get_mvp.return_value = None
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/stats/mvp")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "no_data"

    def test_503_without_engine(self):
        client = TestClient(_make_app(engine=None))
        resp = client.get("/api/game/stats/mvp")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Replay data endpoints
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReplayDataEndpoints:
    """GET /api/game/replay, /replay/heatmap, /replay/timeline"""

    def test_get_replay(self):
        engine = _mock_engine()
        engine.replay_recorder.export_json.return_value = {
            "frames": [{"tick": 0, "targets": []}],
            "events": [],
            "duration": 60.0,
        }
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/replay")
        assert resp.status_code == 200
        data = resp.json()
        assert "frames" in data
        assert "events" in data

    def test_get_heatmap(self):
        engine = _mock_engine()
        engine.replay_recorder.get_heatmap_data.return_value = {
            "kills": [{"x": 10, "y": 20, "count": 3}],
            "deaths": [{"x": 50, "y": 60, "count": 1}],
        }
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/replay/heatmap")
        assert resp.status_code == 200
        data = resp.json()
        assert "kills" in data
        assert len(data["kills"]) == 1

    def test_get_timeline(self):
        engine = _mock_engine()
        engine.replay_recorder.get_timeline.return_value = [
            {"time": 5.0, "type": "wave_start", "wave": 1},
            {"time": 30.0, "type": "elimination", "target_id": "hostile-01"},
        ]
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/replay/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["type"] == "wave_start"

    def test_503_without_engine(self):
        client = TestClient(_make_app(engine=None))
        for path in ("/api/game/replay", "/api/game/replay/heatmap",
                      "/api/game/replay/timeline"):
            resp = client.get(path)
            assert resp.status_code == 503, f"{path} should return 503"


# ---------------------------------------------------------------------------
# Spectator transport controls
# ---------------------------------------------------------------------------


def _make_spectator_engine(playing=False, speed=1.0, frame=0, total=20):
    """Create a mock engine with a spectator mock already wired."""
    engine = _mock_engine()
    spectator = MagicMock()
    spectator._playing = playing
    spectator.current_frame = frame
    spectator.get_state.return_value = {
        "playing": playing,
        "speed": speed,
        "current_frame": frame,
        "total_frames": total,
        "duration": total / 2.0,
        "current_time": frame / 2.0,
        "progress": frame / max(1, total - 1),
    }
    engine._spectator = spectator
    return engine, spectator


@pytest.mark.unit
class TestReplayPlay:
    """POST /api/game/replay/play"""

    def test_play_calls_spectator(self):
        engine, spectator = _make_spectator_engine(playing=False)
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/replay/play")
        assert resp.status_code == 200
        spectator.play.assert_called_once()
        data = resp.json()
        assert "playing" in data

    def test_503_without_engine(self):
        client = TestClient(_make_app(engine=None))
        resp = client.post("/api/game/replay/play")
        assert resp.status_code == 503


@pytest.mark.unit
class TestReplayPause:
    """POST /api/game/replay/pause"""

    def test_pause_calls_spectator(self):
        engine, spectator = _make_spectator_engine(playing=True)
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/replay/pause")
        assert resp.status_code == 200
        spectator.pause.assert_called_once()


@pytest.mark.unit
class TestReplayStop:
    """POST /api/game/replay/stop"""

    def test_stop_calls_spectator(self):
        engine, spectator = _make_spectator_engine(playing=True)
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/replay/stop")
        assert resp.status_code == 200
        spectator.stop.assert_called_once()


@pytest.mark.unit
class TestReplaySeek:
    """POST /api/game/replay/seek"""

    def test_seek_time(self):
        engine, spectator = _make_spectator_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/replay/seek", json={"time": 5.0})
        assert resp.status_code == 200
        spectator.seek_time.assert_called_once_with(5.0)

    def test_422_missing_time(self):
        engine, spectator = _make_spectator_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/replay/seek", json={})
        assert resp.status_code == 422


@pytest.mark.unit
class TestReplaySpeed:
    """POST /api/game/replay/speed"""

    def test_set_speed(self):
        engine, spectator = _make_spectator_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/replay/speed", json={"speed": 2.0})
        assert resp.status_code == 200
        spectator.set_speed.assert_called_once_with(2.0)

    def test_422_missing_speed(self):
        engine, spectator = _make_spectator_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/replay/speed", json={})
        assert resp.status_code == 422


@pytest.mark.unit
class TestReplayStepForward:
    """POST /api/game/replay/step-forward"""

    def test_step_forward(self):
        engine, spectator = _make_spectator_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/replay/step-forward")
        assert resp.status_code == 200
        spectator.step_forward.assert_called_once()


@pytest.mark.unit
class TestReplayStepBackward:
    """POST /api/game/replay/step-backward"""

    def test_step_backward(self):
        engine, spectator = _make_spectator_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/replay/step-backward")
        assert resp.status_code == 200
        spectator.step_backward.assert_called_once()


@pytest.mark.unit
class TestReplaySeekWave:
    """POST /api/game/replay/seek-wave"""

    def test_seek_wave(self):
        engine, spectator = _make_spectator_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/replay/seek-wave", json={"wave": 3})
        assert resp.status_code == 200
        spectator.seek_wave.assert_called_once_with(3)

    def test_422_missing_wave(self):
        engine, spectator = _make_spectator_engine()
        client = TestClient(_make_app(engine=engine))
        resp = client.post("/api/game/replay/seek-wave", json={})
        assert resp.status_code == 422


@pytest.mark.unit
class TestReplayState:
    """GET /api/game/replay/state"""

    def test_get_replay_state(self):
        engine, spectator = _make_spectator_engine(playing=True, speed=2.0, frame=5)
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/game/replay/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["playing"] is True
        assert data["speed"] == 2.0
        assert data["current_frame"] == 5

    def test_503_without_engine(self):
        client = TestClient(_make_app(engine=None))
        resp = client.get("/api/game/replay/state")
        assert resp.status_code == 503
