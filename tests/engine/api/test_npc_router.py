# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
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


# ---- Fixtures for detail endpoint ----

@pytest.fixture
def app_with_plugin() -> FastAPI:
    """Create a test app with NPC router, engine, AND intelligence plugin."""
    from engine.simulation.npc_intelligence.plugin import NPCIntelligencePlugin
    from engine.simulation.npc_intelligence.thought_registry import ThoughtRegistry

    from app.routers.npc import router

    test_app = FastAPI()
    test_app.include_router(router)

    event_bus = EventBus()
    engine = SimulationEngine(event_bus, map_bounds=200.0)
    engine._npc_manager = NPCManager(engine)

    plugin = NPCIntelligencePlugin()
    thought_registry = ThoughtRegistry(event_bus=event_bus, plugin=plugin)

    test_app.state.simulation_engine = engine
    test_app.state.amy = None
    test_app.state.npc_intelligence_plugin = plugin
    test_app.state.npc_thought_registry = thought_registry

    # Wire plugin's internal references
    plugin._engine = engine
    plugin._event_bus = event_bus
    plugin._thought_registry = thought_registry

    return test_app


@pytest.fixture
def client_with_plugin(app_with_plugin: FastAPI) -> TestClient:
    return TestClient(app_with_plugin)


@pytest.fixture
def engine_with_plugin(app_with_plugin: FastAPI) -> SimulationEngine:
    return app_with_plugin.state.simulation_engine


class TestNPCDetail:
    """Tests for GET /api/npc/{target_id} detail endpoint."""

    def test_detail_nonexistent_returns_404(self, client_with_plugin: TestClient) -> None:
        resp = client_with_plugin.get("/api/npc/nonexistent-id")
        assert resp.status_code == 404

    def test_detail_returns_target_fields(self, client_with_plugin: TestClient) -> None:
        resp = client_with_plugin.post("/api/npc/spawn/vehicle")
        assert resp.status_code == 200
        tid = resp.json()["target_id"]
        resp = client_with_plugin.get(f"/api/npc/{tid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == tid
        assert "position" in data
        assert "alliance" in data
        assert data["alliance"] == "neutral"
        assert "speed" in data
        assert "health" in data

    def test_detail_includes_thought(self, client_with_plugin: TestClient) -> None:
        resp = client_with_plugin.post("/api/npc/spawn/pedestrian")
        tid = resp.json()["target_id"]

        # Set a thought
        client_with_plugin.post(
            f"/api/npc/{tid}/thought",
            json={"text": "Nice day!", "emotion": "happy", "duration": 10.0},
        )

        resp = client_with_plugin.get(f"/api/npc/{tid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["thought"] is not None
        assert data["thought"]["text"] == "Nice day!"
        assert data["thought"]["emotion"] == "happy"

    def test_detail_includes_controller(
        self, client_with_plugin: TestClient, app_with_plugin: FastAPI
    ) -> None:
        resp = client_with_plugin.post("/api/npc/spawn/vehicle")
        tid = resp.json()["target_id"]

        # Attach a brain (required for take_control to succeed)
        plugin = app_with_plugin.state.npc_intelligence_plugin
        plugin.attach_brain(tid, "vehicle", "neutral")

        # Take control
        resp_ctrl = client_with_plugin.post(
            f"/api/npc/{tid}/control",
            json={"controller_id": "operator-1"},
        )
        assert resp_ctrl.status_code == 200

        resp = client_with_plugin.get(f"/api/npc/{tid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["controller"] == "operator-1"

    def test_detail_no_thought_returns_null(self, client_with_plugin: TestClient) -> None:
        resp = client_with_plugin.post("/api/npc/spawn/vehicle")
        tid = resp.json()["target_id"]
        resp = client_with_plugin.get(f"/api/npc/{tid}")
        data = resp.json()
        assert data["thought"] is None

    def test_detail_includes_brain_state_when_available(
        self, client_with_plugin: TestClient, app_with_plugin: FastAPI
    ) -> None:
        resp = client_with_plugin.post("/api/npc/spawn/pedestrian")
        tid = resp.json()["target_id"]

        # Attach brain via plugin
        plugin = app_with_plugin.state.npc_intelligence_plugin
        brain = plugin.attach_brain(tid, "person", "neutral")

        resp = client_with_plugin.get(f"/api/npc/{tid}")
        data = resp.json()
        assert data["brain_state"] is not None
        assert "fsm_state" in data["brain_state"]
        assert "personality" in data["brain_state"]
        assert "danger_level" in data["brain_state"]
        assert "interest_level" in data["brain_state"]
        assert "is_bound" in data["brain_state"]

    def test_detail_no_brain_returns_null_brain_state(self, client_with_plugin: TestClient) -> None:
        resp = client_with_plugin.post("/api/npc/spawn/vehicle")
        tid = resp.json()["target_id"]
        resp = client_with_plugin.get(f"/api/npc/{tid}")
        data = resp.json()
        assert data["brain_state"] is None

    def test_detail_includes_personality(
        self, client_with_plugin: TestClient, app_with_plugin: FastAPI
    ) -> None:
        resp = client_with_plugin.post("/api/npc/spawn/pedestrian")
        tid = resp.json()["target_id"]

        plugin = app_with_plugin.state.npc_intelligence_plugin
        plugin.attach_brain(tid, "person", "neutral")

        resp = client_with_plugin.get(f"/api/npc/{tid}")
        data = resp.json()
        assert data["personality"] is not None
        assert "curiosity" in data["personality"]
        assert "caution" in data["personality"]
        assert "sociability" in data["personality"]
        assert "aggression" in data["personality"]

    def test_detail_includes_memory_events(
        self, client_with_plugin: TestClient, app_with_plugin: FastAPI
    ) -> None:
        resp = client_with_plugin.post("/api/npc/spawn/pedestrian")
        tid = resp.json()["target_id"]

        plugin = app_with_plugin.state.npc_intelligence_plugin
        brain = plugin.attach_brain(tid, "person", "neutral")

        # Add some memory events
        brain.memory.add_event("saw_person", {"detail": "neighbor"})
        brain.memory.add_event("heard_noise", {"detail": "dog barking"})

        resp = client_with_plugin.get(f"/api/npc/{tid}")
        data = resp.json()
        assert data["memory_events"] is not None
        assert len(data["memory_events"]) == 2

    def test_detail_includes_npc_mission(self, client_with_plugin: TestClient) -> None:
        resp = client_with_plugin.post("/api/npc/spawn/vehicle")
        tid = resp.json()["target_id"]
        resp = client_with_plugin.get(f"/api/npc/{tid}")
        data = resp.json()
        # Mission might be None if none assigned, or a dict
        assert "npc_mission" in data

    def test_detail_includes_npc_vehicle_type(self, client_with_plugin: TestClient) -> None:
        resp = client_with_plugin.post("/api/npc/spawn/vehicle?vehicle_type=pickup")
        tid = resp.json()["target_id"]
        resp = client_with_plugin.get(f"/api/npc/{tid}")
        data = resp.json()
        assert data["npc_vehicle_type"] == "pickup"
