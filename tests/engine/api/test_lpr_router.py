# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the LPR (License Plate Recognition) router."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.lpr import router
from app.routers import lpr as lpr_module


@pytest.fixture
def lpr_app():
    """Minimal FastAPI app with only the LPR router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(lpr_app):
    lpr_module._detections.clear()
    lpr_module._watchlist.clear()
    return TestClient(lpr_app, raise_server_exceptions=False)


def test_detect_plate(client):
    """Submit a plate detection."""
    resp = client.post("/api/lpr/detect", json={
        "plate_text": "ABC 1234",
        "confidence": 0.92,
        "camera_id": "cam01",
        "vehicle_type": "car",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["plate_text"] == "ABC 1234"
    assert data["target_id"] == "lpr_ABC1234"
    assert data["watchlist_hit"] is False


def test_detect_watchlist_hit(client):
    """Detect a plate that's on the watchlist."""
    client.post("/api/lpr/watchlist", json={
        "plate_text": "STOLEN99",
        "alert_type": "stolen",
        "description": "stolen vehicle",
    })
    resp = client.post("/api/lpr/detect", json={
        "plate_text": "STOLEN99",
        "confidence": 0.88,
    })
    data = resp.json()
    assert data["watchlist_hit"] is True
    assert data["alert_type"] == "stolen"


def test_get_detections(client):
    """List recent detections."""
    for i in range(3):
        client.post("/api/lpr/detect", json={
            "plate_text": f"PLT{i:04d}",
            "camera_id": "cam01",
        })
    resp = client.get("/api/lpr/detections")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_filter_by_camera(client):
    """Filter detections by camera."""
    client.post("/api/lpr/detect", json={"plate_text": "A1", "camera_id": "cam01"})
    client.post("/api/lpr/detect", json={"plate_text": "B2", "camera_id": "cam02"})

    resp = client.get("/api/lpr/detections?camera_id=cam01")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["camera_id"] == "cam01"


def test_search_plates(client):
    """Search by partial plate text."""
    client.post("/api/lpr/detect", json={"plate_text": "ABC1234"})
    client.post("/api/lpr/detect", json={"plate_text": "XYZ5678"})
    client.post("/api/lpr/detect", json={"plate_text": "ABC9999"})

    resp = client.get("/api/lpr/search?q=ABC")
    data = resp.json()
    assert len(data) == 2


def test_stats(client):
    """Get LPR stats."""
    client.post("/api/lpr/detect", json={"plate_text": "A1", "confidence": 0.9})
    client.post("/api/lpr/detect", json={"plate_text": "B2", "confidence": 0.8})

    resp = client.get("/api/lpr/stats")
    data = resp.json()
    assert data["total_detections"] == 2
    assert data["unique_plates"] == 2
    assert abs(data["avg_confidence"] - 0.85) < 0.01


def test_watchlist_crud(client):
    """Add, list, and remove watchlist entries."""
    # Add
    resp = client.post("/api/lpr/watchlist", json={
        "plate_text": "BAD123",
        "alert_type": "wanted",
    })
    assert resp.status_code == 200

    # List
    resp = client.get("/api/lpr/watchlist")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["alert_type"] == "wanted"

    # Remove
    resp = client.delete("/api/lpr/watchlist/BAD123")
    assert resp.status_code == 200

    # Verify removed
    resp = client.get("/api/lpr/watchlist")
    assert len(resp.json()) == 0


def test_watchlist_not_found(client):
    """Remove nonexistent plate from watchlist."""
    resp = client.delete("/api/lpr/watchlist/NOPE")
    assert resp.status_code == 404
