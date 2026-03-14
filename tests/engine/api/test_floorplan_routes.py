# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for floor plan plugin routes."""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure plugins directory is importable
_plugins_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

from floorplan.store import FloorPlanStore
from floorplan.routes import create_router


@pytest.fixture
def app(tmp_path):
    """Create a test FastAPI app with floor plan routes."""
    store = FloorPlanStore(data_dir=tmp_path / "floorplans")
    app = FastAPI()
    router = create_router(store)
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def store(tmp_path):
    return FloorPlanStore(data_dir=tmp_path / "floorplans")


class TestFloorPlanCRUD:
    """Test floor plan CRUD operations."""

    def test_list_empty(self, client):
        resp = client.get("/api/floorplans")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["floorplans"] == []

    def test_create_floorplan(self, client):
        resp = client.post("/api/floorplans", json={
            "name": "Office Floor 1",
            "building": "HQ",
            "floor_level": 1,
        })
        assert resp.status_code == 200
        plan = resp.json()["floorplan"]
        assert plan["name"] == "Office Floor 1"
        assert plan["building"] == "HQ"
        assert plan["floor_level"] == 1
        assert plan["plan_id"].startswith("fp_")

    def test_get_floorplan(self, client):
        # Create
        resp = client.post("/api/floorplans", json={"name": "Test"})
        plan_id = resp.json()["floorplan"]["plan_id"]

        # Get
        resp = client.get(f"/api/floorplans/{plan_id}")
        assert resp.status_code == 200
        assert resp.json()["floorplan"]["plan_id"] == plan_id

    def test_get_floorplan_not_found(self, client):
        resp = client.get("/api/floorplans/nonexistent")
        assert resp.status_code == 404

    def test_update_floorplan(self, client):
        # Create
        resp = client.post("/api/floorplans", json={"name": "Test"})
        plan_id = resp.json()["floorplan"]["plan_id"]

        # Update
        resp = client.put(f"/api/floorplans/{plan_id}", json={
            "name": "Updated",
            "status": "active",
            "bounds": {"north": 40.0, "south": 39.0, "east": -74.0, "west": -75.0},
        })
        assert resp.status_code == 200
        plan = resp.json()["floorplan"]
        assert plan["name"] == "Updated"
        assert plan["status"] == "active"
        assert plan["bounds"]["north"] == 40.0

    def test_delete_floorplan(self, client):
        # Create
        resp = client.post("/api/floorplans", json={"name": "Test"})
        plan_id = resp.json()["floorplan"]["plan_id"]

        # Delete
        resp = client.delete(f"/api/floorplans/{plan_id}")
        assert resp.status_code == 200
        assert resp.json()["removed"] is True

        # Verify gone
        resp = client.get(f"/api/floorplans/{plan_id}")
        assert resp.status_code == 404

    def test_list_with_filter(self, client):
        client.post("/api/floorplans", json={"name": "A", "building": "HQ"})
        client.post("/api/floorplans", json={"name": "B", "building": "Annex"})

        resp = client.get("/api/floorplans?building=HQ")
        assert resp.json()["count"] == 1
        assert resp.json()["floorplans"][0]["building"] == "HQ"


class TestRoomManagement:
    """Test room CRUD within floor plans."""

    def test_add_room(self, client):
        resp = client.post("/api/floorplans", json={"name": "Test"})
        plan_id = resp.json()["floorplan"]["plan_id"]

        resp = client.post(f"/api/floorplans/{plan_id}/rooms", json={
            "name": "Conference A",
            "room_type": "conference",
            "polygon": [
                {"lat": 0.0, "lon": 0.0},
                {"lat": 0.0, "lon": 1.0},
                {"lat": 1.0, "lon": 1.0},
                {"lat": 1.0, "lon": 0.0},
            ],
            "capacity": 12,
        })
        assert resp.status_code == 200
        room = resp.json()["room"]
        assert room["name"] == "Conference A"
        assert room["room_type"] == "conference"
        assert room["capacity"] == 12

    def test_remove_room(self, client):
        resp = client.post("/api/floorplans", json={"name": "Test"})
        plan_id = resp.json()["floorplan"]["plan_id"]

        resp = client.post(f"/api/floorplans/{plan_id}/rooms", json={
            "name": "Room 1",
        })
        room_id = resp.json()["room"]["room_id"]

        resp = client.delete(f"/api/floorplans/{plan_id}/rooms/{room_id}")
        assert resp.status_code == 200


class TestIndoorPositions:
    """Test indoor position tracking."""

    def test_set_and_get_position(self, client):
        resp = client.post("/api/floorplans/positions", json={
            "target_id": "ble_AA:BB:CC:DD:EE:FF",
            "plan_id": "fp_001",
            "room_id": "conf_a",
            "lat": 39.5,
            "lon": -74.5,
            "confidence": 0.85,
        })
        assert resp.status_code == 200

        resp = client.get("/api/floorplans/positions/ble_AA:BB:CC:DD:EE:FF")
        assert resp.status_code == 200
        pos = resp.json()["position"]
        assert pos["target_id"] == "ble_AA:BB:CC:DD:EE:FF"
        assert pos["confidence"] == 0.85

    def test_get_all_positions(self, client):
        client.post("/api/floorplans/positions", json={
            "target_id": "t1",
            "plan_id": "fp_001",
        })
        client.post("/api/floorplans/positions", json={
            "target_id": "t2",
            "plan_id": "fp_001",
        })
        resp = client.get("/api/floorplans/positions/all")
        assert resp.json()["count"] == 2


class TestOccupancy:
    """Test building occupancy computation."""

    def test_occupancy_empty(self, client):
        resp = client.post("/api/floorplans", json={"name": "Test"})
        plan_id = resp.json()["floorplan"]["plan_id"]

        resp = client.get(f"/api/floorplans/{plan_id}/occupancy")
        assert resp.status_code == 200
        occ = resp.json()["occupancy"]
        assert occ["total_persons"] == 0
        assert occ["total_devices"] == 0

    def test_occupancy_not_found(self, client):
        resp = client.get("/api/floorplans/nonexistent/occupancy")
        assert resp.status_code == 404


class TestFingerprints:
    """Test WiFi fingerprint endpoints."""

    def test_add_fingerprint(self, client):
        resp = client.post("/api/floorplans/fingerprints", json={
            "plan_id": "fp_001",
            "lat": 39.5,
            "lon": -74.5,
            "rssi_map": {"AA:BB:CC:DD:EE:01": -45.0},
        })
        assert resp.status_code == 200
        fp = resp.json()["fingerprint"]
        assert fp["plan_id"] == "fp_001"

    def test_list_fingerprints(self, client):
        client.post("/api/floorplans/fingerprints", json={
            "plan_id": "fp_001",
            "lat": 39.5,
            "lon": -74.5,
            "rssi_map": {"AP1": -50.0},
        })
        resp = client.get("/api/floorplans/fingerprints/list?plan_id=fp_001")
        assert resp.json()["count"] == 1

    def test_clear_fingerprints(self, client):
        client.post("/api/floorplans/fingerprints", json={
            "plan_id": "fp_001",
            "lat": 39.5,
            "lon": -74.5,
            "rssi_map": {},
        })
        resp = client.delete("/api/floorplans/fingerprints/clear")
        assert resp.json()["cleared"] >= 1


class TestFloorPlanStore:
    """Direct store tests."""

    def test_store_persistence(self, tmp_path):
        store1 = FloorPlanStore(data_dir=tmp_path / "fp")
        store1.create_plan("Test Plan", building="HQ")

        # Reload from disk
        store2 = FloorPlanStore(data_dir=tmp_path / "fp")
        plans = store2.list_plans()
        assert len(plans) == 1
        assert plans[0]["name"] == "Test Plan"

    def test_compute_occupancy_with_targets(self, tmp_path):
        store = FloorPlanStore(data_dir=tmp_path / "fp")
        plan = store.create_plan("Test", building="HQ")
        plan_id = plan["plan_id"]

        store.add_room(plan_id, {
            "room_id": "r1",
            "name": "Conference A",
            "room_type": "conference",
            "capacity": 10,
        })

        # Add positions
        store.set_position("det_person_1", {
            "plan_id": plan_id,
            "room_id": "r1",
        })
        store.set_position("ble_AA:BB", {
            "plan_id": plan_id,
            "room_id": "r1",
        })

        occ = store.compute_occupancy(plan_id)
        assert occ is not None
        assert occ["total_persons"] == 1
        assert occ["total_devices"] == 1
        assert len(occ["rooms"]) == 1
        assert occ["rooms"][0]["person_count"] == 1
        assert occ["rooms"][0]["device_count"] == 1
