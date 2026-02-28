# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
MQTT Client for hostile agent -- publishes telemetry/thoughts,
subscribes to elimination and situation updates.
"""

import json

try:
    import paho.mqtt.client as mqtt
    HAS_PAHO = True
    # Support both paho-mqtt v1 and v2
    try:
        _CALLBACK_API = mqtt.CallbackAPIVersion.VERSION1
        _client_kwargs = {"callback_api_version": _CALLBACK_API}
    except AttributeError:
        _client_kwargs = {}
except ImportError:
    HAS_PAHO = False
    _client_kwargs = {}


class HostileMQTTClient:
    """MQTT publisher/subscriber for a hostile agent."""

    def __init__(self, hostile_id: str, mqtt_host: str = "localhost",
                 mqtt_port: int = 1883, site: str = "home"):
        self.hostile_id = hostile_id
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.site = site

        # Topics
        base = f"tritium/{site}/hostiles/{hostile_id}"
        self.telemetry_topic = f"{base}/telemetry"
        self.status_topic = f"{base}/status"
        self.thoughts_topic = f"{base}/thoughts"
        self.elimination_topic = f"tritium/{site}/sim/eliminations"
        self.situation_topic = f"tritium/{site}/sim/situation"

        # Callbacks
        self.on_eliminated = None
        self.on_situation = None

        # MQTT client
        self._client = mqtt.Client(**_client_kwargs)
        self._client.on_message = self._on_message

        # Last will: offline status
        will_payload = json.dumps({"status": "offline", "hostile_id": hostile_id})
        self._client.will_set(self.status_topic, will_payload, qos=1, retain=True)

    def start(self):
        """Connect and subscribe."""
        self._client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
        self._client.subscribe(self.elimination_topic, qos=1)
        self._client.subscribe(self.situation_topic, qos=1)
        self._client.loop_start()

    def stop(self):
        """Disconnect cleanly."""
        self.publish_status("offline")
        self._client.loop_stop()
        self._client.disconnect()

    def publish_telemetry(self, telemetry: dict):
        """Publish telemetry JSON to MQTT."""
        payload = json.dumps(telemetry)
        self._client.publish(self.telemetry_topic, payload, qos=0)

    def publish_status(self, status: str):
        """Publish status (retained)."""
        payload = json.dumps({"status": status, "hostile_id": self.hostile_id})
        self._client.publish(self.status_topic, payload, qos=1, retain=True)

    def publish_thought(self, thought: str):
        """Publish a thought/decision to MQTT (visible in UI)."""
        payload = json.dumps({
            "hostile_id": self.hostile_id,
            "thought": thought,
        })
        self._client.publish(self.thoughts_topic, payload, qos=0)

    def _on_message(self, client, userdata, msg):
        """Handle incoming messages."""
        try:
            data = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        if msg.topic == self.elimination_topic:
            target_id = data.get("target_id")
            if target_id == self.hostile_id and self.on_eliminated:
                self.on_eliminated()

        elif msg.topic == self.situation_topic:
            if self.on_situation:
                self.on_situation(data)
