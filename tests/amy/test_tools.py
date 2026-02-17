"""Unit tests for Amy tool dispatch."""

from __future__ import annotations

import pytest

from amy.tools import TOOL_DEFINITIONS, dispatch_tool_call

from .conftest import MockSensorNode


class _FakeCommander:
    """Minimal stand-in for Commander with a controllable primary_camera."""

    def __init__(self, node=None):
        self._node = node

    @property
    def primary_camera(self):
        return self._node


@pytest.mark.unit
class TestDispatchToolCall:
    """Tests for dispatch_tool_call with various tool names."""

    def test_pan_camera_left(self):
        """pan_camera left calls node.move with pan_dir=-1."""
        node = MockSensorNode()
        cmd = _FakeCommander(node)
        result = dispatch_tool_call(cmd, "pan_camera", {"direction": "left", "duration": 0.5})
        assert result["status"] == "ok"
        assert "panned left" in result["action"]
        assert result["moved"] is True
        assert node._move_log[-1] == (-1, 0, 0.5)

    def test_pan_camera_right(self):
        """pan_camera right calls node.move with pan_dir=1."""
        node = MockSensorNode()
        cmd = _FakeCommander(node)
        result = dispatch_tool_call(cmd, "pan_camera", {"direction": "right"})
        assert result["status"] == "ok"
        assert result["moved"] is True
        assert node._move_log[-1][0] == 1

    def test_tilt_camera_up(self):
        """tilt_camera up calls node.move with tilt_dir=1."""
        node = MockSensorNode()
        cmd = _FakeCommander(node)
        result = dispatch_tool_call(cmd, "tilt_camera", {"direction": "up", "duration": 0.3})
        assert result["status"] == "ok"
        assert "tilted up" in result["action"]
        assert result["moved"] is True
        assert node._move_log[-1] == (0, 1, 0.3)

    def test_tilt_camera_down(self):
        """tilt_camera down calls node.move with tilt_dir=-1."""
        node = MockSensorNode()
        cmd = _FakeCommander(node)
        result = dispatch_tool_call(cmd, "tilt_camera", {"direction": "down"})
        assert result["status"] == "ok"
        assert result["moved"] is True
        assert node._move_log[-1][1] == -1

    def test_move_camera_combined(self):
        """move_camera dispatches combined pan and tilt."""
        node = MockSensorNode()
        cmd = _FakeCommander(node)
        result = dispatch_tool_call(cmd, "move_camera", {
            "pan_dir": 1, "tilt_dir": -1, "duration": 0.4,
        })
        assert result["status"] == "ok"
        assert result["pan_moved"] is True
        assert result["tilt_moved"] is True
        assert node._move_log[-1] == (1, -1, 0.4)

    def test_get_camera_status(self):
        """get_camera_status returns position and limit flags."""
        node = MockSensorNode()
        cmd = _FakeCommander(node)
        result = dispatch_tool_call(cmd, "get_camera_status", {})
        assert result["pan"] == 0.0
        assert result["tilt"] == 0.0
        assert result["zoom"] == 100.0
        assert result["can_pan_left"] is True
        assert result["can_pan_right"] is True
        assert result["can_tilt_up"] is True
        assert result["can_tilt_down"] is True

    def test_reset_camera(self):
        """reset_camera calls node.reset_position."""
        node = MockSensorNode()
        node._position.pan = 50.0
        cmd = _FakeCommander(node)
        result = dispatch_tool_call(cmd, "reset_camera", {})
        assert result["status"] == "ok"
        assert node._reset_count == 1
        assert node._position.pan == 0.0

    def test_unknown_tool_returns_error(self):
        """An unknown tool name returns status 'error'."""
        node = MockSensorNode()
        cmd = _FakeCommander(node)
        result = dispatch_tool_call(cmd, "fly_drone", {"altitude": 100})
        assert result["status"] == "error"
        assert "Unknown tool: fly_drone" in result["message"]

    def test_no_camera_returns_error(self):
        """When primary_camera is None, returns an error."""
        cmd = _FakeCommander(node=None)
        result = dispatch_tool_call(cmd, "pan_camera", {"direction": "left"})
        assert result["status"] == "error"
        assert "No camera connected" in result["message"]


@pytest.mark.unit
class TestToolDefinitions:
    """Tests for TOOL_DEFINITIONS schema validity."""

    def test_all_definitions_have_valid_schema(self):
        """Each tool definition has type='function', function.name, and function.parameters."""
        assert len(TOOL_DEFINITIONS) > 0
        for defn in TOOL_DEFINITIONS:
            assert defn["type"] == "function"
            func = defn["function"]
            assert "name" in func
            assert isinstance(func["name"], str)
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"
