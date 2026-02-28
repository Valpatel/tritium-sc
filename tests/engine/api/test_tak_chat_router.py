# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for /api/tak/chat* and /api/tak/history endpoints.

TDD: tests written BEFORE implementation.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.tak import router


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.connected = True
    bridge.callsign = "TRITIUM-SC"
    bridge.send_geochat = MagicMock()
    bridge._tx_queue = MagicMock()
    bridge._tx_queue.qsize.return_value = 0
    return bridge


@pytest.fixture
def client_with_bridge(app, mock_bridge):
    app.state.tak_bridge = mock_bridge
    return TestClient(app)


@pytest.fixture
def client_no_bridge(app):
    return TestClient(app)


class TestTakChatEndpoint:

    def test_send_chat_message(self, client_with_bridge, mock_bridge):
        resp = client_with_bridge.post("/api/tak/chat", json={
            "message": "Enemy spotted at north gate",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "sent"
        mock_bridge.send_geochat.assert_called_once()

    def test_send_chat_with_recipient(self, client_with_bridge, mock_bridge):
        resp = client_with_bridge.post("/api/tak/chat", json={
            "message": "Alpha, move to south fence",
            "to_callsign": "Alpha",
        })
        assert resp.status_code == 200
        mock_bridge.send_geochat.assert_called_once()

    def test_send_chat_without_bridge(self, client_no_bridge):
        resp = client_no_bridge.post("/api/tak/chat", json={
            "message": "Hello",
        })
        assert resp.status_code == 503

    def test_send_chat_empty_message_rejected(self, client_with_bridge):
        resp = client_with_bridge.post("/api/tak/chat", json={
            "message": "",
        })
        assert resp.status_code == 422 or resp.status_code == 400


class TestTakChatMessages:

    def test_get_messages_returns_list(self, client_with_bridge, mock_bridge):
        mock_bridge.chat_history = [
            {
                "sender_callsign": "Alpha",
                "message": "Hostile near gate",
                "direction": "inbound",
                "timestamp": "2026-02-22T10:00:00Z",
            }
        ]
        resp = client_with_bridge.get("/api/tak/chat/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data
        assert isinstance(data["messages"], list)

    def test_get_messages_without_bridge(self, client_no_bridge):
        resp = client_no_bridge.get("/api/tak/chat/messages")
        assert resp.status_code == 503


class TestTakHistory:

    def test_history_endpoint_exists(self, client_with_bridge):
        resp = client_with_bridge.get("/api/tak/history")
        assert resp.status_code == 200

    def test_history_returns_events(self, client_with_bridge, mock_bridge):
        mock_bridge.get_history = MagicMock(return_value=[])
        resp = client_with_bridge.get("/api/tak/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
