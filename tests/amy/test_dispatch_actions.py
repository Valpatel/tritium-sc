"""Unit tests for dispatch/alert/patrol Lua actions."""

from __future__ import annotations

import pytest

from amy.lua_motor import parse_motor_output

pytestmark = pytest.mark.unit


class TestDispatchAction:
    def test_parse_dispatch(self):
        result = parse_motor_output('dispatch("target1", 10.0, 20.0)')
        assert result.valid
        assert result.action == "dispatch"
        assert result.params[0] == "target1"
        assert result.params[1] == 10.0
        assert result.params[2] == 20.0

    def test_dispatch_integer_coords(self):
        result = parse_motor_output('dispatch("rover-1", 5, 15)')
        assert result.valid
        assert result.action == "dispatch"
        assert result.params[1] == 5.0
        assert result.params[2] == 15.0

    def test_dispatch_invalid_target_type(self):
        result = parse_motor_output('dispatch(42, 10.0, 20.0)')
        assert not result.valid
        assert "string target_id" in result.error

    def test_dispatch_invalid_x_type(self):
        result = parse_motor_output('dispatch("target1", "north", 20.0)')
        assert not result.valid
        assert "x must be a number" in result.error

    def test_dispatch_invalid_y_type(self):
        result = parse_motor_output('dispatch("target1", 10.0, "east")')
        assert not result.valid
        assert "y must be a number" in result.error

    def test_dispatch_too_few_params(self):
        result = parse_motor_output('dispatch("target1", 10.0)')
        assert not result.valid
        assert "at least 3" in result.error


class TestAlertAction:
    def test_parse_alert(self):
        result = parse_motor_output('alert("target1", "hostile approaching")')
        assert result.valid
        assert result.action == "alert"
        assert result.params[0] == "target1"
        assert result.params[1] == "hostile approaching"

    def test_alert_invalid_target_type(self):
        result = parse_motor_output('alert(123, "message")')
        assert not result.valid
        assert "string target_id" in result.error

    def test_alert_invalid_message_type(self):
        result = parse_motor_output('alert("target1", 42)')
        assert not result.valid
        assert "string message" in result.error

    def test_alert_too_few_params(self):
        result = parse_motor_output('alert("target1")')
        assert not result.valid
        assert "at least 2" in result.error


class TestPatrolAction:
    def test_parse_patrol(self):
        result = parse_motor_output('patrol("target1", "[[0,0],[10,10]]")')
        assert result.valid
        assert result.action == "patrol"
        assert result.params[0] == "target1"
        assert result.params[1] == "[[0,0],[10,10]]"

    def test_patrol_invalid_target_type(self):
        result = parse_motor_output('patrol(123, "[[0,0]]")')
        assert not result.valid
        assert "string target_id" in result.error

    def test_patrol_invalid_waypoints_type(self):
        result = parse_motor_output('patrol("target1", 42)')
        assert not result.valid
        assert "JSON waypoints string" in result.error

    def test_patrol_too_few_params(self):
        result = parse_motor_output('patrol("target1")')
        assert not result.valid
        assert "at least 2" in result.error


class TestDispatchBoundsClamp:
    """Test that dispatch coordinates are clamped to [-30, 30]."""

    def test_dispatch_coords_clamped_high(self):
        result = parse_motor_output('dispatch("r1", 50.0, 100.0)')
        assert result.valid
        assert result.params[1] == 30.0
        assert result.params[2] == 30.0

    def test_dispatch_coords_clamped_low(self):
        result = parse_motor_output('dispatch("r1", -50.0, -100.0)')
        assert result.valid
        assert result.params[1] == -30.0
        assert result.params[2] == -30.0

    def test_dispatch_coords_within_bounds_unchanged(self):
        result = parse_motor_output('dispatch("r1", 15.0, -20.0)')
        assert result.valid
        assert result.params[1] == 15.0
        assert result.params[2] == -20.0


class TestPatrolJsonValidation:
    """Test that patrol waypoints are validated as JSON."""

    def test_patrol_valid_json(self):
        result = parse_motor_output('patrol("r1", "[[0,0],[10,10],[5,5]]")')
        assert result.valid

    def test_patrol_invalid_json(self):
        result = parse_motor_output('patrol("r1", "not json")')
        assert not result.valid
        assert "valid JSON" in result.error

    def test_patrol_empty_array(self):
        result = parse_motor_output('patrol("r1", "[]")')
        assert not result.valid
        assert "non-empty" in result.error

    def test_patrol_wrong_waypoint_format(self):
        result = parse_motor_output('patrol("r1", "[[1,2],[3]]")')
        assert not result.valid
        assert "waypoint" in result.error.lower()

    def test_patrol_non_numeric_coords(self):
        result = parse_motor_output('patrol("r1", "[[1,\\"a\\"]]")')
        assert not result.valid
