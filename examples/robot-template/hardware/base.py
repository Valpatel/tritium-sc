# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Abstract hardware interface for robot control.

All hardware backends (simulated, GPIO, etc.) implement this interface.
The brain modules only talk to this interface, never directly to hardware.

Extended telemetry includes voltage, current, elevation, GPS, and
temperature — all published via MQTT for Amy's situational awareness.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class BatteryState:
    """Battery telemetry — charge level and electrical state."""
    charge_pct: float = 1.0     # 0.0-1.0 (percentage)
    voltage: float = 12.6       # volts (fully charged 3S LiPo)
    current_draw: float = 0.0   # amps (0 = idle)
    temperature_c: float = 25.0  # battery temp in celsius


@dataclass
class ImuState:
    """Inertial measurement — orientation and acceleration."""
    roll: float = 0.0     # degrees, 0 = level
    pitch: float = 0.0    # degrees, 0 = level
    yaw: float = 0.0      # degrees, 0 = north (same as heading)
    accel_x: float = 0.0  # m/s^2
    accel_y: float = 0.0  # m/s^2
    accel_z: float = 9.81  # m/s^2 (gravity)


class HardwareInterface(ABC):
    """Abstract interface for robot hardware control.

    Core methods (required):
        initialize, shutdown, set_motors, get_position, get_heading,
        get_speed, get_battery, set_turret, fire_trigger

    Extended telemetry (optional, return defaults if not available):
        get_battery_state, get_elevation, get_imu, get_gps,
        get_odometry, get_motor_temps
    """

    @abstractmethod
    def initialize(self) -> None:
        """Initialize hardware (open GPIO, connect to motor drivers, etc)."""

    @abstractmethod
    def shutdown(self) -> None:
        """Safely shut down all hardware."""

    @abstractmethod
    def set_motors(self, left: float, right: float) -> None:
        """Set motor speeds. -1.0 = full reverse, 0 = stop, 1.0 = full forward."""

    @abstractmethod
    def get_position(self) -> tuple[float, float]:
        """Get current (x, y) position in game coordinates (meters from origin)."""

    @abstractmethod
    def get_heading(self) -> float:
        """Get current heading in degrees (0 = north/+y, clockwise)."""

    @abstractmethod
    def get_speed(self) -> float:
        """Get current speed in units/second."""

    @abstractmethod
    def get_battery(self) -> float:
        """Get battery level 0.0-1.0."""

    @abstractmethod
    def set_turret(self, pan: float, tilt: float) -> None:
        """Set turret pan/tilt angles in degrees."""

    @abstractmethod
    def fire_trigger(self) -> None:
        """Activate the firing mechanism (nerf trigger)."""

    # ----- Extended Telemetry (override for real hardware) -----

    def get_battery_state(self) -> BatteryState:
        """Get detailed battery state (voltage, current, temperature).

        REAL HARDWARE: Read from INA219 current sensor or battery BMS.
        SIMULATION: Returns values derived from charge_pct.
        """
        pct = self.get_battery()
        return BatteryState(charge_pct=pct)

    def get_elevation(self) -> float:
        """Get elevation in meters above sea level.

        REAL HARDWARE: Read from barometric pressure sensor (BMP280)
                       or GPS altitude.
        SIMULATION: Returns 0.0 (flat terrain).
        """
        return 0.0

    def get_imu(self) -> ImuState:
        """Get IMU state (roll, pitch, yaw, acceleration).

        REAL HARDWARE: Read from IMU (MPU6050, BNO055, etc).
        SIMULATION: Returns level orientation with heading as yaw.
        """
        return ImuState(yaw=self.get_heading())

    def get_gps(self) -> tuple[float, float, float] | None:
        """Get GPS position as (latitude, longitude, altitude) or None.

        REAL HARDWARE: Read from GPS module (NEO-6M, ZED-F9P, etc).
        SIMULATION: Returns None (no GPS in simulation).
        """
        return None

    def get_odometry(self) -> float:
        """Get total distance traveled in meters (odometer).

        REAL HARDWARE: Integrate from wheel encoders.
        SIMULATION: Returns 0.0 (not tracked by default).
        """
        return 0.0

    def get_motor_temps(self) -> tuple[float, float]:
        """Get motor temperatures (left, right) in celsius.

        REAL HARDWARE: Read from thermistors on motor housings.
        SIMULATION: Returns ambient temperature with load-based warming.
        """
        return (25.0, 25.0)
