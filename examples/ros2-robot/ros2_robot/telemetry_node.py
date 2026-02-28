# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Telemetry publisher node for ROS2 robot.

Subscribes to standard ROS2 topics (/odom, /battery_state, /joint_states)
and publishes consolidated telemetry to TRITIUM-SC via MQTT at a
configurable rate.

Telemetry format matches the TRITIUM-SC protocol:
    {
        "name": "ROS2 Rover Alpha",
        "asset_type": "rover",
        "position": {"x": 3.5, "y": -2.1},
        "heading": 127.4,
        "speed": 1.2,
        "battery": 0.85,
        "status": "navigating",
        "timestamp": "2026-02-16T12:00:00+00:00"
    }
"""

from __future__ import annotations

import math
import os
from typing import TYPE_CHECKING

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState, JointState

if TYPE_CHECKING:
    from .mqtt_bridge_node import MQTTBridgeNode


class TelemetryNode(Node):
    """Subscribes to ROS2 topics and publishes telemetry to MQTT."""

    def __init__(self) -> None:
        super().__init__("telemetry_publisher")

        # Parameters
        self.declare_parameter("telemetry_rate", 2.0)
        self.declare_parameter("robot_id", "ros2-rover-alpha")
        self.declare_parameter("mqtt_host", os.environ.get("MQTT_HOST", "localhost"))
        self.declare_parameter("mqtt_port", int(os.environ.get("MQTT_PORT", "1883")))
        self.declare_parameter("site_id", os.environ.get("MQTT_SITE_ID", "home"))
        self.declare_parameter("robot_name", "ROS2 Rover Alpha")
        self.declare_parameter("asset_type", "rover")

        self._rate = self.get_parameter("telemetry_rate").value

        # Current state (updated by subscriptions)
        self._x: float = 0.0
        self._y: float = 0.0
        self._heading: float = 0.0
        self._speed: float = 0.0
        self._battery: float = 1.0
        self._joint_positions: dict[str, float] = {}

        # Reference to bridge node for publishing (set externally via launch)
        self._bridge_node: MQTTBridgeNode | None = None

        # Subscribe to standard ROS2 topics
        self._odom_sub = self.create_subscription(
            Odometry, "/odom", self._odom_cb, 10
        )
        self._battery_sub = self.create_subscription(
            BatteryState, "/battery_state", self._battery_cb, 10
        )
        self._joint_sub = self.create_subscription(
            JointState, "/joint_states", self._joint_cb, 10
        )

        # Publish timer
        period = 1.0 / max(self._rate, 0.1)
        self._timer = self.create_timer(period, self._publish_telemetry)

        self.get_logger().info(f"Telemetry publisher at {self._rate} Hz")

    def set_bridge(self, bridge: MQTTBridgeNode) -> None:
        """Set the MQTT bridge node for publishing telemetry."""
        self._bridge_node = bridge

    # --- ROS2 subscription callbacks ---

    def _odom_cb(self, msg: Odometry) -> None:
        """Update position, heading, speed from odometry."""
        self._x = msg.pose.pose.position.x
        self._y = msg.pose.pose.position.y

        # Extract yaw from quaternion
        q = msg.pose.pose.orientation
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        self._heading = math.degrees(math.atan2(siny_cosp, cosy_cosp)) % 360.0

        # Speed from twist
        vx = msg.twist.twist.linear.x
        vy = msg.twist.twist.linear.y
        self._speed = math.hypot(vx, vy)

    def _battery_cb(self, msg: BatteryState) -> None:
        """Update battery percentage (0.0 - 1.0)."""
        self._battery = max(0.0, min(1.0, msg.percentage))

    def _joint_cb(self, msg: JointState) -> None:
        """Update joint positions (for turret pan/tilt reporting)."""
        for name, pos in zip(msg.name, msg.position):
            self._joint_positions[name] = pos

    # --- Telemetry publishing ---

    @property
    def x(self) -> float:
        return self._x

    @property
    def y(self) -> float:
        return self._y

    @property
    def heading(self) -> float:
        return self._heading

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def battery(self) -> float:
        return self._battery

    def build_telemetry(self) -> dict:
        """Build the telemetry payload matching TRITIUM-SC protocol."""
        nav_status = "idle"
        if self._bridge_node is not None:
            nav_status = self._bridge_node.nav2_status

        return {
            "position": {"x": round(self._x, 3), "y": round(self._y, 3)},
            "heading": round(self._heading, 1),
            "speed": round(self._speed, 3),
            "battery": round(self._battery, 3),
            "status": nav_status,
        }

    def _publish_telemetry(self) -> None:
        """Publish current telemetry to MQTT via bridge node."""
        if self._bridge_node is None:
            return

        telemetry = self.build_telemetry()
        self._bridge_node.publish_telemetry(telemetry)


def main(args=None):
    rclpy.init(args=args)
    node = TelemetryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
