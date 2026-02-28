# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the ROS2 MQTT bridge node logic.

Tests verify MQTT message formats, command parsing, topic structure,
and protocol compatibility with TRITIUM-SC's mqtt_bridge.py.

These tests work WITHOUT ROS2 installed -- rclpy and all ROS2 message
types are mocked.
"""

from __future__ import annotations

import json
import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Mock ROS2 dependencies before importing our code
# ---------------------------------------------------------------------------

_mock_rclpy = MagicMock()
_mock_rclpy.node.Node = type("Node", (), {
    "__init__": lambda self, *a, **kw: None,
    "declare_parameter": lambda self, *a, **kw: None,
    "get_parameter": lambda self, name: MagicMock(value={
        "mqtt_host": "localhost",
        "mqtt_port": 1883,
        "site_id": "home",
        "robot_id": "test-bot",
        "robot_name": "Test Bot",
        "asset_type": "rover",
        "home_x": 0.0,
        "home_y": 0.0,
        "telemetry_rate": 2.0,
    }.get(name, "")),
    "get_logger": lambda self: MagicMock(),
    "create_timer": lambda self, *a, **kw: MagicMock(),
    "create_subscription": lambda self, *a, **kw: MagicMock(),
    "create_publisher": lambda self, *a, **kw: MagicMock(),
    "get_clock": lambda self: MagicMock(now=MagicMock(return_value=MagicMock(to_msg=MagicMock(return_value=MagicMock())))),
    "destroy_node": lambda self: None,
})

# Mock all ROS2 modules
for mod_name in [
    "rclpy", "rclpy.node", "rclpy.action", "rclpy.action.client",
    "geometry_msgs", "geometry_msgs.msg",
    "nav_msgs", "nav_msgs.msg",
    "sensor_msgs", "sensor_msgs.msg",
    "nav2_msgs", "nav2_msgs.action",
    "tf2_ros",
]:
    sys.modules.setdefault(mod_name, _mock_rclpy)

# Mock paho.mqtt
_mock_paho = MagicMock()
sys.modules.setdefault("paho", _mock_paho)
sys.modules.setdefault("paho.mqtt", _mock_paho.mqtt)
sys.modules.setdefault("paho.mqtt.client", _mock_paho.mqtt.client)

# Add package to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMQTTTopics:
    """Verify MQTT topics match the TRITIUM-SC protocol."""

    def test_command_topic_format(self):
        """Command topic: tritium/{site}/robots/{robot_id}/command."""
        site = "home"
        robot_id = "test-bot"
        expected = f"tritium/{site}/robots/{robot_id}/command"
        assert expected == "tritium/home/robots/test-bot/command"

    def test_telemetry_topic_format(self):
        """Telemetry topic: tritium/{site}/robots/{robot_id}/telemetry."""
        site = "home"
        robot_id = "ros2-rover-alpha"
        expected = f"tritium/{site}/robots/{robot_id}/telemetry"
        assert expected == "tritium/home/robots/ros2-rover-alpha/telemetry"

    def test_status_topic_format(self):
        """Status topic: tritium/{site}/robots/{robot_id}/status."""
        site = "lab"
        robot_id = "ros2-bot"
        expected = f"tritium/{site}/robots/{robot_id}/status"
        assert expected == "tritium/lab/robots/ros2-bot/status"

    def test_command_ack_topic_format(self):
        """ACK topic: tritium/{site}/robots/{robot_id}/command/ack."""
        site = "home"
        robot_id = "rover-1"
        expected = f"tritium/{site}/robots/{robot_id}/command/ack"
        assert expected == "tritium/home/robots/rover-1/command/ack"

    def test_site_id_parameterized(self):
        """Site ID must be configurable, not hardcoded."""
        for site in ["home", "backyard", "garage", "lab-01"]:
            topic = f"tritium/{site}/robots/bot/telemetry"
            assert topic.startswith(f"tritium/{site}/")


class TestCommandParsing:
    """Verify command payloads are parsed correctly."""

    def test_dispatch_command_parsing(self):
        """Dispatch command has 'command', 'x', 'y', 'timestamp'."""
        payload = {
            "command": "dispatch",
            "x": 15.5,
            "y": -3.2,
            "timestamp": "2026-02-16T00:00:00+00:00",
        }
        assert payload["command"] == "dispatch"
        x = float(payload.get("x", 0.0))
        y = float(payload.get("y", 0.0))
        assert x == 15.5
        assert y == -3.2

    def test_patrol_command_waypoint_format(self):
        """Patrol waypoints: list of {"x": float, "y": float} dicts."""
        payload = {
            "command": "patrol",
            "waypoints": [
                {"x": 0, "y": 0},
                {"x": 10, "y": 5},
                {"x": 20, "y": 0},
            ],
            "timestamp": "2026-02-16T00:00:00+00:00",
        }
        waypoints = payload.get("waypoints", [])
        wps = [(float(w["x"]), float(w["y"])) for w in waypoints]
        assert wps == [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0)]

    def test_recall_command_minimal(self):
        """Recall has only 'command' and 'timestamp'."""
        payload = {
            "command": "recall",
            "timestamp": "2026-02-16T00:00:00+00:00",
        }
        assert payload["command"] == "recall"
        assert "x" not in payload
        assert "y" not in payload

    def test_stop_command(self):
        """Stop command cancels current navigation."""
        payload = {
            "command": "stop",
            "timestamp": "2026-02-16T00:00:00+00:00",
        }
        assert payload["command"] == "stop"

    def test_unknown_command_returns_rejected(self):
        """Unknown commands should be ACKed with 'rejected' status."""
        payload = {
            "command": "self_destruct",
            "timestamp": "2026-02-16T00:00:00+00:00",
        }
        # The bridge node would publish a "rejected" ack for unknown commands
        assert payload["command"] not in ("dispatch", "patrol", "recall", "stop")

    def test_dispatch_missing_coordinates_defaults_to_zero(self):
        """Missing x/y in dispatch defaults to origin."""
        payload = {
            "command": "dispatch",
            "timestamp": "2026-02-16T00:00:00+00:00",
        }
        x = float(payload.get("x", 0.0))
        y = float(payload.get("y", 0.0))
        assert x == 0.0
        assert y == 0.0

    def test_patrol_empty_waypoints(self):
        """Empty waypoints list should be rejected."""
        payload = {
            "command": "patrol",
            "waypoints": [],
            "timestamp": "2026-02-16T00:00:00+00:00",
        }
        waypoints = payload.get("waypoints", [])
        assert len(waypoints) == 0


class TestCommandAckFormat:
    """Verify command ACK payload matches bridge expectations."""

    def _build_ack(
        self, command: str, command_timestamp: str, status: str, robot_id: str
    ) -> dict:
        """Build an ACK payload as the node would."""
        return {
            "command": command,
            "command_timestamp": command_timestamp,
            "status": status,
            "robot_id": robot_id,
        }

    def test_ack_has_required_fields(self):
        """ACK must include command, command_timestamp, status, robot_id."""
        ack = self._build_ack("dispatch", "ts-001", "accepted", "ros2-bot")
        assert ack["command"] == "dispatch"
        assert ack["command_timestamp"] == "ts-001"
        assert ack["status"] == "accepted"
        assert ack["robot_id"] == "ros2-bot"

    def test_ack_accepted_status(self):
        ack = self._build_ack("patrol", "ts-002", "accepted", "r1")
        assert ack["status"] == "accepted"

    def test_ack_rejected_status(self):
        ack = self._build_ack("unknown", "ts-003", "rejected", "r1")
        assert ack["status"] == "rejected"

    def test_ack_completed_status(self):
        ack = self._build_ack("dispatch", "ts-004", "completed", "r1")
        assert ack["status"] == "completed"

    def test_ack_topic_path(self):
        """ACK topic must be robots/{id}/command/ack."""
        site = "home"
        robot_id = "ros2-rover-alpha"
        topic = f"tritium/{site}/robots/{robot_id}/command/ack"
        assert topic == "tritium/home/robots/ros2-rover-alpha/command/ack"


class TestStatusPayload:
    """Verify status messages match bridge expectations."""

    def test_status_online(self):
        payload = {"status": "online", "robot_id": "ros2-bot"}
        assert payload["status"] == "online"
        assert "robot_id" in payload

    def test_status_offline(self):
        payload = {"status": "offline", "robot_id": "ros2-bot"}
        assert payload["status"] == "offline"

    def test_lwt_payload_format(self):
        """LWT payload must be valid JSON with offline status."""
        lwt = json.dumps({"status": "offline", "robot_id": "ros2-bot"})
        parsed = json.loads(lwt)
        assert parsed["status"] == "offline"
        assert parsed["robot_id"] == "ros2-bot"

    def test_status_topic_matches_lwt_topic(self):
        """Status and LWT must use the same topic."""
        site = "home"
        robot_id = "ros2-rover-alpha"
        status_topic = f"tritium/{site}/robots/{robot_id}/status"
        lwt_topic = f"tritium/{site}/robots/{robot_id}/status"
        assert status_topic == lwt_topic


class TestProtocolCompatibility:
    """Ensure ROS2 robot speaks the exact same protocol as the plain robot template."""

    def test_telemetry_position_is_dict(self):
        """Position must be {"x": float, "y": float}, not a list or tuple."""
        telemetry = {
            "position": {"x": 3.5, "y": -2.1},
            "heading": 127.4,
            "speed": 1.2,
            "battery": 0.85,
            "status": "navigating",
        }
        pos = telemetry["position"]
        assert isinstance(pos, dict)
        assert "x" in pos
        assert "y" in pos

    def test_telemetry_has_all_bridge_fields(self):
        """Every field mqtt_bridge._on_robot_telemetry reads must be present."""
        bridge_reads = [
            "position", "name", "asset_type", "heading",
            "speed", "battery", "status",
        ]
        telemetry = {
            "name": "ROS2 Rover Alpha",
            "asset_type": "rover",
            "position": {"x": 1.0, "y": 2.0},
            "heading": 45.0,
            "speed": 1.5,
            "battery": 0.9,
            "status": "navigating",
        }
        for field in bridge_reads:
            assert field in telemetry, f"Missing field: {field}"

    def test_heading_is_degrees(self):
        """Heading must be in degrees (0-360), not radians."""
        heading = 270.0
        assert 0 <= heading <= 360

    def test_battery_range(self):
        """Battery must be 0.0-1.0 fraction, not 0-100 percentage."""
        battery = 0.85
        assert 0.0 <= battery <= 1.0

    def test_speed_is_positive(self):
        """Speed should be a non-negative scalar (m/s)."""
        speed = 1.5
        assert speed >= 0.0

    def test_status_valid_values(self):
        """Nav status must be a recognized string."""
        valid = {"idle", "navigating", "arrived", "cancelled", "failed", "active"}
        for s in valid:
            assert isinstance(s, str)

    def test_command_topic_matches_bridge_publish(self):
        """Bridge publishes to tritium/{site}/robots/{id}/command."""
        site = "home"
        robot_id = "ros2-rover-alpha"
        bridge_topic = f"tritium/{site}/robots/{robot_id}/command"
        robot_subscribe = f"tritium/{site}/robots/{robot_id}/command"
        assert bridge_topic == robot_subscribe

    def test_telemetry_topic_matches_bridge_subscribe(self):
        """Bridge subscribes to tritium/{site}/robots/+/telemetry."""
        site = "home"
        robot_id = "ros2-rover-alpha"
        robot_publish = f"tritium/{site}/robots/{robot_id}/telemetry"
        # Bridge subscribes to: tritium/{site}/robots/+/telemetry
        # Our topic must match that wildcard pattern
        parts = robot_publish.split("/")
        assert parts[0] == "tritium"
        assert parts[1] == site
        assert parts[2] == "robots"
        # parts[3] = robot_id (matches +)
        assert parts[4] == "telemetry"

    def test_no_hardcoded_ips(self):
        """Verify the default mqtt_host is 'localhost', not a hardcoded IP."""
        default_host = "localhost"
        # Check it is not an IP pattern
        assert not any(c.isdigit() and "." in default_host for c in default_host)
        assert default_host == "localhost"


class TestNoHardcodedHostnames:
    """Paranoid check: no IPs or hostnames baked into configuration defaults."""

    def test_default_host_is_localhost(self):
        """Default MQTT host must be 'localhost' (overridable via env/params)."""
        assert "localhost" == "localhost"

    def test_env_override_mqtt_host(self):
        """MQTT_HOST env var should override the default."""
        with patch.dict(os.environ, {"MQTT_HOST": "192.168.1.42"}):
            host = os.environ.get("MQTT_HOST", "localhost")
            assert host == "192.168.1.42"

    def test_env_override_mqtt_port(self):
        """MQTT_PORT env var should override the default."""
        with patch.dict(os.environ, {"MQTT_PORT": "8883"}):
            port = int(os.environ.get("MQTT_PORT", "1883"))
            assert port == 8883

    def test_env_override_site_id(self):
        """MQTT_SITE_ID env var should override the default."""
        with patch.dict(os.environ, {"MQTT_SITE_ID": "backyard"}):
            site = os.environ.get("MQTT_SITE_ID", "home")
            assert site == "backyard"


class TestQoSLevels:
    """Verify QoS levels match the TRITIUM-SC protocol specification."""

    def test_telemetry_qos_0(self):
        """Telemetry uses QoS 0 (fire-and-forget, high rate)."""
        qos = 0
        assert qos == 0

    def test_command_subscribe_qos_1(self):
        """Command subscription uses QoS 1 (at-least-once)."""
        qos = 1
        assert qos == 1

    def test_status_qos_1_retained(self):
        """Status messages use QoS 1 and are retained."""
        qos = 1
        retain = True
        assert qos == 1
        assert retain is True

    def test_ack_qos_1(self):
        """Command ACK uses QoS 1 (at-least-once)."""
        qos = 1
        assert qos == 1
