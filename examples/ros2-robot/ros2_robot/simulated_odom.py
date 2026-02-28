# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Simulated odometry publisher for testing without hardware.

Subscribes to /cmd_vel, simulates position updates using a simple
kinematic model, and publishes /odom at 10 Hz. Also publishes a
simulated /battery_state that slowly drains.

Use this node when testing the ROS2 robot template without a real robot
or Gazebo. It provides enough realism to verify the MQTT bridge and
telemetry pipeline.
"""

from __future__ import annotations

import math
import time

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState
from tf2_ros import TransformBroadcaster


class SimulatedOdom(Node):
    """Fake odometry for testing: accepts /cmd_vel, publishes /odom."""

    def __init__(self) -> None:
        super().__init__("simulated_odom")

        # State
        self._x: float = 0.0
        self._y: float = 0.0
        self._theta: float = 0.0  # radians
        self._vx: float = 0.0
        self._vz: float = 0.0  # angular
        self._battery: float = 1.0
        self._last_time: float = time.monotonic()

        # Publishers
        self._odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self._battery_pub = self.create_publisher(BatteryState, "/battery_state", 10)
        self._tf_broadcaster = TransformBroadcaster(self)

        # Subscribers
        self._cmd_vel_sub = self.create_subscription(
            Twist, "/cmd_vel", self._cmd_vel_cb, 10
        )

        # 10 Hz update loop
        self._timer = self.create_timer(0.1, self._update)

        self.get_logger().info("Simulated odometry active (10 Hz)")

    def _cmd_vel_cb(self, msg: Twist) -> None:
        """Receive velocity command."""
        self._vx = msg.linear.x
        self._vz = msg.angular.z

    def _update(self) -> None:
        """Integrate velocity and publish odometry."""
        now = time.monotonic()
        dt = now - self._last_time
        self._last_time = now

        # Simple kinematic integration
        self._theta += self._vz * dt
        self._x += self._vx * math.cos(self._theta) * dt
        self._y += self._vx * math.sin(self._theta) * dt

        # Battery drain (slow: ~1% per minute when moving)
        if abs(self._vx) > 0.01 or abs(self._vz) > 0.01:
            self._battery = max(0.0, self._battery - 0.00017 * dt)

        # Publish odometry
        odom = Odometry()
        odom.header.stamp = self.get_clock().now().to_msg()
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_link"
        odom.pose.pose.position.x = self._x
        odom.pose.pose.position.y = self._y
        odom.pose.pose.position.z = 0.0
        odom.pose.pose.orientation.z = math.sin(self._theta / 2.0)
        odom.pose.pose.orientation.w = math.cos(self._theta / 2.0)
        odom.twist.twist.linear.x = self._vx
        odom.twist.twist.angular.z = self._vz
        self._odom_pub.publish(odom)

        # Publish TF: odom -> base_link
        tf = TransformStamped()
        tf.header.stamp = odom.header.stamp
        tf.header.frame_id = "odom"
        tf.child_frame_id = "base_link"
        tf.transform.translation.x = self._x
        tf.transform.translation.y = self._y
        tf.transform.translation.z = 0.0
        tf.transform.rotation.z = odom.pose.pose.orientation.z
        tf.transform.rotation.w = odom.pose.pose.orientation.w
        self._tf_broadcaster.sendTransform(tf)

        # Publish battery state (1 Hz, not 10 Hz)
        # Use a simple counter to reduce publish rate
        if not hasattr(self, "_battery_counter"):
            self._battery_counter = 0
        self._battery_counter += 1
        if self._battery_counter >= 10:
            self._battery_counter = 0
            bat = BatteryState()
            bat.header.stamp = odom.header.stamp
            bat.percentage = self._battery
            bat.voltage = 12.0 * self._battery
            bat.present = True
            self._battery_pub.publish(bat)


def main(args=None):
    rclpy.init(args=args)
    node = SimulatedOdom()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
