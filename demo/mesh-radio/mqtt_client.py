# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MQTT client for the demo mesh radio node.

Publishes position to tritium/{site}/mesh/{protocol}/{id}/position (QoS 0).
Publishes telemetry to .../telemetry (QoS 0).
Publishes text to .../text (QoS 1).
Publishes status to .../status (retained, QoS 1).
Subscribes to .../command for send_text, set_channel, reboot.
Subscribes to .../text for incoming text messages.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Callable

import paho.mqtt.client as mqtt

from config import MeshRadioConfig

logger = logging.getLogger(__name__)


class MeshMQTTClient:
    """MQTT client for a mesh radio node."""

    def __init__(self, config: MeshRadioConfig):
        self.config = config
        self._prefix = (
            f"tritium/{config.site}/mesh/{config.protocol}/{config.node_id}"
        )

        self.position_topic = f"{self._prefix}/position"
        self.telemetry_topic = f"{self._prefix}/telemetry"
        self.text_topic = f"{self._prefix}/text"
        self.status_topic = f"{self._prefix}/status"
        self.command_topic = f"{self._prefix}/command"

        self.on_command: Callable[[dict], None] | None = None
        self.on_text: Callable[[dict], None] | None = None

        # Build MQTT client (use v2 callback API if available)
        client_kwargs = {
            "client_id": f"mesh-{config.node_id}",
            "protocol": mqtt.MQTTv311,
        }
        if hasattr(mqtt, "CallbackAPIVersion"):
            client_kwargs["callback_api_version"] = mqtt.CallbackAPIVersion.VERSION1
        self._client = mqtt.Client(**client_kwargs)
        self._client.on_message = self._on_message

        # Set last-will to publish offline status on unexpected disconnect
        will_payload = json.dumps({
            "status": "offline",
            "node_id": config.node_id,
            "long_name": config.long_name,
            "protocol": config.protocol,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        self._client.will_set(
            self.status_topic,
            will_payload,
            qos=1,
            retain=True,
        )

    def connect(self) -> None:
        """Connect to the MQTT broker."""
        self._client.connect(self.config.mqtt_host, self.config.mqtt_port)
        self._client.loop_start()
        logger.info(
            "Connected to MQTT broker at %s:%d",
            self.config.mqtt_host,
            self.config.mqtt_port,
        )

    def disconnect(self) -> None:
        """Publish offline status and disconnect."""
        self.publish_status({
            "status": "offline",
            "node_id": self.config.node_id,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("Disconnected from MQTT broker")

    def publish_position(self, payload: dict) -> None:
        """Publish a position update (QoS 0)."""
        data = json.dumps(payload)
        self._client.publish(self.position_topic, data, qos=0)
        logger.debug("Published position to %s", self.position_topic)

    def publish_telemetry(self, payload: dict) -> None:
        """Publish a telemetry update (QoS 0)."""
        data = json.dumps(payload)
        self._client.publish(self.telemetry_topic, data, qos=0)
        logger.debug("Published telemetry to %s", self.telemetry_topic)

    def publish_text(self, msg: dict) -> None:
        """Publish a text message (QoS 1)."""
        data = json.dumps(msg)
        self._client.publish(self.text_topic, data, qos=1)
        logger.debug("Published text to %s", self.text_topic)

    def publish_status(self, payload: dict) -> None:
        """Publish node status (retained, QoS 1)."""
        data = json.dumps(payload)
        self._client.publish(self.status_topic, data, qos=1, retain=True)
        logger.debug("Published status to %s", self.status_topic)

    def subscribe_commands(self) -> None:
        """Subscribe to command and text topics."""
        self._client.subscribe(self.command_topic, qos=1)
        self._client.subscribe(self.text_topic, qos=1)
        logger.info("Subscribed to %s and %s", self.command_topic, self.text_topic)

    def _on_message(self, client, userdata, msg) -> None:
        """Handle incoming MQTT messages (command and text topics)."""
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Invalid JSON on %s: %s", msg.topic, msg.payload)
            return

        if msg.topic == self.command_topic:
            if self.on_command is not None:
                self.on_command(payload)
        elif msg.topic == self.text_topic:
            if self.on_text is not None:
                self.on_text(payload)
