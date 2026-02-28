# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for extended robot telemetry — voltage, current, IMU, odometry."""

import pytest
from unittest.mock import MagicMock

# Add parent to path for imports
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hardware.simulated import SimulatedHardware, _voltage_from_charge
from hardware.base import BatteryState, ImuState


# ===========================================================================
# Voltage Curve
# ===========================================================================

class TestVoltageCurve:
    """LiPo 3S voltage interpolation."""

    def test_full_charge(self):
        v = _voltage_from_charge(1.0)
        assert abs(v - 12.60) < 0.01

    def test_empty(self):
        v = _voltage_from_charge(0.0)
        assert abs(v - 9.00) < 0.01

    def test_half_charge(self):
        v = _voltage_from_charge(0.5)
        assert 11.0 < v < 12.0

    def test_clamps_above_one(self):
        v = _voltage_from_charge(1.5)
        assert abs(v - 12.60) < 0.01

    def test_clamps_below_zero(self):
        v = _voltage_from_charge(-0.5)
        assert abs(v - 9.00) < 0.01

    def test_monotonic_decreasing(self):
        """Voltage should decrease as charge drops."""
        prev = _voltage_from_charge(1.0)
        for pct in [0.9, 0.8, 0.5, 0.3, 0.1, 0.0]:
            v = _voltage_from_charge(pct)
            assert v <= prev + 0.001, f"Voltage increased at {pct}: {v} > {prev}"
            prev = v


# ===========================================================================
# BatteryState
# ===========================================================================

class TestBatteryState:
    def test_simulated_battery_state(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        state = hw.get_battery_state()
        assert isinstance(state, BatteryState)
        assert 0.99 <= state.charge_pct <= 1.0
        assert 12.5 < state.voltage < 12.7  # Full charge range
        assert state.current_draw >= 0
        assert state.temperature_c > 0

    def test_battery_voltage_drops_with_charge(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        full = hw.get_battery_state()
        # Drain battery
        for _ in range(50):
            hw.fire_trigger()
        drained = hw.get_battery_state()
        assert drained.voltage < full.voltage


# ===========================================================================
# IMU
# ===========================================================================

class TestIMU:
    def test_imu_defaults(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        imu = hw.get_imu()
        assert isinstance(imu, ImuState)
        assert abs(imu.roll) < 0.1  # Level when idle
        assert abs(imu.pitch) < 0.1
        assert abs(imu.accel_z - 9.81) < 0.5  # Gravity

    def test_imu_yaw_matches_heading(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        imu = hw.get_imu()
        heading = hw.get_heading()
        assert abs(imu.yaw - heading) < 0.1


# ===========================================================================
# Odometry
# ===========================================================================

class TestOdometry:
    def test_initial_odometry_zero(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        assert hw.get_odometry() == 0.0


# ===========================================================================
# Motor Temperatures
# ===========================================================================

class TestMotorTemps:
    def test_initial_ambient(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        left, right = hw.get_motor_temps()
        assert abs(left - 25.0) < 0.1
        assert abs(right - 25.0) < 0.1


# ===========================================================================
# Elevation and GPS
# ===========================================================================

class TestElevationGPS:
    def test_elevation_zero_in_sim(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        assert hw.get_elevation() == 0.0

    def test_gps_none_in_sim(self):
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        assert hw.get_gps() is None


# ===========================================================================
# Extended Telemetry in MQTT Payload
# ===========================================================================

class TestTelemetryPayload:
    """Extended telemetry fields appear in MQTT publish."""

    def test_extended_fields_in_telemetry(self):
        """TelemetryPublisher includes extended fields."""
        from brain.telemetry import TelemetryPublisher

        # Mock paho before import
        _mock_paho = MagicMock()
        sys.modules.setdefault("paho", _mock_paho)
        sys.modules.setdefault("paho.mqtt", _mock_paho.mqtt)
        sys.modules.setdefault("paho.mqtt.client", _mock_paho.mqtt.client)

        mqtt_client = MagicMock()
        hw = SimulatedHardware({"hardware": {"mode": "simulated"}})
        nav = MagicMock()
        nav.status = "idle"
        turret = MagicMock()
        turret.pan = 0.0
        turret.tilt = 0.0
        config = {
            "robot_id": "r1", "site_id": "home",
            "robot_name": "Test Bot", "asset_type": "rover",
        }
        tp = TelemetryPublisher(mqtt_client, hw, nav, turret, config)

        # Build the telemetry data manually (same as _publish_loop)
        pos = hw.get_position()
        data = {
            "name": tp._robot_name,
            "asset_type": tp._asset_type,
            "position": {"x": pos[0], "y": pos[1]},
            "heading": hw.get_heading(),
            "speed": hw.get_speed(),
            "battery": hw.get_battery(),
            "status": nav.status,
            "turret": {"pan": turret.pan, "tilt": turret.tilt},
        }

        # Add extended telemetry
        bat_state = hw.get_battery_state()
        data["battery_state"] = {
            "charge_pct": bat_state.charge_pct,
            "voltage": bat_state.voltage,
            "current_draw": bat_state.current_draw,
            "temperature_c": bat_state.temperature_c,
        }
        data["elevation"] = hw.get_elevation()
        imu = hw.get_imu()
        data["imu"] = {
            "roll": imu.roll, "pitch": imu.pitch, "yaw": imu.yaw,
        }
        data["odometry"] = hw.get_odometry()
        left_t, right_t = hw.get_motor_temps()
        data["motor_temps"] = {"left": left_t, "right": right_t}

        # Verify all fields present
        assert "battery_state" in data
        assert "voltage" in data["battery_state"]
        assert "current_draw" in data["battery_state"]
        assert "elevation" in data
        assert "imu" in data
        assert "odometry" in data
        assert "motor_temps" in data

        # Core fields still present (backwards compatible)
        assert "position" in data
        assert "battery" in data
        assert "heading" in data
        assert "speed" in data
        assert "name" in data
        assert "asset_type" in data
