# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the WebSocket router — ConnectionManager, TelemetryBatcher, message handling."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _event_loop():
    """Provide a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


def _run(coro):
    """Run an async coroutine synchronously on the current event loop."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# ConnectionManager
# ---------------------------------------------------------------------------


class TestConnectionManager:
    """ConnectionManager — WebSocket lifecycle and broadcast."""

    def test_starts_with_no_connections(self):
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()
        assert len(mgr.active_connections) == 0

    def test_connect_adds_websocket(self):
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.connect(ws))
        assert ws in mgr.active_connections
        ws.accept.assert_awaited_once()

    def test_disconnect_removes_websocket(self):
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.connect(ws))
        _run(mgr.disconnect(ws))
        assert ws not in mgr.active_connections

    def test_disconnect_missing_websocket_no_error(self):
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.disconnect(ws))
        assert len(mgr.active_connections) == 0

    def test_broadcast_sends_to_all(self):
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        _run(mgr.connect(ws1))
        _run(mgr.connect(ws2))
        msg = {"type": "test", "data": "hello"}
        _run(mgr.broadcast(msg))
        expected = json.dumps(msg)
        ws1.send_text.assert_awaited_with(expected)
        ws2.send_text.assert_awaited_with(expected)

    def test_broadcast_removes_failed_connections(self):
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_text = AsyncMock(side_effect=Exception("dead"))
        _run(mgr.connect(ws_good))
        _run(mgr.connect(ws_bad))
        _run(mgr.broadcast({"type": "test"}))
        assert ws_bad not in mgr.active_connections
        assert ws_good in mgr.active_connections

    def test_broadcast_empty_no_op(self):
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()
        _run(mgr.broadcast({"type": "test"}))

    def test_send_to_specific_client(self):
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        msg = {"type": "direct", "value": 42}
        _run(mgr.send_to(ws, msg))
        ws.send_text.assert_awaited_once_with(json.dumps(msg))

    def test_send_to_handles_failure(self):
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.send_text = AsyncMock(side_effect=Exception("broken"))
        _run(mgr.send_to(ws, {"type": "test"}))

    def test_multiple_connect_disconnect_cycles(self):
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        for _ in range(5):
            _run(mgr.connect(ws))
            _run(mgr.disconnect(ws))
        assert len(mgr.active_connections) == 0


# ---------------------------------------------------------------------------
# Message Handling
# ---------------------------------------------------------------------------


class TestMessageHandling:
    """handle_client_message — ping, subscribe, unknown."""

    def test_ping_returns_pong(self):
        from app.routers.ws import handle_client_message, ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        with patch("app.routers.ws.manager", mgr):
            _run(handle_client_message(ws, {"type": "ping"}))
        call_args = ws.send_text.call_args
        data = json.loads(call_args[0][0])
        assert data["type"] == "pong"
        assert "timestamp" in data

    def test_subscribe_returns_confirmation(self):
        from app.routers.ws import handle_client_message, ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        with patch("app.routers.ws.manager", mgr):
            _run(handle_client_message(ws, {"type": "subscribe", "channels": ["alerts", "events"]}))
        call_args = ws.send_text.call_args
        data = json.loads(call_args[0][0])
        assert data["type"] == "subscribed"
        assert data["channels"] == ["alerts", "events"]

    def test_unknown_type_returns_error(self):
        from app.routers.ws import handle_client_message, ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        with patch("app.routers.ws.manager", mgr):
            _run(handle_client_message(ws, {"type": "banana"}))
        call_args = ws.send_text.call_args
        data = json.loads(call_args[0][0])
        assert data["type"] == "error"
        assert "banana" in data["message"]

    def test_subscribe_empty_channels(self):
        from app.routers.ws import handle_client_message, ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        with patch("app.routers.ws.manager", mgr):
            _run(handle_client_message(ws, {"type": "subscribe"}))
        call_args = ws.send_text.call_args
        data = json.loads(call_args[0][0])
        assert data["channels"] == []


# ---------------------------------------------------------------------------
# Broadcast Utility Functions
# ---------------------------------------------------------------------------


class TestBroadcastUtilities:
    """broadcast_event, broadcast_alert, broadcast_camera_status, etc."""

    def test_broadcast_event(self):
        from app.routers.ws import broadcast_event, ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.connect(ws))
        with patch("app.routers.ws.manager", mgr):
            _run(broadcast_event({"label": "person", "confidence": 0.95}))
        data = json.loads(ws.send_text.call_args[0][0])
        assert data["type"] == "event"
        assert data["data"]["label"] == "person"
        assert "timestamp" in data

    def test_broadcast_alert(self):
        from app.routers.ws import broadcast_alert, ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.connect(ws))
        with patch("app.routers.ws.manager", mgr):
            _run(broadcast_alert({"level": "critical", "message": "Intrusion"}))
        data = json.loads(ws.send_text.call_args[0][0])
        assert data["type"] == "alert"
        assert data["data"]["level"] == "critical"

    def test_broadcast_camera_status(self):
        from app.routers.ws import broadcast_camera_status, ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.connect(ws))
        with patch("app.routers.ws.manager", mgr):
            _run(broadcast_camera_status(camera_id=3, status="online"))
        data = json.loads(ws.send_text.call_args[0][0])
        assert data["type"] == "camera_status"
        assert data["camera_id"] == 3
        assert data["status"] == "online"

    def test_broadcast_asset_update(self):
        from app.routers.ws import broadcast_asset_update, ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.connect(ws))
        with patch("app.routers.ws.manager", mgr):
            _run(broadcast_asset_update({"id": "rover1", "battery": 0.8}))
        data = json.loads(ws.send_text.call_args[0][0])
        assert data["type"] == "asset_update"
        assert data["data"]["id"] == "rover1"

    def test_broadcast_task_update(self):
        from app.routers.ws import broadcast_task_update, ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.connect(ws))
        with patch("app.routers.ws.manager", mgr):
            _run(broadcast_task_update({"task_id": "t1", "status": "complete"}))
        data = json.loads(ws.send_text.call_args[0][0])
        assert data["type"] == "task_update"

    def test_broadcast_detection(self):
        from app.routers.ws import broadcast_detection, ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.connect(ws))
        with patch("app.routers.ws.manager", mgr):
            _run(broadcast_detection({"class": "vehicle", "bbox": [10, 20, 100, 150]}))
        data = json.loads(ws.send_text.call_args[0][0])
        assert data["type"] == "detection"

    def test_broadcast_amy_event(self):
        from app.routers.ws import broadcast_amy_event, ConnectionManager
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.connect(ws))
        with patch("app.routers.ws.manager", mgr):
            _run(broadcast_amy_event("thought", {"text": "I see movement"}))
        data = json.loads(ws.send_text.call_args[0][0])
        assert data["type"] == "amy_thought"
        assert data["data"]["text"] == "I see movement"


# ---------------------------------------------------------------------------
# TelemetryBatcher
# ---------------------------------------------------------------------------


class TestTelemetryBatcher:
    """TelemetryBatcher — accumulates and flushes at interval."""

    def test_add_stores_data(self):
        from app.routers.ws import TelemetryBatcher
        loop = asyncio.new_event_loop()
        batcher = TelemetryBatcher(loop, interval=10.0)
        batcher.add({"unit_id": "r1", "x": 5.0})
        assert len(batcher._buffer) == 1
        batcher.stop()
        loop.close()

    def test_add_multiple(self):
        from app.routers.ws import TelemetryBatcher
        loop = asyncio.new_event_loop()
        batcher = TelemetryBatcher(loop, interval=10.0)
        for i in range(10):
            batcher.add({"unit_id": f"r{i}"})
        assert len(batcher._buffer) == 10
        batcher.stop()
        loop.close()

    def test_flush_clears_buffer(self):
        from app.routers.ws import TelemetryBatcher
        loop = asyncio.new_event_loop()
        batcher = TelemetryBatcher(loop, interval=0.05)
        batcher.add({"unit_id": "r1"})
        batcher.add({"unit_id": "r2"})
        batcher.start()
        time.sleep(0.2)
        batcher.stop()
        batcher._flush_thread.join(timeout=1.0)
        assert len(batcher._buffer) == 0
        loop.close()

    def test_stop_sets_running_false(self):
        from app.routers.ws import TelemetryBatcher
        loop = asyncio.new_event_loop()
        batcher = TelemetryBatcher(loop, interval=10.0)
        assert batcher._running is True
        batcher.stop()
        assert batcher._running is False
        loop.close()

    def test_thread_safe_add(self):
        from app.routers.ws import TelemetryBatcher
        loop = asyncio.new_event_loop()
        batcher = TelemetryBatcher(loop, interval=10.0)

        def add_items():
            for i in range(100):
                batcher.add({"i": i})

        threads = [threading.Thread(target=add_items) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(batcher._buffer) == 400
        batcher.stop()
        loop.close()


# ---------------------------------------------------------------------------
# Event Name Translation — escalation events
# ---------------------------------------------------------------------------


class TestNormalizeEventType:
    """_normalize_event_type — translates engine event names to frontend names."""

    def test_threat_escalation_becomes_escalation_change(self):
        from app.routers.ws import _normalize_event_type
        assert _normalize_event_type("threat_escalation") == "escalation_change"

    def test_threat_deescalation_becomes_escalation_change(self):
        from app.routers.ws import _normalize_event_type
        assert _normalize_event_type("threat_deescalation") == "escalation_change"

    def test_other_events_pass_through_unchanged(self):
        from app.routers.ws import _normalize_event_type
        for event in ("sim_telemetry", "game_state_change", "wave_start",
                       "projectile_fired", "detection", "escalation_change"):
            assert _normalize_event_type(event) == event, f"{event} should pass through"


class TestEscalationEventTranslation:
    """Bridge must translate threat_escalation/threat_deescalation to
    escalation_change so the frontend and NPC intelligence receive the
    event name they expect.

    The engine's ThreatClassifier publishes 'threat_escalation' and
    'threat_deescalation', but the frontend websocket.js handles
    'escalation_change' / 'amy_escalation_change'. Without translation,
    escalation events never reach the UI.
    """

    def test_headless_bridge_allowlist_includes_escalation_change(self):
        """The headless bridge allowlist must include 'escalation_change'
        so that translated escalation events are forwarded to clients."""
        import inspect
        from app.routers.ws import start_headless_event_bridge
        source = inspect.getsource(start_headless_event_bridge)
        assert '"escalation_change"' in source or "'escalation_change'" in source, (
            "Headless bridge allowlist must include 'escalation_change'"
        )

    def test_headless_bridge_translates_threat_escalation(self):
        """When the engine publishes 'threat_escalation', the headless
        bridge must translate it to 'escalation_change' before forwarding
        so the frontend receives 'amy_escalation_change'."""
        from engine.comms.event_bus import EventBus
        from app.routers.ws import start_headless_event_bridge, manager

        loop = asyncio.new_event_loop()
        bus = EventBus()
        broadcasts = []

        original_broadcast = manager.broadcast

        async def capture_broadcast(msg):
            broadcasts.append(msg)

        with patch.object(manager, "broadcast", side_effect=capture_broadcast):
            start_headless_event_bridge(bus, loop)

            # Publish threat_escalation (what ThreatClassifier actually emits)
            bus.publish("threat_escalation", {
                "target_id": "h1",
                "old_level": "unknown",
                "new_level": "hostile",
                "reason": "zone:restricted",
            })

            # Give the bridge thread time to process
            time.sleep(0.3)

            # Drain any pending coroutines
            loop.run_until_complete(asyncio.sleep(0.1))

        # The bridge should have translated to escalation_change
        # and broadcast_amy_event adds the amy_ prefix
        escalation_msgs = [
            m for m in broadcasts
            if m.get("type") == "amy_escalation_change"
        ]
        assert len(escalation_msgs) >= 1, (
            f"Expected amy_escalation_change broadcast, got types: "
            f"{[m.get('type') for m in broadcasts]}"
        )
        loop.close()

    def test_headless_bridge_translates_threat_deescalation(self):
        """When the engine publishes 'threat_deescalation', the headless
        bridge must translate it to 'escalation_change' before forwarding."""
        from engine.comms.event_bus import EventBus
        from app.routers.ws import start_headless_event_bridge, manager

        loop = asyncio.new_event_loop()
        bus = EventBus()
        broadcasts = []

        async def capture_broadcast(msg):
            broadcasts.append(msg)

        with patch.object(manager, "broadcast", side_effect=capture_broadcast):
            start_headless_event_bridge(bus, loop)

            bus.publish("threat_deescalation", {
                "target_id": "h1",
                "old_level": "hostile",
                "new_level": "unknown",
                "reason": "de-escalation",
            })

            time.sleep(0.3)
            loop.run_until_complete(asyncio.sleep(0.1))

        escalation_msgs = [
            m for m in broadcasts
            if m.get("type") == "amy_escalation_change"
        ]
        assert len(escalation_msgs) >= 1, (
            f"Expected amy_escalation_change broadcast for deescalation, got types: "
            f"{[m.get('type') for m in broadcasts]}"
        )
        loop.close()

    def test_amy_bridge_translates_threat_escalation(self):
        """When Amy's EventBus publishes 'threat_escalation', the Amy bridge
        must translate it to 'escalation_change' before forwarding."""
        from engine.comms.event_bus import EventBus
        from app.routers.ws import start_amy_event_bridge, manager

        loop = asyncio.new_event_loop()
        bus = EventBus()
        broadcasts = []

        # Create a minimal mock commander with required attributes
        mock_commander = MagicMock()
        mock_commander.event_bus = bus
        mock_commander.simulation_engine = None

        async def capture_broadcast(msg):
            broadcasts.append(msg)

        with patch.object(manager, "broadcast", side_effect=capture_broadcast):
            start_amy_event_bridge(mock_commander, loop)

            bus.publish("threat_escalation", {
                "target_id": "h2",
                "old_level": "suspicious",
                "new_level": "hostile",
                "reason": "zone:front_yard",
            })

            time.sleep(0.3)
            loop.run_until_complete(asyncio.sleep(0.1))

        escalation_msgs = [
            m for m in broadcasts
            if m.get("type") == "amy_escalation_change"
        ]
        assert len(escalation_msgs) >= 1, (
            f"Expected amy_escalation_change from Amy bridge, got types: "
            f"{[m.get('type') for m in broadcasts]}"
        )
        loop.close()

    def test_amy_bridge_translates_threat_deescalation(self):
        """When Amy's EventBus publishes 'threat_deescalation', the Amy bridge
        must translate it to 'escalation_change' before forwarding."""
        from engine.comms.event_bus import EventBus
        from app.routers.ws import start_amy_event_bridge, manager

        loop = asyncio.new_event_loop()
        bus = EventBus()
        broadcasts = []

        mock_commander = MagicMock()
        mock_commander.event_bus = bus
        mock_commander.simulation_engine = None

        async def capture_broadcast(msg):
            broadcasts.append(msg)

        with patch.object(manager, "broadcast", side_effect=capture_broadcast):
            start_amy_event_bridge(mock_commander, loop)

            bus.publish("threat_deescalation", {
                "target_id": "h2",
                "old_level": "hostile",
                "new_level": "unknown",
                "reason": "de-escalation",
            })

            time.sleep(0.3)
            loop.run_until_complete(asyncio.sleep(0.1))

        escalation_msgs = [
            m for m in broadcasts
            if m.get("type") == "amy_escalation_change"
        ]
        assert len(escalation_msgs) >= 1, (
            f"Expected amy_escalation_change from Amy bridge deescalation, got types: "
            f"{[m.get('type') for m in broadcasts]}"
        )
        loop.close()

    def test_translated_escalation_preserves_data(self):
        """The translated event must preserve the original data payload
        (target_id, old_level, new_level, reason)."""
        from engine.comms.event_bus import EventBus
        from app.routers.ws import start_headless_event_bridge, manager

        loop = asyncio.new_event_loop()
        bus = EventBus()
        broadcasts = []

        async def capture_broadcast(msg):
            broadcasts.append(msg)

        with patch.object(manager, "broadcast", side_effect=capture_broadcast):
            start_headless_event_bridge(bus, loop)

            original_data = {
                "target_id": "h3",
                "old_level": "unknown",
                "new_level": "suspicious",
                "reason": "zone:driveway",
            }
            bus.publish("threat_escalation", original_data)

            time.sleep(0.3)
            loop.run_until_complete(asyncio.sleep(0.1))

        escalation_msgs = [
            m for m in broadcasts
            if m.get("type") == "amy_escalation_change"
        ]
        assert len(escalation_msgs) >= 1
        data = escalation_msgs[0]["data"]
        assert data["target_id"] == "h3"
        assert data["old_level"] == "unknown"
        assert data["new_level"] == "suspicious"
        assert data["reason"] == "zone:driveway"
        loop.close()


# ---------------------------------------------------------------------------
# Headless bridge event whitelist — mission-specific events
# ---------------------------------------------------------------------------


class TestHeadlessBridgeWhitelist:
    """Verify headless bridge forwards mission-specific engine events."""

    def test_instigator_identified_forwarded(self):
        """instigator_identified events must reach WebSocket clients."""
        from app.routers.ws import start_headless_event_bridge, manager
        from engine.comms.event_bus import EventBus

        loop = asyncio.new_event_loop()
        bus = EventBus()
        broadcasts = []
        original_broadcast = manager.broadcast

        async def capture(msg):
            broadcasts.append(msg)

        manager.broadcast = capture
        try:
            start_headless_event_bridge(bus, loop)
            bus.publish("instigator_identified", {"unit_id": "h-42", "confidence": 0.9})
            time.sleep(0.3)
            loop.run_until_complete(asyncio.sleep(0.1))

            instigator_msgs = [
                m for m in broadcasts
                if m.get("type") == "amy_instigator_identified"
            ]
            assert len(instigator_msgs) >= 1, f"Expected instigator_identified broadcast, got {broadcasts}"
            assert instigator_msgs[0]["data"]["unit_id"] == "h-42"
        finally:
            manager.broadcast = original_broadcast
            loop.close()

    def test_emp_activated_forwarded(self):
        """emp_activated events must reach WebSocket clients."""
        from app.routers.ws import start_headless_event_bridge, manager
        from engine.comms.event_bus import EventBus

        loop = asyncio.new_event_loop()
        bus = EventBus()
        broadcasts = []
        original_broadcast = manager.broadcast

        async def capture(msg):
            broadcasts.append(msg)

        manager.broadcast = capture
        try:
            start_headless_event_bridge(bus, loop)
            bus.publish("emp_activated", {"position": {"x": 10, "y": 20}, "drones_disabled": 5})
            time.sleep(0.3)
            loop.run_until_complete(asyncio.sleep(0.1))

            emp_msgs = [
                m for m in broadcasts
                if m.get("type") == "amy_emp_activated"
            ]
            assert len(emp_msgs) >= 1, f"Expected emp_activated broadcast, got {broadcasts}"
            assert emp_msgs[0]["data"]["drones_disabled"] == 5
        finally:
            manager.broadcast = original_broadcast
            loop.close()


# ---------------------------------------------------------------------------
# Headless bridge — tactical awareness events (auto_dispatch, zone_violation)
# ---------------------------------------------------------------------------

class TestHeadlessBridgeTacticalEvents:
    """Verify the headless bridge forwards auto-dispatch and zone violation events."""

    def test_allowlist_includes_auto_dispatch_speech(self):
        """auto_dispatch_speech must be in the headless bridge whitelist."""
        import inspect
        from app.routers.ws import start_headless_event_bridge
        source = inspect.getsource(start_headless_event_bridge)
        assert '"auto_dispatch_speech"' in source or "'auto_dispatch_speech'" in source

    def test_allowlist_includes_zone_violation(self):
        """zone_violation must be in the headless bridge whitelist."""
        import inspect
        from app.routers.ws import start_headless_event_bridge
        source = inspect.getsource(start_headless_event_bridge)
        assert '"zone_violation"' in source or "'zone_violation'" in source

    def test_allowlist_includes_formation_created(self):
        """formation_created must be in the headless bridge whitelist."""
        import inspect
        from app.routers.ws import start_headless_event_bridge
        source = inspect.getsource(start_headless_event_bridge)
        assert '"formation_created"' in source or "'formation_created'" in source

    def test_allowlist_includes_mode_change(self):
        """mode_change must be in the headless bridge whitelist."""
        import inspect
        from app.routers.ws import start_headless_event_bridge
        source = inspect.getsource(start_headless_event_bridge)
        assert '"mode_change"' in source or "'mode_change'" in source
