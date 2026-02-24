"""Unit tests for the scenarios API router (/api/scenarios/*).

Tests scenario listing, detail, compare, export, cache status,
run lookup, rating, and cleanup.
"""
from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.scenarios import router, _active_runs, _active_lock, RunRequest, RateRequest
from engine.scenarios.schema import (
    BehavioralProfile, Scenario, ScenarioResult, ScenarioScore,
)
from engine.scenarios.library import ScenarioLibrary


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _setup_library(td: str) -> ScenarioLibrary:
    """Create a ScenarioLibrary with test data in a temp dir."""
    lib = ScenarioLibrary(td)
    # Create a test scenario file
    scenario = Scenario(
        name="test_greeting",
        description="Test greeting",
        duration=30.0,
    )
    lib.save_scenario(scenario)

    # Create a result
    result = ScenarioResult(
        scenario_name="test_greeting",
        run_id="run-abc123",
        duration_actual=28.0,
        score=ScenarioScore(
            total_score=0.95,
            matched=1,
            total_expected=1,
            behavioral=BehavioralProfile(
                verbosity=0.9,
                lexical_diversity=0.85,
                responsiveness=1.0,
                composite_score=0.92,
            ),
        ),
        config={"chat_model": "gemma3:4b"},
        status="completed",
    )
    lib.save_result(result)
    return lib


@pytest.mark.unit
class TestScenariosList:
    """GET /api/scenarios — list all scenarios."""

    def test_list_returns_array(self):
        with tempfile.TemporaryDirectory() as td:
            lib = _setup_library(td)
            with patch("app.routers.scenarios._library", lib):
                client = TestClient(_make_app())
                resp = client.get("/api/scenarios")
                assert resp.status_code == 200
                data = resp.json()
                assert isinstance(data, list)
                assert len(data) >= 1

    def test_list_empty(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            with patch("app.routers.scenarios._library", lib):
                client = TestClient(_make_app())
                resp = client.get("/api/scenarios")
                assert resp.status_code == 200
                assert resp.json() == []


@pytest.mark.unit
class TestScenarioDetail:
    """GET /api/scenarios/{name} — scenario detail."""

    def test_get_existing(self):
        with tempfile.TemporaryDirectory() as td:
            lib = _setup_library(td)
            with patch("app.routers.scenarios._library", lib):
                client = TestClient(_make_app())
                resp = client.get("/api/scenarios/test_greeting")
                assert resp.status_code == 200
                data = resp.json()
                assert "scenario" in data
                assert "results" in data

    def test_get_nonexistent(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            with patch("app.routers.scenarios._library", lib):
                client = TestClient(_make_app())
                resp = client.get("/api/scenarios/nonexistent")
                assert resp.status_code == 404


@pytest.mark.unit
class TestScenarioStats:
    """GET /api/scenarios/stats — aggregate stats."""

    def test_stats_returns_dict(self):
        with tempfile.TemporaryDirectory() as td:
            lib = _setup_library(td)
            with patch("app.routers.scenarios._library", lib):
                client = TestClient(_make_app())
                resp = client.get("/api/scenarios/stats")
                assert resp.status_code == 200
                data = resp.json()
                assert isinstance(data, dict)


@pytest.mark.unit
class TestScenarioExport:
    """GET /api/scenarios/export — flat result export."""

    def test_export_all(self):
        with tempfile.TemporaryDirectory() as td:
            lib = _setup_library(td)
            with patch("app.routers.scenarios._library", lib):
                client = TestClient(_make_app())
                resp = client.get("/api/scenarios/export")
                assert resp.status_code == 200
                data = resp.json()
                assert isinstance(data, list)


@pytest.mark.unit
class TestScenarioCompare:
    """GET /api/scenarios/compare — compare two runs."""

    def test_compare_needs_two_runs(self):
        with tempfile.TemporaryDirectory() as td:
            lib = _setup_library(td)  # Only 1 result
            with patch("app.routers.scenarios._library", lib):
                client = TestClient(_make_app())
                resp = client.get("/api/scenarios/compare?scenario=test_greeting")
                assert resp.status_code == 400


@pytest.mark.unit
class TestScenarioRating:
    """POST /api/scenarios/run/{run_id}/rate — rate a run."""

    def test_rate_existing(self):
        with tempfile.TemporaryDirectory() as td:
            lib = _setup_library(td)
            with patch("app.routers.scenarios._library", lib):
                client = TestClient(_make_app())
                resp = client.post(
                    "/api/scenarios/run/run-abc123/rate",
                    json={"rating": 4},
                )
                assert resp.status_code == 200
                assert resp.json()["rating"] == 4

    def test_rate_nonexistent(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            with patch("app.routers.scenarios._library", lib):
                client = TestClient(_make_app())
                resp = client.post(
                    "/api/scenarios/run/nonexistent/rate",
                    json={"rating": 3},
                )
                assert resp.status_code == 404


@pytest.mark.unit
class TestActiveRuns:
    """GET /api/scenarios/active and DELETE cleanup."""

    def test_active_none(self):
        with patch("app.routers.scenarios._active_runs", {}):
            client = TestClient(_make_app())
            resp = client.get("/api/scenarios/active")
            assert resp.status_code == 200
            assert resp.json()["run_id"] is None

    def test_cleanup_removes_completed(self):
        test_runs = {
            "run-1": {"status": "completed"},
            "run-2": {"status": "running", "scenario_name": "test"},
            "run-3": {"status": "failed"},
        }
        with patch("app.routers.scenarios._active_runs", test_runs):
            client = TestClient(_make_app())
            resp = client.delete("/api/scenarios/runs/cleanup")
            assert resp.status_code == 200
            assert resp.json()["cleaned"] == 2
            assert "run-2" in test_runs  # Running kept
            assert "run-1" not in test_runs
            assert "run-3" not in test_runs


@pytest.mark.unit
class TestRunLookup:
    """GET /api/scenarios/run/{run_id} — run status lookup."""

    def test_active_run_status(self):
        import time
        test_runs = {
            "run-active": {
                "status": "running",
                "scenario_name": "test",
                "started": time.time(),
                "result": None,
            },
        }
        with patch("app.routers.scenarios._active_runs", test_runs):
            client = TestClient(_make_app())
            resp = client.get("/api/scenarios/run/run-active")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "running"

    def test_run_not_found(self):
        with patch("app.routers.scenarios._active_runs", {}):
            with tempfile.TemporaryDirectory() as td:
                lib = ScenarioLibrary(td)
                with patch("app.routers.scenarios._library", lib):
                    client = TestClient(_make_app())
                    resp = client.get("/api/scenarios/run/nonexistent")
                    assert resp.status_code == 404


@pytest.mark.unit
class TestRequestModels:
    """Pydantic model validation."""

    def test_run_request_defaults(self):
        req = RunRequest(name="test")
        assert req.chat_model is None
        assert req.use_listener is False

    def test_rate_request_bounds(self):
        r = RateRequest(rating=3)
        assert r.rating == 3

    def test_rate_request_rejects_invalid(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RateRequest(rating=0)
        with pytest.raises(ValidationError):
            RateRequest(rating=6)
