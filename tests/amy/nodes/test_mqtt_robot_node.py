"""Tests for MQTTSensorNode — written before implementation."""
import json
import time
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.unit
class TestMQTTRobotNode:
    def _make_node(self, robot_id="robot-1"):
        from amy.nodes.mqtt_robot import MQTTSensorNode
        bridge = MagicMock()
        bridge.publish = MagicMock()
        node = MQTTSensorNode(bridge, robot_id)
        return node, bridge

    def test_is_sensor_node(self):
        from amy.nodes.base import SensorNode
        from amy.nodes.mqtt_robot import MQTTSensorNode
        node, _ = self._make_node()
        assert isinstance(node, SensorNode)

    def test_node_id(self):
        node, _ = self._make_node("rover-alpha")
        assert node.node_id == "mqtt-rover-alpha"

    def test_has_camera_false(self):
        node, _ = self._make_node()
        assert node.has_camera is False

    def test_dispatch_publishes_mqtt(self):
        node, bridge = self._make_node()
        node.dispatch_to(10.0, 20.0)
        bridge.publish.assert_called_once()
        topic, payload = bridge.publish.call_args[0]
        assert "robots/robot-1/command" in topic
        data = json.loads(payload)
        assert data["action"] == "dispatch"
        assert data["x"] == 10.0
        assert data["y"] == 20.0

    def test_recall_publishes(self):
        node, bridge = self._make_node()
        node.recall()
        bridge.publish.assert_called_once()
        topic, payload = bridge.publish.call_args[0]
        assert "command" in topic
        data = json.loads(payload)
        assert data["action"] == "recall"

    def test_patrol_publishes(self):
        node, bridge = self._make_node()
        waypoints = [{"x": 0, "y": 0}, {"x": 10, "y": 10}]
        node.patrol(waypoints)
        bridge.publish.assert_called_once()
        topic, payload = bridge.publish.call_args[0]
        data = json.loads(payload)
        assert data["action"] == "patrol"
        assert len(data["waypoints"]) == 2

    def test_telemetry_update(self):
        node, _ = self._make_node()
        node.update_telemetry({
            "x": 5.0, "y": 10.0, "heading": 90.0,
            "battery": 0.75, "status": "active"
        })
        assert node.world_position == (5.0, 10.0)
        assert node._heading == 90.0
        assert node._battery == 0.75
        assert node._status == "active"

    def test_stale_before_telemetry(self):
        node, _ = self._make_node()
        assert node.is_stale is True

    def test_stale_after_telemetry(self):
        node, _ = self._make_node()
        node.update_telemetry({"x": 0, "y": 0})
        assert node.is_stale is False

    def test_world_position_default(self):
        node, _ = self._make_node()
        assert node.world_position == (0.0, 0.0)
