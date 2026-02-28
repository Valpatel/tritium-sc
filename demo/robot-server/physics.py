# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Differential drive kinematics, battery model, motor thermals, IMU."""

import math

# Max speed by asset type (m/s)
MAX_SPEEDS: dict[str, float] = {
    "rover": 3.0,
    "drone": 6.0,
    "turret": 0.0,
    "tank": 3.0,
}

# Track width for differential drive (meters)
TRACK_WIDTH = 0.3

# Battery constants (LiPo)
BATTERY_VOLTAGE_FULL = 12.6
BATTERY_VOLTAGE_EMPTY = 9.0
BATTERY_CAPACITY_AH = 5.0  # 5Ah capacity
BATTERY_IDLE_DRAIN_A = 0.05  # Idle current draw (amps)
BATTERY_MOTOR_DRAIN_A = 3.0  # Max current draw per motor at full load

# Motor thermal constants
MOTOR_AMBIENT_TEMP = 25.0
MOTOR_HEAT_RATE = 0.5  # C/s under full load
MOTOR_COOL_RATE = 0.2  # C/s when idle

# Navigation
ARRIVAL_THRESHOLD = 0.5  # meters


class PhysicsEngine:
    """Differential drive physics simulation with battery and thermals."""

    def __init__(
        self,
        asset_type: str = "rover",
        start_x: float = 0.0,
        start_y: float = 0.0,
    ):
        self.asset_type = asset_type
        self.max_speed = MAX_SPEEDS.get(asset_type, 3.0)

        # Position and kinematics
        self.x = start_x
        self.y = start_y
        self.heading = 0.0  # degrees, 0 = +x axis
        self.speed = 0.0
        self._prev_speed = 0.0

        # Motor commands (-1.0 to 1.0)
        self._motor_left = 0.0
        self._motor_right = 0.0

        # Battery state
        self._battery_charge = BATTERY_CAPACITY_AH  # Remaining Ah
        self.current_draw = 0.0

        # Motor thermals
        self.motor_temp_left = MOTOR_AMBIENT_TEMP
        self.motor_temp_right = MOTOR_AMBIENT_TEMP

        # Odometry
        self.odometry = 0.0

        # Turn rate tracking for IMU
        self._turn_rate = 0.0  # degrees/s

        # Navigation target
        self._nav_target: tuple[float, float] | None = None
        self.arrived = False

    def set_motors(self, left: float, right: float) -> None:
        """Set motor commands. Values clamped to [-1.0, 1.0]."""
        self._motor_left = max(-1.0, min(1.0, left))
        self._motor_right = max(-1.0, min(1.0, right))

    def navigate_to(self, x: float, y: float) -> None:
        """Set navigation target. Motors will be controlled automatically."""
        self._nav_target = (x, y)
        self.arrived = False

    def clear_navigation(self) -> None:
        """Clear navigation target and stop motors."""
        self._nav_target = None
        self.set_motors(0.0, 0.0)

    def tick(self, dt: float) -> None:
        """Advance physics simulation by dt seconds."""
        if self.max_speed == 0.0:
            # Stationary unit (turret) -- no movement
            self.speed = 0.0
            self._update_battery(dt)
            self._update_thermals(dt)
            return

        # Auto-navigation
        if self._nav_target is not None:
            self._navigate(dt)

        # Differential drive kinematics
        left = self._motor_left * self.max_speed
        right = self._motor_right * self.max_speed

        turn = (right - left) / TRACK_WIDTH  # rad/s approximation
        forward = (left + right) / 2.0

        # Update heading
        turn_deg = math.degrees(turn) * dt
        self._turn_rate = turn_deg / dt if dt > 0 else 0.0
        self.heading = (self.heading + turn_deg) % 360.0

        # Update position
        heading_rad = math.radians(self.heading)
        dx = forward * math.cos(heading_rad) * dt
        dy = forward * math.sin(heading_rad) * dt
        self.x += dx
        self.y += dy

        # Update speed
        self._prev_speed = self.speed
        self.speed = min(abs(forward), self.max_speed)

        # Update odometry
        step_dist = math.sqrt(dx * dx + dy * dy)
        self.odometry += step_dist

        # Check arrival
        if self._nav_target is not None:
            tx, ty = self._nav_target
            dist = math.sqrt((self.x - tx) ** 2 + (self.y - ty) ** 2)
            if dist < ARRIVAL_THRESHOLD:
                self.arrived = True
                self._nav_target = None
                self.set_motors(0.0, 0.0)
                self.speed = 0.0

        # Update subsystems
        self._update_battery(dt)
        self._update_thermals(dt)

    def _navigate(self, dt: float) -> None:
        """Simple proportional steering toward navigation target."""
        if self._nav_target is None:
            return

        tx, ty = self._nav_target
        dx = tx - self.x
        dy = ty - self.y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < ARRIVAL_THRESHOLD:
            self.set_motors(0.0, 0.0)
            return

        # Desired heading
        desired = math.degrees(math.atan2(dy, dx)) % 360.0
        current = self.heading % 360.0

        # Angle difference (-180 to 180)
        diff = (desired - current + 180.0) % 360.0 - 180.0

        # Proportional steering
        turn_gain = 0.02
        steer = max(-1.0, min(1.0, diff * turn_gain))

        # Speed control: slow down near target
        speed_factor = min(1.0, dist / 3.0)
        base_speed = max(0.3, speed_factor)

        # Set motors
        left = base_speed - steer
        right = base_speed + steer
        self.set_motors(
            max(-1.0, min(1.0, left)),
            max(-1.0, min(1.0, right)),
        )

    def _update_battery(self, dt: float) -> None:
        """Drain battery proportional to motor load."""
        motor_load = (abs(self._motor_left) + abs(self._motor_right)) / 2.0
        self.current_draw = BATTERY_IDLE_DRAIN_A + motor_load * BATTERY_MOTOR_DRAIN_A
        drain_ah = self.current_draw * dt / 3600.0  # Convert A*s to Ah
        self._battery_charge = max(0.0, self._battery_charge - drain_ah)

    def _update_thermals(self, dt: float) -> None:
        """Update motor temperatures: heat under load, cool when idle."""
        for side in ("left", "right"):
            motor_cmd = abs(self._motor_left if side == "left" else self._motor_right)
            temp_attr = f"motor_temp_{side}"
            current_temp = getattr(self, temp_attr)

            if motor_cmd > 0.01:
                # Heat up: 0.5 C/s at full load, proportional
                new_temp = current_temp + MOTOR_HEAT_RATE * motor_cmd * dt
            else:
                # Cool toward ambient: 0.2 C/s
                delta = current_temp - MOTOR_AMBIENT_TEMP
                if delta > 0:
                    new_temp = current_temp - min(MOTOR_COOL_RATE * dt, delta)
                else:
                    new_temp = MOTOR_AMBIENT_TEMP

            setattr(self, temp_attr, new_temp)

    @property
    def battery_pct(self) -> float:
        """Battery charge as 0.0-1.0 fraction."""
        return max(0.0, min(1.0, self._battery_charge / BATTERY_CAPACITY_AH))

    @property
    def battery_voltage(self) -> float:
        """Battery voltage following LiPo discharge curve.

        Simple linear approximation between full (12.6V) and empty (9.0V).
        Real LiPo curves have a plateau, but linear is good enough for sim.
        """
        pct = self.battery_pct
        return BATTERY_VOLTAGE_EMPTY + pct * (BATTERY_VOLTAGE_FULL - BATTERY_VOLTAGE_EMPTY)

    def get_imu(self) -> dict:
        """Return IMU readings derived from dynamics."""
        heading_rad = math.radians(self.heading)

        # Acceleration derived from speed change
        accel_forward = (self.speed - self._prev_speed)  # Simplified

        # Roll from turning (simplified centripetal)
        roll = self._turn_rate * 0.1 if abs(self._turn_rate) > 0.1 else 0.0

        # Pitch from acceleration (simplified)
        pitch = -accel_forward * 2.0

        return {
            "roll": float(roll),
            "pitch": float(pitch),
            "yaw": float(self.heading),
            "accel_x": float(accel_forward * math.cos(heading_rad)),
            "accel_y": float(accel_forward * math.sin(heading_rad)),
            "accel_z": 9.81,
        }
