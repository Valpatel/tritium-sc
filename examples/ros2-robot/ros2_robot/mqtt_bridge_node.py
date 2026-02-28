# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ROS2 <-> TRITIUM-SC MQTT bridge node.

Subscribes to TRITIUM-SC command topics via MQTT, translates them into
Nav2 goals, and publishes telemetry back. This is the central node that
ties a ROS2 robot into the TRITIUM-SC tactical network.

All configuration via ROS2 parameters -- NO hardcoded IPs or hostnames.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import rclpy
from rclpy.node import Node

import paho.mqtt.client as mqtt

from .nav2_client import Nav2Client


class MQTTBridgeNode(Node):
    """ROS2 node that bridges MQTT commands to Nav2 actions."""

    def __init__(self) -> None:
        super().__init__("mqtt_bridge")

        # Declare parameters with defaults -- env vars override
        self.declare_parameter("mqtt_host", os.environ.get("MQTT_HOST", "localhost"))
        self.declare_parameter("mqtt_port", int(os.environ.get("MQTT_PORT", "1883")))
        self.declare_parameter("site_id", os.environ.get("MQTT_SITE_ID", "home"))
        self.declare_parameter("robot_id", "ros2-rover-alpha")
        self.declare_parameter("robot_name", "ROS2 Rover Alpha")
        self.declare_parameter("asset_type", "rover")
        self.declare_parameter("home_x", 0.0)
        self.declare_parameter("home_y", 0.0)

        self._mqtt_host: str = self.get_parameter("mqtt_host").value
        self._mqtt_port: int = self.get_parameter("mqtt_port").value
        self._site: str = self.get_parameter("site_id").value
        self._robot_id: str = self.get_parameter("robot_id").value
        self._robot_name: str = self.get_parameter("robot_name").value
        self._asset_type: str = self.get_parameter("asset_type").value
        self._home_x: float = self.get_parameter("home_x").value
        self._home_y: float = self.get_parameter("home_y").value

        # MQTT client setup
        client_id = f"ros2-{self._robot_id}-{int(time.time()) % 10000}"
        self._mqtt_client = mqtt.Client(client_id=client_id)

        # Set Last Will and Testament
        status_topic = f"tritium/{self._site}/robots/{self._robot_id}/status"
        will_payload = json.dumps({
            "status": "offline",
            "robot_id": self._robot_id,
        })
        self._mqtt_client.will_set(status_topic, will_payload, qos=1, retain=True)

        self._mqtt_client.on_connect = self._on_mqtt_connect
        self._mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self._mqtt_client.on_message = self._on_mqtt_message
        self._mqtt_connected = False

        # Nav2 client for sending goals
        self._nav2 = Nav2Client(self)

        # Connect to MQTT broker
        try:
            self._mqtt_client.connect(self._mqtt_host, self._mqtt_port, keepalive=60)
            self._mqtt_client.loop_start()
            self.get_logger().info(
                f"MQTT connecting to {self._mqtt_host}:{self._mqtt_port}"
            )
        except Exception as e:
            self.get_logger().error(f"MQTT connection failed: {e}")

        # Timer to poll MQTT (paho loop_start handles networking, but we
        # log periodic status)
        self._status_timer = self.create_timer(10.0, self._log_status)

    def destroy_node(self) -> None:
        """Clean shutdown: publish offline, disconnect MQTT."""
        self._publish_status("offline")
        time.sleep(0.1)
        self._mqtt_client.loop_stop()
        self._mqtt_client.disconnect()
        super().destroy_node()

    # --- MQTT callbacks ---

    def _on_mqtt_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        if rc == 0:
            self._mqtt_connected = True
            cmd_topic = f"tritium/{self._site}/robots/{self._robot_id}/command"
            client.subscribe(cmd_topic, qos=1)
            self.get_logger().info(f"MQTT connected. Subscribed to {cmd_topic}")
            self._publish_status("online")
        else:
            self._mqtt_connected = False
            self.get_logger().error(f"MQTT connection refused (rc={rc})")

    def _on_mqtt_disconnect(self, client: Any, userdata: Any, rc: int) -> None:
        self._mqtt_connected = False
        if rc != 0:
            self.get_logger().warn(
                f"MQTT disconnected unexpectedly (rc={rc}), will auto-reconnect"
            )

    def _on_mqtt_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Route incoming MQTT command to the appropriate handler."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.get_logger().warn(f"Bad MQTT payload: {e}")
            return

        command = payload.get("command", "")
        cmd_ts = payload.get("timestamp", "")

        self.get_logger().info(f"Received command: {command}")

        if command == "dispatch":
            self._handle_dispatch(payload, cmd_ts)
        elif command == "patrol":
            self._handle_patrol(payload, cmd_ts)
        elif command == "recall":
            self._handle_recall(payload, cmd_ts)
        elif command == "stop":
            self._handle_stop(payload, cmd_ts)
        else:
            self.get_logger().warn(f"Unknown command: {command}")
            self._publish_command_ack(command, cmd_ts, "rejected")

    # --- Command handlers ---

    def _handle_dispatch(self, payload: dict, cmd_ts: str) -> None:
        """Translate dispatch command to a Nav2 goal."""
        x = float(payload.get("x", 0.0))
        y = float(payload.get("y", 0.0))
        self.get_logger().info(f"Dispatching to ({x:.1f}, {y:.1f})")
        self._nav2.navigate_to(x, y)
        self._publish_command_ack("dispatch", cmd_ts, "accepted")

    def _handle_patrol(self, payload: dict, cmd_ts: str) -> None:
        """Translate patrol command to a Nav2 waypoint sequence."""
        waypoints_raw = payload.get("waypoints", [])
        if not waypoints_raw:
            self._publish_command_ack("patrol", cmd_ts, "rejected")
            return
        waypoints = [(float(w["x"]), float(w["y"])) for w in waypoints_raw]
        self.get_logger().info(f"Patrolling {len(waypoints)} waypoints")
        self._nav2.follow_waypoints(waypoints)
        self._publish_command_ack("patrol", cmd_ts, "accepted")

    def _handle_recall(self, payload: dict, cmd_ts: str) -> None:
        """Navigate back to home position."""
        self.get_logger().info(
            f"Recall to home ({self._home_x:.1f}, {self._home_y:.1f})"
        )
        self._nav2.navigate_to(self._home_x, self._home_y)
        self._publish_command_ack("recall", cmd_ts, "accepted")

    def _handle_stop(self, payload: dict, cmd_ts: str) -> None:
        """Cancel current navigation goal."""
        self.get_logger().info("Stop command received")
        self._nav2.cancel_goal()
        self._publish_command_ack("stop", cmd_ts, "accepted")

    # --- MQTT publishing ---

    def _mqtt_publish(
        self, topic: str, payload: dict, qos: int = 0, retain: bool = False
    ) -> None:
        """Publish a JSON payload to MQTT."""
        if not self._mqtt_connected:
            return
        try:
            payload["timestamp"] = datetime.now(timezone.utc).isoformat()
            self._mqtt_client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
        except Exception as e:
            self.get_logger().debug(f"MQTT publish error: {e}")

    def _publish_status(self, status: str) -> None:
        topic = f"tritium/{self._site}/robots/{self._robot_id}/status"
        self._mqtt_publish(
            topic,
            {"status": status, "robot_id": self._robot_id},
            qos=1,
            retain=True,
        )

    def _publish_command_ack(
        self, command: str, command_timestamp: str, status: str
    ) -> None:
        """Acknowledge a command back to TRITIUM-SC."""
        topic = f"tritium/{self._site}/robots/{self._robot_id}/command/ack"
        self._mqtt_publish(
            topic,
            {
                "command": command,
                "command_timestamp": command_timestamp,
                "status": status,
                "robot_id": self._robot_id,
            },
            qos=1,
        )

    def publish_telemetry(self, telemetry: dict) -> None:
        """Publish telemetry data to MQTT. Called by TelemetryNode."""
        topic = f"tritium/{self._site}/robots/{self._robot_id}/telemetry"
        # Inject robot identity fields
        telemetry["name"] = self._robot_name
        telemetry["asset_type"] = self._asset_type
        self._mqtt_publish(topic, telemetry, qos=0)

    # --- Status ---

    @property
    def nav2_status(self) -> str:
        """Current Nav2 navigation status."""
        return self._nav2.status

    def _log_status(self) -> None:
        """Periodic status log."""
        mqtt_status = "connected" if self._mqtt_connected else "disconnected"
        nav_status = self._nav2.status
        self.get_logger().info(
            f"[{self._robot_id}] MQTT: {mqtt_status}, Nav: {nav_status}"
        )


def main(args=None):
    rclpy.init(args=args)
    node = MQTTBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
