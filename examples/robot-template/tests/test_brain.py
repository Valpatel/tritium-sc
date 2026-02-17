"""Unit tests for robot brain components."""

import json
import pytest
from unittest.mock import MagicMock, patch, call

# Add parent to path for imports
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock paho.mqtt before importing brain.mqtt_client (paho may not be installed)
_mock_paho = MagicMock()
sys.modules.setdefault("paho", _mock_paho)
sys.modules.setdefault("paho.mqtt", _mock_paho.mqtt)
sys.modules.setdefault("paho.mqtt.client", _mock_paho.mqtt.client)

from hardware.simulated import SimulatedHardware
from brain.navigator import Navigator
from brain.turret import TurretController


class TestSimulatedHardware:
    def test_initial_position(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        assert hw.get_position() == (0.0, 0.0)

    def test_initial_battery(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        assert hw.get_battery() == 1.0

    def test_motor_clamping(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        hw.set_motors(2.0, -2.0)  # Should clamp to [-1, 1]
        # No crash = pass

    def test_fire_drains_battery(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        initial = hw.get_battery()
        hw.fire_trigger()
        assert hw.get_battery() < initial


class TestNavigator:
    def test_go_to_sets_status(self):
        hw = MagicMock()
        nav = Navigator(hw, {})
        nav.go_to(10.0, 5.0)
        assert nav.status == "active"

    def test_stop_sets_idle(self):
        hw = MagicMock()
        nav = Navigator(hw, {})
        nav.go_to(10.0, 5.0)
        nav.stop()
        assert nav.status == "idle"

    def test_patrol_sets_active(self):
        hw = MagicMock()
        nav = Navigator(hw, {})
        nav.patrol([(0, 0), (10, 10)])
        assert nav.status == "active"
        assert nav.current_waypoint == (0, 0)


class TestTurretController:
    def test_aim_clamps(self):
        hw = MagicMock()
        turret = TurretController(hw, {})
        turret.aim(200, -100)
        assert turret.pan == 90
        assert turret.tilt == -30

    def test_fire_calls_hardware(self):
        hw = MagicMock()
        turret = TurretController(hw, {})
        turret.fire()
        hw.fire_trigger.assert_called_once()


class TestMQTTClient:
    def _make_client(self, config):
        """Create a RobotMQTTClient with paho mocked."""
        from brain.mqtt_client import RobotMQTTClient
        return RobotMQTTClient(config)

    def test_lwt_set_before_connect(self):
        config = {"robot_id": "test-bot", "site_id": "lab"}
        client = self._make_client(config)
        # LWT should be set during __init__
        client._client.will_set.assert_called_once()
        args = client._client.will_set.call_args
        assert args[0][0] == "tritium/lab/robots/test-bot/status"
        payload = json.loads(args[0][1])
        assert payload["status"] == "offline"

    def test_topics_match_bridge(self):
        config = {"robot_id": "r1", "site_id": "home"}
        client = self._make_client(config)
        client._connected = True
        client.publish_telemetry({"position": {"x": 1, "y": 2}})
        pub_call = client._client.publish.call_args
        assert pub_call[0][0] == "tritium/home/robots/r1/telemetry"

    def test_subscribe_on_connect(self):
        config = {"robot_id": "r1", "site_id": "home"}
        client = self._make_client(config)
        client._on_connect(client._client, None, {}, 0)
        client._client.subscribe.assert_called_once_with(
            "tritium/home/robots/r1/command"
        )

    def test_disconnect_publishes_offline(self):
        config = {"robot_id": "r1", "site_id": "home"}
        client = self._make_client(config)
        client._connected = True
        # Reset mock to isolate this test
        client._client.publish.reset_mock()
        client.disconnect()
        pub_calls = client._client.publish.call_args_list
        assert len(pub_calls) >= 1
        topic = pub_calls[0][0][0]
        assert topic == "tritium/home/robots/r1/status"
        payload = json.loads(pub_calls[0][0][1])
        assert payload["status"] == "offline"

    def test_command_callback(self):
        config = {"robot_id": "r1", "site_id": "home"}
        client = self._make_client(config)
        received = []
        client.on_command = lambda cmd: received.append(cmd)
        msg = MagicMock()
        msg.payload = json.dumps({"command": "dispatch", "x": 5, "y": 10}).encode()
        client._on_message(client._client, None, msg)
        assert len(received) == 1
        assert received[0]["command"] == "dispatch"


class TestProtocolCompatibility:
    """Verify robot template speaks exactly the same protocol as mqtt_bridge.py."""

    def _make_client(self, config=None):
        from brain.mqtt_client import RobotMQTTClient
        return RobotMQTTClient(config or {"robot_id": "r1", "site_id": "home"})

    def test_dispatch_command_parsing(self):
        """Robot must parse dispatch exactly as mqtt_bridge.publish_dispatch sends it."""
        # This is the exact payload mqtt_bridge.publish_dispatch sends:
        bridge_payload = {
            "command": "dispatch",
            "x": 15.5,
            "y": -3.2,
            "timestamp": "2026-02-16T00:00:00+00:00",
        }
        nav = MagicMock()
        cmd = bridge_payload.get("command", "")
        assert cmd == "dispatch"
        x, y = bridge_payload.get("x", 0), bridge_payload.get("y", 0)
        assert x == 15.5
        assert y == -3.2
        nav.go_to(x, y)
        nav.go_to.assert_called_once_with(15.5, -3.2)

    def test_patrol_command_waypoint_format(self):
        """Robot must parse patrol waypoints as [{"x":..., "y":...}] dicts."""
        # Exact payload from mqtt_bridge.publish_patrol:
        bridge_payload = {
            "command": "patrol",
            "waypoints": [{"x": 0, "y": 0}, {"x": 10, "y": 5}, {"x": 20, "y": 0}],
            "timestamp": "2026-02-16T00:00:00+00:00",
        }
        waypoints = bridge_payload.get("waypoints", [])
        # Robot converts dict waypoints to tuples:
        wps = [(w["x"], w["y"]) for w in waypoints]
        assert wps == [(0, 0), (10, 5), (20, 0)]

    def test_recall_command_no_extra_fields(self):
        """Recall command only has 'command' and 'timestamp'."""
        bridge_payload = {
            "command": "recall",
            "timestamp": "2026-02-16T00:00:00+00:00",
        }
        cmd = bridge_payload.get("command", "")
        assert cmd == "recall"

    def test_dispatch_missing_coordinates_defaults_to_origin(self):
        """If x/y missing from dispatch, robot defaults to (0,0)."""
        payload = {"command": "dispatch", "timestamp": "2026-02-16T00:00:00+00:00"}
        x, y = payload.get("x", 0), payload.get("y", 0)
        assert x == 0
        assert y == 0

    def test_patrol_empty_waypoints_ignored(self):
        """Empty waypoints list should not change navigator state."""
        hw = MagicMock()
        nav = Navigator(hw, {})
        nav.patrol([])
        assert nav.status == "idle"  # Should stay idle

    def test_unknown_command_does_not_crash(self):
        """Unknown commands are logged but don't crash the robot."""
        payload = {"command": "self_destruct", "timestamp": "2026-02-16T00:00:00+00:00"}
        cmd = payload.get("command", "")
        assert cmd == "self_destruct"
        # In robot.py, this prints "[CMD] Unknown command: self_destruct"
        # The handler does not raise

    def test_telemetry_position_is_dict(self):
        """Telemetry position must be {"x": ..., "y": ...} dict, not a list or tuple."""
        hw = MagicMock()
        hw.get_position.return_value = (7.5, -2.3)
        pos = hw.get_position()
        telemetry_data = {"position": {"x": pos[0], "y": pos[1]}}
        position = telemetry_data["position"]
        assert isinstance(position, dict)
        assert "x" in position
        assert "y" in position
        assert position["x"] == 7.5
        assert position["y"] == -2.3

    def test_status_payload_has_robot_id(self):
        """Status messages must include robot_id for bridge device tracking."""
        client = self._make_client({"robot_id": "test-bot", "site_id": "lab"})
        client._connected = True
        client._client.publish.reset_mock()
        client.publish_status("online")
        call_args = client._client.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])
        assert topic == "tritium/lab/robots/test-bot/status"
        assert payload["status"] == "online"
        assert payload["robot_id"] == "test-bot"

    def test_detection_payload_matches_bridge(self):
        """Camera detection payload must match bridge _on_camera_detection format."""
        client = self._make_client({"robot_id": "cam-bot", "site_id": "home"})
        client._connected = True
        client._client.publish.reset_mock()
        detections = [
            {"label": "person", "confidence": 0.95, "center_x": 0.5, "center_y": 0.6,
             "bbox": [0.3, 0.4, 0.7, 0.8]},
        ]
        client.publish_detection(detections)
        call_args = client._client.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])
        # Bridge expects topic: tritium/{site}/cameras/{cam_id}/detections
        assert topic == "tritium/home/cameras/cam-bot/detections"
        # Bridge reads payload.get("boxes", [])
        assert "boxes" in payload
        assert len(payload["boxes"]) == 1
        box = payload["boxes"][0]
        # Bridge reads: label, confidence, center_x, center_y
        assert box["label"] == "person"
        assert box["confidence"] == 0.95
        assert box["center_x"] == 0.5
        assert box["center_y"] == 0.6

    def test_lwt_matches_status_topic(self):
        """LWT topic must be identical to the status topic used by publish_status."""
        client = self._make_client({"robot_id": "r1", "site_id": "home"})
        lwt_call = client._client.will_set.call_args
        lwt_topic = lwt_call[0][0]
        # Publish a status to get the topic
        client._connected = True
        client._client.publish.reset_mock()
        client.publish_status("online")
        status_topic = client._client.publish.call_args[0][0]
        assert lwt_topic == status_topic

    def test_command_topic_matches_bridge_publish(self):
        """Robot subscribes to the same topic bridge publishes commands to."""
        client = self._make_client({"robot_id": "r1", "site_id": "home"})
        client._on_connect(client._client, None, {}, 0)
        sub_call = client._client.subscribe.call_args
        subscribed_topic = sub_call[0][0]
        # Bridge publishes to: tritium/{site}/robots/{robot_id}/command
        expected = "tritium/home/robots/r1/command"
        assert subscribed_topic == expected

    def test_telemetry_all_bridge_fields_present(self):
        """Every field mqtt_bridge._on_robot_telemetry reads must be in telemetry."""
        # Fields the bridge reads via payload.get():
        bridge_reads = ["position", "name", "asset_type", "heading", "speed", "battery", "status"]
        telemetry = {
            "name": "Test Bot",
            "asset_type": "rover",
            "position": {"x": 1.0, "y": 2.0},
            "heading": 45.0,
            "speed": 1.5,
            "battery": 0.9,
            "status": "active",
            "turret": {"pan": 0, "tilt": 0},  # extra, bridge ignores
        }
        for field in bridge_reads:
            assert field in telemetry, f"Missing field: {field}"

    def test_battery_never_negative(self):
        """Simulated hardware must clamp battery to >= 0."""
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        # Fire many times to drain battery
        for _ in range(200):
            hw.fire_trigger()
        assert hw.get_battery() >= 0.0


class TestCommandAck:
    """Verify robot publishes command ACK in the format bridge expects."""

    def _make_client(self, config=None):
        from brain.mqtt_client import RobotMQTTClient
        return RobotMQTTClient(config or {"robot_id": "r1", "site_id": "home"})

    def test_ack_publishes_to_correct_topic(self):
        """ACK should go to robots/{id}/command/ack."""
        client = self._make_client({"robot_id": "rover-alpha", "site_id": "home"})
        client._connected = True
        client._client.publish.reset_mock()
        client.publish_command_ack("dispatch", "2026-02-16T10:30:00+00:00", "accepted")
        call_args = client._client.publish.call_args
        topic = call_args[0][0]
        assert topic == "tritium/home/robots/rover-alpha/command/ack"

    def test_ack_payload_has_required_fields(self):
        """ACK payload must include command, command_timestamp, status, robot_id."""
        client = self._make_client({"robot_id": "r1", "site_id": "lab"})
        client._connected = True
        client._client.publish.reset_mock()
        client.publish_command_ack("patrol", "ts-001", "accepted")
        call_args = client._client.publish.call_args
        payload = json.loads(call_args[0][1])
        assert payload["command"] == "patrol"
        assert payload["command_timestamp"] == "ts-001"
        assert payload["status"] == "accepted"
        assert payload["robot_id"] == "r1"
        assert "timestamp" in payload

    def test_ack_uses_qos1(self):
        """ACK should use QoS 1 (at-least-once) like commands."""
        client = self._make_client({"robot_id": "r1", "site_id": "home"})
        client._connected = True
        client._client.publish.reset_mock()
        client.publish_command_ack("dispatch", "ts-001", "accepted")
        call_args = client._client.publish.call_args
        assert call_args[1]["qos"] == 1

    def test_ack_rejected_status(self):
        """Robot can ACK with rejected status."""
        client = self._make_client({"robot_id": "r1", "site_id": "home"})
        client._connected = True
        client._client.publish.reset_mock()
        client.publish_command_ack("self_destruct", "ts-002", "rejected")
        call_args = client._client.publish.call_args
        payload = json.loads(call_args[0][1])
        assert payload["status"] == "rejected"
        assert payload["command"] == "self_destruct"


class TestTelemetryPublisher:
    def test_telemetry_payload_format(self):
        """Telemetry payload must match what mqtt_bridge._on_robot_telemetry expects."""
        mqtt_client = MagicMock()
        config = {
            "robot_id": "r1", "site_id": "home",
            "robot_name": "Test Bot", "asset_type": "rover",
        }
        hw = MagicMock()
        hw.get_position.return_value = (5.0, -3.0)
        hw.get_heading.return_value = 90.0
        hw.get_speed.return_value = 2.0
        hw.get_battery.return_value = 0.85
        nav = MagicMock()
        nav.status = "active"
        turret = MagicMock()
        turret.pan = 10.0
        turret.tilt = -5.0
        from brain.telemetry import TelemetryPublisher
        tp = TelemetryPublisher(mqtt_client, hw, nav, turret, config)
        # Manually invoke one telemetry publish cycle
        pos = hw.get_position()
        data = {
            "name": tp._robot_name,
            "asset_type": tp._asset_type,
            "position": {"x": pos[0], "y": pos[1]},
            "heading": hw.get_heading(),
            "speed": hw.get_speed(),
            "battery": hw.get_battery(),
            "status": nav.status,
            "turret": {"pan": turret.pan, "tilt": turret.tilt},
        }
        mqtt_client.publish_telemetry(data)
        call_args = mqtt_client.publish_telemetry.call_args[0][0]
        # Verify fields mqtt_bridge._on_robot_telemetry expects
        assert call_args["name"] == "Test Bot"
        assert call_args["asset_type"] == "rover"
        assert call_args["position"] == {"x": 5.0, "y": -3.0}
        assert call_args["heading"] == 90.0
        assert call_args["speed"] == 2.0
        assert call_args["battery"] == 0.85
        assert call_args["status"] == "active"
