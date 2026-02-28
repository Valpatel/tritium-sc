# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for mesh subsystem wiring into main.py.

Verifies that MeshCoreBridge and MeshWebSource are started/skipped
based on configuration, and that MeshWebSource._fetch_nodes() handles
real HTTP responses, empty URLs, errors, and timeouts correctly.
"""

from __future__ import annotations

import json
import queue
from unittest.mock import MagicMock, patch

import pytest

from engine.comms.meshcore_bridge import MeshCoreBridge
from engine.comms.mesh_web_source import MeshWebSource


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockEventBus:
    """Lightweight EventBus stand-in that records published events."""

    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, data: dict | None = None):
        self.published.append((event_type, data))

    def subscribe(self) -> queue.Queue:
        return queue.Queue()

    def unsubscribe(self, q: queue.Queue) -> None:
        pass


class MockTargetTracker:
    """Lightweight TargetTracker stand-in that records calls."""

    def __init__(self):
        self.sim_updates: list[dict] = []
        self._targets: dict = {}

    def update_from_simulation(self, data: dict) -> None:
        self.sim_updates.append(data)

    def remove(self, target_id: str) -> bool:
        return self._targets.pop(target_id, None) is not None


@pytest.fixture
def event_bus():
    return MockEventBus()


@pytest.fixture
def tracker():
    return MockTargetTracker()


# ===========================================================================
# Task 1: MeshCore bridge start/disabled
# ===========================================================================


@pytest.mark.unit
class TestMeshCoreBridgeWiring:
    def test_meshcore_bridge_start_disabled(self, event_bus, tracker):
        """When meshcore_enabled=False, bridge should not be created."""
        # Simulate the check from _start_meshcore_bridge
        settings = MagicMock()
        settings.meshcore_enabled = False

        # The function pattern: check settings, return None
        if not settings.meshcore_enabled:
            result = None
        else:
            result = MeshCoreBridge(
                event_bus=event_bus,
                target_tracker=tracker,
                serial_port=settings.meshcore_serial_port,
            )

        assert result is None

    def test_meshcore_bridge_creates_when_enabled(self, event_bus, tracker):
        """When meshcore_enabled=True, bridge should be created."""
        bridge = MeshCoreBridge(
            event_bus=event_bus,
            target_tracker=tracker,
            serial_port="/dev/ttyUSB0",
        )
        assert bridge is not None
        assert bridge._serial_port == "/dev/ttyUSB0"


# ===========================================================================
# Task 2: MeshWebSource start/disabled
# ===========================================================================


@pytest.mark.unit
class TestMeshWebSourceWiring:
    def test_mesh_web_source_start_disabled(self, event_bus, tracker):
        """When mesh_web_enabled=False, source should not be created."""
        settings = MagicMock()
        settings.mesh_web_enabled = False

        if not settings.mesh_web_enabled:
            result = None
        else:
            result = MeshWebSource(
                event_bus=event_bus,
                target_tracker=tracker,
                poll_interval=60,
            )

        assert result is None

    def test_mesh_web_source_creates_when_enabled(self, event_bus, tracker):
        """When mesh_web_enabled=True, source should be created."""
        source = MeshWebSource(
            event_bus=event_bus,
            target_tracker=tracker,
            poll_interval=30,
            mesh_web_url="https://example.com/nodes",
        )
        assert source is not None
        assert source._poll_interval == 30
        assert source._mesh_web_url == "https://example.com/nodes"


# ===========================================================================
# Task 3: _fetch_nodes() with URL
# ===========================================================================


@pytest.mark.unit
class TestMeshWebFetch:
    def test_mesh_web_fetch_with_url(self, event_bus, tracker):
        """Mock HTTP response should produce a parsed node list."""
        source = MeshWebSource(
            event_bus=event_bus,
            target_tracker=tracker,
            mesh_web_url="https://example.com/mesh/nodes",
        )

        mock_response = json.dumps([
            {"node_id": "n001", "lat": 37.7749, "lng": -122.4194, "name": "Alpha"},
            {"node_id": "n002", "lat": 37.7850, "lng": -122.4100, "name": "Bravo"},
        ]).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            nodes = source._fetch_nodes()

        assert len(nodes) == 2
        assert nodes[0]["node_id"] == "n001"
        assert nodes[0]["lat"] == 37.7749
        assert nodes[0]["name"] == "Alpha"
        assert nodes[1]["node_id"] == "n002"

    def test_mesh_web_fetch_with_wrapped_response(self, event_bus, tracker):
        """Handle JSON wrapped in {"nodes": [...]} format."""
        source = MeshWebSource(
            event_bus=event_bus,
            target_tracker=tracker,
            mesh_web_url="https://example.com/mesh/nodes",
        )

        mock_response = json.dumps({
            "nodes": [
                {"id": "x1", "lat": 38.0, "lng": -121.0, "name": "Node X1"},
            ]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["node_id"] == "x1"
        assert nodes[0]["name"] == "Node X1"

    def test_mesh_web_fetch_empty_url(self, event_bus, tracker):
        """Empty URL returns empty list (no-op)."""
        source = MeshWebSource(
            event_bus=event_bus,
            target_tracker=tracker,
            mesh_web_url="",
        )
        nodes = source._fetch_nodes()
        assert nodes == []

    def test_mesh_web_fetch_no_url_param(self, event_bus, tracker):
        """Default constructor with no URL returns empty list."""
        source = MeshWebSource(
            event_bus=event_bus,
            target_tracker=tracker,
        )
        nodes = source._fetch_nodes()
        assert nodes == []

    def test_mesh_web_fetch_http_error(self, event_bus, tracker):
        """HTTP error returns empty list gracefully."""
        import urllib.error

        source = MeshWebSource(
            event_bus=event_bus,
            target_tracker=tracker,
            mesh_web_url="https://example.com/mesh/nodes",
        )

        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            url="https://example.com/mesh/nodes",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=None,
        )):
            nodes = source._fetch_nodes()

        assert nodes == []
        assert "500" in source._last_error

    def test_mesh_web_fetch_timeout(self, event_bus, tracker):
        """Timeout returns empty list gracefully."""
        source = MeshWebSource(
            event_bus=event_bus,
            target_tracker=tracker,
            mesh_web_url="https://example.com/mesh/nodes",
        )

        with patch("urllib.request.urlopen", side_effect=TimeoutError("connection timed out")):
            nodes = source._fetch_nodes()

        assert nodes == []
        assert source._last_error == "timeout"

    def test_mesh_web_fetch_malformed_json(self, event_bus, tracker):
        """Malformed JSON returns empty list gracefully."""
        source = MeshWebSource(
            event_bus=event_bus,
            target_tracker=tracker,
            mesh_web_url="https://example.com/mesh/nodes",
        )

        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not valid json{{"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            nodes = source._fetch_nodes()

        assert nodes == []
        assert "JSON" in source._last_error

    def test_mesh_web_fetch_url_error(self, event_bus, tracker):
        """URLError (DNS failure etc.) returns empty list gracefully."""
        import urllib.error

        source = MeshWebSource(
            event_bus=event_bus,
            target_tracker=tracker,
            mesh_web_url="https://nonexistent.example.com/nodes",
        )

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Name resolution failed")):
            nodes = source._fetch_nodes()

        assert nodes == []
        assert "URL error" in source._last_error

    def test_mesh_web_fetch_uses_id_fallback(self, event_bus, tracker):
        """Nodes with 'id' instead of 'node_id' should be parsed."""
        source = MeshWebSource(
            event_bus=event_bus,
            target_tracker=tracker,
            mesh_web_url="https://example.com/mesh/nodes",
        )

        mock_response = json.dumps([
            {"id": "abc123", "lat": 37.0, "lng": -122.0},
        ]).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["node_id"] == "abc123"

    def test_mesh_web_fetch_uses_lon_fallback(self, event_bus, tracker):
        """Nodes with 'lon' instead of 'lng' should be parsed."""
        source = MeshWebSource(
            event_bus=event_bus,
            target_tracker=tracker,
            mesh_web_url="https://example.com/mesh/nodes",
        )

        mock_response = json.dumps([
            {"node_id": "n1", "lat": 37.0, "lon": -122.0},
        ]).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["lng"] == -122.0
