# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the mesh API router (/api/mesh/*).

Tests all endpoints: nodes, messages, send, status, discover.
Uses FastAPI TestClient with a mocked MeshtasticBridge.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.mesh import router
from engine.comms.meshtastic_bridge import MeshtasticNode


def _make_app(bridge=None):
    """Create a minimal FastAPI app with mesh router and optional bridge."""
    app = FastAPI()
    app.include_router(router)
    if bridge is not None:
        app.state.meshtastic_bridge = bridge
    return app


def _mock_bridge(connected=True, nodes=None, messages=None):
    """Create a mock MeshtasticBridge."""
    bridge = MagicMock()
    bridge.connected = connected
    bridge.nodes = nodes or {}
    bridge.messages = messages or []
    bridge.stats = {
        "connected": connected,
        "host": "192.168.1.50:4403",
        "messages_received": 10,
        "messages_sent": 3,
        "nodes_discovered": len(nodes) if nodes else 0,
        "last_error": "",
    }
    bridge.send_text.return_value = True
    return bridge


# ===========================================================================
# GET /api/mesh/nodes
# ===========================================================================


@pytest.mark.unit
class TestGetNodes:
    def test_returns_nodes(self):
        nodes = {
            "!abc": MeshtasticNode(
                node_id="!abc",
                long_name="Base Station",
                short_name="BS",
                hardware="HELTEC_V3",
                battery=75,
                snr=10.5,
            ),
        }
        client = TestClient(_make_app(bridge=_mock_bridge(nodes=nodes)))
        resp = client.get("/api/mesh/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["nodes"][0]["node_id"] == "!abc"
        assert data["nodes"][0]["long_name"] == "Base Station"
        assert data["nodes"][0]["battery"] == 75

    def test_empty_nodes(self):
        client = TestClient(_make_app(bridge=_mock_bridge()))
        resp = client.get("/api/mesh/nodes")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_503_without_bridge(self):
        client = TestClient(_make_app(bridge=None))
        resp = client.get("/api/mesh/nodes")
        assert resp.status_code == 503


# ===========================================================================
# GET /api/mesh/messages
# ===========================================================================


@pytest.mark.unit
class TestGetMessages:
    def test_returns_messages(self):
        messages = [
            {"from": "!abc", "text": "Hello", "timestamp": "2026-02-21T10:00:00Z"},
            {"from": "!def", "text": "World", "timestamp": "2026-02-21T10:01:00Z"},
        ]
        client = TestClient(_make_app(bridge=_mock_bridge(messages=messages)))
        resp = client.get("/api/mesh/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["total"] == 2
        # Most recent first
        assert data["messages"][0]["text"] == "World"

    def test_limit_parameter(self):
        messages = [{"text": f"msg-{i}"} for i in range(10)]
        client = TestClient(_make_app(bridge=_mock_bridge(messages=messages)))
        resp = client.get("/api/mesh/messages?limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert data["total"] == 10

    def test_503_without_bridge(self):
        client = TestClient(_make_app(bridge=None))
        resp = client.get("/api/mesh/messages")
        assert resp.status_code == 503


# ===========================================================================
# POST /api/mesh/send
# ===========================================================================


@pytest.mark.unit
class TestPostSend:
    def test_send_text(self):
        bridge = _mock_bridge()
        client = TestClient(_make_app(bridge=bridge))
        resp = client.post("/api/mesh/send", json={"text": "Hello mesh!"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "sent"
        bridge.send_text.assert_called_once_with(
            text="Hello mesh!", channel=0, destination=None
        )

    def test_send_with_channel_and_destination(self):
        bridge = _mock_bridge()
        client = TestClient(_make_app(bridge=bridge))
        resp = client.post("/api/mesh/send", json={
            "text": "DM", "channel": 2, "destination": "!abc"
        })
        assert resp.status_code == 200
        bridge.send_text.assert_called_once_with(
            text="DM", channel=2, destination="!abc"
        )

    def test_send_failure_returns_500(self):
        bridge = _mock_bridge()
        bridge.send_text.return_value = False
        client = TestClient(_make_app(bridge=bridge))
        resp = client.post("/api/mesh/send", json={"text": "fail"})
        assert resp.status_code == 500

    def test_503_without_bridge(self):
        client = TestClient(_make_app(bridge=None))
        resp = client.post("/api/mesh/send", json={"text": "hello"})
        assert resp.status_code == 503

    def test_send_missing_text(self):
        """Missing required 'text' field should return 422."""
        client = TestClient(_make_app(bridge=_mock_bridge()))
        resp = client.post("/api/mesh/send", json={})
        assert resp.status_code == 422


# ===========================================================================
# GET /api/mesh/status
# ===========================================================================


@pytest.mark.unit
class TestGetStatus:
    def test_status_with_bridge(self):
        client = TestClient(_make_app(bridge=_mock_bridge()))
        resp = client.get("/api/mesh/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["connected"] is True
        assert data["messages_received"] == 10

    def test_status_without_bridge(self):
        """When bridge is not configured, status should return enabled=False."""
        client = TestClient(_make_app(bridge=None))
        resp = client.get("/api/mesh/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["connected"] is False


# ===========================================================================
# GET /api/mesh/discover
# ===========================================================================


@pytest.mark.unit
class TestGetDiscover:
    def test_discover_returns_devices(self):
        with patch(
            "engine.comms.meshtastic_bridge.MeshtasticBridge.discover",
            return_value=[{"host": "192.168.1.50", "port": 4403, "name": "radio.local"}],
        ):
            client = TestClient(_make_app(bridge=_mock_bridge()))
            resp = client.get("/api/mesh/discover")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 1
            assert data["devices"][0]["host"] == "192.168.1.50"

    def test_discover_empty(self):
        with patch("engine.comms.meshtastic_bridge.MeshtasticBridge.discover", return_value=[]):
            client = TestClient(_make_app(bridge=_mock_bridge()))
            resp = client.get("/api/mesh/discover")
            assert resp.status_code == 200
            assert resp.json()["count"] == 0
