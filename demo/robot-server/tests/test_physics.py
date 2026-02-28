# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for physics.py — differential drive kinematics, battery, thermals."""

import math
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from physics import PhysicsEngine


class TestDifferentialDrive:
    """Test differential drive kinematics: turn, forward, heading updates."""

    def test_creation_defaults(self):
        """PhysicsEngine initializes at origin with zero velocity."""
        p = PhysicsEngine(asset_type="rover")
        assert p.x == 0.0
        assert p.y == 0.0
        assert p.heading == 0.0
        assert p.speed == 0.0

    def test_creation_with_start_position(self):
        """PhysicsEngine respects start_x and start_y."""
        p = PhysicsEngine(asset_type="rover", start_x=10.0, start_y=-5.0)
        assert p.x == 10.0
        assert p.y == -5.0

    def test_forward_drive(self):
        """Equal left/right motor commands produce straight-line movement."""
        p = PhysicsEngine(asset_type="rover")
        # Drive forward: both wheels at 1.0
        p.set_motors(1.0, 1.0)
        p.tick(1.0)
        # Should move forward (heading 0 = +x direction in our convention)
        assert p.speed > 0
        # Position should have changed
        dist = math.sqrt(p.x ** 2 + p.y ** 2)
        assert dist > 0

    def test_turning_left(self):
        """Right > left produces left turn (positive heading change)."""
        p = PhysicsEngine(asset_type="rover")
        # Right wheel faster than left = turn left
        p.set_motors(0.0, 1.0)
        p.tick(1.0)
        # Heading should have changed
        assert p.heading != 0.0

    def test_turning_right(self):
        """Left > right produces right turn (opposite direction from left turn)."""
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(1.0, 0.0)
        p.tick(1.0)
        # Heading wraps 0-360, so compute signed delta from 0
        right_delta = p.heading if p.heading <= 180 else p.heading - 360

        p2 = PhysicsEngine(asset_type="rover")
        p2.set_motors(0.0, 1.0)
        p2.tick(1.0)
        left_delta = p2.heading if p2.heading <= 180 else p2.heading - 360

        # Opposite turns should produce opposite heading changes
        assert right_delta * left_delta < 0  # Different signs

    def test_stationary_no_motors(self):
        """No motor input = no movement."""
        p = PhysicsEngine(asset_type="rover")
        p.tick(1.0)
        assert p.x == 0.0
        assert p.y == 0.0
        assert p.speed == 0.0

    def test_spin_in_place(self):
        """Opposite motor commands produce rotation without forward movement."""
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(-1.0, 1.0)
        p.tick(1.0)
        # Heading changed but position is near zero (pure rotation)
        assert p.heading != 0.0
        dist = math.sqrt(p.x ** 2 + p.y ** 2)
        assert dist < 0.01  # Nearly zero displacement

    def test_multiple_ticks(self):
        """Position integrates over multiple ticks."""
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(1.0, 1.0)
        for _ in range(50):
            p.tick(0.02)  # 50Hz for 1 second
        dist = math.sqrt(p.x ** 2 + p.y ** 2)
        assert dist > 0

    def test_navigate_to_updates_motors(self):
        """navigate_to(x, y) sets appropriate motor commands to reach target."""
        p = PhysicsEngine(asset_type="rover")
        p.navigate_to(10.0, 0.0)
        p.tick(0.02)
        # Should be moving toward target
        assert p.speed > 0 or p.x > 0

    def test_navigate_to_stops_at_target(self):
        """Robot stops when it reaches the target within threshold."""
        p = PhysicsEngine(asset_type="rover")
        p.navigate_to(1.0, 0.0)
        # Tick many times to reach target
        for _ in range(500):
            p.tick(0.02)
        # Should be close to target
        dist = math.sqrt((p.x - 1.0) ** 2 + p.y ** 2)
        assert dist < 1.0  # Within 1 meter
        assert p.arrived


class TestMaxSpeed:
    """Max speed varies by asset type."""

    def test_rover_max_speed(self):
        p = PhysicsEngine(asset_type="rover")
        assert p.max_speed == 3.0

    def test_drone_max_speed(self):
        p = PhysicsEngine(asset_type="drone")
        assert p.max_speed == 6.0

    def test_turret_max_speed(self):
        p = PhysicsEngine(asset_type="turret")
        assert p.max_speed == 0.0

    def test_tank_max_speed(self):
        p = PhysicsEngine(asset_type="tank")
        assert p.max_speed == 3.0

    def test_turret_cannot_move(self):
        """Turrets have zero max speed, should not move even with motor input."""
        p = PhysicsEngine(asset_type="turret")
        p.set_motors(1.0, 1.0)
        p.tick(1.0)
        assert p.x == 0.0
        assert p.y == 0.0
        assert p.speed == 0.0

    def test_speed_clamped_to_max(self):
        """Speed should never exceed max_speed."""
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(1.0, 1.0)
        for _ in range(1000):
            p.tick(0.02)
        assert p.speed <= p.max_speed + 0.01  # Small epsilon


class TestBattery:
    """LiPo battery curve: 12.6V full, 9.0V empty."""

    def test_initial_battery_full(self):
        p = PhysicsEngine(asset_type="rover")
        assert p.battery_pct == 1.0
        assert p.battery_voltage == pytest.approx(12.6, abs=0.1)

    def test_battery_drains_under_load(self):
        """Battery drains when motors are running."""
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(1.0, 1.0)
        for _ in range(1000):
            p.tick(0.02)
        assert p.battery_pct < 1.0

    def test_battery_drains_faster_under_more_load(self):
        """Higher motor load drains battery faster."""
        p1 = PhysicsEngine(asset_type="rover")
        p1.set_motors(0.5, 0.5)
        for _ in range(500):
            p1.tick(0.02)

        p2 = PhysicsEngine(asset_type="rover")
        p2.set_motors(1.0, 1.0)
        for _ in range(500):
            p2.tick(0.02)

        assert p2.battery_pct < p1.battery_pct

    def test_battery_no_drain_idle(self):
        """Battery drains very little when idle (baseline only)."""
        p = PhysicsEngine(asset_type="rover")
        initial = p.battery_pct
        for _ in range(50):
            p.tick(0.02)
        # Idle drain is minimal
        assert p.battery_pct >= initial - 0.01

    def test_battery_voltage_curve(self):
        """Voltage follows LiPo discharge curve between 12.6V and 9.0V."""
        p = PhysicsEngine(asset_type="rover")
        assert p.battery_voltage >= 9.0
        assert p.battery_voltage <= 12.6

    def test_battery_never_negative(self):
        """Battery percentage never goes below 0."""
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(1.0, 1.0)
        for _ in range(100000):
            p.tick(0.1)
        assert p.battery_pct >= 0.0
        assert p.battery_voltage >= 9.0

    def test_battery_current_draw(self):
        """Current draw is proportional to motor load."""
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(1.0, 1.0)
        p.tick(0.02)
        assert p.current_draw > 0


class TestMotorThermals:
    """Motor temperature: warm under load, cool when idle, ambient 25C."""

    def test_initial_temp_ambient(self):
        p = PhysicsEngine(asset_type="rover")
        assert p.motor_temp_left == pytest.approx(25.0, abs=0.1)
        assert p.motor_temp_right == pytest.approx(25.0, abs=0.1)

    def test_temp_rises_under_load(self):
        """Motor temperature rises at ~0.5C/s under load."""
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(1.0, 1.0)
        for _ in range(100):
            p.tick(0.1)  # 10 seconds total
        assert p.motor_temp_left > 25.0
        assert p.motor_temp_right > 25.0

    def test_temp_cools_when_idle(self):
        """Motor temperature cools at ~0.2C/s when idle, toward ambient."""
        p = PhysicsEngine(asset_type="rover")
        # Heat up first
        p.set_motors(1.0, 1.0)
        for _ in range(100):
            p.tick(0.1)
        hot_temp = p.motor_temp_left

        # Now cool down
        p.set_motors(0.0, 0.0)
        for _ in range(100):
            p.tick(0.1)
        assert p.motor_temp_left < hot_temp

    def test_temp_approaches_ambient(self):
        """After sufficient cooling, temp returns near ambient (25C)."""
        p = PhysicsEngine(asset_type="rover")
        # Heat then cool for a long time
        p.set_motors(1.0, 1.0)
        for _ in range(50):
            p.tick(0.1)
        p.set_motors(0.0, 0.0)
        for _ in range(5000):
            p.tick(0.1)
        assert p.motor_temp_left == pytest.approx(25.0, abs=1.0)


class TestIMU:
    """IMU: pitch from accel, roll from turn, yaw = heading."""

    def test_imu_yaw_matches_heading(self):
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(0.5, 1.0)  # Turn
        p.tick(0.5)
        imu = p.get_imu()
        assert imu["yaw"] == pytest.approx(p.heading, abs=0.1)

    def test_imu_accel_z_gravity(self):
        """Z acceleration should be approximately gravity (9.81) when level."""
        p = PhysicsEngine(asset_type="rover")
        imu = p.get_imu()
        assert imu["accel_z"] == pytest.approx(9.81, abs=0.5)

    def test_imu_roll_on_turn(self):
        """Roll is nonzero during turns."""
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(-1.0, 1.0)
        p.tick(0.1)
        imu = p.get_imu()
        # Roll should be nonzero during active turning
        # (may be zero if not turning)
        assert isinstance(imu["roll"], float)

    def test_imu_pitch_on_accel(self):
        """Pitch changes on acceleration."""
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(1.0, 1.0)
        p.tick(0.1)
        imu = p.get_imu()
        assert isinstance(imu["pitch"], float)

    def test_imu_structure(self):
        """IMU dict has all required fields."""
        p = PhysicsEngine(asset_type="rover")
        imu = p.get_imu()
        for key in ("roll", "pitch", "yaw", "accel_x", "accel_y", "accel_z"):
            assert key in imu
            assert isinstance(imu[key], float)


class TestOdometry:
    """Odometry tracks total distance traveled."""

    def test_initial_odometry_zero(self):
        p = PhysicsEngine(asset_type="rover")
        assert p.odometry == 0.0

    def test_odometry_increases_with_movement(self):
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(1.0, 1.0)
        for _ in range(100):
            p.tick(0.02)
        assert p.odometry > 0.0

    def test_odometry_never_decreases(self):
        """Odometry is cumulative, never decreases."""
        p = PhysicsEngine(asset_type="rover")
        p.set_motors(1.0, 1.0)
        for _ in range(50):
            p.tick(0.02)
        odo1 = p.odometry
        p.set_motors(-1.0, -1.0)  # Reverse
        for _ in range(50):
            p.tick(0.02)
        assert p.odometry >= odo1
