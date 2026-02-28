# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MQTT client for swarm drone -- pub/sub telemetry, commands, eliminations."""

import json
import logging
from typing import Callable

import paho.mqtt.client as mqtt

try:
    from paho.mqtt.client import CallbackAPIVersion
    _PAHO_V2 = True
except ImportError:
    _PAHO_V2 = False

logger = logging.getLogger(__name__)


def parse_command(raw: str | bytes) -> dict | None:
    """Parse a command message from raw JSON. Returns dict or None."""
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


def _parse_json(raw: bytes) -> dict | None:
    """Parse JSON bytes into a dict, or None on failure."""
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


class DroneMQTTClient:
    """MQTT client for a single swarm drone."""

    def __init__(
        self,
        drone_id: str,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        site: str = "home",
    ):
        self.drone_id = drone_id
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.site = site
        self._client: mqtt.Client | None = None

        # Build topic paths
        prefix = f"tritium/{site}/robots/{drone_id}"
        self.telemetry_topic = f"{prefix}/telemetry"
        self.status_topic = f"{prefix}/status"
        self.command_topic = f"{prefix}/command"
        self.eliminations_topic = f"tritium/{site}/sim/eliminations"

        # Callbacks
        self.on_command: Callable[[dict], None] | None = None
        self.on_elimination: Callable[[dict], None] | None = None

    def setup(self) -> None:
        """Create MQTT client, configure LWT, set callbacks."""
        client_id = f"drone-{self.drone_id}"
        if _PAHO_V2:
            self._client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION1,
                client_id=client_id,
            )
        else:
            self._client = mqtt.Client(client_id=client_id)

        # Last Will and Testament
        lwt_payload = json.dumps({"status": "offline"})
        self._client.will_set(
            self.status_topic,
            lwt_payload,
            qos=1,
            retain=True,
        )

        # Callbacks
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def connect(self) -> None:
        """Connect to MQTT broker."""
        if self._client is None:
            self.setup()
        self._client.connect(self.mqtt_host, self.mqtt_port)
        self._client.loop_start()

    def disconnect(self) -> None:
        """Publish offline status and disconnect."""
        if self._client is not None:
            self.publish_status("offline")
            self._client.loop_stop()
            self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc) -> None:
        """Handle MQTT connection."""
        if rc == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe(self.command_topic, qos=1)
            client.subscribe(self.eliminations_topic, qos=1)
            self.publish_status("online")
        else:
            logger.error(f"MQTT connection failed with code {rc}")

    def _on_message(self, client, userdata, msg) -> None:
        """Route incoming messages to callbacks."""
        if msg.topic == self.command_topic:
            cmd = parse_command(msg.payload)
            if cmd is not None and self.on_command is not None:
                self.on_command(cmd)
        elif msg.topic == self.eliminations_topic:
            data = _parse_json(msg.payload)
            if data is not None and self.on_elimination is not None:
                self.on_elimination(data)

    def publish_telemetry(self, telemetry: dict) -> None:
        """Publish telemetry data (QoS 0)."""
        if self._client is None:
            return
        payload = json.dumps(telemetry)
        self._client.publish(self.telemetry_topic, payload, qos=0)

    def publish_status(self, status: str) -> None:
        """Publish status with retain + QoS 1."""
        if self._client is None:
            return
        payload = json.dumps({"status": status})
        self._client.publish(self.status_topic, payload, qos=1, retain=True)
