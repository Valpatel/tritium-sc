# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for NPC thought bubble / control API endpoints."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from engine.comms.event_bus import EventBus
from engine.simulation.engine import SimulationEngine
from engine.simulation.npc import NPCManager
from engine.simulation.npc_intelligence.plugin import NPCIntelligencePlugin
from engine.simulation.npc_intelligence.thought_registry import ThoughtRegistry

pytestmark = pytest.mark.unit


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def app(event_bus: EventBus) -> FastAPI:
    """Create a test app with NPC router, engine, and thought registry."""
    from app.routers.npc import router

    test_app = FastAPI()
    test_app.include_router(router)

    engine = SimulationEngine(event_bus, map_bounds=200.0)
    engine._npc_manager = NPCManager(engine)

    # Set up NPC intelligence plugin with thought registry
    plugin = NPCIntelligencePlugin()
    thought_registry = ThoughtRegistry(event_bus=event_bus, plugin=plugin)

    test_app.state.simulation_engine = engine
    test_app.state.amy = None
    test_app.state.npc_thought_registry = thought_registry
    test_app.state.npc_intelligence_plugin = plugin

    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def engine(app: FastAPI) -> SimulationEngine:
    return app.state.simulation_engine


@pytest.fixture
def thought_registry(app: FastAPI) -> ThoughtRegistry:
    return app.state.npc_thought_registry


@pytest.fixture
def plugin(app: FastAPI) -> NPCIntelligencePlugin:
    return app.state.npc_intelligence_plugin


class TestListControllable:
    def test_list_controllable(self, client: TestClient) -> None:
        """GET /api/npc/controllable returns NPC list."""
        resp = client.get("/api/npc/controllable")
        assert resp.status_code == 200
        data = resp.json()
        assert "npcs" in data

    def test_list_controllable_with_spawned(
        self, client: TestClient, engine: SimulationEngine
    ) -> None:
        """Controllable list includes spawned NPCs."""
        client.post("/api/npc/spawn/pedestrian")
        resp = client.get("/api/npc/controllable")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["npcs"]) >= 1


class TestTakeAndReleaseControl:
    def test_take_and_release_control(
        self, client: TestClient, plugin: NPCIntelligencePlugin
    ) -> None:
        """POST then DELETE control on an NPC."""
        # Spawn an NPC and attach a brain
        resp = client.post("/api/npc/spawn/pedestrian")
        tid = resp.json()["target_id"]
        plugin.attach_brain(tid, "person", "neutral")

        # Take control
        resp = client.post(
            f"/api/npc/{tid}/control",
            json={"controller_id": "test-client"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "controlled"

        # Release control
        resp = client.delete(f"/api/npc/{tid}/control")
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"

    def test_take_control_nonexistent(self, client: TestClient) -> None:
        resp = client.post(
            "/api/npc/nonexistent/control",
            json={"controller_id": "test-client"},
        )
        assert resp.status_code in (404, 409)


class TestSetThoughtViaAPI:
    def test_set_thought_via_api(
        self, client: TestClient, thought_registry: ThoughtRegistry
    ) -> None:
        """POST /api/npc/{id}/thought sets a thought bubble."""
        resp = client.post("/api/npc/spawn/pedestrian")
        tid = resp.json()["target_id"]

        resp = client.post(
            f"/api/npc/{tid}/thought",
            json={"text": "I see something", "emotion": "curious", "duration": 10.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "I see something"
        assert data["emotion"] == "curious"

        # Verify in registry
        thought = thought_registry.get_thought(tid)
        assert thought is not None
        assert thought.text == "I see something"


class TestActionRequiresControl:
    def test_action_requires_control(
        self, client: TestClient, plugin: NPCIntelligencePlugin
    ) -> None:
        """POST /api/npc/{id}/action requires control lock."""
        resp = client.post("/api/npc/spawn/pedestrian")
        tid = resp.json()["target_id"]
        plugin.attach_brain(tid, "person", "neutral")

        # Action without control -> 403
        resp = client.post(
            f"/api/npc/{tid}/action",
            json={"action": "WALK", "thought": "Walking around"},
        )
        assert resp.status_code == 403

    def test_action_with_control(
        self, client: TestClient, plugin: NPCIntelligencePlugin
    ) -> None:
        """Action succeeds when controller has lock."""
        resp = client.post("/api/npc/spawn/pedestrian")
        tid = resp.json()["target_id"]
        plugin.attach_brain(tid, "person", "neutral")

        # Take control
        client.post(f"/api/npc/{tid}/control", json={"controller_id": "test"})

        # Now action should work
        resp = client.post(
            f"/api/npc/{tid}/action",
            json={"action": "WALK", "thought": "Walking around"},
        )
        assert resp.status_code == 200


class TestActionWithWaypoints:
    def test_action_with_waypoints(
        self, client: TestClient, plugin: NPCIntelligencePlugin
    ) -> None:
        """Action can include waypoints."""
        resp = client.post("/api/npc/spawn/pedestrian")
        tid = resp.json()["target_id"]
        plugin.attach_brain(tid, "person", "neutral")

        client.post(f"/api/npc/{tid}/control", json={"controller_id": "test"})

        resp = client.post(
            f"/api/npc/{tid}/action",
            json={
                "action": "WALK",
                "thought": "Going to the park",
                "waypoints": [{"x": 10.0, "y": 20.0}, {"x": 30.0, "y": 40.0}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "WALK"
