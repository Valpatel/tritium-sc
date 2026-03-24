# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the heatmap API — /api/heatmap."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import heatmap as heatmap_module
from app.routers.heatmap import router
from tritium_lib.tracking.heatmap import HeatmapEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client():
    """Create a fresh TestClient with an isolated HeatmapEngine."""
    app = FastAPI()
    app.include_router(router)
    engine = HeatmapEngine()
    heatmap_module._engine = engine
    return TestClient(app), engine


# ---------------------------------------------------------------------------
# GET /api/heatmap
# ---------------------------------------------------------------------------

class TestHeatmapEndpoint:
    def test_empty_heatmap(self):
        client, _ = _make_client()
        resp = client.get("/api/heatmap")
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_count"] == 0
        assert data["max_value"] == 0.0
        assert data["resolution"] == 50
        assert len(data["grid"]) == 50

    def test_with_events(self):
        client, engine = _make_client()
        engine.record_event("ble_activity", x=10.0, y=20.0)
        engine.record_event("ble_activity", x=10.0, y=20.0)
        resp = client.get("/api/heatmap?layer=ble_activity")
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_count"] == 2
        assert data["max_value"] == 2.0
        assert data["layer"] == "ble_activity"

    def test_layer_filter(self):
        client, engine = _make_client()
        engine.record_event("ble_activity", x=1, y=1)
        engine.record_event("camera_activity", x=2, y=2)
        resp = client.get("/api/heatmap?layer=camera_activity")
        data = resp.json()
        assert data["event_count"] == 1
        assert data["layer"] == "camera_activity"

    def test_all_layer(self):
        client, engine = _make_client()
        engine.record_event("ble_activity", x=1, y=1)
        engine.record_event("camera_activity", x=1, y=1)
        engine.record_event("motion_activity", x=1, y=1)
        resp = client.get("/api/heatmap?layer=all")
        data = resp.json()
        assert data["event_count"] == 3

    def test_resolution_param(self):
        client, engine = _make_client()
        engine.record_event("ble_activity", x=5, y=5)
        resp = client.get("/api/heatmap?resolution=20")
        data = resp.json()
        assert data["resolution"] == 20
        assert len(data["grid"]) == 20
        assert len(data["grid"][0]) == 20

    def test_window_param(self):
        client, engine = _make_client()
        import time
        # Old event
        engine.record_event("ble_activity", x=1, y=1,
                            timestamp=time.time() - 7200)
        # Recent event
        engine.record_event("ble_activity", x=2, y=2)
        resp = client.get("/api/heatmap?window=30")
        data = resp.json()
        assert data["event_count"] == 1

    def test_invalid_layer(self):
        client, _ = _make_client()
        resp = client.get("/api/heatmap?layer=bogus")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_default_params(self):
        client, _ = _make_client()
        resp = client.get("/api/heatmap")
        data = resp.json()
        assert data["resolution"] == 50
        assert data["layer"] == "all"
