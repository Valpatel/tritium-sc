# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Tests for hostile agent MQTT client.
TDD: Write tests first, watch them fail, then implement.
"""

import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMQTTTopics(unittest.TestCase):
    """MQTT topic construction."""

    @patch('paho.mqtt.client.Client')
    def test_telemetry_topic_format(self, MockClient):
        from mqtt_client import HostileMQTTClient
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        self.assertEqual(client.telemetry_topic, 'tritium/home/hostiles/hostile-01/telemetry')

    @patch('paho.mqtt.client.Client')
    def test_status_topic_format(self, MockClient):
        from mqtt_client import HostileMQTTClient
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        self.assertEqual(client.status_topic, 'tritium/home/hostiles/hostile-01/status')

    @patch('paho.mqtt.client.Client')
    def test_thoughts_topic_format(self, MockClient):
        from mqtt_client import HostileMQTTClient
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        self.assertEqual(client.thoughts_topic, 'tritium/home/hostiles/hostile-01/thoughts')

    @patch('paho.mqtt.client.Client')
    def test_elimination_subscribe_topic(self, MockClient):
        from mqtt_client import HostileMQTTClient
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        self.assertEqual(client.elimination_topic, 'tritium/home/sim/eliminations')

    @patch('paho.mqtt.client.Client')
    def test_situation_subscribe_topic(self, MockClient):
        from mqtt_client import HostileMQTTClient
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        self.assertEqual(client.situation_topic, 'tritium/home/sim/situation')

    @patch('paho.mqtt.client.Client')
    def test_custom_site(self, MockClient):
        from mqtt_client import HostileMQTTClient
        client = HostileMQTTClient(hostile_id='bad-01', site='campus')
        self.assertIn('campus', client.telemetry_topic)


class TestMQTTPublish(unittest.TestCase):
    """MQTT publishing behavior."""

    @patch('paho.mqtt.client.Client')
    def test_publish_telemetry(self, MockClient):
        from mqtt_client import HostileMQTTClient
        mock_instance = MockClient.return_value
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        telemetry = {'robot_id': 'hostile-01', 'position': {'x': 10, 'y': 20}}
        client.publish_telemetry(telemetry)
        mock_instance.publish.assert_called_once()
        args = mock_instance.publish.call_args
        self.assertEqual(args[0][0], 'tritium/home/hostiles/hostile-01/telemetry')

    @patch('paho.mqtt.client.Client')
    def test_publish_telemetry_qos_0(self, MockClient):
        from mqtt_client import HostileMQTTClient
        mock_instance = MockClient.return_value
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        client.publish_telemetry({'test': True})
        args = mock_instance.publish.call_args
        self.assertEqual(args[1].get('qos', args[0][2] if len(args[0]) > 2 else 0), 0)

    @patch('paho.mqtt.client.Client')
    def test_publish_thought(self, MockClient):
        from mqtt_client import HostileMQTTClient
        mock_instance = MockClient.return_value
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        client.publish_thought("I see a turret ahead, I should flank left")
        mock_instance.publish.assert_called_once()
        args = mock_instance.publish.call_args
        self.assertEqual(args[0][0], 'tritium/home/hostiles/hostile-01/thoughts')

    @patch('paho.mqtt.client.Client')
    def test_publish_status_retained(self, MockClient):
        from mqtt_client import HostileMQTTClient
        mock_instance = MockClient.return_value
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        client.publish_status('active')
        args = mock_instance.publish.call_args
        self.assertTrue(args[1].get('retain', False))


class TestMQTTSubscribe(unittest.TestCase):
    """MQTT subscription behavior."""

    @patch('paho.mqtt.client.Client')
    def test_subscribes_to_eliminations(self, MockClient):
        from mqtt_client import HostileMQTTClient
        mock_instance = MockClient.return_value
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        client.start()
        # Check subscribe was called with elimination topic
        subscribe_calls = mock_instance.subscribe.call_args_list
        topics = [c[0][0] for c in subscribe_calls]
        self.assertIn('tritium/home/sim/eliminations', topics)

    @patch('paho.mqtt.client.Client')
    def test_subscribes_to_situation(self, MockClient):
        from mqtt_client import HostileMQTTClient
        mock_instance = MockClient.return_value
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        client.start()
        subscribe_calls = mock_instance.subscribe.call_args_list
        topics = [c[0][0] for c in subscribe_calls]
        self.assertIn('tritium/home/sim/situation', topics)

    @patch('paho.mqtt.client.Client')
    def test_elimination_callback(self, MockClient):
        from mqtt_client import HostileMQTTClient
        mock_instance = MockClient.return_value
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        killed = []
        client.on_eliminated = lambda: killed.append(True)
        # Simulate elimination message
        msg = MagicMock()
        msg.topic = 'tritium/home/sim/eliminations'
        msg.payload = json.dumps({'target_id': 'hostile-01'}).encode()
        client._on_message(mock_instance, None, msg)
        self.assertEqual(len(killed), 1)

    @patch('paho.mqtt.client.Client')
    def test_elimination_ignores_other_ids(self, MockClient):
        from mqtt_client import HostileMQTTClient
        mock_instance = MockClient.return_value
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        killed = []
        client.on_eliminated = lambda: killed.append(True)
        msg = MagicMock()
        msg.topic = 'tritium/home/sim/eliminations'
        msg.payload = json.dumps({'target_id': 'hostile-99'}).encode()
        client._on_message(mock_instance, None, msg)
        self.assertEqual(len(killed), 0)

    @patch('paho.mqtt.client.Client')
    def test_lwt_offline_status(self, MockClient):
        from mqtt_client import HostileMQTTClient
        mock_instance = MockClient.return_value
        client = HostileMQTTClient(hostile_id='hostile-01', site='home')
        mock_instance.will_set.assert_called_once()
        will_args = mock_instance.will_set.call_args
        self.assertIn('offline', will_args[0][1])


if __name__ == '__main__':
    unittest.main()
