# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MQTT client for publishing detections, status, and subscribing to commands.

Topics:
  - tritium/{site}/cameras/{id}/detections  (OUT, QoS 0)
  - tritium/{site}/cameras/{id}/status      (OUT, QoS 1, retained)
  - tritium/{site}/cameras/{id}/command     (IN, QoS 1)
"""
import json
import logging

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)


class MQTTPublisher:
    """MQTT client for the demo camera server."""

    def __init__(
        self,
        camera_id: str = "demo-cam-01",
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        site: str = "home",
    ):
        self.camera_id = camera_id
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.site = site

        # Topic strings
        prefix = f"tritium/{site}/cameras/{camera_id}"
        self.detection_topic = f"{prefix}/detections"
        self.status_topic = f"{prefix}/status"
        self.command_topic = f"{prefix}/command"

        # Command handler callback -- set externally if desired
        self.on_command = None

        # Create MQTT client
        self._client = mqtt.Client()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        # Set Last Will and Testament (offline status)
        offline_payload = json.dumps({"status": "offline"})
        self._client.will_set(
            self.status_topic,
            offline_payload,
            qos=1,
            retain=True,
        )

    def connect(self) -> None:
        """Connect to MQTT broker and subscribe to command topic."""
        try:
            self._client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
            self._client.subscribe(self.command_topic, qos=1)
            self._client.loop_start()
            log.info("MQTT connected to %s:%d", self.mqtt_host, self.mqtt_port)
        except Exception as e:
            log.warning("MQTT connect failed: %s", e)

    def disconnect(self) -> None:
        """Publish offline status and disconnect."""
        self.publish_status("offline")
        self._client.loop_stop()
        self._client.disconnect()

    def publish_detection(self, detection: dict) -> None:
        """Publish a detection payload (QoS 0, not retained)."""
        payload = json.dumps(detection)
        self._client.publish(
            self.detection_topic,
            payload,
            qos=0,
            retain=False,
        )

    def publish_status(self, status: str) -> None:
        """Publish camera status (QoS 1, retained).

        Args:
            status: "online" or "offline"
        """
        payload = json.dumps({"status": status})
        self._client.publish(
            self.status_topic,
            payload,
            qos=1,
            retain=True,
        )

    def _on_connect(self, client, userdata, flags, rc):
        """Re-subscribe on reconnect."""
        if rc == 0:
            log.info("MQTT connected (rc=%d)", rc)
            client.subscribe(self.command_topic, qos=1)
        else:
            log.warning("MQTT connect returned rc=%d", rc)

    def _on_message(self, client, userdata, msg):
        """Handle incoming command messages."""
        try:
            payload = json.loads(msg.payload.decode())
            log.info("Command received: %s", payload)
            if self.on_command:
                self.on_command(payload)
        except Exception as e:
            log.warning("Failed to parse command: %s", e)
