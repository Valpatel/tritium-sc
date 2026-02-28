# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for robot.py — state machine transitions, dispatch/patrol/recall."""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from robot import Robot


class TestRobotCreation:
    """Robot initializes with correct defaults."""

    def test_default_state_idle(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        assert r.state == "idle"

    def test_robot_id(self):
        r = Robot(robot_id="demo-rover-01", asset_type="rover")
        assert r.robot_id == "demo-rover-01"

    def test_asset_type(self):
        r = Robot(robot_id="test-01", asset_type="drone")
        assert r.asset_type == "drone"

    def test_default_name(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        assert r.name == "test-01"

    def test_custom_name(self):
        r = Robot(robot_id="test-01", asset_type="rover", name="Rover Alpha")
        assert r.name == "Rover Alpha"

    def test_start_position(self):
        r = Robot(robot_id="test-01", asset_type="rover", start_x=5.0, start_y=-3.0)
        assert r.x == pytest.approx(5.0)
        assert r.y == pytest.approx(-3.0)

    def test_turret_defaults(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        assert r.turret_pan == 0.0
        assert r.turret_tilt == 0.0


class TestDispatch:
    """dispatch(x, y) transitions to 'moving' and navigates to target."""

    def test_dispatch_changes_state_to_moving(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.dispatch(10.0, 20.0)
        assert r.state == "moving"

    def test_dispatch_sets_target(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.dispatch(10.0, 20.0)
        assert r.target_x == pytest.approx(10.0)
        assert r.target_y == pytest.approx(20.0)

    def test_dispatch_moves_toward_target(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.dispatch(10.0, 0.0)
        # Tick several times
        for _ in range(100):
            r.tick(0.02)
        # Should have moved toward target
        assert r.x > 0

    def test_dispatch_arrives_and_goes_idle(self):
        """Robot transitions to idle when reaching dispatch target."""
        r = Robot(robot_id="test-01", asset_type="rover")
        r.dispatch(1.0, 0.0)
        for _ in range(500):
            r.tick(0.02)
        assert r.state == "idle"

    def test_dispatch_overrides_previous(self):
        """New dispatch overrides previous dispatch target."""
        r = Robot(robot_id="test-01", asset_type="rover")
        r.dispatch(100.0, 0.0)
        r.dispatch(1.0, 0.0)
        assert r.target_x == pytest.approx(1.0)


class TestPatrol:
    """patrol(waypoints) follows a waypoint loop."""

    def test_patrol_changes_state(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        waypoints = [{"x": 5, "y": 0}, {"x": 5, "y": 5}, {"x": 0, "y": 5}]
        r.patrol(waypoints)
        assert r.state == "patrolling"

    def test_patrol_stores_waypoints(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        waypoints = [{"x": 5, "y": 0}, {"x": 10, "y": 0}]
        r.patrol(waypoints)
        assert len(r.patrol_waypoints) == 2

    def test_patrol_moves_toward_first_waypoint(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        waypoints = [{"x": 5, "y": 0}]
        r.patrol(waypoints)
        for _ in range(100):
            r.tick(0.02)
        assert r.x > 0

    def test_patrol_advances_to_next_waypoint(self):
        """After reaching first waypoint, patrol moves to second."""
        r = Robot(robot_id="test-01", asset_type="rover")
        waypoints = [{"x": 1, "y": 0}, {"x": 2, "y": 0}]
        r.patrol(waypoints)
        for _ in range(1000):
            r.tick(0.02)
        # Should have passed through first waypoint
        assert r.x > 0.5

    def test_patrol_loops(self):
        """Patrol loops back to first waypoint after reaching last."""
        r = Robot(robot_id="test-01", asset_type="rover")
        waypoints = [{"x": 1, "y": 0}, {"x": 1, "y": 1}]
        r.patrol(waypoints)
        # Should stay in patrolling state (it loops)
        for _ in range(2000):
            r.tick(0.02)
        assert r.state == "patrolling"

    def test_empty_patrol_stays_idle(self):
        """Empty waypoint list does not change state."""
        r = Robot(robot_id="test-01", asset_type="rover")
        r.patrol([])
        assert r.state == "idle"


class TestRecall:
    """recall() returns to start position."""

    def test_recall_changes_state_to_returning(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.dispatch(10.0, 0.0)
        for _ in range(50):
            r.tick(0.02)
        r.recall()
        assert r.state == "returning"

    def test_recall_navigates_to_start(self):
        r = Robot(robot_id="test-01", asset_type="rover", start_x=5.0, start_y=5.0)
        r.dispatch(20.0, 20.0)
        for _ in range(100):
            r.tick(0.02)
        r.recall()
        for _ in range(2000):
            r.tick(0.02)
        # Should be back near start
        import math
        dist = math.sqrt((r.x - 5.0) ** 2 + (r.y - 5.0) ** 2)
        assert dist < 2.0

    def test_recall_goes_idle_on_arrival(self):
        r = Robot(robot_id="test-01", asset_type="rover", start_x=0.0, start_y=0.0)
        r.dispatch(2.0, 0.0)
        for _ in range(100):
            r.tick(0.02)
        r.recall()
        for _ in range(1000):
            r.tick(0.02)
        assert r.state == "idle"


class TestFire:
    """fire(target_x, target_y) simulates weapon discharge."""

    def test_fire_changes_state_to_engaging(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.fire(10.0, 10.0)
        assert r.state == "engaging"

    def test_fire_records_target(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.fire(10.0, 20.0)
        assert r.fire_target_x == pytest.approx(10.0)
        assert r.fire_target_y == pytest.approx(20.0)

    def test_fire_returns_to_previous_state(self):
        """After firing, robot returns to previous state."""
        r = Robot(robot_id="test-01", asset_type="rover")
        r.fire(10.0, 10.0)
        # After a few ticks, should return to idle
        for _ in range(50):
            r.tick(0.02)
        assert r.state == "idle"

    def test_fire_during_patrol_returns_to_patrol(self):
        """Firing during patrol returns to patrolling after."""
        r = Robot(robot_id="test-01", asset_type="rover")
        r.patrol([{"x": 10, "y": 0}, {"x": 20, "y": 0}])
        r.fire(5.0, 5.0)
        assert r.state == "engaging"
        for _ in range(50):
            r.tick(0.02)
        assert r.state == "patrolling"


class TestAim:
    """aim(pan, tilt) adjusts turret angles."""

    def test_aim_sets_pan(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.aim(45.0, 0.0)
        assert r.turret_pan == pytest.approx(45.0)

    def test_aim_sets_tilt(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.aim(0.0, -10.0)
        assert r.turret_tilt == pytest.approx(-10.0)

    def test_aim_clamps_pan(self):
        """Pan should be clamped to -180..180."""
        r = Robot(robot_id="test-01", asset_type="rover")
        r.aim(200.0, 0.0)
        assert r.turret_pan <= 180.0

    def test_aim_clamps_tilt(self):
        """Tilt should be clamped to -30..90."""
        r = Robot(robot_id="test-01", asset_type="rover")
        r.aim(0.0, 100.0)
        assert r.turret_tilt <= 90.0


class TestStop:
    """stop() halts all movement."""

    def test_stop_from_moving(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.dispatch(100.0, 0.0)
        r.stop()
        assert r.state == "idle"

    def test_stop_from_patrolling(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.patrol([{"x": 10, "y": 0}])
        r.stop()
        assert r.state == "idle"

    def test_stop_clears_velocity(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.dispatch(100.0, 0.0)
        for _ in range(50):
            r.tick(0.02)
        r.stop()
        r.tick(0.02)
        assert r.speed == pytest.approx(0.0, abs=0.01)


class TestTick:
    """tick(dt) advances simulation and returns telemetry dict."""

    def test_tick_returns_telemetry(self):
        r = Robot(robot_id="test-01", asset_type="rover", name="Test Rover")
        tel = r.tick(0.02)
        assert isinstance(tel, dict)

    def test_telemetry_has_required_fields(self):
        r = Robot(robot_id="test-01", asset_type="rover", name="Test Rover")
        tel = r.tick(0.02)
        required = [
            "name", "asset_type", "position", "heading", "speed",
            "battery", "status", "turret", "timestamp",
            "battery_state", "imu", "motor_temps", "odometry"
        ]
        for field in required:
            assert field in tel, f"Missing field: {field}"

    def test_telemetry_position_format(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        tel = r.tick(0.02)
        assert "x" in tel["position"]
        assert "y" in tel["position"]
        assert isinstance(tel["position"]["x"], float)
        assert isinstance(tel["position"]["y"], float)

    def test_telemetry_battery_state_format(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        tel = r.tick(0.02)
        bs = tel["battery_state"]
        assert "charge_pct" in bs
        assert "voltage" in bs
        assert "current_draw" in bs
        assert "temperature_c" in bs

    def test_telemetry_imu_format(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        tel = r.tick(0.02)
        imu = tel["imu"]
        for key in ("roll", "pitch", "yaw", "accel_x", "accel_y", "accel_z"):
            assert key in imu

    def test_telemetry_motor_temps_format(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        tel = r.tick(0.02)
        mt = tel["motor_temps"]
        assert "left" in mt
        assert "right" in mt

    def test_telemetry_odometry_format(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        tel = r.tick(0.02)
        assert "total_distance" in tel["odometry"]

    def test_telemetry_turret_format(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        tel = r.tick(0.02)
        assert "pan" in tel["turret"]
        assert "tilt" in tel["turret"]

    def test_telemetry_timestamp_iso8601(self):
        """Timestamp should be ISO8601 UTC format."""
        r = Robot(robot_id="test-01", asset_type="rover")
        tel = r.tick(0.02)
        ts = tel["timestamp"]
        assert ts.endswith("Z") or "+00:00" in ts
        # Should be parseable
        from datetime import datetime
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_telemetry_status_active_when_moving(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        r.dispatch(10.0, 0.0)
        tel = r.tick(0.02)
        assert tel["status"] == "active"

    def test_telemetry_status_idle_when_idle(self):
        r = Robot(robot_id="test-01", asset_type="rover")
        tel = r.tick(0.02)
        assert tel["status"] == "idle"


class TestTurretOnly:
    """Turret asset type is stationary but can aim and fire."""

    def test_turret_cannot_dispatch(self):
        """Turret should remain stationary even on dispatch."""
        r = Robot(robot_id="test-01", asset_type="turret")
        r.dispatch(10.0, 10.0)
        for _ in range(100):
            r.tick(0.02)
        assert r.x == pytest.approx(0.0, abs=0.1)
        assert r.y == pytest.approx(0.0, abs=0.1)

    def test_turret_can_aim(self):
        r = Robot(robot_id="test-01", asset_type="turret")
        r.aim(45.0, -10.0)
        assert r.turret_pan == pytest.approx(45.0)

    def test_turret_can_fire(self):
        r = Robot(robot_id="test-01", asset_type="turret")
        r.fire(10.0, 10.0)
        assert r.state == "engaging"
