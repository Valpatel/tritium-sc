"""Unit tests for IPCameraNode — RTSP IP camera sensor node stub.

Tests construction, capabilities, and SensorNode inheritance.
"""
from __future__ import annotations

import pytest

from engine.nodes.ip_camera import IPCameraNode
from engine.nodes.base import SensorNode


@pytest.mark.unit
class TestIPCameraNode:
    """IPCameraNode — RTSP camera (view-only)."""

    def test_construction(self):
        node = IPCameraNode(
            node_id="cam-01", name="Front Door",
            rtsp_url="rtsp://10.0.0.5:554/stream1",
        )
        assert node.node_id == "cam-01"
        assert node.name == "Front Door"
        assert node.rtsp_url == "rtsp://10.0.0.5:554/stream1"

    def test_is_sensor_node(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://x")
        assert isinstance(node, SensorNode)

    def test_has_camera_true(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://x")
        assert node.has_camera is True

    def test_no_ptz(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://x")
        assert node.has_ptz is False

    def test_no_mic(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://x")
        assert node.has_mic is False

    def test_no_speaker(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://x")
        assert node.has_speaker is False

    def test_get_frame_none_stub(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://x")
        assert node.get_frame() is None

    def test_get_jpeg_none_stub(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://x")
        assert node.get_jpeg() is None
