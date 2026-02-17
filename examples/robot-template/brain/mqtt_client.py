"""MQTT client for robot communication with TRITIUM-SC."""

from __future__ import annotations

import json
import time
from typing import Callable

import paho.mqtt.client as mqtt


class RobotMQTTClient:
    """Handles MQTT connection and message routing for the robot."""

    def __init__(self, config: dict) -> None:
        self._robot_id = config.get("robot_id", "rover-alpha")
        self._site = config.get("site_id", "home")
        mqtt_cfg = config.get("mqtt", {})
        self._broker = mqtt_cfg.get("broker", "localhost")
        self._port = mqtt_cfg.get("port", 1883)
        self._username = mqtt_cfg.get("username", "")
        self._password = mqtt_cfg.get("password", "")

        self._client = mqtt.Client(client_id=f"robot-{self._robot_id}")
        self._connected = False
        self.on_command: Callable[[dict], None] | None = None

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        if self._username:
            self._client.username_pw_set(self._username, self._password)

        # Set Last Will and Testament so broker publishes offline if we drop
        status_topic = f"tritium/{self._site}/robots/{self._robot_id}/status"
        will_payload = json.dumps({
            "status": "offline",
            "robot_id": self._robot_id,
        })
        self._client.will_set(status_topic, will_payload, qos=1, retain=True)

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        try:
            self._client.connect(self._broker, self._port, keepalive=60)
            self._client.loop_start()
            print(f"  MQTT connecting to {self._broker}:{self._port}...")
        except Exception as e:
            print(f"  MQTT connection failed: {e}")

    def disconnect(self) -> None:
        self.publish_status("offline")
        time.sleep(0.1)  # Allow offline message to send
        self._client.loop_stop()
        self._client.disconnect()
        self._connected = False

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            cmd_topic = f"tritium/{self._site}/robots/{self._robot_id}/command"
            client.subscribe(cmd_topic)
            print(f"  MQTT connected. Subscribed to {cmd_topic}")
            # Announce online
            self.publish_status("online")
        else:
            print(f"  MQTT connection refused (rc={rc})")

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False
        if rc != 0:
            print(f"  MQTT disconnected unexpectedly (rc={rc}), will auto-reconnect")

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode())
            if self.on_command:
                self.on_command(payload)
        except Exception as e:
            print(f"  MQTT message error: {e}")

    def publish_telemetry(self, data: dict) -> None:
        topic = f"tritium/{self._site}/robots/{self._robot_id}/telemetry"
        self._publish(topic, data)

    def publish_status(self, status: str) -> None:
        topic = f"tritium/{self._site}/robots/{self._robot_id}/status"
        self._publish(topic, {"status": status, "robot_id": self._robot_id}, qos=1, retain=True)

    def publish_detection(self, detections: list[dict]) -> None:
        """Publish YOLO detections (if camera is running)."""
        topic = f"tritium/{self._site}/cameras/{self._robot_id}/detections"
        self._publish(topic, {"boxes": detections, "camera_id": self._robot_id})

    def publish_command_ack(self, command: str, command_timestamp: str, status: str = "accepted") -> None:
        """Acknowledge a command back to TRITIUM-SC.

        Args:
            command: The command name (dispatch, patrol, recall, etc).
            command_timestamp: The timestamp from the original command message.
            status: "accepted" (will execute), "rejected" (cannot), or "completed".
        """
        topic = f"tritium/{self._site}/robots/{self._robot_id}/command/ack"
        self._publish(topic, {
            "command": command,
            "command_timestamp": command_timestamp,
            "status": status,
            "robot_id": self._robot_id,
        }, qos=1)

    def _publish(self, topic: str, payload: dict, qos: int = 0, retain: bool = False) -> None:
        if not self._connected:
            return
        try:
            from datetime import datetime, timezone
            payload["timestamp"] = datetime.now(timezone.utc).isoformat()
            self._client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
        except Exception:
            pass
