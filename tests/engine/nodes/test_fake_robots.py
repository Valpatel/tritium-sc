# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for fake MQTT robot fleet (scripts/fake_robots.py).

Tests the FakeRobot class logic: physics ticking, telemetry format,
command handling. Uses MagicMock for MQTT client — no broker needed.
"""
import json
import pytest
from unittest.mock import MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from scripts.fake_robots import FakeRobot

pytestmark = pytest.mark.unit


class TestFakeRobotInit:
    def test_creates_with_random_position(self):
        client = MagicMock()
        robot = FakeRobot("test-01", client)
        assert robot.robot_id == "test-01"
        assert robot.target.asset_type == "rover"
        assert robot.target.alliance == "friendly"
        assert -20 <= robot.target.position[0] <= 20
        assert -20 <= robot.target.position[1] <= 20

    def test_has_patrol_waypoints(self):
        client = MagicMock()
        robot = FakeRobot("test-01", client)
        assert len(robot.target.waypoints) >= 3
        assert robot.target.loop_waypoints is True

    def test_custom_site(self):
        client = MagicMock()
        robot = FakeRobot("test-01", client, site="office")
        assert robot.site == "office"


class TestFakeRobotTick:
    def test_tick_moves_robot(self):
        client = MagicMock()
        robot = FakeRobot("test-01", client)
        pos_before = robot.target.position
        for _ in range(100):
            robot.tick(0.1)
        pos_after = robot.target.position
        dx = abs(pos_after[0] - pos_before[0])
        dy = abs(pos_after[1] - pos_before[1])
        assert dx > 0.1 or dy > 0.1, "Robot should move after 100 ticks"


class TestFakeRobotTelemetry:
    def test_publishes_correct_topic(self):
        client = MagicMock()
        robot = FakeRobot("rover-01", client, site="home")
        robot.publish_telemetry()
        client.publish.assert_called_once()
        topic = client.publish.call_args[0][0]
        assert topic == "tritium/home/robots/rover-01/telemetry"

    def test_payload_has_required_fields(self):
        client = MagicMock()
        robot = FakeRobot("rover-01", client)
        robot.publish_telemetry()
        payload = json.loads(client.publish.call_args[0][1])
        assert payload["robot_id"] == "rover-01"
        for key in ("x", "y", "heading", "battery", "status", "timestamp"):
            assert key in payload, f"Missing key: {key}"

    def test_payload_uses_flat_position_keys(self):
        """Telemetry uses flat x/y keys (not nested position dict)."""
        client = MagicMock()
        robot = FakeRobot("rover-01", client)
        robot.publish_telemetry()
        payload = json.loads(client.publish.call_args[0][1])
        assert isinstance(payload["x"], float)
        assert isinstance(payload["y"], float)
        assert "position" not in payload


class TestFakeRobotCommands:
    def test_dispatch_sets_waypoint(self):
        client = MagicMock()
        robot = FakeRobot("rover-01", client)
        robot.handle_command({"action": "dispatch", "x": 10.0, "y": 5.0})
        assert robot.target.waypoints == [(10.0, 5.0)]
        assert robot.target.loop_waypoints is False
        assert robot.target.status == "active"

    def test_patrol_sets_waypoints(self):
        client = MagicMock()
        robot = FakeRobot("rover-01", client)
        wps = [{"x": 0, "y": 0}, {"x": 10, "y": 10}]
        robot.handle_command({"action": "patrol", "waypoints": wps})
        assert robot.target.waypoints == [(0, 0), (10, 10)]
        assert robot.target.loop_waypoints is True

    def test_recall_goes_to_origin(self):
        client = MagicMock()
        robot = FakeRobot("rover-01", client)
        robot.handle_command({"action": "recall"})
        assert robot.target.waypoints == [(0, 0)]
        assert robot.target.loop_waypoints is False

    def test_command_publishes_ack(self):
        client = MagicMock()
        robot = FakeRobot("rover-01", client, site="home")
        robot.handle_command({"action": "dispatch", "x": 5, "y": 5})
        calls = client.publish.call_args_list
        ack_call = calls[-1]
        topic = ack_call[0][0]
        payload = json.loads(ack_call[0][1])
        assert topic == "tritium/home/robots/rover-01/command/ack"
        assert payload["action"] == "dispatch"
        assert payload["status"] == "acknowledged"

    def test_unknown_action_still_acks(self):
        client = MagicMock()
        robot = FakeRobot("rover-01", client)
        robot.handle_command({"action": "self_destruct"})
        assert client.publish.called
        payload = json.loads(client.publish.call_args[0][1])
        assert payload["action"] == "self_destruct"
        assert payload["status"] == "acknowledged"
