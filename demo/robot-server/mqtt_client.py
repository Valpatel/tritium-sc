# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MQTT client for the demo robot server.

Publishes telemetry, status, ACKs, thoughts.
Subscribes to command topic.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Callable

import paho.mqtt.client as mqtt
try:
    from paho.mqtt.client import CallbackAPIVersion
    _PAHO_V2 = True
except ImportError:
    _PAHO_V2 = False

from config import RobotConfig

logger = logging.getLogger(__name__)

# Valid command names
VALID_COMMANDS = {"dispatch", "patrol", "recall", "fire", "aim", "stop"}


def parse_command(raw: str | bytes) -> dict | None:
    """Parse a command message from raw JSON string or bytes.

    Returns parsed dict if valid command, None if invalid.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if "command" not in data:
        return None
    return data


def build_ack(
    command: str,
    command_timestamp: str,
    status: str,
    robot_id: str,
) -> dict:
    """Build an ACK message dict matching the spec format."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "command": command,
        "command_timestamp": command_timestamp,
        "status": status,
        "robot_id": robot_id,
        "timestamp": now,
    }


class RobotMQTTClient:
    """MQTT client for robot telemetry, commands, and status."""

    def __init__(self, config: RobotConfig):
        self._config = config
        self._client: mqtt.Client | None = None

        # Build topic paths
        prefix = f"tritium/{config.site}/robots/{config.robot_id}"
        self.telemetry_topic = f"{prefix}/telemetry"
        self.status_topic = f"{prefix}/status"
        self.command_topic = f"{prefix}/command"
        self.ack_topic = f"{prefix}/command/ack"
        self.thoughts_topic = f"{prefix}/thoughts"

        # Command callback
        self.on_command: Callable[[dict], None] | None = None

    def setup(self) -> None:
        """Create MQTT client, configure LWT, set callbacks."""
        client_id = f"robot-{self._config.robot_id}"
        if _PAHO_V2:
            self._client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION1,
                client_id=client_id,
            )
        else:
            self._client = mqtt.Client(client_id=client_id)

        # Set Last Will and Testament (offline status)
        lwt_payload = json.dumps({"status": "offline"})
        self._client.will_set(
            self.status_topic,
            lwt_payload,
            qos=1,
            retain=True,
        )

        # Set callbacks
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def connect(self) -> None:
        """Connect to MQTT broker."""
        if self._client is None:
            self.setup()
        self._client.connect(self._config.mqtt_host, self._config.mqtt_port)
        self._client.loop_start()

    def disconnect(self) -> None:
        """Publish offline status and disconnect."""
        if self._client is not None:
            self.publish_status("offline")
            self._client.loop_stop()
            self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc) -> None:
        """Handle MQTT connection established."""
        if rc == 0:
            logger.info("Connected to MQTT broker")
            # Subscribe to command topic
            client.subscribe(self.command_topic, qos=1)
            # Publish online status
            self.publish_status("online")
        else:
            logger.error(f"MQTT connection failed with code {rc}")

    def _on_message(self, client, userdata, msg) -> None:
        """Handle incoming MQTT messages."""
        if msg.topic == self.command_topic:
            cmd = parse_command(msg.payload)
            if cmd is not None and self.on_command is not None:
                self.on_command(cmd)

    def publish_telemetry(self, telemetry: dict) -> None:
        """Publish telemetry data (QoS 0)."""
        if self._client is None:
            return
        payload = json.dumps(telemetry)
        self._client.publish(self.telemetry_topic, payload, qos=0)

    def publish_status(self, status: str) -> None:
        """Publish status (online/offline) with retain flag (QoS 1)."""
        if self._client is None:
            return
        payload = json.dumps({"status": status})
        self._client.publish(self.status_topic, payload, qos=1, retain=True)

    def publish_ack(self, command: str, command_timestamp: str, status: str) -> None:
        """Publish command acknowledgement (QoS 1)."""
        if self._client is None:
            return
        ack = build_ack(command, command_timestamp, status, self._config.robot_id)
        payload = json.dumps(ack)
        self._client.publish(self.ack_topic, payload, qos=1)

    def publish_thought(self, thought: str) -> None:
        """Publish robot thought text (QoS 0)."""
        if self._client is None:
            return
        payload = json.dumps({"thought": thought, "robot_id": self._config.robot_id})
        self._client.publish(self.thoughts_topic, payload, qos=0)
