# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MQTT client for the demo motion sensor.

Publishes detection events to tritium/{site}/sensors/{id}/events (QoS 1).
Publishes status to .../status (retained, QoS 1).
Subscribes to .../command for enable/disable.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Callable

import paho.mqtt.client as mqtt

from config import SensorConfig

logger = logging.getLogger(__name__)


class SensorMQTTClient:
    """MQTT client for a motion sensor."""

    def __init__(self, config: SensorConfig):
        self.config = config
        self._prefix = f"tritium/{config.site}/sensors/{config.sensor_id}"

        self.events_topic = f"{self._prefix}/events"
        self.status_topic = f"{self._prefix}/status"
        self.command_topic = f"{self._prefix}/command"

        self.on_command: Callable[[dict], None] | None = None

        # Build MQTT client (use v2 callback API if available)
        client_kwargs = {
            "client_id": f"sensor-{config.sensor_id}",
            "protocol": mqtt.MQTTv311,
        }
        if hasattr(mqtt, "CallbackAPIVersion"):
            client_kwargs["callback_api_version"] = mqtt.CallbackAPIVersion.VERSION1
        self._client = mqtt.Client(**client_kwargs)
        self._client.on_message = self._on_message

        # Set last-will to publish offline status on unexpected disconnect
        will_payload = json.dumps({
            "status": "offline",
            "sensor_id": config.sensor_id,
            "sensor_type": config.sensor_type,
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
        self.publish_status("offline")
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("Disconnected from MQTT broker")

    def publish_event(self, event: dict) -> None:
        """Publish a detection event (QoS 1)."""
        payload = json.dumps(event)
        self._client.publish(self.events_topic, payload, qos=1)
        logger.debug("Published event to %s", self.events_topic)

    def publish_status(self, status: str) -> None:
        """Publish sensor status (retained, QoS 1)."""
        payload = json.dumps({
            "status": status,
            "sensor_id": self.config.sensor_id,
            "sensor_type": self.config.sensor_type,
            "zone": self.config.zone,
            "position": {"x": self.config.position_x, "y": self.config.position_y},
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        self._client.publish(self.status_topic, payload, qos=1, retain=True)
        logger.debug("Published status '%s' to %s", status, self.status_topic)

    def subscribe_commands(self) -> None:
        """Subscribe to the command topic for enable/disable."""
        self._client.subscribe(self.command_topic, qos=1)
        logger.info("Subscribed to %s", self.command_topic)

    def _on_message(self, client, userdata, msg) -> None:
        """Handle incoming MQTT messages (command topic)."""
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Invalid JSON on %s: %s", msg.topic, msg.payload)
            return

        if self.on_command is not None:
            self.on_command(payload)
