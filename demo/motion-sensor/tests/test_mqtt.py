# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for MQTT client.

TDD: written BEFORE implementation.
Tests MQTT pub/sub, event format matches spec, enable/disable commands.
Uses mock MQTT client to avoid needing a real broker.
"""

import json
import unittest
from unittest.mock import MagicMock, patch, call

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mqtt_client import SensorMQTTClient
from config import SensorConfig


class TestMQTTTopics(unittest.TestCase):
    """Test MQTT topic construction matches spec."""

    def _make_client(self, **overrides):
        defaults = dict(
            sensor_id="demo-pir-01",
            sensor_type="pir",
            zone="front_door",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
        )
        defaults.update(overrides)
        config = SensorConfig(**defaults)
        return SensorMQTTClient(config)

    def test_events_topic(self):
        c = self._make_client()
        self.assertEqual(c.events_topic, "tritium/home/sensors/demo-pir-01/events")

    def test_status_topic(self):
        c = self._make_client()
        self.assertEqual(c.status_topic, "tritium/home/sensors/demo-pir-01/status")

    def test_command_topic(self):
        c = self._make_client()
        self.assertEqual(c.command_topic, "tritium/home/sensors/demo-pir-01/command")

    def test_custom_site(self):
        c = self._make_client(site="campus")
        self.assertEqual(c.events_topic, "tritium/campus/sensors/demo-pir-01/events")

    def test_custom_sensor_id(self):
        c = self._make_client(sensor_id="mw-zone-b")
        self.assertEqual(c.events_topic, "tritium/home/sensors/mw-zone-b/events")


class TestMQTTPublish(unittest.TestCase):
    """Test MQTT message publishing."""

    def _make_client(self, **overrides):
        defaults = dict(
            sensor_id="demo-pir-01",
            sensor_type="pir",
            zone="front_door",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
        )
        defaults.update(overrides)
        config = SensorConfig(**defaults)
        client = SensorMQTTClient(config)
        client._client = MagicMock()
        return client

    def test_publish_event(self):
        c = self._make_client()
        event = {
            "sensor_id": "demo-pir-01",
            "sensor_type": "pir",
            "event": "motion_detected",
            "confidence": 0.92,
            "position": {"x": 25.0, "y": -10.0},
            "zone": "front_door",
            "timestamp": "2026-02-27T12:00:00Z",
            "metadata": {"duration_ms": 2500, "peak_amplitude": 0.87},
        }
        c.publish_event(event)
        c._client.publish.assert_called_once()
        args, kwargs = c._client.publish.call_args
        self.assertEqual(args[0], "tritium/home/sensors/demo-pir-01/events")
        payload = json.loads(args[1])
        self.assertEqual(payload["sensor_id"], "demo-pir-01")
        self.assertEqual(payload["event"], "motion_detected")
        self.assertEqual(kwargs.get("qos", args[2] if len(args) > 2 else None), 1)

    def test_publish_status_online(self):
        c = self._make_client()
        c.publish_status("online")
        c._client.publish.assert_called_once()
        args, kwargs = c._client.publish.call_args
        self.assertEqual(args[0], "tritium/home/sensors/demo-pir-01/status")
        payload = json.loads(args[1])
        self.assertEqual(payload["status"], "online")
        self.assertIn("sensor_id", payload)
        self.assertIn("sensor_type", payload)
        self.assertIn("timestamp", payload)
        # Status should be retained
        self.assertTrue(kwargs.get("retain", False))

    def test_publish_status_offline(self):
        c = self._make_client()
        c.publish_status("offline")
        args, kwargs = c._client.publish.call_args
        payload = json.loads(args[1])
        self.assertEqual(payload["status"], "offline")
        self.assertTrue(kwargs.get("retain", False))

    def test_event_qos_is_1(self):
        c = self._make_client()
        event = {"sensor_id": "demo-pir-01", "event": "motion_detected",
                 "sensor_type": "pir", "confidence": 0.9,
                 "position": {"x": 0, "y": 0}, "zone": "test",
                 "timestamp": "2026-02-27T12:00:00Z",
                 "metadata": {"duration_ms": 100, "peak_amplitude": 0.5}}
        c.publish_event(event)
        args, kwargs = c._client.publish.call_args
        # QoS should be 1 (either positional arg or kwarg)
        qos = kwargs.get("qos", args[2] if len(args) > 2 else None)
        self.assertEqual(qos, 1)


class TestMQTTCommand(unittest.TestCase):
    """Test MQTT command handling for enable/disable."""

    def _make_client(self, **overrides):
        defaults = dict(
            sensor_id="demo-pir-01",
            sensor_type="pir",
            zone="front_door",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
        )
        defaults.update(overrides)
        config = SensorConfig(**defaults)
        client = SensorMQTTClient(config)
        client._client = MagicMock()
        return client

    def test_subscribes_to_command_topic(self):
        c = self._make_client()
        c.subscribe_commands()
        c._client.subscribe.assert_called_with(
            "tritium/home/sensors/demo-pir-01/command", qos=1
        )

    def test_enable_command_callback(self):
        c = self._make_client()
        callback_called = []

        def on_command(cmd):
            callback_called.append(cmd)

        c.on_command = on_command
        # Simulate receiving an enable command
        msg = MagicMock()
        msg.payload = json.dumps({"command": "enable"}).encode()
        msg.topic = "tritium/home/sensors/demo-pir-01/command"
        c._on_message(None, None, msg)
        self.assertEqual(len(callback_called), 1)
        self.assertEqual(callback_called[0]["command"], "enable")

    def test_disable_command_callback(self):
        c = self._make_client()
        callback_called = []

        def on_command(cmd):
            callback_called.append(cmd)

        c.on_command = on_command
        msg = MagicMock()
        msg.payload = json.dumps({"command": "disable"}).encode()
        msg.topic = "tritium/home/sensors/demo-pir-01/command"
        c._on_message(None, None, msg)
        self.assertEqual(len(callback_called), 1)
        self.assertEqual(callback_called[0]["command"], "disable")

    def test_invalid_json_command_ignored(self):
        c = self._make_client()
        callback_called = []

        def on_command(cmd):
            callback_called.append(cmd)

        c.on_command = on_command
        msg = MagicMock()
        msg.payload = b"not json"
        msg.topic = "tritium/home/sensors/demo-pir-01/command"
        # Should not raise
        c._on_message(None, None, msg)
        self.assertEqual(len(callback_called), 0)


class TestMQTTWill(unittest.TestCase):
    """Test MQTT last-will message for offline status."""

    def test_will_is_set(self):
        """Client should set last-will to publish offline status."""
        config = SensorConfig(
            sensor_id="demo-pir-01",
            sensor_type="pir",
            zone="front_door",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
        )
        with patch("mqtt_client.mqtt.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            client = SensorMQTTClient(config)
            # will_set should have been called
            mock_instance.will_set.assert_called_once()
            args, kwargs = mock_instance.will_set.call_args
            self.assertEqual(args[0], "tritium/home/sensors/demo-pir-01/status")
            payload = json.loads(args[1])
            self.assertEqual(payload["status"], "offline")
            self.assertTrue(kwargs.get("retain", False))


class TestEventFormatSpec(unittest.TestCase):
    """Verify event JSON matches the spec in DEMO-SPEC.md section 3.3."""

    def test_full_event_structure(self):
        """Event must match:
        {
          "sensor_id": "demo-pir-01",
          "sensor_type": "pir",
          "event": "motion_detected",
          "confidence": 0.92,
          "position": {"x": 25.0, "y": -10.0},
          "zone": "front_door",
          "timestamp": "2026-02-27T12:00:00Z",
          "metadata": {
            "duration_ms": 2500,
            "peak_amplitude": 0.87
          }
        }
        """
        from sensor import MotionSensor

        s = MotionSensor(
            sensor_id="demo-pir-01",
            sensor_type="pir",
            zone="front_door",
            position_x=25.0,
            position_y=-10.0,
        )
        event = s.trigger()

        # Check all top-level keys
        required_keys = {
            "sensor_id", "sensor_type", "event", "confidence",
            "position", "zone", "timestamp", "metadata"
        }
        self.assertEqual(set(event.keys()), required_keys)

        # Check types
        self.assertIsInstance(event["sensor_id"], str)
        self.assertIsInstance(event["sensor_type"], str)
        self.assertIsInstance(event["event"], str)
        self.assertIsInstance(event["confidence"], float)
        self.assertIsInstance(event["position"], dict)
        self.assertIsInstance(event["zone"], str)
        self.assertIsInstance(event["timestamp"], str)
        self.assertIsInstance(event["metadata"], dict)

        # Check position structure
        self.assertIn("x", event["position"])
        self.assertIn("y", event["position"])

        # Check metadata structure
        self.assertIn("duration_ms", event["metadata"])
        self.assertIn("peak_amplitude", event["metadata"])

    def test_event_is_json_serializable(self):
        from sensor import MotionSensor

        s = MotionSensor(sensor_id="pir-01", sensor_type="pir")
        event = s.trigger()
        # Must not raise
        serialized = json.dumps(event)
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized["sensor_id"], "pir-01")


if __name__ == "__main__":
    unittest.main()
