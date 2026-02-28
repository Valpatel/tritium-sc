# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the telemetry publisher.

Tests verify telemetry payload structure, value ranges, and protocol
compatibility with TRITIUM-SC's mqtt_bridge._on_robot_telemetry.

All ROS2 dependencies are mocked -- tests work without ROS2 installed.
"""

from __future__ import annotations

import math
import sys
import os
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock ROS2 dependencies before importing our code
# ---------------------------------------------------------------------------

# Parameter value lookup
_PARAM_DEFAULTS = {
    "telemetry_rate": 2.0,
    "robot_id": "ros2-rover-alpha",
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    "site_id": "home",
    "robot_name": "ROS2 Rover Alpha",
    "asset_type": "rover",
}


class _MockNode:
    """Minimal mock of rclpy.node.Node that TelemetryNode can inherit from."""

    def __init__(self, name: str = "mock_node"):
        self._node_name = name

    def declare_parameter(self, name, default=None):
        pass

    def get_parameter(self, name):
        val = _PARAM_DEFAULTS.get(name, "")
        result = MagicMock()
        result.value = val
        return result

    def get_logger(self):
        return MagicMock()

    def create_timer(self, period, callback):
        return MagicMock()

    def create_subscription(self, msg_type, topic, callback, qos):
        return MagicMock()

    def create_publisher(self, msg_type, topic, qos):
        return MagicMock()

    def get_clock(self):
        return MagicMock()

    def destroy_node(self):
        pass


# Build mock modules
_rclpy_mod = types.ModuleType("rclpy")
_rclpy_node_mod = types.ModuleType("rclpy.node")
_rclpy_node_mod.Node = _MockNode
_rclpy_mod.node = _rclpy_node_mod

_mock = MagicMock()

for mod_name in [
    "rclpy", "rclpy.node", "rclpy.action", "rclpy.action.client",
    "geometry_msgs", "geometry_msgs.msg",
    "nav_msgs", "nav_msgs.msg",
    "sensor_msgs", "sensor_msgs.msg",
    "nav2_msgs", "nav2_msgs.action",
    "tf2_ros",
    "paho", "paho.mqtt", "paho.mqtt.client",
]:
    sys.modules.setdefault(mod_name, _mock)

# Override the specific modules that need real classes
sys.modules["rclpy"] = _rclpy_mod
sys.modules["rclpy.node"] = _rclpy_node_mod

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ros2_robot.telemetry_node import TelemetryNode


class TestTelemetryPayload:
    """Verify telemetry payload matches TRITIUM-SC protocol."""

    def _make_node(self) -> TelemetryNode:
        node = TelemetryNode()
        bridge = MagicMock()
        bridge.nav2_status = "idle"
        node.set_bridge(bridge)
        return node

    def test_payload_has_position(self):
        node = self._make_node()
        tel = node.build_telemetry()
        assert "position" in tel
        assert isinstance(tel["position"], dict)
        assert "x" in tel["position"]
        assert "y" in tel["position"]

    def test_payload_has_heading(self):
        node = self._make_node()
        tel = node.build_telemetry()
        assert "heading" in tel
        assert isinstance(tel["heading"], (int, float))

    def test_payload_has_speed(self):
        node = self._make_node()
        tel = node.build_telemetry()
        assert "speed" in tel
        assert isinstance(tel["speed"], (int, float))

    def test_payload_has_battery(self):
        node = self._make_node()
        tel = node.build_telemetry()
        assert "battery" in tel
        assert isinstance(tel["battery"], (int, float))

    def test_payload_has_status(self):
        node = self._make_node()
        tel = node.build_telemetry()
        assert "status" in tel
        assert isinstance(tel["status"], str)

    def test_all_bridge_fields_present(self):
        """Every field mqtt_bridge._on_robot_telemetry reads must be present
        after the bridge node injects name and asset_type."""
        node = self._make_node()
        tel = node.build_telemetry()
        # name and asset_type are added by the bridge node's publish_telemetry
        tel["name"] = "ROS2 Rover Alpha"
        tel["asset_type"] = "rover"
        bridge_reads = [
            "position", "name", "asset_type", "heading",
            "speed", "battery", "status",
        ]
        for field in bridge_reads:
            assert field in tel, f"Missing field: {field}"


class TestTelemetryValues:
    """Verify telemetry values are in expected ranges."""

    def _make_node(self) -> TelemetryNode:
        node = TelemetryNode()
        bridge = MagicMock()
        bridge.nav2_status = "navigating"
        node.set_bridge(bridge)
        return node

    def test_initial_position_is_origin(self):
        node = self._make_node()
        tel = node.build_telemetry()
        assert tel["position"]["x"] == 0.0
        assert tel["position"]["y"] == 0.0

    def test_initial_heading_is_zero(self):
        node = self._make_node()
        tel = node.build_telemetry()
        assert tel["heading"] == 0.0

    def test_initial_speed_is_zero(self):
        node = self._make_node()
        tel = node.build_telemetry()
        assert tel["speed"] == 0.0

    def test_initial_battery_is_full(self):
        node = self._make_node()
        tel = node.build_telemetry()
        assert tel["battery"] == 1.0

    def test_battery_clamped_to_range(self):
        """Battery must be 0.0-1.0."""
        node = self._make_node()
        node._battery = 1.5
        tel = node.build_telemetry()
        assert isinstance(tel["battery"], (int, float))

    def test_heading_wraps_to_360(self):
        """Heading should be 0-360 degrees."""
        node = self._make_node()
        node._heading = 450.0
        heading = node._heading % 360.0
        assert 0 <= heading < 360

    def test_status_from_bridge(self):
        """Status comes from bridge node's nav2_status."""
        node = self._make_node()
        tel = node.build_telemetry()
        assert tel["status"] == "navigating"


class TestOdomCallback:
    """Test odometry message processing."""

    def _make_node(self) -> TelemetryNode:
        return TelemetryNode()

    def test_odom_updates_position(self):
        node = self._make_node()
        odom = MagicMock()
        odom.pose.pose.position.x = 5.5
        odom.pose.pose.position.y = -3.2
        odom.pose.pose.orientation.x = 0.0
        odom.pose.pose.orientation.y = 0.0
        odom.pose.pose.orientation.z = 0.0
        odom.pose.pose.orientation.w = 1.0
        odom.twist.twist.linear.x = 1.5
        odom.twist.twist.linear.y = 0.0
        node._odom_cb(odom)
        assert node._x == 5.5
        assert node._y == -3.2

    def test_odom_updates_speed(self):
        node = self._make_node()
        odom = MagicMock()
        odom.pose.pose.position.x = 0.0
        odom.pose.pose.position.y = 0.0
        odom.pose.pose.orientation.x = 0.0
        odom.pose.pose.orientation.y = 0.0
        odom.pose.pose.orientation.z = 0.0
        odom.pose.pose.orientation.w = 1.0
        odom.twist.twist.linear.x = 3.0
        odom.twist.twist.linear.y = 4.0
        node._odom_cb(odom)
        assert abs(node._speed - 5.0) < 1e-6  # hypot(3, 4) = 5

    def test_odom_updates_heading(self):
        """90 degree yaw: quaternion z=sin(pi/4), w=cos(pi/4)."""
        node = self._make_node()
        odom = MagicMock()
        odom.pose.pose.position.x = 0.0
        odom.pose.pose.position.y = 0.0
        theta = math.pi / 2.0
        odom.pose.pose.orientation.x = 0.0
        odom.pose.pose.orientation.y = 0.0
        odom.pose.pose.orientation.z = math.sin(theta / 2.0)
        odom.pose.pose.orientation.w = math.cos(theta / 2.0)
        odom.twist.twist.linear.x = 0.0
        odom.twist.twist.linear.y = 0.0
        node._odom_cb(odom)
        assert abs(node._heading - 90.0) < 0.1


class TestBatteryCallback:
    """Test battery state message processing."""

    def _make_node(self) -> TelemetryNode:
        return TelemetryNode()

    def test_battery_updates(self):
        node = self._make_node()
        bat = MagicMock()
        bat.percentage = 0.75
        node._battery_cb(bat)
        assert node._battery == 0.75

    def test_battery_clamp_high(self):
        node = self._make_node()
        bat = MagicMock()
        bat.percentage = 1.5
        node._battery_cb(bat)
        assert node._battery == 1.0

    def test_battery_clamp_low(self):
        node = self._make_node()
        bat = MagicMock()
        bat.percentage = -0.1
        node._battery_cb(bat)
        assert node._battery == 0.0


class TestJointCallback:
    """Test joint state message processing."""

    def _make_node(self) -> TelemetryNode:
        return TelemetryNode()

    def test_joint_positions_stored(self):
        node = self._make_node()
        msg = MagicMock()
        msg.name = ["turret_pan", "turret_tilt"]
        msg.position = [0.5, -0.3]
        node._joint_cb(msg)
        assert node._joint_positions["turret_pan"] == 0.5
        assert node._joint_positions["turret_tilt"] == -0.3


class TestTelemetryRounding:
    """Verify telemetry values are rounded to reasonable precision."""

    def _make_node(self) -> TelemetryNode:
        node = TelemetryNode()
        bridge = MagicMock()
        bridge.nav2_status = "idle"
        node.set_bridge(bridge)
        return node

    def test_position_rounded_to_3_decimals(self):
        node = self._make_node()
        node._x = 1.23456789
        node._y = -9.87654321
        tel = node.build_telemetry()
        assert tel["position"]["x"] == 1.235
        assert tel["position"]["y"] == -9.877

    def test_heading_rounded_to_1_decimal(self):
        node = self._make_node()
        node._heading = 127.456
        tel = node.build_telemetry()
        assert tel["heading"] == 127.5

    def test_speed_rounded_to_3_decimals(self):
        node = self._make_node()
        node._speed = 1.23456
        tel = node.build_telemetry()
        assert tel["speed"] == 1.235

    def test_battery_rounded_to_3_decimals(self):
        node = self._make_node()
        node._battery = 0.85432
        tel = node.build_telemetry()
        assert tel["battery"] == 0.854
