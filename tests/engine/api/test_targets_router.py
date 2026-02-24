"""Unit tests for the unified targets API (/api/targets/*) and WebSocket bridge.

Tests:
  - /api/targets — all tracked targets
  - /api/targets/hostiles — hostile only
  - /api/targets/friendlies — friendly only
  - start_headless_event_bridge — sim telemetry forwarding
"""
from __future__ import annotations

import asyncio
import queue
import threading
import time

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.targets_unified import router


def _make_sim_target(target_id: str, alliance: str, x: float = 0, y: float = 0):
    """Create a mock SimulationTarget."""
    t = MagicMock()
    t.target_id = target_id
    t.alliance = alliance
    t.position = (x, y)
    t.to_dict.return_value = {
        "target_id": target_id,
        "alliance": alliance,
        "position": {"x": x, "y": y},
    }
    return t


def _make_app(engine=None, amy=None):
    """Create a minimal FastAPI app with targets router."""
    app = FastAPI()
    app.include_router(router)
    app.state.simulation_engine = engine
    app.state.amy = amy
    return app


def _mock_engine_with_targets(targets):
    """Create a mock engine that returns specific targets."""
    engine = MagicMock()
    engine.get_targets.return_value = targets
    return engine


@pytest.mark.unit
class TestGetTargets:
    """GET /api/targets"""

    def test_returns_targets_from_headless_engine(self):
        targets = [
            _make_sim_target("turret-1", "friendly", 5, 10),
            _make_sim_target("hostile-1", "hostile", -5, -10),
        ]
        engine = _mock_engine_with_targets(targets)
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 2
        assert "summary" in data

    def test_empty_when_no_engine(self):
        client = TestClient(_make_app())
        resp = client.get("/api/targets")
        assert resp.status_code == 200
        assert resp.json()["targets"] == []

    def test_prefers_amy_tracker(self):
        """When Amy is running, uses tracker over headless engine."""
        amy = MagicMock()
        tracked = MagicMock()
        tracked.to_dict.return_value = {"target_id": "yolo-1", "alliance": "unknown"}
        amy.target_tracker.get_all.return_value = [tracked]
        amy.target_tracker.summary.return_value = "1 target"

        headless_engine = _mock_engine_with_targets([
            _make_sim_target("sim-1", "friendly"),
        ])

        client = TestClient(_make_app(engine=headless_engine, amy=amy))
        resp = client.get("/api/targets")
        data = resp.json()
        assert len(data["targets"]) == 1
        assert data["targets"][0]["target_id"] == "yolo-1"

    def test_returns_wrapped_dict(self):
        """Response is {targets: [...], summary: ...} — not a flat list."""
        engine = _mock_engine_with_targets([])
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/targets")
        data = resp.json()
        assert "targets" in data
        assert isinstance(data["targets"], list)


@pytest.mark.unit
class TestGetHostiles:
    """GET /api/targets/hostiles"""

    def test_filters_hostiles_only(self):
        targets = [
            _make_sim_target("turret-1", "friendly"),
            _make_sim_target("hostile-1", "hostile"),
            _make_sim_target("hostile-2", "hostile"),
        ]
        engine = _mock_engine_with_targets(targets)
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/targets/hostiles")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["targets"]) == 2
        for t in data["targets"]:
            assert t["alliance"] == "hostile"

    def test_empty_when_no_hostiles(self):
        targets = [_make_sim_target("turret-1", "friendly")]
        engine = _mock_engine_with_targets(targets)
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/targets/hostiles")
        assert resp.json()["targets"] == []

    def test_empty_without_engine(self):
        client = TestClient(_make_app())
        resp = client.get("/api/targets/hostiles")
        assert resp.json()["targets"] == []

    def test_returns_wrapped_dict(self):
        """Response is {targets: [...]} — not a flat list."""
        engine = _mock_engine_with_targets([])
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/targets/hostiles")
        data = resp.json()
        assert "targets" in data
        assert isinstance(data["targets"], list)


@pytest.mark.unit
class TestGetFriendlies:
    """GET /api/targets/friendlies"""

    def test_filters_friendlies_only(self):
        targets = [
            _make_sim_target("turret-1", "friendly"),
            _make_sim_target("turret-2", "friendly"),
            _make_sim_target("hostile-1", "hostile"),
        ]
        engine = _mock_engine_with_targets(targets)
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/targets/friendlies")
        data = resp.json()
        assert len(data["targets"]) == 2
        for t in data["targets"]:
            assert t["alliance"] == "friendly"

    def test_empty_when_no_friendlies(self):
        targets = [_make_sim_target("hostile-1", "hostile")]
        engine = _mock_engine_with_targets(targets)
        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/targets/friendlies")
        assert resp.json()["targets"] == []


@pytest.mark.unit
class TestHeadlessEventBridge:
    """Tests for start_headless_event_bridge in ws.py."""

    def test_bridge_subscribes_to_event_bus(self):
        """Bridge subscribes to the provided EventBus."""
        from engine.comms.event_bus import EventBus
        bus = EventBus()
        loop = asyncio.new_event_loop()

        with patch("app.routers.ws.TelemetryBatcher") as MockBatcher:
            batcher = MagicMock()
            MockBatcher.return_value = batcher

            from app.routers.ws import start_headless_event_bridge
            start_headless_event_bridge(bus, loop)

            # Batcher should have been started
            batcher.start.assert_called_once()

        loop.close()
        # EventBus should have at least one subscriber
        assert len(bus._subscribers) >= 1

    def test_bridge_routes_sim_telemetry_to_batcher(self):
        """sim_telemetry events go through the TelemetryBatcher."""
        from engine.comms.event_bus import EventBus
        bus = EventBus()
        loop = asyncio.new_event_loop()
        batcher_calls = []

        with patch("app.routers.ws.TelemetryBatcher") as MockBatcher:
            batcher = MagicMock()
            batcher.add = lambda data: batcher_calls.append(data)
            MockBatcher.return_value = batcher

            from app.routers.ws import start_headless_event_bridge
            start_headless_event_bridge(bus, loop)

            # Publish a sim_telemetry event
            bus.publish("sim_telemetry", {"target_id": "turret-1", "x": 5})
            time.sleep(0.3)  # Let the bridge thread process

        loop.close()
        assert len(batcher_calls) >= 1
        assert batcher_calls[0]["target_id"] == "turret-1"

    def test_bridge_routes_game_events(self):
        """Game state events are forwarded via broadcast_amy_event."""
        from engine.comms.event_bus import EventBus
        bus = EventBus()
        loop = asyncio.new_event_loop()
        broadcast_calls = []

        async def mock_broadcast(event_type, data):
            broadcast_calls.append((event_type, data))

        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()
        try:
            with patch("app.routers.ws.TelemetryBatcher") as MockBatcher:
                MockBatcher.return_value = MagicMock()
                with patch("app.routers.ws.broadcast_amy_event", side_effect=mock_broadcast):
                    from app.routers.ws import start_headless_event_bridge
                    start_headless_event_bridge(bus, loop)

                    # Publish game events
                    bus.publish("game_state_change", {"state": "active"})
                    bus.publish("wave_started", {"wave": 2})
                    time.sleep(0.3)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=2.0)
            loop.close()
        assert len(broadcast_calls) >= 1

    def test_bridge_ignores_unknown_events(self):
        """Events not in the whitelist are silently dropped."""
        from engine.comms.event_bus import EventBus
        bus = EventBus()
        loop = asyncio.new_event_loop()
        batcher_calls = []

        with patch("app.routers.ws.TelemetryBatcher") as MockBatcher:
            batcher = MagicMock()
            batcher.add = lambda data: batcher_calls.append(data)
            MockBatcher.return_value = batcher

            from app.routers.ws import start_headless_event_bridge
            start_headless_event_bridge(bus, loop)

            # Publish an event NOT in the whitelist
            bus.publish("some_random_event", {"data": "test"})
            time.sleep(0.3)

        loop.close()
        # Batcher should NOT have received anything (not sim_telemetry)
        assert len(batcher_calls) == 0


@pytest.mark.unit
class TestSimulationEngineEventBusProperty:
    """Test that SimulationEngine exposes event_bus property."""

    def test_event_bus_property_exists(self):
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine
        bus = EventBus()
        engine = SimulationEngine(bus)
        assert engine.event_bus is bus

    def test_event_bus_updated_after_set(self):
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine
        bus1 = EventBus()
        bus2 = EventBus()
        engine = SimulationEngine(bus1)
        engine.set_event_bus(bus2)
        assert engine.event_bus is bus2
