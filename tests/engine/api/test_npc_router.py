"""Unit tests for NPC API router."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.comms.event_bus import EventBus
from engine.simulation.engine import SimulationEngine
from engine.simulation.npc import NPCManager

pytestmark = pytest.mark.unit


@pytest.fixture
def app() -> FastAPI:
    """Create a test app with NPC router and engine."""
    from app.routers.npc import router

    test_app = FastAPI()
    test_app.include_router(router)

    # Set up engine on app state
    event_bus = EventBus()
    engine = SimulationEngine(event_bus, map_bounds=200.0)
    engine._npc_manager = NPCManager(engine)

    test_app.state.simulation_engine = engine
    test_app.state.amy = None

    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def engine(app: FastAPI) -> SimulationEngine:
    return app.state.simulation_engine


class TestListNPCs:
    def test_empty_list(self, client: TestClient) -> None:
        resp = client.get("/api/npc")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["npcs"] == []

    def test_list_after_spawn(self, client: TestClient) -> None:
        client.post("/api/npc/spawn/vehicle")
        resp = client.get("/api/npc")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["npcs"][0]["alliance"] == "neutral"


class TestSpawnVehicle:
    def test_spawn_vehicle(self, client: TestClient) -> None:
        resp = client.post("/api/npc/spawn/vehicle")
        assert resp.status_code == 200
        data = resp.json()
        assert "target_id" in data
        assert "name" in data
        assert "vehicle_type" in data
        assert data["speed"] > 0

    def test_spawn_specific_type(self, client: TestClient) -> None:
        resp = client.post("/api/npc/spawn/vehicle?vehicle_type=police")
        assert resp.status_code == 200
        data = resp.json()
        assert data["vehicle_type"] == "police"

    def test_spawn_at_capacity(self, client: TestClient, engine: SimulationEngine) -> None:
        engine._npc_manager.max_vehicles = 2
        client.post("/api/npc/spawn/vehicle")
        client.post("/api/npc/spawn/vehicle")
        resp = client.post("/api/npc/spawn/vehicle")
        assert resp.status_code == 409


class TestSpawnPedestrian:
    def test_spawn_pedestrian(self, client: TestClient) -> None:
        resp = client.post("/api/npc/spawn/pedestrian")
        assert resp.status_code == 200
        data = resp.json()
        assert "target_id" in data
        assert "name" in data
        assert data["speed"] > 0

    def test_spawn_at_capacity(self, client: TestClient, engine: SimulationEngine) -> None:
        engine._npc_manager.max_pedestrians = 1
        client.post("/api/npc/spawn/pedestrian")
        resp = client.post("/api/npc/spawn/pedestrian")
        assert resp.status_code == 409


class TestBindNPC:
    def test_bind_npc(self, client: TestClient) -> None:
        resp = client.post("/api/npc/spawn/vehicle")
        tid = resp.json()["target_id"]
        resp = client.post(
            f"/api/npc/{tid}/bind",
            json={"source": "cot", "track_id": "TRACK-001"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "bound"

    def test_bind_nonexistent(self, client: TestClient) -> None:
        resp = client.post(
            "/api/npc/nonexistent/bind",
            json={"source": "cot", "track_id": "TRACK-001"},
        )
        assert resp.status_code == 404

    def test_unbind_npc(self, client: TestClient) -> None:
        resp = client.post("/api/npc/spawn/vehicle")
        tid = resp.json()["target_id"]
        client.post(f"/api/npc/{tid}/bind", json={"source": "cot", "track_id": "T1"})
        resp = client.delete(f"/api/npc/{tid}/bind")
        assert resp.status_code == 200
        assert resp.json()["status"] == "unbound"

    def test_unbind_not_bound(self, client: TestClient) -> None:
        resp = client.post("/api/npc/spawn/vehicle")
        tid = resp.json()["target_id"]
        resp = client.delete(f"/api/npc/{tid}/bind")
        assert resp.status_code == 404


class TestUpdatePosition:
    def test_update_bound_position(self, client: TestClient) -> None:
        resp = client.post("/api/npc/spawn/vehicle")
        tid = resp.json()["target_id"]
        client.post(f"/api/npc/{tid}/bind", json={"source": "cot", "track_id": "T1"})
        resp = client.put(
            f"/api/npc/{tid}/position",
            json={"x": 10.0, "y": 20.0, "heading": 90.0, "speed": 5.0},
        )
        assert resp.status_code == 200

    def test_update_unbound_fails(self, client: TestClient) -> None:
        resp = client.post("/api/npc/spawn/vehicle")
        tid = resp.json()["target_id"]
        resp = client.put(
            f"/api/npc/{tid}/position",
            json={"x": 10.0, "y": 20.0},
        )
        assert resp.status_code == 400


class TestDensity:
    def test_get_density(self, client: TestClient) -> None:
        resp = client.get("/api/npc/density")
        assert resp.status_code == 200
        data = resp.json()
        assert "hour" in data
        assert "density" in data
        assert 0.0 < data["density"] <= 1.0
        assert "vehicle_types" in data
        assert len(data["vehicle_types"]) == 7
