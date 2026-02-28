# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the unified targets router — /api/targets, /hostiles, /friendlies.

Tests with mocked tracker and simulation engine.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.targets_unified import router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(tracker=None, engine=None, amy=None):
    """Create FastAPI app with targets router and optional state."""
    app = FastAPI()
    app.include_router(router)

    if amy is not None:
        app.state.amy = amy
    if engine is not None:
        app.state.simulation_engine = engine

    return app


def _mock_target(target_id="t1", alliance="friendly", name="Unit-1"):
    """Create a mock target with to_dict()."""
    t = MagicMock()
    t.target_id = target_id
    t.alliance = alliance
    t.name = name
    t.to_dict.return_value = {
        "target_id": target_id,
        "alliance": alliance,
        "name": name,
    }
    return t


def _mock_tracker(all_targets=None, hostiles=None, friendlies=None, summary="test"):
    """Create a mock TargetTracker."""
    tracker = MagicMock()
    tracker.get_all.return_value = all_targets or []
    tracker.get_hostiles.return_value = hostiles or []
    tracker.get_friendlies.return_value = friendlies or []
    tracker.summary.return_value = summary
    return tracker


def _amy_with_tracker(tracker):
    """Create a mock Amy with a target_tracker."""
    amy = MagicMock()
    amy.target_tracker = tracker
    return amy


def _mock_engine(targets=None):
    """Create a mock SimulationEngine with get_targets."""
    engine = MagicMock()
    engine.get_targets.return_value = targets or []
    return engine


# ---------------------------------------------------------------------------
# GET /api/targets — All targets
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetTargets:
    """GET /api/targets — all tracked targets."""

    def test_with_tracker(self):
        t1 = _mock_target("unit-1", "friendly")
        t2 = _mock_target("hostile-1", "hostile")
        tracker = _mock_tracker(all_targets=[t1, t2], summary="2 targets")
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 2
        assert data["summary"] == "2 targets"

    def test_headless_mode(self):
        t1 = _mock_target("sim-1", "friendly")
        engine = _mock_engine(targets=[t1])
        client = TestClient(_make_app(engine=engine))

        resp = client.get("/api/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 1
        assert data["summary"] == "1 simulation targets"

    def test_no_tracking(self):
        client = TestClient(_make_app())
        resp = client.get("/api/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["targets"] == []
        assert data["summary"] == "No tracking available"

    def test_amy_without_tracker_falls_to_engine(self):
        amy = MagicMock()
        amy.target_tracker = None
        t1 = _mock_target("sim-1", "hostile")
        engine = _mock_engine(targets=[t1])
        client = TestClient(_make_app(amy=amy, engine=engine))

        resp = client.get("/api/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 1

    def test_empty_tracker(self):
        tracker = _mock_tracker(all_targets=[], summary="0 targets")
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets")
        assert resp.status_code == 200
        assert resp.json()["targets"] == []


# ---------------------------------------------------------------------------
# GET /api/targets/hostiles
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetHostiles:
    """GET /api/targets/hostiles — hostile targets only."""

    def test_with_tracker(self):
        h = _mock_target("h-1", "hostile")
        tracker = _mock_tracker(hostiles=[h])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets/hostiles")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 1
        assert data["targets"][0]["alliance"] == "hostile"

    def test_headless_filters(self):
        friendly = _mock_target("f-1", "friendly")
        hostile = _mock_target("h-1", "hostile")
        engine = _mock_engine(targets=[friendly, hostile])
        client = TestClient(_make_app(engine=engine))

        resp = client.get("/api/targets/hostiles")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 1
        assert data["targets"][0]["alliance"] == "hostile"

    def test_no_tracking(self):
        client = TestClient(_make_app())
        resp = client.get("/api/targets/hostiles")
        assert resp.status_code == 200
        assert resp.json()["targets"] == []

    def test_empty_hostiles(self):
        tracker = _mock_tracker(hostiles=[])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets/hostiles")
        assert resp.status_code == 200
        assert resp.json()["targets"] == []


# ---------------------------------------------------------------------------
# GET /api/targets/friendlies
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetFriendlies:
    """GET /api/targets/friendlies — friendly targets only."""

    def test_with_tracker(self):
        f = _mock_target("f-1", "friendly")
        tracker = _mock_tracker(friendlies=[f])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets/friendlies")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 1
        assert data["targets"][0]["alliance"] == "friendly"

    def test_headless_filters(self):
        friendly = _mock_target("f-1", "friendly")
        hostile = _mock_target("h-1", "hostile")
        engine = _mock_engine(targets=[friendly, hostile])
        client = TestClient(_make_app(engine=engine))

        resp = client.get("/api/targets/friendlies")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 1
        assert data["targets"][0]["alliance"] == "friendly"

    def test_no_tracking(self):
        client = TestClient(_make_app())
        resp = client.get("/api/targets/friendlies")
        assert resp.status_code == 200
        assert resp.json()["targets"] == []

    def test_multiple_friendlies(self):
        f1 = _mock_target("f-1", "friendly")
        f2 = _mock_target("f-2", "friendly")
        tracker = _mock_tracker(friendlies=[f1, f2])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets/friendlies")
        assert resp.status_code == 200
        assert len(resp.json()["targets"]) == 2
