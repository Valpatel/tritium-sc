# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for MQTT client for mesh radio node.

TDD: written BEFORE implementation.
Tests MQTT topic construction, publish payloads, command handling.
Uses mock MQTT client to avoid needing a real broker.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mqtt_client import MeshMQTTClient
from config import MeshRadioConfig


class TestMQTTTopics(unittest.TestCase):
    """Test MQTT topic construction matches spec.

    Topics follow: tritium/{site}/mesh/{protocol}/{id}/position, /telemetry, /text, /status
    """

    def _make_client(self, **overrides):
        defaults = dict(
            node_id="!aabbccdd",
            long_name="Hilltop Node",
            protocol="meshtastic",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
        )
        defaults.update(overrides)
        config = MeshRadioConfig(**defaults)
        return MeshMQTTClient(config)

    def test_position_topic(self):
        c = self._make_client()
        self.assertEqual(
            c.position_topic,
            "tritium/home/mesh/meshtastic/!aabbccdd/position",
        )

    def test_telemetry_topic(self):
        c = self._make_client()
        self.assertEqual(
            c.telemetry_topic,
            "tritium/home/mesh/meshtastic/!aabbccdd/telemetry",
        )

    def test_text_topic(self):
        c = self._make_client()
        self.assertEqual(
            c.text_topic,
            "tritium/home/mesh/meshtastic/!aabbccdd/text",
        )

    def test_status_topic(self):
        c = self._make_client()
        self.assertEqual(
            c.status_topic,
            "tritium/home/mesh/meshtastic/!aabbccdd/status",
        )

    def test_command_topic(self):
        c = self._make_client()
        self.assertEqual(
            c.command_topic,
            "tritium/home/mesh/meshtastic/!aabbccdd/command",
        )

    def test_meshcore_protocol_in_topic(self):
        c = self._make_client(protocol="meshcore")
        self.assertEqual(
            c.position_topic,
            "tritium/home/mesh/meshcore/!aabbccdd/position",
        )

    def test_custom_site_in_topic(self):
        c = self._make_client(site="campus")
        self.assertEqual(
            c.position_topic,
            "tritium/campus/mesh/meshtastic/!aabbccdd/position",
        )

    def test_custom_node_id_in_topic(self):
        c = self._make_client(node_id="!11223344")
        self.assertEqual(
            c.position_topic,
            "tritium/home/mesh/meshtastic/!11223344/position",
        )


class TestMQTTPublish(unittest.TestCase):
    """Test MQTT message publishing."""

    def _make_client(self, **overrides):
        defaults = dict(
            node_id="!aabbccdd",
            long_name="Hilltop Node",
            protocol="meshtastic",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
        )
        defaults.update(overrides)
        config = MeshRadioConfig(**defaults)
        client = MeshMQTTClient(config)
        client._client = MagicMock()
        return client

    def test_publish_position(self):
        c = self._make_client()
        payload = {
            "node_id": "!aabbccdd",
            "long_name": "Hilltop Node",
            "short_name": "HT01",
            "protocol": "meshtastic",
            "position": {"lat": 37.7749, "lng": -122.4194, "alt": 15.0},
            "battery": 0.72,
            "voltage": 3.85,
            "snr": 8.5,
            "rssi": -95,
            "hops": 1,
            "hardware": "heltec_v3",
            "timestamp": "2026-02-27T12:00:00Z",
        }
        c.publish_position(payload)
        c._client.publish.assert_called_once()
        args, kwargs = c._client.publish.call_args
        self.assertEqual(args[0], "tritium/home/mesh/meshtastic/!aabbccdd/position")
        parsed = json.loads(args[1])
        self.assertEqual(parsed["node_id"], "!aabbccdd")
        # Position is QoS 0
        qos = kwargs.get("qos", args[2] if len(args) > 2 else None)
        self.assertEqual(qos, 0)

    def test_publish_telemetry(self):
        c = self._make_client()
        payload = {
            "node_id": "!aabbccdd",
            "battery": 0.72,
            "voltage": 3.85,
            "snr": 8.5,
            "rssi": -95,
            "channel": 0,
            "uptime_s": 3600,
            "tx_count": 42,
            "rx_count": 100,
            "timestamp": "2026-02-27T12:00:00Z",
        }
        c.publish_telemetry(payload)
        c._client.publish.assert_called_once()
        args, kwargs = c._client.publish.call_args
        self.assertEqual(args[0], "tritium/home/mesh/meshtastic/!aabbccdd/telemetry")
        parsed = json.loads(args[1])
        self.assertEqual(parsed["battery"], 0.72)
        qos = kwargs.get("qos", args[2] if len(args) > 2 else None)
        self.assertEqual(qos, 0)

    def test_publish_text(self):
        c = self._make_client()
        msg = {
            "from": "!aabbccdd",
            "to": "!11223344",
            "text": "Hello mesh!",
            "channel": 0,
            "timestamp": "2026-02-27T12:00:00Z",
        }
        c.publish_text(msg)
        c._client.publish.assert_called_once()
        args, kwargs = c._client.publish.call_args
        self.assertEqual(args[0], "tritium/home/mesh/meshtastic/!aabbccdd/text")
        parsed = json.loads(args[1])
        self.assertEqual(parsed["text"], "Hello mesh!")
        # Text is QoS 1
        qos = kwargs.get("qos", args[2] if len(args) > 2 else None)
        self.assertEqual(qos, 1)

    def test_publish_status_online(self):
        c = self._make_client()
        c.publish_status({"status": "online", "node_id": "!aabbccdd",
                          "timestamp": "2026-02-27T12:00:00Z"})
        c._client.publish.assert_called_once()
        args, kwargs = c._client.publish.call_args
        self.assertEqual(args[0], "tritium/home/mesh/meshtastic/!aabbccdd/status")
        parsed = json.loads(args[1])
        self.assertEqual(parsed["status"], "online")
        # Status is retained, QoS 1
        qos = kwargs.get("qos", args[2] if len(args) > 2 else None)
        self.assertEqual(qos, 1)
        self.assertTrue(kwargs.get("retain", False))

    def test_publish_status_offline(self):
        c = self._make_client()
        c.publish_status({"status": "offline", "node_id": "!aabbccdd",
                          "timestamp": "2026-02-27T12:00:00Z"})
        args, kwargs = c._client.publish.call_args
        parsed = json.loads(args[1])
        self.assertEqual(parsed["status"], "offline")
        self.assertTrue(kwargs.get("retain", False))


class TestMQTTSubscribe(unittest.TestCase):
    """Test MQTT command subscription."""

    def _make_client(self, **overrides):
        defaults = dict(
            node_id="!aabbccdd",
            long_name="Hilltop Node",
            protocol="meshtastic",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
        )
        defaults.update(overrides)
        config = MeshRadioConfig(**defaults)
        client = MeshMQTTClient(config)
        client._client = MagicMock()
        return client

    def test_subscribe_commands(self):
        c = self._make_client()
        c.subscribe_commands()
        c._client.subscribe.assert_called()
        # Should subscribe to command topic
        calls = c._client.subscribe.call_args_list
        topics = [call[0][0] for call in calls]
        self.assertIn("tritium/home/mesh/meshtastic/!aabbccdd/command", topics)

    def test_subscribe_text(self):
        c = self._make_client()
        c.subscribe_commands()
        # Should also subscribe to text topic for incoming messages
        calls = c._client.subscribe.call_args_list
        topics = [call[0][0] for call in calls]
        self.assertIn("tritium/home/mesh/meshtastic/!aabbccdd/text", topics)


class TestMQTTCommandHandler(unittest.TestCase):
    """Test MQTT command handling for send_text, set_channel, reboot."""

    def _make_client(self, **overrides):
        defaults = dict(
            node_id="!aabbccdd",
            long_name="Hilltop Node",
            protocol="meshtastic",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
        )
        defaults.update(overrides)
        config = MeshRadioConfig(**defaults)
        client = MeshMQTTClient(config)
        client._client = MagicMock()
        return client

    def test_send_text_command(self):
        c = self._make_client()
        received = []
        c.on_command = lambda cmd: received.append(cmd)

        msg = MagicMock()
        msg.payload = json.dumps({
            "command": "send_text",
            "text": "Hello!",
            "to": "!11223344",
        }).encode()
        msg.topic = c.command_topic
        c._on_message(None, None, msg)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["command"], "send_text")
        self.assertEqual(received[0]["text"], "Hello!")

    def test_set_channel_command(self):
        c = self._make_client()
        received = []
        c.on_command = lambda cmd: received.append(cmd)

        msg = MagicMock()
        msg.payload = json.dumps({
            "command": "set_channel",
            "channel": 3,
        }).encode()
        msg.topic = c.command_topic
        c._on_message(None, None, msg)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["command"], "set_channel")
        self.assertEqual(received[0]["channel"], 3)

    def test_reboot_command(self):
        c = self._make_client()
        received = []
        c.on_command = lambda cmd: received.append(cmd)

        msg = MagicMock()
        msg.payload = json.dumps({"command": "reboot"}).encode()
        msg.topic = c.command_topic
        c._on_message(None, None, msg)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["command"], "reboot")

    def test_invalid_json_ignored(self):
        c = self._make_client()
        received = []
        c.on_command = lambda cmd: received.append(cmd)

        msg = MagicMock()
        msg.payload = b"not json at all"
        msg.topic = c.command_topic
        # Should not raise
        c._on_message(None, None, msg)
        self.assertEqual(len(received), 0)

    def test_incoming_text_message_callback(self):
        c = self._make_client()
        received = []
        c.on_text = lambda msg_data: received.append(msg_data)

        msg = MagicMock()
        msg.payload = json.dumps({
            "from": "!11223344",
            "to": "!aabbccdd",
            "text": "Incoming!",
            "channel": 0,
            "timestamp": "2026-02-27T12:00:00Z",
        }).encode()
        msg.topic = c.text_topic
        c._on_message(None, None, msg)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["text"], "Incoming!")

    def test_no_callback_no_crash(self):
        """If no callback is set, incoming messages should not crash."""
        c = self._make_client()
        msg = MagicMock()
        msg.payload = json.dumps({"command": "reboot"}).encode()
        msg.topic = c.command_topic
        # Should not raise even without on_command set
        c._on_message(None, None, msg)


class TestMQTTWill(unittest.TestCase):
    """Test MQTT last-will for offline status on unexpected disconnect."""

    def test_will_is_set(self):
        config = MeshRadioConfig(
            node_id="!aabbccdd",
            long_name="Hilltop Node",
            protocol="meshtastic",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
        )
        with patch("mqtt_client.mqtt.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            client = MeshMQTTClient(config)
            mock_instance.will_set.assert_called_once()
            args, kwargs = mock_instance.will_set.call_args
            self.assertEqual(
                args[0],
                "tritium/home/mesh/meshtastic/!aabbccdd/status",
            )
            payload = json.loads(args[1])
            self.assertEqual(payload["status"], "offline")
            self.assertTrue(kwargs.get("retain", False))


class TestConfigModel(unittest.TestCase):
    """Test MeshRadioConfig Pydantic model."""

    def test_defaults(self):
        c = MeshRadioConfig()
        self.assertEqual(c.node_id, "!aabbccdd")
        self.assertEqual(c.protocol, "meshtastic")
        self.assertEqual(c.mqtt_host, "localhost")
        self.assertEqual(c.mqtt_port, 1883)
        self.assertEqual(c.site, "home")

    def test_custom_values(self):
        c = MeshRadioConfig(
            node_id="!11223344",
            long_name="Valley Node",
            protocol="meshcore",
            lat=40.0,
            lng=-74.0,
            alt=100.0,
            mqtt_host="broker.local",
            mqtt_port=8883,
            site="campus",
            hardware="tbeam_v1.1",
            movement="waypoint",
            position_interval=30.0,
            telemetry_interval=120.0,
        )
        self.assertEqual(c.node_id, "!11223344")
        self.assertEqual(c.long_name, "Valley Node")
        self.assertEqual(c.protocol, "meshcore")
        self.assertAlmostEqual(c.lat, 40.0)
        self.assertAlmostEqual(c.lng, -74.0)
        self.assertAlmostEqual(c.alt, 100.0)
        self.assertEqual(c.mqtt_host, "broker.local")
        self.assertEqual(c.mqtt_port, 8883)
        self.assertEqual(c.site, "campus")
        self.assertEqual(c.hardware, "tbeam_v1.1")
        self.assertEqual(c.movement, "waypoint")
        self.assertAlmostEqual(c.position_interval, 30.0)
        self.assertAlmostEqual(c.telemetry_interval, 120.0)

    def test_default_intervals(self):
        c = MeshRadioConfig()
        # Position every 15s, telemetry every 60s are reasonable defaults
        self.assertGreater(c.position_interval, 0)
        self.assertGreater(c.telemetry_interval, 0)


if __name__ == "__main__":
    unittest.main()
