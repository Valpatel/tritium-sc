# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for MeshWebSource._fetch_nodes() multi-format parsing.

TDD — written before implementation changes. These tests exercise the
various real-world API response formats that _fetch_nodes() must handle:
Meshtastic community map (liamcottle), generic array, wrapped objects,
missing fields, edge cases.
"""

from __future__ import annotations

import json
import queue
from unittest.mock import MagicMock, patch

import pytest

from engine.comms.mesh_web_source import MeshWebSource


# ---------------------------------------------------------------------------
# Mock helpers (same pattern as test_mesh_web_source.py)
# ---------------------------------------------------------------------------


class MockEventBus:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, data: dict | None = None):
        self.published.append((event_type, data))

    def subscribe(self) -> queue.Queue:
        return queue.Queue()

    def unsubscribe(self, q: queue.Queue) -> None:
        pass


class MockTargetTracker:
    def __init__(self):
        self.sim_updates: list[dict] = []
        self._targets: dict = {}

    def update_from_simulation(self, data: dict) -> None:
        self.sim_updates.append(data)

    def remove(self, target_id: str) -> bool:
        return self._targets.pop(target_id, None) is not None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus():
    return MockEventBus()


@pytest.fixture
def tracker():
    return MockTargetTracker()


def _make_source(event_bus, tracker, url="https://example.com/mesh/nodes"):
    return MeshWebSource(
        event_bus=event_bus,
        target_tracker=tracker,
        mesh_web_url=url,
    )


def _mock_http(data: bytes):
    """Create a mock urllib response returning the given bytes."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = data
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ===========================================================================
# Multi-format parsing
# ===========================================================================


@pytest.mark.unit
class TestMeshWebFetchFormats:
    """Test _fetch_nodes() with various real-world API response formats."""

    def test_liamcottle_format(self, event_bus, tracker):
        """Meshtastic community map format with latitude/longitude/long_name."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {
                "node_id": "!abc123",
                "long_name": "MyNode",
                "latitude": 37.7749,
                "longitude": -122.4194,
                "last_heard": 1709000000,
            },
            {
                "node_id": "!def456",
                "long_name": "OtherNode",
                "latitude": 37.7850,
                "longitude": -122.4100,
                "last_heard": 1709000100,
            },
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 2
        assert nodes[0]["node_id"] == "!abc123"
        assert nodes[0]["name"] == "MyNode"
        assert nodes[0]["lat"] == 37.7749
        assert nodes[0]["lng"] == -122.4194
        assert nodes[1]["node_id"] == "!def456"
        assert nodes[1]["name"] == "OtherNode"

    def test_generic_array_format(self, event_bus, tracker):
        """Simple [{id, lat, lng, name}] format."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"id": "abc", "lat": 37.77, "lng": -122.42, "name": "Node1"},
            {"id": "def", "lat": 37.78, "lng": -122.43, "name": "Node2"},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 2
        assert nodes[0]["node_id"] == "abc"
        assert nodes[0]["name"] == "Node1"
        assert nodes[0]["lat"] == 37.77
        assert nodes[0]["lng"] == -122.42

    def test_wrapped_nodes_format(self, event_bus, tracker):
        """{"nodes": [...]} wrapper format."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps({
            "nodes": [
                {"node_id": "w1", "lat": 38.0, "lng": -121.0, "name": "Wrapped1"},
            ]
        }).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["node_id"] == "w1"
        assert nodes[0]["name"] == "Wrapped1"

    def test_wrapped_data_format(self, event_bus, tracker):
        """{"data": [...]} wrapper format."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps({
            "data": [
                {"id": "d1", "lat": 39.0, "lng": -120.0, "name": "DataNode"},
            ]
        }).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["node_id"] == "d1"
        assert nodes[0]["name"] == "DataNode"

    def test_missing_name_uses_node_id(self, event_bus, tracker):
        """Nodes without name field use node_id as fallback."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"node_id": "!noname99", "lat": 37.7, "lng": -122.4},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["name"] == "!noname99"

    def test_missing_position_skipped(self, event_bus, tracker):
        """Nodes without lat/lng are silently skipped."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"node_id": "noloc", "name": "No Location"},
            {"node_id": "hasloc", "lat": 37.7, "lng": -122.4, "name": "Has Location"},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        # Only the node with coordinates should be returned
        assert len(nodes) == 1
        assert nodes[0]["node_id"] == "hasloc"

    def test_zero_position_skipped(self, event_bus, tracker):
        """Nodes at exactly (0,0) are skipped (invalid GPS)."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"node_id": "zero", "lat": 0.0, "lng": 0.0, "name": "Zero"},
            {"node_id": "valid", "lat": 37.7, "lng": -122.4, "name": "Valid"},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        # Zero-coordinate node should be filtered out at _fetch_nodes level
        # (process_poll_result also filters, but _fetch_nodes should too)
        node_ids = [n["node_id"] for n in nodes]
        assert "zero" not in node_ids
        assert "valid" in node_ids

    def test_protocol_field_preserved(self, event_bus, tracker):
        """If source data includes protocol, it's preserved."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"node_id": "p1", "lat": 37.7, "lng": -122.4, "protocol": "meshcore"},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["protocol"] == "meshcore"

    def test_protocol_defaults_to_meshtastic(self, event_bus, tracker):
        """Missing protocol field defaults to 'meshtastic'."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"node_id": "np1", "lat": 37.7, "lng": -122.4, "name": "NoProto"},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["protocol"] == "meshtastic"

    def test_last_seen_from_unix_timestamp(self, event_bus, tracker):
        """Unix timestamp in last_heard is preserved as last_seen."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"node_id": "ts1", "lat": 37.7, "lng": -122.4, "last_heard": 1709000000},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        # last_seen should contain the timestamp (as string or number)
        assert nodes[0]["last_seen"] != ""

    def test_last_seen_from_iso_string(self, event_bus, tracker):
        """ISO string last_seen is preserved."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"node_id": "iso1", "lat": 37.7, "lng": -122.4, "last_seen": "2026-02-26T12:00:00Z"},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert "2026-02-26" in str(nodes[0]["last_seen"])

    def test_empty_response(self, event_bus, tracker):
        """Empty array returns empty list."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert nodes == []

    def test_html_response_returns_empty(self, event_bus, tracker):
        """Non-JSON response (HTML error page) returns empty list."""
        source = _make_source(event_bus, tracker)
        html = b"<html><body>502 Bad Gateway</body></html>"

        with patch("urllib.request.urlopen", return_value=_mock_http(html)):
            nodes = source._fetch_nodes()

        assert nodes == []
        assert source._last_error != ""

    def test_timeout_returns_empty(self, event_bus, tracker):
        """HTTP timeout returns empty list, no crash."""
        source = _make_source(event_bus, tracker)

        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            nodes = source._fetch_nodes()

        assert nodes == []
        assert source._last_error == "timeout"

    def test_user_agent_header(self, event_bus, tracker):
        """Request includes tritium-sc User-Agent header."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([]).encode()

        with patch("urllib.request.Request") as mock_req_cls, \
             patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            mock_req_cls.return_value = MagicMock()
            source._fetch_nodes()

            # Check that Request was called with appropriate headers
            call_args = mock_req_cls.call_args
            headers = call_args[1].get("headers", {}) if call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else {}
            # The User-Agent should contain "tritium-sc"
            ua = headers.get("User-Agent", "")
            assert "tritium-sc" in ua.lower() or "TRITIUM" in ua

    def test_latitude_longitude_field_aliases(self, event_bus, tracker):
        """Fields named 'latitude'/'longitude' are recognized."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"node_id": "ll1", "latitude": 37.7749, "longitude": -122.4194},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["lat"] == 37.7749
        assert nodes[0]["lng"] == -122.4194

    def test_long_name_field_alias(self, event_bus, tracker):
        """Field named 'long_name' is used as name."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"node_id": "ln1", "lat": 37.7, "lng": -122.4, "long_name": "My Long Name"},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["name"] == "My Long Name"

    def test_last_heard_field_alias(self, event_bus, tracker):
        """Field named 'last_heard' maps to last_seen."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"node_id": "lh1", "lat": 37.7, "lng": -122.4, "last_heard": 1709000000},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["last_seen"] != ""

    def test_mixed_formats_in_single_response(self, event_bus, tracker):
        """Response with mixed field naming still parses all valid nodes."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"node_id": "!a", "latitude": 37.7, "longitude": -122.4, "long_name": "A"},
            {"id": "b", "lat": 37.8, "lng": -122.3, "name": "B"},
            {"node_id": "c", "lat": 37.9, "lon": -122.2},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 3
        assert nodes[0]["node_id"] == "!a"
        assert nodes[0]["lat"] == 37.7
        assert nodes[0]["name"] == "A"
        assert nodes[1]["node_id"] == "b"
        assert nodes[1]["name"] == "B"
        assert nodes[2]["node_id"] == "c"
        assert nodes[2]["lng"] == -122.2
        # node without name should default to node_id
        assert nodes[2]["name"] == "c"

    def test_non_dict_entries_skipped(self, event_bus, tracker):
        """Non-dict entries in the array are silently skipped."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            "just a string",
            42,
            None,
            {"node_id": "valid", "lat": 37.7, "lng": -122.4},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["node_id"] == "valid"

    def test_no_id_field_skipped(self, event_bus, tracker):
        """Entries with no node_id or id field are skipped."""
        source = _make_source(event_bus, tracker)
        payload = json.dumps([
            {"lat": 37.7, "lng": -122.4, "name": "NoID"},
            {"node_id": "hasid", "lat": 37.8, "lng": -122.3},
        ]).encode()

        with patch("urllib.request.urlopen", return_value=_mock_http(payload)):
            nodes = source._fetch_nodes()

        assert len(nodes) == 1
        assert nodes[0]["node_id"] == "hasid"
