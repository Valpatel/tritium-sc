"""Unit tests for SensorNode abstract base class and Position dataclass.

Tests default behavior (no-op implementations) and Position limit awareness.
"""
from __future__ import annotations

import numpy as np
import pytest

from engine.nodes.base import Position, SensorNode


# ===========================================================================
# Position Dataclass
# ===========================================================================

@pytest.mark.unit
class TestPosition:
    """Position — PTZ position with limit awareness."""

    def test_defaults(self):
        p = Position()
        assert p.pan == 0.0
        assert p.tilt == 0.0
        assert p.zoom == 100.0

    def test_no_limits(self):
        p = Position()
        assert p.can_pan_left is True
        assert p.can_pan_right is True
        assert p.can_tilt_up is True
        assert p.can_tilt_down is True

    def test_pan_limits(self):
        p = Position(pan=-90, pan_min=-90, pan_max=90)
        assert p.can_pan_left is False  # At min
        assert p.can_pan_right is True

    def test_pan_at_max(self):
        p = Position(pan=90, pan_min=-90, pan_max=90)
        assert p.can_pan_left is True
        assert p.can_pan_right is False  # At max

    def test_pan_in_range(self):
        p = Position(pan=0, pan_min=-90, pan_max=90)
        assert p.can_pan_left is True
        assert p.can_pan_right is True

    def test_tilt_limits(self):
        p = Position(tilt=-30, tilt_min=-30, tilt_max=30)
        assert p.can_tilt_up is True
        assert p.can_tilt_down is False  # At min

    def test_tilt_at_max(self):
        p = Position(tilt=30, tilt_min=-30, tilt_max=30)
        assert p.can_tilt_up is False  # At max
        assert p.can_tilt_down is True

    def test_mixed_limits(self):
        """Some axes limited, some not."""
        p = Position(pan=0, tilt=0, pan_min=-45, pan_max=45)
        assert p.can_pan_left is True
        assert p.can_pan_right is True
        # Tilt has no limits
        assert p.can_tilt_up is True
        assert p.can_tilt_down is True


# ===========================================================================
# SensorNode — Concrete Subclass for Testing
# ===========================================================================

class _TestNode(SensorNode):
    """Minimal concrete subclass for testing."""
    pass


# ===========================================================================
# SensorNode — Default Behavior
# ===========================================================================

@pytest.mark.unit
class TestSensorNodeDefaults:
    """SensorNode — default (no-op) implementations."""

    def test_construction(self):
        node = _TestNode("node-1", "Test Node")
        assert node.node_id == "node-1"
        assert node.name == "Test Node"

    def test_capabilities_false(self):
        node = _TestNode("n1", "Test")
        assert node.has_camera is False
        assert node.has_ptz is False
        assert node.has_mic is False
        assert node.has_speaker is False

    def test_get_frame_returns_none(self):
        node = _TestNode("n1", "Test")
        assert node.get_frame() is None

    def test_get_jpeg_returns_none(self):
        node = _TestNode("n1", "Test")
        assert node.get_jpeg() is None

    def test_frame_id_zero(self):
        node = _TestNode("n1", "Test")
        assert node.frame_id == 0

    def test_move_returns_false(self):
        node = _TestNode("n1", "Test")
        pan_moved, tilt_moved = node.move(1, 1, 0.5)
        assert pan_moved is False
        assert tilt_moved is False

    def test_get_position_default(self):
        node = _TestNode("n1", "Test")
        pos = node.get_position()
        assert isinstance(pos, Position)
        assert pos.pan == 0.0

    def test_reset_position_no_error(self):
        node = _TestNode("n1", "Test")
        node.reset_position()  # Should not raise

    def test_record_audio_returns_none(self):
        node = _TestNode("n1", "Test")
        assert node.record_audio(1.0) is None

    def test_play_audio_no_error(self):
        node = _TestNode("n1", "Test")
        node.play_audio(b"\x00" * 100)  # Should not raise

    def test_start_stop_no_error(self):
        node = _TestNode("n1", "Test")
        node.start()
        node.stop()
