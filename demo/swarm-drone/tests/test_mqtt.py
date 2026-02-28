# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for mqtt_client.py -- MQTT pub/sub for swarm drone."""

import json
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mqtt_client import DroneMQTTClient, parse_command


# ---------------------------------------------------------------------------
# parse_command
# ---------------------------------------------------------------------------
class TestParseCommand:
    """parse_command extracts valid commands from JSON."""

    def test_valid_dispatch(self):
        raw = json.dumps({"command": "dispatch", "x": 10.0, "y": 20.0})
        cmd = parse_command(raw)
        assert cmd is not None
        assert cmd["command"] == "dispatch"

    def test_valid_recall(self):
        raw = json.dumps({"command": "recall"})
        cmd = parse_command(raw)
        assert cmd is not None
        assert cmd["command"] == "recall"

    def test_valid_patrol(self):
        raw = json.dumps({"command": "patrol", "waypoints": [{"x": 1, "y": 2}]})
        cmd = parse_command(raw)
        assert cmd is not None
        assert cmd["command"] == "patrol"

    def test_valid_stop(self):
        raw = json.dumps({"command": "stop"})
        cmd = parse_command(raw)
        assert cmd is not None

    def test_invalid_json(self):
        assert parse_command("not json") is None

    def test_missing_command_key(self):
        assert parse_command(json.dumps({"x": 10})) is None

    def test_bytes_input(self):
        raw = json.dumps({"command": "stop"}).encode()
        cmd = parse_command(raw)
        assert cmd is not None

    def test_non_dict(self):
        assert parse_command(json.dumps([1, 2, 3])) is None


# ---------------------------------------------------------------------------
# Topic format
# ---------------------------------------------------------------------------
class TestTopicFormat:
    """MQTT topics follow tritium/{site}/robots/{id}/... format."""

    def test_telemetry_topic(self):
        c = DroneMQTTClient(drone_id="swarm-01", site="home")
        assert c.telemetry_topic == "tritium/home/robots/swarm-01/telemetry"

    def test_command_topic(self):
        c = DroneMQTTClient(drone_id="swarm-01", site="home")
        assert c.command_topic == "tritium/home/robots/swarm-01/command"

    def test_status_topic(self):
        c = DroneMQTTClient(drone_id="swarm-01", site="home")
        assert c.status_topic == "tritium/home/robots/swarm-01/status"

    def test_eliminations_topic(self):
        c = DroneMQTTClient(drone_id="swarm-01", site="home")
        assert c.eliminations_topic == "tritium/home/sim/eliminations"

    def test_custom_site(self):
        c = DroneMQTTClient(drone_id="swarm-01", site="warehouse")
        assert c.telemetry_topic == "tritium/warehouse/robots/swarm-01/telemetry"

    def test_custom_drone_id(self):
        c = DroneMQTTClient(drone_id="swarm-42", site="home")
        assert c.telemetry_topic == "tritium/home/robots/swarm-42/telemetry"


# ---------------------------------------------------------------------------
# LWT
# ---------------------------------------------------------------------------
class TestLWT:
    """Last Will and Testament configured for offline status."""

    @patch("mqtt_client.mqtt.Client")
    def test_lwt_set_on_setup(self, MockClient):
        mock_inst = MagicMock()
        MockClient.return_value = mock_inst
        c = DroneMQTTClient(drone_id="swarm-01", site="home")
        c.setup()
        mock_inst.will_set.assert_called_once()
        args, kwargs = mock_inst.will_set.call_args
        assert args[0] == "tritium/home/robots/swarm-01/status"
        payload = json.loads(args[1])
        assert payload["status"] == "offline"
        qos = args[2] if len(args) > 2 else kwargs.get("qos", 0)
        retain = args[3] if len(args) > 3 else kwargs.get("retain", False)
        assert qos == 1
        assert retain is True


# ---------------------------------------------------------------------------
# Publish telemetry
# ---------------------------------------------------------------------------
class TestPublishTelemetry:
    """Telemetry published at QoS 0."""

    @patch("mqtt_client.mqtt.Client")
    def test_publish_telemetry(self, MockClient):
        mock_inst = MagicMock()
        MockClient.return_value = mock_inst
        c = DroneMQTTClient(drone_id="swarm-01", site="home")
        c.setup()
        telemetry = {"robot_id": "swarm-01", "position": {"x": 0, "y": 0}}
        c.publish_telemetry(telemetry)
        mock_inst.publish.assert_called_once()
        args, kwargs = mock_inst.publish.call_args
        assert args[0] == "tritium/home/robots/swarm-01/telemetry"
        qos = kwargs.get("qos", args[2] if len(args) > 2 else 0)
        assert qos == 0


# ---------------------------------------------------------------------------
# Publish status
# ---------------------------------------------------------------------------
class TestPublishStatus:
    """Status published with retain + QoS 1."""

    @patch("mqtt_client.mqtt.Client")
    def test_publish_online(self, MockClient):
        mock_inst = MagicMock()
        MockClient.return_value = mock_inst
        c = DroneMQTTClient(drone_id="swarm-01", site="home")
        c.setup()
        c.publish_status("online")
        mock_inst.publish.assert_called_once()
        args, kwargs = mock_inst.publish.call_args
        assert args[0] == "tritium/home/robots/swarm-01/status"
        payload = json.loads(args[1])
        assert payload["status"] == "online"
        assert kwargs.get("qos", 0) == 1
        assert kwargs.get("retain", False) is True


# ---------------------------------------------------------------------------
# Subscribe + command callback
# ---------------------------------------------------------------------------
class TestCommandSubscription:
    """Subscribes to command and eliminations topics."""

    @patch("mqtt_client.mqtt.Client")
    def test_subscribe_on_connect(self, MockClient):
        mock_inst = MagicMock()
        MockClient.return_value = mock_inst
        c = DroneMQTTClient(drone_id="swarm-01", site="home")
        c.setup()
        c._on_connect(mock_inst, None, None, 0)
        sub_calls = mock_inst.subscribe.call_args_list
        topics = [call[0][0] for call in sub_calls]
        assert "tritium/home/robots/swarm-01/command" in topics
        assert "tritium/home/sim/eliminations" in topics

    @patch("mqtt_client.mqtt.Client")
    def test_command_callback(self, MockClient):
        mock_inst = MagicMock()
        MockClient.return_value = mock_inst
        c = DroneMQTTClient(drone_id="swarm-01", site="home")
        c.setup()
        received = []
        c.on_command = lambda cmd: received.append(cmd)
        msg = MagicMock()
        msg.topic = "tritium/home/robots/swarm-01/command"
        msg.payload = json.dumps({"command": "dispatch", "x": 5, "y": 10}).encode()
        c._on_message(mock_inst, None, msg)
        assert len(received) == 1
        assert received[0]["command"] == "dispatch"

    @patch("mqtt_client.mqtt.Client")
    def test_elimination_callback(self, MockClient):
        mock_inst = MagicMock()
        MockClient.return_value = mock_inst
        c = DroneMQTTClient(drone_id="swarm-01", site="home")
        c.setup()
        received = []
        c.on_elimination = lambda data: received.append(data)
        msg = MagicMock()
        msg.topic = "tritium/home/sim/eliminations"
        msg.payload = json.dumps({"target_id": "swarm-01", "eliminated_by": "turret-1"}).encode()
        c._on_message(mock_inst, None, msg)
        assert len(received) == 1
        assert received[0]["target_id"] == "swarm-01"

    @patch("mqtt_client.mqtt.Client")
    def test_invalid_message_ignored(self, MockClient):
        mock_inst = MagicMock()
        MockClient.return_value = mock_inst
        c = DroneMQTTClient(drone_id="swarm-01", site="home")
        c.setup()
        received = []
        c.on_command = lambda cmd: received.append(cmd)
        msg = MagicMock()
        msg.topic = "tritium/home/robots/swarm-01/command"
        msg.payload = b"not json"
        c._on_message(mock_inst, None, msg)
        assert len(received) == 0
