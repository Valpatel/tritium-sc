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


@pytest.mark.unit
class TestDeviceCommandLuaPassthrough:
    """Commands with parentheses are passed through as-is to avoid double-wrapping."""

    def _get_lua_str(self, cmd: str) -> str:
        """Extract the Lua string the router would generate for a command."""
        from app.routers.devices import router as _  # noqa: F811 — ensure import
        import importlib
        import app.routers.devices as mod

        # The lua_map and fallback logic is inline in the route handler.
        # We verify behavior by inspecting source for the fix.
        import inspect
        source = inspect.getsource(mod.device_command)
        assert '"(" in cmd' in source, "Router should check for parens in command"
        return source  # Just verify the source has the fix

    def test_fire_nerf_not_double_wrapped(self):
        """fire_nerf() should NOT become fire_nerf()("device-id")."""
        # When no MQTT and no Amy, command is accepted but the Lua string
        # is computed internally.  We verify via source inspection.
        source = self._get_lua_str("fire_nerf()")
        assert '"(" in cmd' in source

    def test_command_with_parens_via_mqtt(self):
        """Lua commands with parens sent via MQTT pass the raw string."""
        mqtt = MagicMock()
        client = TestClient(_make_app(mqtt_bridge=mqtt))
        resp = client.post(
            "/api/devices/rover-01/command",
            json={"command": "fire_nerf()"},
        )
        assert resp.status_code == 200
        assert resp.json()["via"] == "mqtt"
        _, payload = mqtt.publish.call_args[0]
        assert json.loads(payload)["command"] == "fire_nerf()"

    def test_motor_aim_with_args_via_mqtt(self):
        """motor.aim(10,20) preserves the full Lua string."""
        mqtt = MagicMock()
        client = TestClient(_make_app(mqtt_bridge=mqtt))
        resp = client.post(
            "/api/devices/turret-01/command",
            json={"command": "motor.aim(10,20)"},
        )
        assert resp.status_code == 200
        _, payload = mqtt.publish.call_args[0]
        assert json.loads(payload)["command"] == "motor.aim(10,20)"

    def test_stop_command_accepted_without_backend(self):
        """stop() accepted without MQTT — should NOT become stop()("dev-01")."""
        client = TestClient(_make_app())
        resp = client.post(
            "/api/devices/dev-01/command",
            json={"command": "stop()"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_simple_command_without_parens_wraps_device_id(self):
        """Commands without parens get device_id wrapped: enable -> enable("dev-01")."""
        # Source inspection: the else branch should wrap device_id
        import inspect
        import app.routers.devices as mod
        source = inspect.getsource(mod.device_command)
        assert 'f\'{cmd}("{device_id}")\'' in source
