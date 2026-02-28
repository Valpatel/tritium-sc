# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for AudioNode — standalone mic/speaker sensor node stub.

Tests construction, capabilities, and SensorNode inheritance.
"""
from __future__ import annotations

import pytest

from engine.nodes.audio import AudioNode
from engine.nodes.base import SensorNode


@pytest.mark.unit
class TestAudioNode:
    """AudioNode — standalone mic/speaker."""

    def test_construction(self):
        node = AudioNode(node_id="mic-01", name="Hallway Mic")
        assert node.node_id == "mic-01"
        assert node.name == "Hallway Mic"

    def test_is_sensor_node(self):
        node = AudioNode(node_id="m1", name="Test")
        assert isinstance(node, SensorNode)

    def test_has_mic_true(self):
        node = AudioNode(node_id="m1", name="Test")
        assert node.has_mic is True

    def test_has_speaker_false_by_default(self):
        node = AudioNode(node_id="m1", name="Test")
        assert node.has_speaker is False

    def test_has_speaker_with_output(self):
        node = AudioNode(node_id="m1", name="Test", output_device="hw:0,0")
        assert node.has_speaker is True

    def test_no_camera(self):
        node = AudioNode(node_id="m1", name="Test")
        assert node.has_camera is False

    def test_no_ptz(self):
        node = AudioNode(node_id="m1", name="Test")
        assert node.has_ptz is False

    def test_input_device_default(self):
        node = AudioNode(node_id="m1", name="Test")
        assert node.input_device is None

    def test_input_device_custom(self):
        node = AudioNode(node_id="m1", name="Test", input_device=3)
        assert node.input_device == 3

    def test_output_device_default(self):
        node = AudioNode(node_id="m1", name="Test")
        assert node.output_device is None

    def test_get_frame_none(self):
        node = AudioNode(node_id="m1", name="Test")
        assert node.get_frame() is None
