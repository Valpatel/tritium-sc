# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the demo mode controller and API router."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# DemoController tests
# ---------------------------------------------------------------------------

from engine.synthetic.demo_mode import DemoController
from engine.comms.event_bus import EventBus


class TestDemoController:
    """Verify DemoController lifecycle."""

    def _make_controller(self, **kwargs) -> tuple[DemoController, EventBus]:
        bus = EventBus()
        ctrl = DemoController(event_bus=bus, **kwargs)
        return ctrl, bus

    def test_initial_state(self):
        ctrl, _ = self._make_controller()
        assert ctrl.active is False
        status = ctrl.status()
        assert status["active"] is False
        assert status["uptime_s"] is None
        assert status["generators"] == []
        assert status["generator_count"] == 0

    def test_start_activates(self):
        ctrl, bus = self._make_controller()
        q = bus.subscribe()

        ctrl.start()
        assert ctrl.active is True

        status = ctrl.status()
        assert status["active"] is True
        assert status["generator_count"] > 0
        assert status["uptime_s"] is not None

        # Should have published demo:started event
        events = []
        import queue as _q
        while True:
            try:
                events.append(q.get_nowait())
            except _q.Empty:
                break
        started_events = [e for e in events if e["type"] == "demo:started"]
        assert len(started_events) == 1
        assert started_events[0]["data"]["ble_devices"] == 5
        assert started_events[0]["data"]["mesh_nodes"] == 3
        assert started_events[0]["data"]["cameras"] == 2

        ctrl.stop()

    def test_stop_deactivates(self):
        ctrl, bus = self._make_controller()
        ctrl.start()
        assert ctrl.active is True

        q = bus.subscribe()
        ctrl.stop()
        assert ctrl.active is False

        status = ctrl.status()
        assert status["active"] is False

        # Should have published demo:stopped event
        events = []
        import queue as _q
        while True:
            try:
                events.append(q.get_nowait())
            except _q.Empty:
                break
        stopped_events = [e for e in events if e["type"] == "demo:stopped"]
        assert len(stopped_events) == 1

    def test_double_start_is_noop(self):
        ctrl, _ = self._make_controller()
        ctrl.start()
        ctrl.start()  # should not raise
        assert ctrl.active is True
        ctrl.stop()

    def test_double_stop_is_noop(self):
        ctrl, _ = self._make_controller()
        ctrl.stop()  # not active, should not raise
        assert ctrl.active is False

    def test_custom_counts(self):
        ctrl, _ = self._make_controller(
            ble_device_count=3,
            mesh_node_count=2,
            camera_count=1,
        )
        ctrl.start()
        status = ctrl.status()
        # 1 BLE + 1 Mesh + 1 Camera + 1 Fusion = 4 generators
        assert status["generator_count"] == 4
        ctrl.stop()

    def test_generators_produce_events(self):
        ctrl, bus = self._make_controller(camera_count=1)
        q = bus.subscribe()
        ctrl.start()

        # Wait a bit for generators to tick
        time.sleep(2.0)

        events = []
        import queue as _q
        while True:
            try:
                events.append(q.get_nowait())
            except _q.Empty:
                break

        ctrl.stop()

        event_types = {e["type"] for e in events}
        # Camera generator ticks at 1s, so should have produced events
        assert "detection:camera" in event_types

    def test_status_reports_generators(self):
        ctrl, _ = self._make_controller(
            ble_device_count=5,
            mesh_node_count=3,
            camera_count=2,
        )
        ctrl.start()
        status = ctrl.status()

        names = [g["name"] for g in status["generators"]]
        assert "BLEScanGenerator" in names
        assert "MeshtasticNodeGenerator" in names
        assert "CameraDetectionGenerator" in names

        # All should be running
        for g in status["generators"]:
            assert g["running"] is True

        ctrl.stop()


# ---------------------------------------------------------------------------
# API router tests
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.routers.demo import router as demo_router


def _make_app_with_amy() -> tuple[FastAPI, EventBus]:
    """Create a test FastAPI app with a mock Amy that has an EventBus."""
    app = FastAPI()
    app.include_router(demo_router)

    bus = EventBus()
    mock_amy = MagicMock()
    mock_amy.event_bus = bus
    mock_amy.target_tracker = None
    app.state.amy = mock_amy

    return app, bus


def _make_app_no_amy() -> FastAPI:
    """Create a test FastAPI app with no Amy."""
    app = FastAPI()
    app.include_router(demo_router)
    app.state.amy = None
    return app


class TestDemoRouter:
    """Verify demo API endpoints."""

    def test_status_when_inactive(self):
        app = _make_app_no_amy()
        client = TestClient(app)
        resp = client.get("/api/demo/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False
        assert data["generators"] == []

    def test_start_without_amy_returns_503(self):
        app = _make_app_no_amy()
        client = TestClient(app)
        resp = client.post("/api/demo/start")
        assert resp.status_code == 503

    def test_start_and_stop_lifecycle(self):
        app, bus = _make_app_with_amy()
        client = TestClient(app)

        # Start
        resp = client.post("/api/demo/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["active"] is True

        # Status
        resp = client.get("/api/demo/status")
        assert resp.status_code == 200
        assert resp.json()["active"] is True

        # Double start
        resp = client.post("/api/demo/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_active"

        # Stop
        resp = client.post("/api/demo/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stopped"
        assert data["active"] is False

    def test_stop_when_not_active(self):
        app, _ = _make_app_with_amy()
        client = TestClient(app)
        resp = client.post("/api/demo/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_active"
