"""Unit tests for VirtualNode — no-hardware stub for dashboard testing.

Minimal tests since VirtualNode is just a passthrough to SensorNode defaults.
"""
from __future__ import annotations

import pytest

from amy.nodes.virtual import VirtualNode
from amy.nodes.base import SensorNode, Position


@pytest.mark.unit
class TestVirtualNode:
    """VirtualNode — no-hardware SensorNode."""

    def test_default_construction(self):
        node = VirtualNode()
        assert node.node_id == "virtual"
        assert node.name == "Virtual (no hardware)"

    def test_custom_construction(self):
        node = VirtualNode(node_id="test-node", name="Test Virtual")
        assert node.node_id == "test-node"
        assert node.name == "Test Virtual"

    def test_is_sensor_node(self):
        node = VirtualNode()
        assert isinstance(node, SensorNode)

    def test_no_camera(self):
        node = VirtualNode()
        assert node.has_camera is False

    def test_no_ptz(self):
        node = VirtualNode()
        assert node.has_ptz is False

    def test_no_mic(self):
        node = VirtualNode()
        assert node.has_mic is False

    def test_no_speaker(self):
        node = VirtualNode()
        assert node.has_speaker is False

    def test_get_frame_returns_none(self):
        node = VirtualNode()
        assert node.get_frame() is None

    def test_get_jpeg_returns_none(self):
        node = VirtualNode()
        assert node.get_jpeg() is None

    def test_get_position_returns_default(self):
        node = VirtualNode()
        pos = node.get_position()
        assert isinstance(pos, Position)
        assert pos.pan == 0.0
        assert pos.tilt == 0.0

    def test_start_stop_no_error(self):
        node = VirtualNode()
        node.start()
        node.stop()
