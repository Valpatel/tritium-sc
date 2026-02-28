# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Fake robot simulator for testing without hardware.

Provides FakeRobot that simulates robot behavior: publishes telemetry,
responds to commands, moves along paths, drains battery. Uses in-process
message passing (no real MQTT needed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from engine.units import get_type as _get_unit_type

# Earth radius in meters (for lat/lng movement approximation)
_EARTH_RADIUS = 6_371_000.0


def _meters_to_lat(meters: float) -> float:
    """Convert meters of north/south displacement to latitude degrees."""
    return meters / (_EARTH_RADIUS * math.pi / 180.0)


def _meters_to_lng(meters: float, lat: float) -> float:
    """Convert meters of east/west displacement to longitude degrees at given lat."""
    cos_lat = math.cos(math.radians(lat))
    if cos_lat < 1e-9:
        return 0.0
    return meters / (_EARTH_RADIUS * cos_lat * math.pi / 180.0)


@dataclass
class FakeRobot:
    """Simulates a physical robot for testing."""

    robot_id: str
    asset_type: str = "rover"
    alliance: str = "friendly"
    lat: float = 37.7749
    lng: float = -122.4194
    alt: float = 16.0
    heading: float = 0.0
    speed: float = 0.0
    battery: float = 1.0
    motor_temps: list[float] = field(
        default_factory=lambda: [25.0, 25.0, 25.0, 25.0]
    )

    # Movement
    _waypoints: list[tuple[float, float]] = field(default_factory=list)
    _patrol_loop: bool = False
    _waypoint_index: int = 0
    _start_lat: float = 0.0
    _start_lng: float = 0.0

    # State
    status: str = "idle"  # idle, moving, patrolling, returning

    # Message queues (in-process, no MQTT needed)
    _telemetry_log: list[dict] = field(default_factory=list)
    _command_log: list[dict] = field(default_factory=list)
    _thought_log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._start_lat = self.lat
        self._start_lng = self.lng

    def tick(self, dt: float) -> dict:
        """Advance simulation by dt seconds. Returns telemetry dict."""
        # Drain battery based on unit type drain_rate
        type_def = _get_unit_type(self.asset_type)
        drain_rate = type_def.drain_rate if type_def else 0.001
        if self.status in ("moving", "patrolling", "returning"):
            self.battery = max(0.0, self.battery - drain_rate * dt)
        else:
            # Idle drain is much lower
            self.battery = max(0.0, self.battery - drain_rate * 0.1 * dt)

        # Motor temps
        if self.status in ("moving", "patrolling", "returning"):
            # Heat up during movement: 0.5 C/s
            self.motor_temps = [
                min(85.0, t + 0.5 * dt) for t in self.motor_temps
            ]
        else:
            # Cool down when idle: 0.2 C/s
            self.motor_temps = [
                max(25.0, t - 0.2 * dt) for t in self.motor_temps
            ]

        # Movement
        if self.status in ("moving", "patrolling", "returning") and self._waypoints:
            self._move_toward_waypoint(dt)

        telemetry = self.get_telemetry()
        self._telemetry_log.append(telemetry)
        return telemetry

    def _move_toward_waypoint(self, dt: float) -> None:
        """Move toward the current waypoint."""
        if not self._waypoints or self._waypoint_index >= len(self._waypoints):
            self.speed = 0.0
            if self.status == "patrolling" and self._patrol_loop and self._waypoints:
                self._waypoint_index = 0
            else:
                self.status = "idle"
            return

        target_lat, target_lng = self._waypoints[self._waypoint_index]

        # Calculate bearing and distance
        dlat = target_lat - self.lat
        dlng = target_lng - self.lng

        # Approximate distance in meters
        dlat_m = dlat * (_EARTH_RADIUS * math.pi / 180.0)
        dlng_m = dlng * (_EARTH_RADIUS * math.cos(math.radians(self.lat)) * math.pi / 180.0)
        dist_m = math.hypot(dlat_m, dlng_m)

        if dist_m < 1.0:
            # Arrived at waypoint
            self.lat = target_lat
            self.lng = target_lng
            self._waypoint_index += 1

            if self._waypoint_index >= len(self._waypoints):
                if self.status == "patrolling" and self._patrol_loop:
                    self._waypoint_index = 0
                else:
                    self.speed = 0.0
                    self.status = "idle"
            return

        # Heading: atan2(dlng_m, dlat_m) gives bearing (0=north, CW)
        self.heading = math.degrees(math.atan2(dlng_m, dlat_m)) % 360.0

        # Movement speed from unit type
        type_def = _get_unit_type(self.asset_type)
        max_speed = type_def.speed if type_def else 2.0
        self.speed = max_speed

        # Step in meters
        step = min(max_speed * dt, dist_m)

        # Convert step to lat/lng
        step_lat = _meters_to_lat(step * (dlat_m / dist_m))
        step_lng = _meters_to_lng(step * (dlng_m / dist_m), self.lat)

        self.lat += step_lat
        self.lng += step_lng

    def dispatch(self, lat: float, lng: float) -> None:
        """Command: move to position."""
        self._waypoints = [(lat, lng)]
        self._waypoint_index = 0
        self._patrol_loop = False
        self.status = "moving"
        self._command_log.append({
            "command": "dispatch",
            "lat": lat,
            "lng": lng,
        })

    def patrol(
        self, waypoints: list[tuple[float, float]], loop: bool = True
    ) -> None:
        """Command: follow waypoint path."""
        self._waypoints = list(waypoints)
        self._waypoint_index = 0
        self._patrol_loop = loop
        self.status = "patrolling"
        self._command_log.append({
            "command": "patrol",
            "waypoints": waypoints,
            "loop": loop,
        })

    def recall(self) -> None:
        """Command: return to start position."""
        self._waypoints = [(self._start_lat, self._start_lng)]
        self._waypoint_index = 0
        self._patrol_loop = False
        self.status = "returning"
        self._command_log.append({"command": "recall"})

    def receive_command(self, command: str, params: dict | None = None) -> None:
        """Process a command (dispatch/patrol/recall)."""
        params = params or {}
        if command == "dispatch":
            self.dispatch(params.get("lat", 0.0), params.get("lng", 0.0))
        elif command == "patrol":
            wp = params.get("waypoints", [])
            loop = params.get("loop", True)
            self.patrol(wp, loop=loop)
        elif command == "recall":
            self.recall()

    def get_telemetry(self) -> dict:
        """Return current telemetry as MQTT-compatible dict."""
        return {
            "robot_id": self.robot_id,
            "asset_type": self.asset_type,
            "alliance": self.alliance,
            "lat": self.lat,
            "lng": self.lng,
            "alt": self.alt,
            "heading": round(self.heading, 2),
            "speed": round(self.speed, 2),
            "battery": round(self.battery, 4),
            "motor_temps": [round(t, 1) for t in self.motor_temps],
            "status": self.status,
        }

    def get_cot_telemetry(self) -> str:
        """Return telemetry as CoT XML string."""
        from engine.comms.mqtt_cot import telemetry_to_cot

        return telemetry_to_cot(self.robot_id, self.get_telemetry())


class FakeRobotFleet:
    """Manages multiple FakeRobots for integration testing."""

    def __init__(self) -> None:
        self._robots: dict[str, FakeRobot] = {}

    def add_robot(self, robot_id: str, **kwargs) -> FakeRobot:
        """Add a robot to the fleet."""
        robot = FakeRobot(robot_id=robot_id, **kwargs)
        self._robots[robot_id] = robot
        return robot

    def tick_all(self, dt: float) -> list[dict]:
        """Tick all robots, return list of telemetry dicts."""
        return [robot.tick(dt) for robot in self._robots.values()]

    def dispatch(self, robot_id: str, lat: float, lng: float) -> None:
        """Dispatch a specific robot."""
        robot = self._robots.get(robot_id)
        if robot is not None:
            robot.dispatch(lat, lng)

    def get_robot(self, robot_id: str) -> FakeRobot | None:
        """Get robot by ID."""
        return self._robots.get(robot_id)

    @property
    def robots(self) -> dict[str, FakeRobot]:
        """All robots in the fleet."""
        return dict(self._robots)

    def __len__(self) -> int:
        return len(self._robots)
