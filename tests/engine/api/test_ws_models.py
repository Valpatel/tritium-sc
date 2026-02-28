# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for WebSocket module — ConnectionManager and TelemetryBatcher.

Tests ConnectionManager sync logic and TelemetryBatcher buffer management.
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.ws import ConnectionManager, TelemetryBatcher


# ===========================================================================
# ConnectionManager — Construction
# ===========================================================================

@pytest.mark.unit
class TestConnectionManagerInit:
    """ConnectionManager — initialization."""

    def test_starts_empty(self):
        mgr = ConnectionManager()
        assert len(mgr.active_connections) == 0

    def test_active_connections_is_set(self):
        mgr = ConnectionManager()
        assert isinstance(mgr.active_connections, set)


# ===========================================================================
# ConnectionManager — connect/disconnect
# ===========================================================================

@pytest.mark.unit
class TestConnectionManagerConnectDisconnect:
    """ConnectionManager — connect and disconnect."""

    def test_connect_adds(self):
        mgr = ConnectionManager()
        ws = AsyncMock()

        async def _test():
            await mgr.connect(ws)
            return len(mgr.active_connections)

        count = asyncio.run(_test())
        assert count == 1
        ws.accept.assert_called_once()

    def test_disconnect_removes(self):
        mgr = ConnectionManager()
        ws = AsyncMock()

        async def _test():
            await mgr.connect(ws)
            await mgr.disconnect(ws)
            return len(mgr.active_connections)

        count = asyncio.run(_test())
        assert count == 0

    def test_disconnect_nonexistent_no_error(self):
        mgr = ConnectionManager()
        ws = AsyncMock()

        async def _test():
            await mgr.disconnect(ws)  # Not connected

        asyncio.run(_test())  # Should not raise

    def test_multiple_connections(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws3 = AsyncMock()

        async def _test():
            await mgr.connect(ws1)
            await mgr.connect(ws2)
            await mgr.connect(ws3)
            return len(mgr.active_connections)

        count = asyncio.run(_test())
        assert count == 3


# ===========================================================================
# ConnectionManager — broadcast
# ===========================================================================

@pytest.mark.unit
class TestConnectionManagerBroadcast:
    """ConnectionManager — message broadcasting."""

    def test_broadcast_to_all(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        async def _test():
            await mgr.connect(ws1)
            await mgr.connect(ws2)
            await mgr.broadcast({"type": "test", "data": "hello"})

        asyncio.run(_test())
        assert ws1.send_text.called
        assert ws2.send_text.called

    def test_broadcast_empty_connections_no_error(self):
        mgr = ConnectionManager()

        async def _test():
            await mgr.broadcast({"type": "test"})

        asyncio.run(_test())  # Should not raise

    def test_broadcast_removes_failed(self):
        mgr = ConnectionManager()
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_text.side_effect = Exception("Connection closed")

        async def _test():
            await mgr.connect(ws_good)
            await mgr.connect(ws_bad)
            await mgr.broadcast({"type": "test"})
            return len(mgr.active_connections)

        count = asyncio.run(_test())
        assert count == 1

    def test_broadcast_json_format(self):
        mgr = ConnectionManager()
        ws = AsyncMock()

        async def _test():
            await mgr.connect(ws)
            await mgr.broadcast({"type": "event", "value": 42})

        asyncio.run(_test())
        sent = ws.send_text.call_args[0][0]
        parsed = json.loads(sent)
        assert parsed["type"] == "event"
        assert parsed["value"] == 42


# ===========================================================================
# ConnectionManager — send_to
# ===========================================================================

@pytest.mark.unit
class TestConnectionManagerSendTo:
    """ConnectionManager — send to specific client."""

    def test_send_to_success(self):
        mgr = ConnectionManager()
        ws = AsyncMock()

        async def _test():
            await mgr.send_to(ws, {"type": "pong"})

        asyncio.run(_test())
        ws.send_text.assert_called_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["type"] == "pong"

    def test_send_to_failure_no_error(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.send_text.side_effect = Exception("Connection closed")

        async def _test():
            await mgr.send_to(ws, {"type": "test"})

        asyncio.run(_test())  # Should not raise


# ===========================================================================
# TelemetryBatcher — Buffer Logic
# ===========================================================================

@pytest.mark.unit
class TestTelemetryBatcher:
    """TelemetryBatcher — buffer accumulation."""

    def test_add_item(self):
        loop = MagicMock()
        batcher = TelemetryBatcher(loop)
        batcher.add({"id": "target-1", "x": 5.0})
        assert len(batcher._buffer) == 1

    def test_add_multiple_items(self):
        loop = MagicMock()
        batcher = TelemetryBatcher(loop)
        for i in range(10):
            batcher.add({"id": f"target-{i}"})
        assert len(batcher._buffer) == 10

    def test_default_interval(self):
        loop = MagicMock()
        batcher = TelemetryBatcher(loop)
        assert batcher._interval == 0.1

    def test_custom_interval(self):
        loop = MagicMock()
        batcher = TelemetryBatcher(loop, interval=0.5)
        assert batcher._interval == 0.5

    def test_stop_sets_flag(self):
        loop = MagicMock()
        batcher = TelemetryBatcher(loop)
        batcher.stop()
        assert batcher._running is False

    def test_starts_running(self):
        loop = MagicMock()
        batcher = TelemetryBatcher(loop)
        assert batcher._running is True
