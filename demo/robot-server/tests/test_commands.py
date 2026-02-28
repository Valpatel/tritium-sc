# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for command parsing, ACK format, unknown command handling."""

import json
import sys
import os
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mqtt_client import RobotMQTTClient, parse_command, build_ack


class TestParseCommand:
    """Test command JSON parsing."""

    def test_parse_dispatch(self):
        raw = json.dumps({
            "command": "dispatch",
            "x": 50.0,
            "y": 100.0,
            "timestamp": "2026-02-27T12:00:00Z"
        })
        cmd = parse_command(raw)
        assert cmd["command"] == "dispatch"
        assert cmd["x"] == 50.0
        assert cmd["y"] == 100.0

    def test_parse_patrol(self):
        raw = json.dumps({
            "command": "patrol",
            "waypoints": [{"x": 10, "y": 10}, {"x": 20, "y": 20}],
            "timestamp": "2026-02-27T12:00:00Z"
        })
        cmd = parse_command(raw)
        assert cmd["command"] == "patrol"
        assert len(cmd["waypoints"]) == 2

    def test_parse_recall(self):
        raw = json.dumps({
            "command": "recall",
            "timestamp": "2026-02-27T12:00:00Z"
        })
        cmd = parse_command(raw)
        assert cmd["command"] == "recall"

    def test_parse_fire(self):
        raw = json.dumps({
            "command": "fire",
            "target_x": 30.0,
            "target_y": 40.0,
            "timestamp": "2026-02-27T12:00:00Z"
        })
        cmd = parse_command(raw)
        assert cmd["command"] == "fire"
        assert cmd["target_x"] == 30.0
        assert cmd["target_y"] == 40.0

    def test_parse_aim(self):
        raw = json.dumps({
            "command": "aim",
            "pan": 45.0,
            "tilt": -10.0,
            "timestamp": "2026-02-27T12:00:00Z"
        })
        cmd = parse_command(raw)
        assert cmd["command"] == "aim"
        assert cmd["pan"] == 45.0
        assert cmd["tilt"] == -10.0

    def test_parse_stop(self):
        raw = json.dumps({
            "command": "stop",
            "timestamp": "2026-02-27T12:00:00Z"
        })
        cmd = parse_command(raw)
        assert cmd["command"] == "stop"

    def test_parse_invalid_json(self):
        """Invalid JSON should return None or raise."""
        result = parse_command("not json at all")
        assert result is None

    def test_parse_missing_command_field(self):
        """JSON without 'command' field returns None."""
        raw = json.dumps({"x": 10, "y": 20})
        result = parse_command(raw)
        assert result is None

    def test_parse_bytes_input(self):
        """Should handle bytes (from MQTT payload)."""
        raw = json.dumps({"command": "recall", "timestamp": "2026-02-27T12:00:00Z"}).encode()
        cmd = parse_command(raw)
        assert cmd["command"] == "recall"


class TestBuildAck:
    """Test ACK message format matches spec."""

    def test_ack_structure(self):
        ack = build_ack(
            command="dispatch",
            command_timestamp="2026-02-27T12:00:00Z",
            status="accepted",
            robot_id="demo-rover-01"
        )
        assert ack["command"] == "dispatch"
        assert ack["command_timestamp"] == "2026-02-27T12:00:00Z"
        assert ack["status"] == "accepted"
        assert ack["robot_id"] == "demo-rover-01"
        assert "timestamp" in ack

    def test_ack_timestamp_is_iso8601(self):
        ack = build_ack("recall", "2026-02-27T12:00:00Z", "accepted", "test-01")
        ts = ack["timestamp"]
        assert ts.endswith("Z") or "+00:00" in ts

    def test_ack_rejected_status(self):
        ack = build_ack("unknown_cmd", "2026-02-27T12:00:00Z", "rejected", "test-01")
        assert ack["status"] == "rejected"

    def test_ack_serializes_to_json(self):
        ack = build_ack("dispatch", "2026-02-27T12:00:00Z", "accepted", "test-01")
        serialized = json.dumps(ack)
        parsed = json.loads(serialized)
        assert parsed["command"] == "dispatch"


class TestUnknownCommands:
    """Unknown commands should be rejected gracefully."""

    def test_unknown_command_parsed(self):
        raw = json.dumps({
            "command": "self_destruct",
            "timestamp": "2026-02-27T12:00:00Z"
        })
        cmd = parse_command(raw)
        assert cmd is not None
        assert cmd["command"] == "self_destruct"

    def test_unknown_command_ack_rejected(self):
        """Unknown commands should get a 'rejected' ACK."""
        ack = build_ack("self_destruct", "2026-02-27T12:00:00Z", "rejected", "test-01")
        assert ack["status"] == "rejected"


class TestCommandHandling:
    """Test the full command handling flow with Robot integration."""

    def test_dispatch_command_handling(self):
        """Dispatch command should be handled by robot."""
        from robot import Robot
        r = Robot(robot_id="test-01", asset_type="rover")
        cmd = parse_command(json.dumps({
            "command": "dispatch",
            "x": 10.0,
            "y": 20.0,
            "timestamp": "2026-02-27T12:00:00Z"
        }))
        # Simulate command handling
        if cmd["command"] == "dispatch":
            r.dispatch(cmd["x"], cmd["y"])
        assert r.state == "moving"

    def test_patrol_command_handling(self):
        from robot import Robot
        r = Robot(robot_id="test-01", asset_type="rover")
        cmd = parse_command(json.dumps({
            "command": "patrol",
            "waypoints": [{"x": 5, "y": 0}, {"x": 10, "y": 0}],
            "timestamp": "2026-02-27T12:00:00Z"
        }))
        if cmd["command"] == "patrol":
            r.patrol(cmd["waypoints"])
        assert r.state == "patrolling"

    def test_recall_command_handling(self):
        from robot import Robot
        r = Robot(robot_id="test-01", asset_type="rover")
        r.dispatch(10.0, 0.0)
        cmd = parse_command(json.dumps({
            "command": "recall",
            "timestamp": "2026-02-27T12:00:00Z"
        }))
        if cmd["command"] == "recall":
            r.recall()
        assert r.state == "returning"

    def test_fire_command_handling(self):
        from robot import Robot
        r = Robot(robot_id="test-01", asset_type="rover")
        cmd = parse_command(json.dumps({
            "command": "fire",
            "target_x": 30.0,
            "target_y": 40.0,
            "timestamp": "2026-02-27T12:00:00Z"
        }))
        if cmd["command"] == "fire":
            r.fire(cmd["target_x"], cmd["target_y"])
        assert r.state == "engaging"

    def test_aim_command_handling(self):
        from robot import Robot
        r = Robot(robot_id="test-01", asset_type="rover")
        cmd = parse_command(json.dumps({
            "command": "aim",
            "pan": 45.0,
            "tilt": -10.0,
            "timestamp": "2026-02-27T12:00:00Z"
        }))
        if cmd["command"] == "aim":
            r.aim(cmd["pan"], cmd["tilt"])
        assert r.turret_pan == pytest.approx(45.0)

    def test_stop_command_handling(self):
        from robot import Robot
        r = Robot(robot_id="test-01", asset_type="rover")
        r.dispatch(100.0, 0.0)
        cmd = parse_command(json.dumps({
            "command": "stop",
            "timestamp": "2026-02-27T12:00:00Z"
        }))
        if cmd["command"] == "stop":
            r.stop()
        assert r.state == "idle"


class TestValidCommands:
    """Test the VALID_COMMANDS set."""

    def test_known_commands(self):
        from mqtt_client import VALID_COMMANDS
        expected = {"dispatch", "patrol", "recall", "fire", "aim", "stop"}
        assert expected.issubset(VALID_COMMANDS)
