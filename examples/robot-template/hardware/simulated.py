# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Simulated hardware backend — no real hardware required.

Simulates an RC car moving on a 2D plane. Position updates based on
motor commands and elapsed time. Provides realistic-ish telemetry:
- Battery: voltage curve, current draw, temperature
- IMU: heading as yaw, simulated tilt on acceleration
- Odometry: total distance traveled
- Motor temperatures: warm up under load

Useful for testing the full MQTT pipeline without any physical hardware.
"""

from __future__ import annotations

import math
import random
import threading
import time

from .base import HardwareInterface, BatteryState, ImuState


# 3S LiPo voltage curve (charge_pct -> voltage)
_LIPO_3S_CURVE = [
    (1.00, 12.60),  # Full
    (0.90, 12.30),
    (0.80, 12.00),
    (0.50, 11.40),
    (0.30, 11.10),
    (0.20, 10.80),
    (0.10, 10.50),
    (0.00, 9.00),   # Empty (cutoff)
]


def _voltage_from_charge(charge: float) -> float:
    """Interpolate voltage from charge percentage using LiPo curve."""
    charge = max(0.0, min(1.0, charge))
    for i in range(len(_LIPO_3S_CURVE) - 1):
        c1, v1 = _LIPO_3S_CURVE[i]
        c2, v2 = _LIPO_3S_CURVE[i + 1]
        if c2 <= charge <= c1:
            t = (charge - c2) / (c1 - c2) if (c1 - c2) > 0 else 0
            return v2 + t * (v1 - v2)
    return _LIPO_3S_CURVE[-1][1]


class SimulatedHardware(HardwareInterface):
    """Simulated robot hardware with realistic telemetry."""

    def __init__(self, config: dict) -> None:
        self._x = 0.0
        self._y = 0.0
        self._heading = 0.0  # degrees, 0 = north
        self._speed = 0.0
        self._battery = 1.0
        self._left_motor = 0.0
        self._right_motor = 0.0
        self._turret_pan = 0.0
        self._turret_tilt = 0.0
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Movement params
        self._max_speed = 3.0  # units/second
        self._turn_rate = 90.0  # degrees/second at full differential
        self._battery_drain = 0.0005  # per second when moving

        # Extended telemetry state
        self._odometer = 0.0          # total distance meters
        self._motor_temp_left = 25.0  # celsius
        self._motor_temp_right = 25.0
        self._ambient_temp = 25.0
        self._current_draw = 0.0      # amps
        self._battery_temp = 25.0

    def initialize(self) -> None:
        print("  Hardware: SIMULATED MODE")
        print(f"  Position: ({self._x:.1f}, {self._y:.1f})")
        self._running = True
        self._thread = threading.Thread(target=self._physics_loop, daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        print("  Simulated hardware shut down")

    def set_motors(self, left: float, right: float) -> None:
        with self._lock:
            self._left_motor = max(-1.0, min(1.0, left))
            self._right_motor = max(-1.0, min(1.0, right))

    def get_position(self) -> tuple[float, float]:
        with self._lock:
            return (self._x, self._y)

    def get_heading(self) -> float:
        with self._lock:
            return self._heading

    def get_speed(self) -> float:
        with self._lock:
            return self._speed

    def get_battery(self) -> float:
        with self._lock:
            return self._battery

    def set_turret(self, pan: float, tilt: float) -> None:
        with self._lock:
            self._turret_pan = pan
            self._turret_tilt = tilt

    def fire_trigger(self) -> None:
        print("  [SIM] Trigger fired! (pew pew)")
        with self._lock:
            self._battery = max(0, self._battery - 0.01)
            # Firing draws a spike of current
            self._current_draw = 5.0

    # ----- Extended Telemetry -----

    def get_battery_state(self) -> BatteryState:
        with self._lock:
            voltage = _voltage_from_charge(self._battery)
            # Add slight noise for realism
            voltage += random.gauss(0, 0.02)
            return BatteryState(
                charge_pct=self._battery,
                voltage=round(voltage, 2),
                current_draw=round(self._current_draw, 2),
                temperature_c=round(self._battery_temp, 1),
            )

    def get_elevation(self) -> float:
        # Flat simulation terrain
        return 0.0

    def get_imu(self) -> ImuState:
        with self._lock:
            # Simulate slight pitch on acceleration
            forward = (self._left_motor + self._right_motor) / 2.0
            pitch = -forward * 3.0  # slight nose-down when accelerating
            # Simulate slight roll on turning
            turn_diff = self._left_motor - self._right_motor
            roll = turn_diff * 5.0
            return ImuState(
                roll=round(roll, 1),
                pitch=round(pitch, 1),
                yaw=round(self._heading, 1),
                accel_x=round(turn_diff * 2.0, 2),
                accel_y=round(forward * 3.0, 2),
                accel_z=round(9.81 + random.gauss(0, 0.05), 2),
            )

    def get_odometry(self) -> float:
        with self._lock:
            return round(self._odometer, 2)

    def get_motor_temps(self) -> tuple[float, float]:
        with self._lock:
            return (round(self._motor_temp_left, 1), round(self._motor_temp_right, 1))

    # ----- Physics Simulation -----

    def _physics_loop(self) -> None:
        """Differential drive physics + thermal/electrical simulation at 50Hz."""
        dt = 0.02
        while self._running:
            time.sleep(dt)
            with self._lock:
                left = self._left_motor
                right = self._right_motor

                # Differential drive: average = forward speed, difference = turning
                forward = (left + right) / 2.0
                turn = (left - right) * self._turn_rate * dt

                self._heading = (self._heading + turn) % 360
                self._speed = abs(forward) * self._max_speed

                # Move in heading direction
                rad = math.radians(self._heading)
                dx = math.sin(rad) * forward * self._max_speed * dt
                dy = math.cos(rad) * forward * self._max_speed * dt
                self._x += dx
                self._y += dy

                # Odometry
                self._odometer += math.hypot(dx, dy)

                # Battery drain when moving
                motor_load = abs(forward)
                if motor_load > 0.05:
                    self._battery = max(0, self._battery - self._battery_drain * dt)

                # Current draw simulation (A)
                # Idle: ~0.3A, moving: ~2A, turning: ~3A, firing spike handled in fire_trigger
                idle_current = 0.3
                motor_current = (abs(left) + abs(right)) * 1.5
                self._current_draw = idle_current + motor_current
                # Decay firing spike
                if self._current_draw > 4.0:
                    self._current_draw *= 0.9

                # Motor temperature simulation
                # Warm up under load, cool down toward ambient
                thermal_gain = 0.5  # degrees per second at full load
                thermal_loss = 0.1  # cooling rate toward ambient
                self._motor_temp_left += (abs(left) * thermal_gain - (self._motor_temp_left - self._ambient_temp) * thermal_loss) * dt
                self._motor_temp_right += (abs(right) * thermal_gain - (self._motor_temp_right - self._ambient_temp) * thermal_loss) * dt

                # Battery temperature (warms with current draw)
                battery_thermal = self._current_draw * 0.3
                self._battery_temp += (battery_thermal - (self._battery_temp - self._ambient_temp) * 0.05) * dt
