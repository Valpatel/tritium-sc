# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the device command API router (/api/devices/*).

Tests sensor, camera, and mesh radio command routing.
Uses FastAPI TestClient with mocked backends.
"""
from __future__ import annotations

import json

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.devices import router


def _make_app(mqtt_bridge=None, meshtastic_bridge=None, amy=None):
    """Create a minimal FastAPI app with devices router."""
    app = FastAPI()
    app.include_router(router)
    if mqtt_bridge is not None:
        app.state.mqtt_bridge = mqtt_bridge
        app.state.mqtt_site_id = "test"
    if meshtastic_bridge is not None:
        app.state.meshtastic_bridge = meshtastic_bridge
    if amy is not None:
        app.state.amy = amy
    return app


@pytest.mark.unit
class TestDeviceCommandSensor:
    """POST /api/devices/{id}/command — sensor commands."""

    def test_sensor_enable_via_mqtt(self):
        mqtt = MagicMock()
        client = TestClient(_make_app(mqtt_bridge=mqtt))
        resp = client.post(
            "/api/devices/sensor-01/command",
            json={"command": "enable"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["command"] == "enable"
        assert data["via"] == "mqtt"
        mqtt.publish.assert_called_once()
        topic, payload = mqtt.publish.call_args[0]
        assert "sensor-01" in topic
        assert json.loads(payload)["command"] == "enable"

    def test_sensor_disable_via_mqtt(self):
        mqtt = MagicMock()
        client = TestClient(_make_app(mqtt_bridge=mqtt))
        resp = client.post(
            "/api/devices/sensor-01/command",
            json={"command": "disable"},
        )
        assert resp.status_code == 200
        assert resp.json()["command"] == "disable"

    def test_sensor_test_trigger_via_mqtt(self):
        mqtt = MagicMock()
        client = TestClient(_make_app(mqtt_bridge=mqtt))
        resp = client.post(
            "/api/devices/sensor-01/command",
            json={"command": "test_trigger"},
        )
        assert resp.status_code == 200
        assert resp.json()["command"] == "test_trigger"


@pytest.mark.unit
class TestDeviceCommandCamera:
    """POST /api/devices/{id}/command — camera commands."""

    def test_camera_off_via_mqtt(self):
        mqtt = MagicMock()
        client = TestClient(_make_app(mqtt_bridge=mqtt))
        resp = client.post(
            "/api/devices/cam-front/command",
            json={"command": "camera_off"},
        )
        assert resp.status_code == 200
        assert resp.json()["command"] == "camera_off"
        assert resp.json()["via"] == "mqtt"


@pytest.mark.unit
class TestDeviceCommandMesh:
    """POST /api/devices/{id}/command — mesh radio text."""

    def test_mesh_text_sent(self):
        mesh = MagicMock()
        mesh.send_text.return_value = True
        client = TestClient(_make_app(meshtastic_bridge=mesh))
        resp = client.post(
            "/api/devices/mesh-01/command",
            json={"text": "Hello mesh"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "sent"
        assert data["text"] == "Hello mesh"
        mesh.send_text.assert_called_once_with(text="Hello mesh")

    def test_mesh_text_bridge_unavailable(self):
        client = TestClient(_make_app())
        resp = client.post(
            "/api/devices/mesh-01/command",
            json={"text": "Hello mesh"},
        )
        assert resp.status_code == 503

    def test_mesh_text_send_failure(self):
        mesh = MagicMock()
        mesh.send_text.return_value = False
        client = TestClient(_make_app(meshtastic_bridge=mesh))
        resp = client.post(
            "/api/devices/mesh-01/command",
            json={"text": "test"},
        )
        assert resp.status_code == 500


@pytest.mark.unit
class TestDeviceCommandFallback:
    """POST /api/devices/{id}/command — fallback behavior."""

    def test_no_command_or_text_returns_400(self):
        client = TestClient(_make_app())
        resp = client.post(
            "/api/devices/dev-01/command",
            json={},
        )
        assert resp.status_code == 400

    def test_accepted_without_backend(self):
        """When no MQTT, no mesh, no Amy — command is accepted but unhandled."""
        client = TestClient(_make_app())
        resp = client.post(
            "/api/devices/dev-01/command",
            json={"command": "enable"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["via"] == "none"

    def test_mqtt_failure_falls_through(self):
        """When MQTT publish fails, falls through to Lua/accepted."""
        mqtt = MagicMock()
        mqtt.publish.side_effect = Exception("MQTT error")
        client = TestClient(_make_app(mqtt_bridge=mqtt))
        resp = client.post(
            "/api/devices/dev-01/command",
            json={"command": "enable"},
        )
        assert resp.status_code == 200
        # Should fall through to accepted (no Amy either)
        assert resp.json()["via"] == "none"

    def test_generic_command_uses_fallback_lua(self):
        """Unknown commands get generic Lua mapping."""
        mqtt = MagicMock()
        client = TestClient(_make_app(mqtt_bridge=mqtt))
        resp = client.post(
            "/api/devices/dev-01/command",
            json={"command": "custom_action"},
        )
        assert resp.status_code == 200
        assert resp.json()["command"] == "custom_action"
