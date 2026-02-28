# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for mqtt_client.py — MQTT pub/sub with mock client, LWT, QoS."""

import json
import sys
import os
import pytest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mqtt_client import RobotMQTTClient, VALID_COMMANDS
from config import RobotConfig


def make_config(**overrides) -> RobotConfig:
    defaults = dict(
        robot_id="test-rover-01",
        name="Test Rover",
        asset_type="rover",
        mqtt_host="localhost",
        mqtt_port=1883,
        site="home",
        start_x=0.0,
        start_y=0.0,
        telemetry_interval=0.5,
    )
    defaults.update(overrides)
    return RobotConfig(**defaults)


class TestTopicFormat:
    """MQTT topics follow tritium/{site}/robots/{id}/... format."""

    def test_telemetry_topic(self):
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        assert client.telemetry_topic == "tritium/home/robots/test-rover-01/telemetry"

    def test_status_topic(self):
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        assert client.status_topic == "tritium/home/robots/test-rover-01/status"

    def test_command_topic(self):
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        assert client.command_topic == "tritium/home/robots/test-rover-01/command"

    def test_ack_topic(self):
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        assert client.ack_topic == "tritium/home/robots/test-rover-01/command/ack"

    def test_thoughts_topic(self):
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        assert client.thoughts_topic == "tritium/home/robots/test-rover-01/thoughts"

    def test_custom_site(self):
        cfg = make_config(site="warehouse")
        client = RobotMQTTClient(cfg)
        assert client.telemetry_topic == "tritium/warehouse/robots/test-rover-01/telemetry"

    def test_custom_robot_id(self):
        cfg = make_config(robot_id="drone-42")
        client = RobotMQTTClient(cfg)
        assert client.telemetry_topic == "tritium/home/robots/drone-42/telemetry"


class TestLWTSetup:
    """Last Will and Testament configured for offline status."""

    @patch("mqtt_client.mqtt.Client")
    def test_lwt_set(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        client.setup()
        # LWT should be set with offline status, retained, QoS 1
        mock_instance.will_set.assert_called_once()
        args, kwargs = mock_instance.will_set.call_args
        topic = args[0]
        payload = args[1] if len(args) > 1 else kwargs.get("payload")
        assert topic == "tritium/home/robots/test-rover-01/status"
        parsed = json.loads(payload)
        assert parsed["status"] == "offline"
        # QoS 1, retained
        qos = args[2] if len(args) > 2 else kwargs.get("qos", 0)
        retain = args[3] if len(args) > 3 else kwargs.get("retain", False)
        assert qos == 1
        assert retain is True


class TestPublishTelemetry:
    """Telemetry published at configurable interval, QoS 0."""

    @patch("mqtt_client.mqtt.Client")
    def test_publish_telemetry(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        client.setup()

        telemetry = {
            "name": "Test Rover",
            "asset_type": "rover",
            "position": {"x": 5.0, "y": 10.0},
            "heading": 90.0,
            "speed": 2.0,
            "battery": 0.85,
            "status": "active",
            "turret": {"pan": 0.0, "tilt": 0.0},
            "timestamp": "2026-02-27T12:00:00Z",
            "battery_state": {"charge_pct": 0.85, "voltage": 12.3, "current_draw": 1.8, "temperature_c": 28.5},
            "imu": {"roll": 0.0, "pitch": 0.0, "yaw": 90.0, "accel_x": 0.0, "accel_y": 0.0, "accel_z": 9.81},
            "motor_temps": {"left": 30.0, "right": 30.0},
            "odometry": {"total_distance": 100.0},
        }
        client.publish_telemetry(telemetry)

        mock_instance.publish.assert_called_once()
        args, kwargs = mock_instance.publish.call_args
        assert args[0] == "tritium/home/robots/test-rover-01/telemetry"
        # QoS 0 for telemetry
        qos = kwargs.get("qos", args[2] if len(args) > 2 else 0)
        assert qos == 0


class TestPublishStatus:
    """Status published with retained flag, QoS 1."""

    @patch("mqtt_client.mqtt.Client")
    def test_publish_online(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        client.setup()
        client.publish_status("online")

        mock_instance.publish.assert_called_once()
        args, kwargs = mock_instance.publish.call_args
        assert args[0] == "tritium/home/robots/test-rover-01/status"
        payload = json.loads(args[1])
        assert payload["status"] == "online"
        assert kwargs.get("qos", 0) == 1
        assert kwargs.get("retain", False) is True


class TestSubscribeCommand:
    """Subscribes to command topic with QoS 1."""

    @patch("mqtt_client.mqtt.Client")
    def test_subscribe_on_connect(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        client.setup()

        # Simulate on_connect callback
        client._on_connect(mock_instance, None, None, 0)

        mock_instance.subscribe.assert_called()
        # Find the command topic subscription
        sub_calls = mock_instance.subscribe.call_args_list
        topics = [c[0][0] for c in sub_calls]
        assert "tritium/home/robots/test-rover-01/command" in topics


class TestPublishAck:
    """ACK published to command/ack topic, QoS 1."""

    @patch("mqtt_client.mqtt.Client")
    def test_publish_ack(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        client.setup()
        client.publish_ack("dispatch", "2026-02-27T12:00:00Z", "accepted")

        mock_instance.publish.assert_called()
        # Find the ack publish call
        for c in mock_instance.publish.call_args_list:
            if "command/ack" in c[0][0]:
                payload = json.loads(c[0][1])
                assert payload["command"] == "dispatch"
                assert payload["status"] == "accepted"
                assert payload["robot_id"] == "test-rover-01"
                assert c[1].get("qos", 0) == 1
                return
        pytest.fail("No ACK published to command/ack topic")


class TestCommandCallback:
    """Command messages routed to callback."""

    @patch("mqtt_client.mqtt.Client")
    def test_command_callback_called(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        client.setup()

        received = []
        client.on_command = lambda cmd: received.append(cmd)

        # Simulate message arrival
        msg = MagicMock()
        msg.topic = "tritium/home/robots/test-rover-01/command"
        msg.payload = json.dumps({
            "command": "dispatch",
            "x": 10.0,
            "y": 20.0,
            "timestamp": "2026-02-27T12:00:00Z"
        }).encode()
        client._on_message(mock_instance, None, msg)

        assert len(received) == 1
        assert received[0]["command"] == "dispatch"

    @patch("mqtt_client.mqtt.Client")
    def test_invalid_message_ignored(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        cfg = make_config()
        client = RobotMQTTClient(cfg)
        client.setup()

        received = []
        client.on_command = lambda cmd: received.append(cmd)

        msg = MagicMock()
        msg.topic = "tritium/home/robots/test-rover-01/command"
        msg.payload = b"not json"
        client._on_message(mock_instance, None, msg)

        # Invalid JSON should not crash or call callback
        assert len(received) == 0


class TestTelemetryInterval:
    """Telemetry interval from config."""

    def test_default_interval(self):
        cfg = make_config()
        assert cfg.telemetry_interval == 0.5

    def test_custom_interval(self):
        cfg = make_config(telemetry_interval=1.0)
        assert cfg.telemetry_interval == 1.0
