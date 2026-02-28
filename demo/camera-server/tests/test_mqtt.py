# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for MQTT publisher — written BEFORE implementation (TDD).

Uses mock MQTT client to avoid needing a real broker.
"""
import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMQTTPublisher(unittest.TestCase):
    """MQTT client publishes detections, status, and subscribes to commands."""

    def _make_publisher(self, **kwargs):
        from mqtt_publisher import MQTTPublisher
        defaults = dict(
            camera_id="test-cam-01",
            mqtt_host="localhost",
            mqtt_port=1883,
            site="home",
        )
        defaults.update(kwargs)
        return MQTTPublisher(**defaults)

    @patch("mqtt_publisher.mqtt.Client")
    def test_creates_mqtt_client(self, mock_client_cls):
        pub = self._make_publisher()
        mock_client_cls.assert_called()

    @patch("mqtt_publisher.mqtt.Client")
    def test_detection_topic_format(self, mock_client_cls):
        pub = self._make_publisher(camera_id="cam-01", site="home")
        expected = "tritium/home/cameras/cam-01/detections"
        self.assertEqual(pub.detection_topic, expected)

    @patch("mqtt_publisher.mqtt.Client")
    def test_status_topic_format(self, mock_client_cls):
        pub = self._make_publisher(camera_id="cam-01", site="home")
        expected = "tritium/home/cameras/cam-01/status"
        self.assertEqual(pub.status_topic, expected)

    @patch("mqtt_publisher.mqtt.Client")
    def test_command_topic_format(self, mock_client_cls):
        pub = self._make_publisher(camera_id="cam-01", site="home")
        expected = "tritium/home/cameras/cam-01/command"
        self.assertEqual(pub.command_topic, expected)

    @patch("mqtt_publisher.mqtt.Client")
    def test_custom_site(self, mock_client_cls):
        pub = self._make_publisher(camera_id="cam-02", site="warehouse")
        self.assertEqual(pub.detection_topic, "tritium/warehouse/cameras/cam-02/detections")
        self.assertEqual(pub.status_topic, "tritium/warehouse/cameras/cam-02/status")

    @patch("mqtt_publisher.mqtt.Client")
    def test_publish_detection(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        pub = self._make_publisher()

        detection = {
            "boxes": [{"label": "person", "confidence": 0.9,
                        "center_x": 0.5, "center_y": 0.5,
                        "bbox": [0.3, 0.3, 0.7, 0.7]}],
            "camera_id": "test-cam-01",
            "timestamp": "2026-02-27T12:00:00Z",
            "frame_id": 1,
        }
        pub.publish_detection(detection)

        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        topic = call_args[0][0] if call_args[0] else call_args[1].get("topic")
        self.assertEqual(topic, "tritium/home/cameras/test-cam-01/detections")

    @patch("mqtt_publisher.mqtt.Client")
    def test_publish_detection_qos_0(self, mock_client_cls):
        """Detections published at QoS 0 per spec."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        pub = self._make_publisher()

        detection = {"boxes": [], "camera_id": "test-cam-01",
                      "timestamp": "2026-02-27T12:00:00Z", "frame_id": 1}
        pub.publish_detection(detection)

        call_args = mock_client.publish.call_args
        # QoS should be 0
        qos = call_args[1].get("qos", call_args[0][2] if len(call_args[0]) > 2 else 0)
        self.assertEqual(qos, 0)

    @patch("mqtt_publisher.mqtt.Client")
    def test_publish_status_online(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        pub = self._make_publisher()
        pub.publish_status("online")

        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])
        self.assertEqual(topic, "tritium/home/cameras/test-cam-01/status")
        self.assertEqual(payload["status"], "online")

    @patch("mqtt_publisher.mqtt.Client")
    def test_publish_status_retained(self, mock_client_cls):
        """Status messages must be retained (QoS 1)."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        pub = self._make_publisher()
        pub.publish_status("online")

        call_args = mock_client.publish.call_args
        retain = call_args[1].get("retain", False)
        self.assertTrue(retain, "Status should be retained")

    @patch("mqtt_publisher.mqtt.Client")
    def test_publish_status_qos_1(self, mock_client_cls):
        """Status messages at QoS 1."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        pub = self._make_publisher()
        pub.publish_status("online")

        call_args = mock_client.publish.call_args
        qos = call_args[1].get("qos", 0)
        self.assertEqual(qos, 1, "Status should be QoS 1")

    @patch("mqtt_publisher.mqtt.Client")
    def test_subscribes_to_command_topic(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        pub = self._make_publisher()
        pub.connect()

        # After connect, should subscribe to command topic
        mock_client.subscribe.assert_called()
        subscribed_topics = [c[0][0] for c in mock_client.subscribe.call_args_list]
        self.assertIn("tritium/home/cameras/test-cam-01/command", subscribed_topics)

    @patch("mqtt_publisher.mqtt.Client")
    def test_command_callback_registered(self, mock_client_cls):
        """Should have a message callback for commands."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        pub = self._make_publisher()
        # on_command should be a callable attribute or similar mechanism
        self.assertTrue(hasattr(pub, "on_command") or hasattr(pub, "_on_message"),
                        "Publisher should have command handler")

    @patch("mqtt_publisher.mqtt.Client")
    def test_last_will_offline(self, mock_client_cls):
        """MQTT client should set LWT to offline status."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        pub = self._make_publisher()

        # will_set should have been called with offline status
        mock_client.will_set.assert_called_once()
        call_args = mock_client.will_set.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])
        self.assertEqual(topic, "tritium/home/cameras/test-cam-01/status")
        self.assertEqual(payload["status"], "offline")

    @patch("mqtt_publisher.mqtt.Client")
    def test_detection_payload_is_json(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        pub = self._make_publisher()

        detection = {"boxes": [], "camera_id": "test-cam-01",
                      "timestamp": "2026-02-27T12:00:00Z", "frame_id": 1}
        pub.publish_detection(detection)

        call_args = mock_client.publish.call_args
        payload_str = call_args[0][1]
        # Should be valid JSON
        parsed = json.loads(payload_str)
        self.assertEqual(parsed["camera_id"], "test-cam-01")


if __name__ == "__main__":
    unittest.main()
