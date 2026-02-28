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
