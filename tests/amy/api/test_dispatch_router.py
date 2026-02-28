# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for POST /api/amy/simulation/dispatch endpoint.

Tests:
  - Happy path: dispatch succeeds, returns 200
  - Unit not found: returns 404
  - Simulation not active: returns 409
  - Invalid body (missing fields): returns 422
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amy.router import router


def _make_sim_target(target_id: str, alliance: str = "friendly",
                     asset_type: str = "rover", x: float = 0, y: float = 0):
    """Create a mock SimulationTarget."""
    t = MagicMock()
    t.target_id = target_id
    t.alliance = alliance
    t.asset_type = asset_type
    t.position = (x, y)
    t.waypoints = []
    t.status = "idle"
    t.to_dict.return_value = {
        "target_id": target_id,
        "alliance": alliance,
        "asset_type": asset_type,
        "position": {"x": x, "y": y},
        "status": "idle",
    }
    return t


def _make_app(engine=None):
    """Create a minimal FastAPI app with Amy router."""
    app = FastAPI()
    app.include_router(router)
    app.state.amy = None
    app.state.simulation_engine = engine
    return app


def _mock_engine(targets=None, running=True):
    """Create a mock SimulationEngine with optional targets."""
    engine = MagicMock()
    engine._running = running
    target_dict = {}
    if targets:
        for t in targets:
            target_dict[t.target_id] = t
    engine.get_target = lambda tid: target_dict.get(tid)
    engine.get_targets.return_value = list(target_dict.values())
    engine.dispatch_unit = MagicMock()
    return engine


@pytest.mark.unit
class TestDispatchEndpoint:
    """POST /api/amy/simulation/dispatch"""

    def test_dispatch_happy_path(self):
        """Dispatch a known unit to a valid position returns 200."""
        rover = _make_sim_target("rover-abc123", "friendly", "rover", 0, 0)
        engine = _mock_engine(targets=[rover], running=True)
        client = TestClient(_make_app(engine=engine))

        resp = client.post("/api/amy/simulation/dispatch", json={
            "unit_id": "rover-abc123",
            "target": {"x": 10.0, "y": 20.0},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "dispatched"
        assert body["unit_id"] == "rover-abc123"
        assert body["target"]["x"] == 10.0
        assert body["target"]["y"] == 20.0
        engine.dispatch_unit.assert_called_once_with("rover-abc123", (10.0, 20.0))

    def test_dispatch_unit_not_found(self):
        """Dispatch a non-existent unit returns 404."""
        engine = _mock_engine(targets=[], running=True)
        client = TestClient(_make_app(engine=engine))

        resp = client.post("/api/amy/simulation/dispatch", json={
            "unit_id": "nonexistent-unit",
            "target": {"x": 5.0, "y": 5.0},
        })
        assert resp.status_code == 404
        assert "not found" in resp.json()["error"].lower()

    def test_dispatch_simulation_not_active(self):
        """Dispatch when simulation engine is not running returns 409."""
        rover = _make_sim_target("rover-abc123", "friendly", "rover", 0, 0)
        engine = _mock_engine(targets=[rover], running=False)
        client = TestClient(_make_app(engine=engine))

        resp = client.post("/api/amy/simulation/dispatch", json={
            "unit_id": "rover-abc123",
            "target": {"x": 10.0, "y": 20.0},
        })
        assert resp.status_code == 409
        assert "not active" in resp.json()["error"].lower()

    def test_dispatch_no_engine(self):
        """Dispatch when no simulation engine exists returns 503."""
        client = TestClient(_make_app(engine=None))

        resp = client.post("/api/amy/simulation/dispatch", json={
            "unit_id": "rover-abc123",
            "target": {"x": 10.0, "y": 20.0},
        })
        assert resp.status_code == 503

    def test_dispatch_missing_unit_id(self):
        """Dispatch without unit_id returns 422."""
        engine = _mock_engine(targets=[], running=True)
        client = TestClient(_make_app(engine=engine))

        resp = client.post("/api/amy/simulation/dispatch", json={
            "target": {"x": 10.0, "y": 20.0},
        })
        assert resp.status_code == 422

    def test_dispatch_missing_target(self):
        """Dispatch without target returns 422."""
        engine = _mock_engine(targets=[], running=True)
        client = TestClient(_make_app(engine=engine))

        resp = client.post("/api/amy/simulation/dispatch", json={
            "unit_id": "rover-abc123",
        })
        assert resp.status_code == 422

    def test_dispatch_empty_body(self):
        """Dispatch with empty body returns 422."""
        engine = _mock_engine(targets=[], running=True)
        client = TestClient(_make_app(engine=engine))

        resp = client.post("/api/amy/simulation/dispatch", json={})
        assert resp.status_code == 422

    def test_dispatch_returns_target_position(self):
        """Dispatch response includes the target position sent."""
        rover = _make_sim_target("rover-xyz", "friendly", "rover", 5, 10)
        engine = _mock_engine(targets=[rover], running=True)
        client = TestClient(_make_app(engine=engine))

        resp = client.post("/api/amy/simulation/dispatch", json={
            "unit_id": "rover-xyz",
            "target": {"x": -15.5, "y": 30.2},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["target"]["x"] == -15.5
        assert body["target"]["y"] == 30.2
