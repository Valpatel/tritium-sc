# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the patrols API — /api/patrols/*."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import patrols as patrols_module
from app.routers.patrols import router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client():
    """Create a fresh TestClient with an isolated PatrolManager."""
    from tritium_lib.tracking.patrol import PatrolManager

    app = FastAPI()
    app.include_router(router)
    mgr = PatrolManager()
    patrols_module._manager = mgr
    return TestClient(app), mgr


SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10]]


# ---------------------------------------------------------------------------
# Route CRUD
# ---------------------------------------------------------------------------

class TestRouteEndpoints:
    def test_create_route(self):
        client, _ = _make_client()
        resp = client.post("/api/patrols/routes", json={
            "name": "Perimeter",
            "waypoints": SQUARE,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Perimeter"
        assert data["loop"] is True
        assert data["speed"] == 1.0
        assert len(data["waypoints"]) == 4
        assert "route_id" in data

    def test_create_route_custom(self):
        client, _ = _make_client()
        resp = client.post("/api/patrols/routes", json={
            "name": "Fast",
            "waypoints": [[0, 0], [5, 5]],
            "loop": False,
            "speed": 3.0,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["loop"] is False
        assert data["speed"] == 3.0

    def test_create_route_too_few_waypoints(self):
        client, _ = _make_client()
        resp = client.post("/api/patrols/routes", json={
            "name": "Bad",
            "waypoints": [[0, 0]],
        })
        assert resp.status_code == 400

    def test_create_route_bad_speed(self):
        client, _ = _make_client()
        resp = client.post("/api/patrols/routes", json={
            "name": "Bad",
            "waypoints": [[0, 0], [1, 1]],
            "speed": -1.0,
        })
        assert resp.status_code in (400, 422)  # 422 from Pydantic Field validation

    def test_create_route_bad_waypoint_shape(self):
        client, _ = _make_client()
        resp = client.post("/api/patrols/routes", json={
            "name": "Bad",
            "waypoints": [[0, 0, 0], [1, 1]],
        })
        assert resp.status_code == 400

    def test_list_routes_empty(self):
        client, _ = _make_client()
        resp = client.get("/api/patrols/routes")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_routes(self):
        client, _ = _make_client()
        client.post("/api/patrols/routes", json={
            "name": "A", "waypoints": [[0, 0], [1, 1]],
        })
        client.post("/api/patrols/routes", json={
            "name": "B", "waypoints": [[2, 2], [3, 3]],
        })
        resp = client.get("/api/patrols/routes")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

class TestAssignmentEndpoints:
    def test_assign_asset(self):
        client, _ = _make_client()
        r = client.post("/api/patrols/routes", json={
            "name": "R", "waypoints": SQUARE,
        })
        route_id = r.json()["route_id"]
        resp = client.post("/api/patrols/assign", json={
            "route_id": route_id, "asset_id": "drone-1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_id"] == "drone-1"
        assert data["route_id"] == route_id
        assert data["completed"] is False

    def test_assign_bad_route(self):
        client, _ = _make_client()
        resp = client.post("/api/patrols/assign", json={
            "route_id": "nonexistent", "asset_id": "drone-1",
        })
        assert resp.status_code == 404

    def test_unassign_asset(self):
        client, _ = _make_client()
        r = client.post("/api/patrols/routes", json={
            "name": "R", "waypoints": SQUARE,
        })
        route_id = r.json()["route_id"]
        client.post("/api/patrols/assign", json={
            "route_id": route_id, "asset_id": "drone-1",
        })
        resp = client.post("/api/patrols/unassign", json={
            "asset_id": "drone-1",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "unassigned"

    def test_unassign_not_patrolling(self):
        client, _ = _make_client()
        resp = client.post("/api/patrols/unassign", json={
            "asset_id": "ghost",
        })
        assert resp.status_code == 404

    def test_active_patrols(self):
        client, mgr = _make_client()
        r = client.post("/api/patrols/routes", json={
            "name": "R", "waypoints": SQUARE,
        })
        route_id = r.json()["route_id"]
        client.post("/api/patrols/assign", json={
            "route_id": route_id, "asset_id": "drone-1",
        })
        client.post("/api/patrols/assign", json={
            "route_id": route_id, "asset_id": "drone-2",
        })
        resp = client.get("/api/patrols/active")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        ids = {a["asset_id"] for a in data}
        assert ids == {"drone-1", "drone-2"}

    def test_active_patrols_empty(self):
        client, _ = _make_client()
        resp = client.get("/api/patrols/active")
        assert resp.status_code == 200
        assert resp.json() == []
