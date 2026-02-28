# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for game mission generation API endpoints.

Covers:
- GET /api/game/modes
- GET /api/game/models
- POST /api/game/generate
- POST /api/game/mission/apply
- GET /api/game/mission/current
- POST /api/game/models/evaluate
- GET /api/game/models/results
"""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_test_app():
    """Create a test FastAPI app with game router and mock engine.

    Each call creates a fresh engine with no cached MissionDirector/Evaluator,
    so tests are isolated.
    """
    from app.routers.game import router

    app = FastAPI()
    app.include_router(router)

    # Mock engine with real event bus behavior
    mock_bus = MagicMock()
    mock_bus.publish = MagicMock()
    mock_bus.subscribe = MagicMock(return_value=MagicMock())

    mock_game_mode = MagicMock()
    mock_game_mode.state = "setup"
    mock_game_mode.begin_war = MagicMock()

    # Use a simple namespace instead of MagicMock to avoid attr auto-creation
    class FreshEngine:
        def __init__(self):
            self.game_mode = mock_game_mode
            self._event_bus = mock_bus
            self.combat = MagicMock()
            self.combat.get_active_projectiles = MagicMock(return_value=[])
            self.add_target = MagicMock()
            self.reset_game = MagicMock()
            self.begin_war = MagicMock()

        def get_game_state(self):
            return {"state": "setup"}

    mock_engine = FreshEngine()
    app.state.simulation_engine = mock_engine
    return app, mock_engine


class TestGameModesEndpoint:
    def test_list_game_modes(self):
        app, _ = _create_test_app()
        client = TestClient(app)
        resp = client.get("/api/game/modes")
        assert resp.status_code == 200
        data = resp.json()
        assert "battle" in data
        assert "defense" in data
        assert "patrol" in data
        assert "escort" in data

    def test_mode_has_description(self):
        app, _ = _create_test_app()
        client = TestClient(app)
        resp = client.get("/api/game/modes")
        data = resp.json()
        assert "description" in data["battle"]
        assert "default_waves" in data["battle"]


class TestModelsEndpoint:
    def test_list_models(self):
        app, engine = _create_test_app()
        client = TestClient(app)
        resp = client.get("/api/game/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert isinstance(data["models"], list)


class TestGenerateEndpoint:
    def test_generate_scripted(self):
        app, engine = _create_test_app()
        client = TestClient(app)
        resp = client.post("/api/game/generate", json={
            "game_mode": "battle",
            "use_llm": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "complete"
        assert data["source"] == "scripted"
        assert "scenario" in data
        assert data["scenario"]["game_mode"] == "battle"

    def test_generate_llm_returns_generating(self):
        app, engine = _create_test_app()
        client = TestClient(app)
        resp = client.post("/api/game/generate", json={
            "game_mode": "defense",
            "use_llm": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "generating"
        assert data["source"] == "llm"

    def test_generate_with_custom_model(self):
        app, engine = _create_test_app()
        client = TestClient(app)
        resp = client.post("/api/game/generate", json={
            "game_mode": "battle",
            "use_llm": True,
            "model": "qwen2.5:7b",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"] == "qwen2.5:7b"


class TestMissionCurrentEndpoint:
    def test_no_scenario_initially(self):
        app, engine = _create_test_app()
        client = TestClient(app)
        resp = client.get("/api/game/mission/current")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "none"

    def test_scenario_after_generate(self):
        app, engine = _create_test_app()
        client = TestClient(app)

        # Generate scripted scenario
        client.post("/api/game/generate", json={
            "game_mode": "battle",
            "use_llm": False,
        })

        # Check current
        resp = client.get("/api/game/mission/current")
        data = resp.json()
        assert data["status"] == "ready"
        assert "scenario" in data


class TestMissionApplyEndpoint:
    def test_apply_without_scenario_fails(self):
        app, engine = _create_test_app()
        client = TestClient(app)
        resp = client.post("/api/game/mission/apply")
        assert resp.status_code == 400

    def test_apply_after_generate(self):
        app, engine = _create_test_app()
        client = TestClient(app)

        # Generate first
        client.post("/api/game/generate", json={
            "game_mode": "battle",
            "use_llm": False,
        })

        # Apply — now uses load_scenario() which places defenders + sets waves
        resp = client.post("/api/game/mission/apply")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "scenario_applied"
        assert data["game_mode"] == "battle"
        assert data["wave_count"] == 10
        assert data["defender_count"] >= 3
        assert engine.reset_game.called
        assert engine.begin_war.called
        assert engine.game_mode.load_scenario.called


class TestModelEvaluationEndpoints:
    def test_evaluate_starts(self):
        app, engine = _create_test_app()
        client = TestClient(app)
        resp = client.post("/api/game/models/evaluate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "evaluating"

    def test_results_initially_empty(self):
        app, engine = _create_test_app()
        client = TestClient(app)
        resp = client.get("/api/game/models/results")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "no_results"
        assert data["recommendation"] == "gemma3:4b"
