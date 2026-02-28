# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SwarmDrone -- minimal drone state machine for swarm fleet.

A single drone process that hovers, flies to waypoints, patrols, and
can be eliminated. Battery drains at ~2% per minute.
"""

import math
from datetime import datetime, timezone


class SwarmDrone:
    """A single swarm drone with simple state machine and movement."""

    STATES = {"hovering", "flying", "patrolling", "returning", "eliminated"}

    # Movement speed (meters/second)
    SPEED = 6.0

    # Battery drain rate: 2% per minute = 0.02/60 per second
    BATTERY_DRAIN_PER_SEC = 0.02 / 60.0

    # Full battery voltage / empty voltage (LiPo 3S)
    VOLTAGE_FULL = 12.6
    VOLTAGE_EMPTY = 9.0

    # Arrival threshold (meters)
    ARRIVE_DIST = 1.0

    def __init__(
        self,
        drone_id: str,
        start_x: float = 0.0,
        start_y: float = 0.0,
        name: str | None = None,
    ):
        self.drone_id = drone_id
        self.name = name or f"Drone {drone_id}"
        self.alliance = "friendly"

        # Position
        self.x = start_x
        self.y = start_y
        self.start_x = start_x
        self.start_y = start_y
        self.heading = 0.0

        # State
        self._state = "hovering"
        self._status = "active"

        # Battery
        self.battery_pct = 1.0

        # Navigation
        self.target_x = start_x
        self.target_y = start_y

        # Patrol
        self.patrol_waypoints: list[dict] = []
        self._patrol_index = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def status(self) -> str:
        return self._status

    @property
    def battery_voltage(self) -> float:
        """LiPo voltage curve: linear interpolation full->empty."""
        return self.VOLTAGE_EMPTY + self.battery_pct * (self.VOLTAGE_FULL - self.VOLTAGE_EMPTY)

    def dispatch(self, x: float, y: float) -> None:
        """Fly to a specific point."""
        if self._state == "eliminated":
            return
        self.target_x = x
        self.target_y = y
        self._state = "flying"

    def patrol(self, waypoints: list[dict]) -> None:
        """Loop through waypoints."""
        if self._state == "eliminated":
            return
        if not waypoints:
            return
        self.patrol_waypoints = list(waypoints)
        self._patrol_index = 0
        self._state = "patrolling"
        wp = self.patrol_waypoints[0]
        self.target_x = wp["x"]
        self.target_y = wp["y"]

    def recall(self) -> None:
        """Return to start position."""
        if self._state == "eliminated":
            return
        self.target_x = self.start_x
        self.target_y = self.start_y
        self._state = "returning"

    def stop(self) -> None:
        """Stop all movement, hover in place."""
        if self._state == "eliminated":
            return
        self._state = "hovering"
        self.patrol_waypoints = []

    def eliminate(self) -> None:
        """Mark this drone as eliminated."""
        self._state = "eliminated"
        self._status = "eliminated"

    def tick(self, dt: float) -> dict:
        """Advance simulation by dt seconds. Returns telemetry dict."""
        # Drain battery
        self.battery_pct = max(0.0, self.battery_pct - self.BATTERY_DRAIN_PER_SEC * dt)

        # Move toward target if in a moving state
        if self._state in ("flying", "patrolling", "returning"):
            self._move_toward_target(dt)

        # Build telemetry
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "robot_id": self.drone_id,
            "name": self.name,
            "asset_type": "drone",
            "position": {"x": float(self.x), "y": float(self.y)},
            "heading": float(self.heading),
            "battery": {
                "voltage": float(self.battery_voltage),
                "percentage": float(self.battery_pct),
            },
            "status": self._status,
            "fsm_state": self._state,
            "alliance": self.alliance,
            "timestamp": now,
        }

    def _move_toward_target(self, dt: float) -> None:
        """Move toward current target at constant speed."""
        dx = self.target_x - self.x
        dy = self.target_y - self.y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < self.ARRIVE_DIST:
            self._on_arrival()
            return

        # Update heading (degrees, 0=north, clockwise)
        self.heading = math.degrees(math.atan2(dx, dy)) % 360.0

        # Move
        step = min(self.SPEED * dt, dist)
        self.x += (dx / dist) * step
        self.y += (dy / dist) * step

    def _on_arrival(self) -> None:
        """Handle reaching the current target."""
        if self._state == "flying":
            self._state = "hovering"
        elif self._state == "returning":
            self.x = self.start_x
            self.y = self.start_y
            self._state = "hovering"
        elif self._state == "patrolling":
            # Advance to next waypoint (loop)
            self._patrol_index = (self._patrol_index + 1) % len(self.patrol_waypoints)
            wp = self.patrol_waypoints[self._patrol_index]
            self.target_x = wp["x"]
            self.target_y = wp["y"]
