"""Unit tests for WebSocket infrastructure — ConnectionManager, TelemetryBatcher,
handle_client_message, and broadcast utility functions.

Uses asyncio.run() wrappers instead of pytest-asyncio (not installed).
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.routers.ws import (
    ConnectionManager,
    TelemetryBatcher,
    handle_client_message,
)


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# ConnectionManager
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConnectionManager:
    """ConnectionManager tracks WebSocket connections."""

    def test_connect_adds_to_set(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.connect(ws))
        assert ws in mgr.active_connections
        ws.accept.assert_awaited_once()

    def test_disconnect_removes_from_set(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.connect(ws))
        _run(mgr.disconnect(ws))
        assert ws not in mgr.active_connections

    def test_disconnect_nonexistent_is_safe(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.disconnect(ws))  # Should not raise

    def test_broadcast_sends_to_all(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        _run(mgr.connect(ws1))
        _run(mgr.connect(ws2))

        msg = {"type": "test", "data": "hello"}
        _run(mgr.broadcast(msg))

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()
        sent = json.loads(ws1.send_text.call_args[0][0])
        assert sent["type"] == "test"

    def test_broadcast_no_connections(self):
        mgr = ConnectionManager()
        _run(mgr.broadcast({"type": "test"}))

    def test_broadcast_removes_failed_connection(self):
        mgr = ConnectionManager()
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_text.side_effect = Exception("Connection lost")
        _run(mgr.connect(ws_good))
        _run(mgr.connect(ws_bad))

        _run(mgr.broadcast({"type": "test"}))

        assert ws_good in mgr.active_connections
        assert ws_bad not in mgr.active_connections

    def test_send_to_specific(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        _run(mgr.send_to(ws, {"type": "ping"}))
        ws.send_text.assert_awaited_once()

    def test_send_to_handles_error(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.send_text.side_effect = Exception("broken")
        _run(mgr.send_to(ws, {"type": "test"}))  # Should not raise

    def test_connection_count(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        _run(mgr.connect(ws1))
        assert len(mgr.active_connections) == 1
        _run(mgr.connect(ws2))
        assert len(mgr.active_connections) == 2
        _run(mgr.disconnect(ws1))
        assert len(mgr.active_connections) == 1


# ---------------------------------------------------------------------------
# handle_client_message
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHandleClientMessage:
    """Message routing for WebSocket client messages."""

    def test_ping_returns_pong(self):
        ws = AsyncMock()
        with patch("app.routers.ws.manager") as mock_mgr:
            mock_mgr.send_to = AsyncMock()
            _run(handle_client_message(ws, {"type": "ping"}))
            mock_mgr.send_to.assert_awaited_once()
            sent = mock_mgr.send_to.call_args[0][1]
            assert sent["type"] == "pong"
            assert "timestamp" in sent

    def test_subscribe_returns_confirmation(self):
        ws = AsyncMock()
        with patch("app.routers.ws.manager") as mock_mgr:
            mock_mgr.send_to = AsyncMock()
            _run(handle_client_message(ws, {
                "type": "subscribe",
                "channels": ["events", "alerts"],
            }))
            sent = mock_mgr.send_to.call_args[0][1]
            assert sent["type"] == "subscribed"
            assert sent["channels"] == ["events", "alerts"]

    def test_unknown_type_returns_error(self):
        ws = AsyncMock()
        with patch("app.routers.ws.manager") as mock_mgr:
            mock_mgr.send_to = AsyncMock()
            _run(handle_client_message(ws, {"type": "invalid_type"}))
            sent = mock_mgr.send_to.call_args[0][1]
            assert sent["type"] == "error"
            assert "Unknown" in sent["message"]

    def test_subscribe_empty_channels(self):
        ws = AsyncMock()
        with patch("app.routers.ws.manager") as mock_mgr:
            mock_mgr.send_to = AsyncMock()
            _run(handle_client_message(ws, {"type": "subscribe"}))
            sent = mock_mgr.send_to.call_args[0][1]
            assert sent["type"] == "subscribed"
            assert sent["channels"] == []


# ---------------------------------------------------------------------------
# TelemetryBatcher
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTelemetryBatcher:
    """TelemetryBatcher accumulates events and flushes in batches."""

    def test_add_accumulates(self):
        loop = asyncio.new_event_loop()
        batcher = TelemetryBatcher(loop, interval=1.0)
        batcher.add({"x": 1})
        batcher.add({"x": 2})
        assert len(batcher._buffer) == 2
        loop.close()

    def test_flush_clears_buffer(self):
        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
        loop_thread.start()
        try:
            batcher = TelemetryBatcher(loop, interval=0.05)
            batcher.add({"target_id": "turret-1", "x": 5})
            batcher.start()
            time.sleep(0.2)
            batcher.stop()
            assert len(batcher._buffer) == 0
        finally:
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=2.0)
            loop.close()

    def test_stop_sets_running_false(self):
        loop = asyncio.new_event_loop()
        batcher = TelemetryBatcher(loop)
        assert batcher._running is True
        batcher.stop()
        assert batcher._running is False
        loop.close()

    def test_empty_buffer_no_flush(self):
        loop = asyncio.new_event_loop()
        batcher = TelemetryBatcher(loop, interval=0.05)
        batcher.start()
        time.sleep(0.2)
        batcher.stop()
        loop.close()

    def test_thread_safety(self):
        loop = asyncio.new_event_loop()
        batcher = TelemetryBatcher(loop, interval=1.0)
        errors = []

        def add_many(tid):
            try:
                for i in range(50):
                    batcher.add({"tid": tid, "seq": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_many, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(batcher._buffer) == 200
        loop.close()

    def test_interval_stored(self):
        loop = asyncio.new_event_loop()
        batcher = TelemetryBatcher(loop, interval=0.5)
        assert batcher._interval == 0.5
        loop.close()
