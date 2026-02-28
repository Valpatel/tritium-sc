# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Robot state machine: idle, moving, patrolling, engaging, returning."""

from datetime import datetime, timezone

from physics import PhysicsEngine


class Robot:
    """Simulated robot with state machine and physics engine."""

    # Valid states
    STATES = {"idle", "moving", "patrolling", "engaging", "returning"}

    def __init__(
        self,
        robot_id: str,
        asset_type: str,
        name: str | None = None,
        start_x: float = 0.0,
        start_y: float = 0.0,
    ):
        self.robot_id = robot_id
        self.asset_type = asset_type
        self.name = name or robot_id
        self.start_x = start_x
        self.start_y = start_y

        # Physics engine
        self._physics = PhysicsEngine(
            asset_type=asset_type,
            start_x=start_x,
            start_y=start_y,
        )

        # State machine
        self._state = "idle"
        self._previous_state = "idle"

        # Turret
        self.turret_pan = 0.0
        self.turret_tilt = 0.0

        # Navigation targets
        self.target_x = 0.0
        self.target_y = 0.0

        # Patrol
        self.patrol_waypoints: list[dict] = []
        self._patrol_index = 0

        # Fire
        self.fire_target_x = 0.0
        self.fire_target_y = 0.0
        self._engage_timer = 0.0
        self._engage_duration = 0.5  # seconds to "fire"

    @property
    def state(self) -> str:
        return self._state

    @property
    def x(self) -> float:
        return self._physics.x

    @property
    def y(self) -> float:
        return self._physics.y

    @property
    def heading(self) -> float:
        return self._physics.heading

    @property
    def speed(self) -> float:
        return self._physics.speed

    def dispatch(self, x: float, y: float) -> None:
        """Navigate to a specific point."""
        self.target_x = x
        self.target_y = y
        self._physics.navigate_to(x, y)
        self._state = "moving"

    def patrol(self, waypoints: list[dict]) -> None:
        """Follow a waypoint loop. Each waypoint is {"x": float, "y": float}."""
        if not waypoints:
            return
        self.patrol_waypoints = list(waypoints)
        self._patrol_index = 0
        self._state = "patrolling"
        # Navigate to first waypoint
        wp = self.patrol_waypoints[0]
        self._physics.navigate_to(wp["x"], wp["y"])

    def recall(self) -> None:
        """Return to start position."""
        self._physics.navigate_to(self.start_x, self.start_y)
        self._state = "returning"

    def fire(self, target_x: float, target_y: float) -> None:
        """Simulate firing at a target."""
        self.fire_target_x = target_x
        self.fire_target_y = target_y
        self._engage_timer = 0.0
        if self._state != "engaging":
            self._previous_state = self._state
        self._state = "engaging"

    def aim(self, pan: float, tilt: float) -> None:
        """Set turret pan and tilt angles."""
        self.turret_pan = max(-180.0, min(180.0, pan))
        self.turret_tilt = max(-30.0, min(90.0, tilt))

    def stop(self) -> None:
        """Stop all movement and return to idle."""
        self._physics.clear_navigation()
        self._state = "idle"
        self.patrol_waypoints = []

    def tick(self, dt: float) -> dict:
        """Advance simulation by dt seconds. Returns telemetry dict."""
        # Handle engaging state timer
        if self._state == "engaging":
            self._engage_timer += dt
            if self._engage_timer >= self._engage_duration:
                # Return to previous state
                self._state = self._previous_state
                self._engage_timer = 0.0

        # Advance physics
        self._physics.tick(dt)

        # Handle state transitions
        if self._state == "moving" and self._physics.arrived:
            self._state = "idle"
            self._physics.arrived = False

        elif self._state == "returning" and self._physics.arrived:
            self._state = "idle"
            self._physics.arrived = False

        elif self._state == "patrolling" and self._physics.arrived:
            self._physics.arrived = False
            # Advance to next waypoint (loop)
            self._patrol_index = (self._patrol_index + 1) % len(self.patrol_waypoints)
            wp = self.patrol_waypoints[self._patrol_index]
            self._physics.navigate_to(wp["x"], wp["y"])

        # Build telemetry
        imu = self._physics.get_imu()
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Map state to status
        status = "idle" if self._state == "idle" else "active"

        return {
            "name": self.name,
            "asset_type": self.asset_type,
            "position": {"x": float(self._physics.x), "y": float(self._physics.y)},
            "heading": float(self._physics.heading),
            "speed": float(self._physics.speed),
            "battery": float(self._physics.battery_pct),
            "status": status,
            "turret": {"pan": float(self.turret_pan), "tilt": float(self.turret_tilt)},
            "timestamp": now,
            "battery_state": {
                "charge_pct": float(self._physics.battery_pct),
                "voltage": float(self._physics.battery_voltage),
                "current_draw": float(self._physics.current_draw),
                "temperature_c": float(
                    (self._physics.motor_temp_left + self._physics.motor_temp_right) / 2.0
                ),
            },
            "imu": {
                "roll": float(imu["roll"]),
                "pitch": float(imu["pitch"]),
                "yaw": float(imu["yaw"]),
                "accel_x": float(imu["accel_x"]),
                "accel_y": float(imu["accel_y"]),
                "accel_z": float(imu["accel_z"]),
            },
            "motor_temps": {
                "left": float(self._physics.motor_temp_left),
                "right": float(self._physics.motor_temp_right),
            },
            "odometry": {"total_distance": float(self._physics.odometry)},
        }
