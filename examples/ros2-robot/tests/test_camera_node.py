# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the ROS2 synthetic camera node.

Tests verify frame generation, MQTT publishing, detection format,
scene configuration, and toggle behavior.

All ROS2 dependencies are mocked -- tests work without ROS2 installed.
"""

from __future__ import annotations

import json
import os
import sys
import time
import types
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Mock ROS2 dependencies before importing our code
# ---------------------------------------------------------------------------

_PARAM_DEFAULTS = {
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    "site_id": "home",
    "robot_id": "test-cam-bot",
    "robot_name": "Test Camera Bot",
    "asset_type": "rover",
    "camera_enabled": True,
    "camera_scene_type": "bird_eye",
    "camera_fps": 5,
    "camera_width": 320,
    "camera_height": 240,
}


class _MockNode:
    """Minimal mock of rclpy.node.Node for CameraNode."""

    def __init__(self, name: str = "mock_node"):
        self._node_name = name

    def declare_parameter(self, name, default=None):
        pass

    def get_parameter(self, name):
        val = _PARAM_DEFAULTS.get(name, "")
        result = MagicMock()
        result.value = val
        return result

    def get_logger(self):
        return MagicMock()

    def create_timer(self, period, callback):
        return MagicMock()

    def create_subscription(self, msg_type, topic, callback, qos):
        return MagicMock()

    def create_publisher(self, msg_type, topic, qos):
        return MagicMock()

    def get_clock(self):
        return MagicMock()

    def destroy_node(self):
        pass


# Build mock modules
_rclpy_mod = types.ModuleType("rclpy")
_rclpy_node_mod = types.ModuleType("rclpy.node")
_rclpy_node_mod.Node = _MockNode
_rclpy_mod.node = _rclpy_node_mod

_mock = MagicMock()

for mod_name in [
    "rclpy", "rclpy.node", "rclpy.action", "rclpy.action.client",
    "geometry_msgs", "geometry_msgs.msg",
    "nav_msgs", "nav_msgs.msg",
    "sensor_msgs", "sensor_msgs.msg",
    "nav2_msgs", "nav2_msgs.action",
    "tf2_ros",
    "paho", "paho.mqtt", "paho.mqtt.client",
]:
    sys.modules.setdefault(mod_name, _mock)

# Override the specific modules that need real classes
sys.modules["rclpy"] = _rclpy_mod
sys.modules["rclpy.node"] = _rclpy_node_mod

# Add ros2-robot package to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Add project root to path for amy.synthetic imports
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "..",
))

from ros2_robot.camera_node import CameraNode


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(**overrides) -> CameraNode:
    """Create a CameraNode with optional parameter overrides."""
    if overrides:
        old_defaults = dict(_PARAM_DEFAULTS)
        _PARAM_DEFAULTS.update(overrides)
        try:
            node = CameraNode()
        finally:
            _PARAM_DEFAULTS.clear()
            _PARAM_DEFAULTS.update(old_defaults)
    else:
        node = CameraNode()
    return node


# ===========================================================================
# Test classes
# ===========================================================================


class TestCameraNodeInit:
    """Verify CameraNode initializes correctly with config params."""

    def test_creates_with_defaults(self):
        node = _make_node()
        assert node is not None

    def test_scene_type_from_param(self):
        node = _make_node()
        assert node._scene_type == "bird_eye"

    def test_fps_from_param(self):
        node = _make_node()
        assert node._fps == 5

    def test_resolution_from_params(self):
        node = _make_node()
        assert node._width == 320
        assert node._height == 240

    def test_robot_id_from_param(self):
        node = _make_node()
        assert node._robot_id == "test-cam-bot"

    def test_site_id_from_param(self):
        node = _make_node()
        assert node._site == "home"

    def test_no_hardcoded_ips(self):
        """Default mqtt_host must be 'localhost', not an IP."""
        node = _make_node()
        assert node._mqtt_host == "localhost"

    def test_camera_enabled_by_default(self):
        node = _make_node()
        assert node._camera_enabled is True


class TestCameraNodeFrameGeneration:
    """Test that frames are generated correctly from renderers."""

    def test_generate_frame_returns_bgr_array(self):
        node = _make_node()
        frame = node.generate_frame()
        assert isinstance(frame, np.ndarray)
        assert frame.dtype == np.uint8
        assert frame.shape == (240, 320, 3)

    def test_generate_frame_nonzero(self):
        """Frame should not be entirely black."""
        node = _make_node()
        frame = node.generate_frame()
        assert np.max(frame) > 0

    def test_generate_jpeg_valid(self):
        """JPEG bytes should start with the magic bytes."""
        node = _make_node()
        jpeg = node.generate_jpeg()
        assert jpeg is not None
        assert jpeg[:2] == b"\xff\xd8", "Should start with JPEG magic bytes"
        assert len(jpeg) > 100, "JPEG should have meaningful size"

    def test_scene_type_bird_eye(self):
        node = _make_node(camera_scene_type="bird_eye")
        frame = node.generate_frame()
        assert frame.shape == (240, 320, 3)

    def test_scene_type_street_cam(self):
        node = _make_node(camera_scene_type="street_cam")
        frame = node.generate_frame()
        assert frame.shape == (240, 320, 3)

    def test_scene_type_battle(self):
        node = _make_node(camera_scene_type="battle")
        frame = node.generate_frame()
        assert frame.shape == (240, 320, 3)

    def test_scene_type_neighborhood(self):
        node = _make_node(camera_scene_type="neighborhood")
        frame = node.generate_frame()
        assert frame.shape == (240, 320, 3)

    def test_resolution_respected(self):
        node = _make_node(camera_width=640, camera_height=480)
        frame = node.generate_frame()
        assert frame.shape == (480, 640, 3)

    def test_frame_count_increments(self):
        node = _make_node()
        assert node._frame_count == 0
        node.generate_frame()
        assert node._frame_count == 1
        node.generate_frame()
        assert node._frame_count == 2


class TestCameraNodeMQTTPublishing:
    """Test MQTT message formatting and topics."""

    def test_frame_topic_format(self):
        """Frame topic: tritium/{site}/cameras/{robot_id}/frame."""
        node = _make_node()
        expected = f"tritium/{node._site}/cameras/{node._robot_id}/frame"
        assert expected == "tritium/home/cameras/test-cam-bot/frame"

    def test_detection_topic_format(self):
        """Detection topic: tritium/{site}/cameras/{robot_id}/detections."""
        node = _make_node()
        expected = f"tritium/{node._site}/cameras/{node._robot_id}/detections"
        assert expected == "tritium/home/cameras/test-cam-bot/detections"

    def test_build_detection_payload(self):
        """Detection payload should be valid JSON with target counts."""
        node = _make_node()
        payload = node.build_detection_payload()
        assert isinstance(payload, dict)
        assert "camera_id" in payload
        assert "detections" in payload
        assert isinstance(payload["detections"], list)
        assert "frame_id" in payload

    def test_detection_payload_camera_id(self):
        node = _make_node()
        payload = node.build_detection_payload()
        assert payload["camera_id"] == "test-cam-bot"

    def test_publish_frame_mqtt(self):
        """publish_frame should send JPEG bytes to the frame topic."""
        node = _make_node()
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        node._mqtt_client = mock_client

        node.publish_frame()

        expected_topic = f"tritium/{node._site}/cameras/{node._robot_id}/frame"
        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        assert call_args[0][0] == expected_topic
        # Payload should be JPEG bytes
        payload = call_args[0][1]
        assert isinstance(payload, bytes)
        assert payload[:2] == b"\xff\xd8"

    def test_publish_detections_mqtt(self):
        """publish_detections should send JSON to the detections topic."""
        node = _make_node()
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        node._mqtt_client = mock_client

        node.publish_detections()

        expected_topic = f"tritium/{node._site}/cameras/{node._robot_id}/detections"
        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        assert call_args[0][0] == expected_topic
        # Payload should be valid JSON
        payload_str = call_args[0][1]
        payload = json.loads(payload_str)
        assert "camera_id" in payload

    def test_publish_frame_skipped_when_disabled(self):
        """When camera is disabled, publish_frame should not send."""
        node = _make_node()
        node._camera_enabled = False
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        node._mqtt_client = mock_client

        node.publish_frame()
        mock_client.publish.assert_not_called()

    def test_publish_frame_skipped_when_disconnected(self):
        """When MQTT is disconnected, publish should not crash."""
        node = _make_node()
        mock_client = MagicMock()
        mock_client.is_connected.return_value = False
        node._mqtt_client = mock_client

        node.publish_frame()
        mock_client.publish.assert_not_called()


class TestCameraNodeToggle:
    """Test on/off toggle via MQTT command."""

    def test_toggle_off(self):
        node = _make_node()
        assert node._camera_enabled is True
        node.handle_camera_command({"command": "camera_off"})
        assert node._camera_enabled is False

    def test_toggle_on(self):
        node = _make_node()
        node._camera_enabled = False
        node.handle_camera_command({"command": "camera_on"})
        assert node._camera_enabled is True

    def test_toggle_with_unknown_command(self):
        """Unknown camera commands should not crash or change state."""
        node = _make_node()
        original = node._camera_enabled
        node.handle_camera_command({"command": "camera_dance"})
        assert node._camera_enabled == original

    def test_toggle_preserves_other_state(self):
        node = _make_node()
        node.generate_frame()  # increment frame count
        count_before = node._frame_count
        node.handle_camera_command({"command": "camera_off"})
        assert node._frame_count == count_before


class TestCameraNodeDetections:
    """Test YOLO-style detection output."""

    def test_detection_has_bbox_format(self):
        """Each detection should have class_name, confidence, bbox."""
        node = _make_node()
        # Inject some demo targets to get detections
        node._targets = [
            {"target_id": "hostile-1", "alliance": "hostile", "asset_type": "person",
             "position": {"x": 5.0, "y": 5.0}},
        ]
        payload = node.build_detection_payload()
        assert len(payload["detections"]) > 0
        det = payload["detections"][0]
        assert "class_name" in det
        assert "confidence" in det
        assert "bbox" in det

    def test_detection_confidence_range(self):
        """Confidence should be 0.0-1.0."""
        node = _make_node()
        node._targets = [
            {"target_id": "h-1", "alliance": "hostile", "asset_type": "person",
             "position": {"x": 0, "y": 0}},
        ]
        payload = node.build_detection_payload()
        for det in payload["detections"]:
            assert 0.0 <= det["confidence"] <= 1.0

    def test_detection_class_name_from_asset_type(self):
        """Class name should map from asset type."""
        node = _make_node()
        node._targets = [
            {"target_id": "r-1", "alliance": "friendly", "asset_type": "rover",
             "position": {"x": 0, "y": 0}},
        ]
        payload = node.build_detection_payload()
        assert payload["detections"][0]["class_name"] == "rover"

    def test_detection_bbox_has_four_values(self):
        """bbox should be [x1, y1, x2, y2]."""
        node = _make_node()
        node._targets = [
            {"target_id": "t-1", "alliance": "friendly", "asset_type": "turret",
             "position": {"x": 0, "y": 0}},
        ]
        payload = node.build_detection_payload()
        bbox = payload["detections"][0]["bbox"]
        assert len(bbox) == 4
        assert all(isinstance(v, (int, float)) for v in bbox)

    def test_empty_targets_empty_detections(self):
        """No targets means no detections."""
        node = _make_node()
        node._targets = []
        payload = node.build_detection_payload()
        assert payload["detections"] == []


class TestCameraNodeSceneConfig:
    """Test that scene configuration is properly passed to renderers."""

    def test_valid_scene_types(self):
        """All four scene types should work."""
        for scene in ["bird_eye", "street_cam", "battle", "neighborhood"]:
            node = _make_node(camera_scene_type=scene)
            frame = node.generate_frame()
            assert frame is not None
            assert frame.shape[2] == 3

    def test_invalid_scene_type_falls_back(self):
        """Invalid scene type should fall back to bird_eye."""
        node = _make_node(camera_scene_type="nonexistent_scene")
        frame = node.generate_frame()
        assert frame is not None
        assert frame.shape == (240, 320, 3)


class TestCameraNodeProtocolCompatibility:
    """Ensure camera node speaks TRITIUM-SC camera protocol."""

    def test_frame_topic_matches_tritium_pattern(self):
        """Frame topic must match: tritium/{site}/cameras/{id}/frame."""
        node = _make_node()
        topic = f"tritium/{node._site}/cameras/{node._robot_id}/frame"
        parts = topic.split("/")
        assert parts[0] == "tritium"
        assert parts[2] == "cameras"
        assert parts[4] == "frame"

    def test_detection_topic_matches_tritium_pattern(self):
        """Detection topic must match: tritium/{site}/cameras/{id}/detections."""
        node = _make_node()
        topic = f"tritium/{node._site}/cameras/{node._robot_id}/detections"
        parts = topic.split("/")
        assert parts[0] == "tritium"
        assert parts[2] == "cameras"
        assert parts[4] == "detections"

    def test_detection_payload_json_serializable(self):
        """Detection payload must be JSON-serializable."""
        node = _make_node()
        node._targets = [
            {"target_id": "h-1", "alliance": "hostile", "asset_type": "person",
             "position": {"x": 3, "y": -2}},
        ]
        payload = node.build_detection_payload()
        serialized = json.dumps(payload)
        deserialized = json.loads(serialized)
        assert deserialized["camera_id"] == node._robot_id

    def test_no_hardcoded_hostnames(self):
        """No hardcoded IPs in default config."""
        node = _make_node()
        assert node._mqtt_host == "localhost"
        assert "192" not in str(node._mqtt_host)
        assert "10." not in str(node._mqtt_host)


class TestCameraNodeCommandSubscription:
    """Test that camera node subscribes to camera command topic."""

    def test_command_topic_format(self):
        """Camera command topic: tritium/{site}/cameras/{id}/command."""
        node = _make_node()
        expected = f"tritium/{node._site}/cameras/{node._robot_id}/command"
        assert expected == "tritium/home/cameras/test-cam-bot/command"

    def test_handle_camera_command_on(self):
        node = _make_node()
        node._camera_enabled = False
        node.handle_camera_command({"command": "camera_on"})
        assert node._camera_enabled is True

    def test_handle_camera_command_off(self):
        node = _make_node()
        node.handle_camera_command({"command": "camera_off"})
        assert node._camera_enabled is False

    def test_handle_camera_command_set_scene(self):
        node = _make_node()
        node.handle_camera_command({
            "command": "set_scene",
            "scene_type": "street_cam",
        })
        assert node._scene_type == "street_cam"

    def test_handle_camera_command_set_fps(self):
        node = _make_node()
        node.handle_camera_command({"command": "set_fps", "fps": 10})
        assert node._fps == 10

    def test_set_scene_invalid_ignored(self):
        """Invalid scene type in command should be ignored."""
        node = _make_node()
        original = node._scene_type
        node.handle_camera_command({
            "command": "set_scene",
            "scene_type": "nonexistent",
        })
        assert node._scene_type == original
