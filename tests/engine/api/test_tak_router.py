# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for /api/tak/* endpoints.

Tests run against the FastAPI router with a mocked TAKBridge.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.tak import router


@pytest.fixture
def app():
    """FastAPI app with TAK router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.connected = True
    bridge.stats = {
        "connected": True,
        "cot_url": "tcp://localhost:8088",
        "callsign": "TRITIUM-SC",
        "team": "Cyan",
        "role": "HQ",
        "messages_sent": 42,
        "messages_received": 7,
        "clients": 2,
        "last_error": "",
        "tx_queue_size": 0,
    }
    bridge.clients = {
        "ANDROID-abc": {
            "callsign": "Alpha",
            "uid": "ANDROID-abc",
            "lat": 37.7749,
            "lng": -122.4194,
            "alliance": "friendly",
            "last_seen": 1700000000,
        },
    }
    return bridge


@pytest.fixture
def client_with_bridge(app, mock_bridge):
    app.state.tak_bridge = mock_bridge
    return TestClient(app)


@pytest.fixture
def client_no_bridge(app):
    return TestClient(app)


class TestTakStatus:

    def test_status_with_bridge(self, client_with_bridge):
        resp = client_with_bridge.get("/api/tak/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["connected"] is True

    def test_status_without_bridge(self, client_no_bridge):
        resp = client_no_bridge.get("/api/tak/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["connected"] is False


class TestTakClients:

    def test_clients_returns_list(self, client_with_bridge):
        resp = client_with_bridge.get("/api/tak/clients")
        assert resp.status_code == 200
        data = resp.json()
        assert "clients" in data
        assert len(data["clients"]) == 1
        assert data["clients"][0]["callsign"] == "Alpha"

    def test_clients_without_bridge(self, client_no_bridge):
        resp = client_no_bridge.get("/api/tak/clients")
        assert resp.status_code == 503


class TestTakSend:

    def test_send_raw_cot(self, client_with_bridge, mock_bridge):
        resp = client_with_bridge.post("/api/tak/send", json={
            "cot_xml": "<event version='2.0'/>"
        })
        assert resp.status_code == 200
        mock_bridge.send_cot.assert_called_once()

    def test_send_without_bridge(self, client_no_bridge):
        resp = client_no_bridge.post("/api/tak/send", json={
            "cot_xml": "<event/>"
        })
        assert resp.status_code == 503


class TestTakAlert:

    def test_send_alert(self, client_with_bridge, mock_bridge):
        resp = client_with_bridge.post("/api/tak/alert", json={
            "callsign": "THREAT-1",
            "lat": 37.7753,
            "lng": -122.4198,
            "remarks": "Hostile spotted near perimeter",
        })
        assert resp.status_code == 200
        mock_bridge.send_cot.assert_called_once()
        # Verify the XML contains the threat data
        call_args = mock_bridge.send_cot.call_args[0][0]
        assert "THREAT-1" in call_args
        assert "a-h-G" in call_args

    def test_alert_without_bridge(self, client_no_bridge):
        resp = client_no_bridge.post("/api/tak/alert", json={
            "callsign": "THREAT-1",
            "lat": 37.7753,
            "lng": -122.4198,
        })
        assert resp.status_code == 503
