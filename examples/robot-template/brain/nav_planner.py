# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Navigation Planner — path planning and position management.

Provides a clear separation between simulation and real navigation:

SIMULATION MODE (default):
    - Position comes from SimulatedHardware (2D plane physics)
    - Path planning is simple straight-line waypoint following
    - World coordinates match TRITIUM-SC simulation (1 unit = 1 meter)
    - No GPS required

REAL HARDWARE MODE (stubs — implement for your platform):
    - Position from GPS (lat/lng → game coordinates via geo.js math)
    - Path planning via ROS2 Nav2, SLAM, or custom A*
    - Obstacle avoidance from LiDAR/ultrasonic sensors
    - Coordinate transform between GPS WGS84 and game meters

The thinker and commander speak in game coordinates (meters from map center).
This module handles the translation to/from whatever the hardware uses.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorldPosition:
    """Position in the game world (meters from map center)."""
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0  # degrees, 0 = north, clockwise

    def distance_to(self, other: "WorldPosition") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def bearing_to(self, other: "WorldPosition") -> float:
        """Compass bearing from this position to another (degrees)."""
        dx = other.x - self.x
        dy = other.y - self.y
        return math.degrees(math.atan2(dx, dy)) % 360

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "heading": self.heading}

    @classmethod
    def from_dict(cls, d: dict) -> "WorldPosition":
        return cls(x=d.get("x", 0), y=d.get("y", 0), heading=d.get("heading", 0))


@dataclass
class GpsPosition:
    """GPS position (WGS84)."""
    lat: float = 0.0
    lng: float = 0.0
    altitude: float = 0.0


@dataclass
class NavWaypoint:
    """A waypoint in a navigation path."""
    position: WorldPosition
    speed: float = 1.0  # 0.0-1.0 normalized
    action: str = ""  # Optional action at waypoint: "fire", "scan", "wait"

    def to_dict(self) -> dict:
        d = self.position.to_dict()
        d["speed"] = self.speed
        if self.action:
            d["action"] = self.action
        return d


@dataclass
class NavPath:
    """A planned navigation path."""
    waypoints: list[NavWaypoint] = field(default_factory=list)
    loop: bool = False

    @property
    def total_distance(self) -> float:
        """Total path distance in meters."""
        if len(self.waypoints) < 2:
            return 0.0
        total = 0.0
        for i in range(len(self.waypoints) - 1):
            total += self.waypoints[i].position.distance_to(self.waypoints[i + 1].position)
        return total


# =========================================================================
# Coordinate Transforms
# =========================================================================

# Earth constants for coordinate math
_EARTH_RADIUS = 6371000  # meters
_DEG_TO_RAD = math.pi / 180


def gps_to_world(
    gps: GpsPosition,
    origin_lat: float,
    origin_lng: float,
) -> WorldPosition:
    """Convert GPS (WGS84) to game world coordinates (meters from origin).

    Uses equirectangular projection — accurate enough for neighborhood scale
    (<1km). Same math as frontend/js/geo.js latlngToGame().

    Args:
        gps: GPS position to convert.
        origin_lat: Map center latitude (from layout config).
        origin_lng: Map center longitude (from layout config).

    Returns:
        WorldPosition in game meters.
    """
    dlat = (gps.lat - origin_lat) * _DEG_TO_RAD
    dlng = (gps.lng - origin_lng) * _DEG_TO_RAD
    cos_lat = math.cos(origin_lat * _DEG_TO_RAD)

    x = dlng * cos_lat * _EARTH_RADIUS  # East = +X
    y = dlat * _EARTH_RADIUS  # North = +Y

    return WorldPosition(x=x, y=y)


def world_to_gps(
    pos: WorldPosition,
    origin_lat: float,
    origin_lng: float,
) -> GpsPosition:
    """Convert game world coordinates back to GPS (WGS84).

    Inverse of gps_to_world().
    """
    cos_lat = math.cos(origin_lat * _DEG_TO_RAD)
    lat = origin_lat + (pos.y / _EARTH_RADIUS) / _DEG_TO_RAD
    lng = origin_lng + (pos.x / (_EARTH_RADIUS * cos_lat)) / _DEG_TO_RAD

    return GpsPosition(lat=lat, lng=lng)


# =========================================================================
# Path Planner Interface
# =========================================================================

class PathPlanner(ABC):
    """Abstract path planner — implement for your navigation stack."""

    @abstractmethod
    def plan(self, start: WorldPosition, goal: WorldPosition) -> NavPath:
        """Plan a path from start to goal.

        Returns a NavPath with waypoints. The planner should handle
        obstacle avoidance, terrain, and any constraints.
        """

    @abstractmethod
    def replan(self, current: WorldPosition, goal: WorldPosition) -> NavPath:
        """Replan after deviation or new obstacles."""


class StraightLinePlanner(PathPlanner):
    """Simulation path planner — direct line between points.

    No obstacle avoidance. Works well with SimulatedHardware where
    the 2D plane is obstacle-free. This is the default for simulation.
    """

    def plan(self, start: WorldPosition, goal: WorldPosition) -> NavPath:
        return NavPath(waypoints=[
            NavWaypoint(position=start),
            NavWaypoint(position=goal),
        ])

    def replan(self, current: WorldPosition, goal: WorldPosition) -> NavPath:
        return self.plan(current, goal)


class WaypointPlanner(PathPlanner):
    """Multi-waypoint planner — follows a predefined route.

    Useful for patrol routes defined in TRITIUM-SC layouts.
    No dynamic obstacle avoidance.
    """

    def __init__(self, waypoints: list[WorldPosition] | None = None):
        self._waypoints = waypoints or []

    def plan(self, start: WorldPosition, goal: WorldPosition) -> NavPath:
        # If we have predefined waypoints, use them
        if self._waypoints:
            return NavPath(waypoints=[
                NavWaypoint(position=wp) for wp in self._waypoints
            ])
        # Otherwise straight line
        return NavPath(waypoints=[
            NavWaypoint(position=start),
            NavWaypoint(position=goal),
        ])

    def replan(self, current: WorldPosition, goal: WorldPosition) -> NavPath:
        return self.plan(current, goal)


# =========================================================================
# REAL NAVIGATION STUBS — Replace these for actual hardware
# =========================================================================

class Nav2Planner(PathPlanner):
    """STUB: ROS2 Nav2 path planner.

    TODO: Implement for real ROS2 navigation. This would:
    1. Connect to the Nav2 action server
    2. Send NavigateToPose goals
    3. Use costmaps for obstacle avoidance
    4. Return the planned path from Nav2's planner

    Requires: rclpy, nav2_simple_commander
    """

    def plan(self, start: WorldPosition, goal: WorldPosition) -> NavPath:
        raise NotImplementedError(
            "Nav2Planner is a stub. Implement with ROS2 Nav2 integration. "
            "See: https://docs.nav2.org/commander_api/index.html"
        )

    def replan(self, current: WorldPosition, goal: WorldPosition) -> NavPath:
        raise NotImplementedError("Nav2Planner.replan() not implemented")


class SlamPlanner(PathPlanner):
    """STUB: SLAM-based path planner.

    TODO: Implement for robots with LiDAR/depth cameras. This would:
    1. Maintain a local occupancy grid from sensor data
    2. Run A* or RRT* for path planning
    3. Update the map as obstacles are detected
    4. Re-plan when path is blocked

    Requires: OpenCV, NumPy, sensor driver
    """

    def plan(self, start: WorldPosition, goal: WorldPosition) -> NavPath:
        raise NotImplementedError(
            "SlamPlanner is a stub. Implement with your SLAM stack. "
            "See: ORB-SLAM3, rtabmap, or cartographer for mapping."
        )

    def replan(self, current: WorldPosition, goal: WorldPosition) -> NavPath:
        raise NotImplementedError("SlamPlanner.replan() not implemented")


class GpsNavigator:
    """STUB: GPS-based outdoor navigation.

    TODO: Implement for robots with GPS receivers. This would:
    1. Read GPS position from serial/NMEA device
    2. Convert GPS → game world coordinates using gps_to_world()
    3. Calculate bearing and distance to next waypoint
    4. Generate motor commands for heading correction

    Requires: pyserial or gpsd-py3
    """

    def __init__(self, origin_lat: float = 0.0, origin_lng: float = 0.0):
        self._origin_lat = origin_lat
        self._origin_lng = origin_lng

    def get_position(self) -> WorldPosition:
        """STUB: Read GPS and convert to game coordinates."""
        raise NotImplementedError(
            "GpsNavigator.get_position() is a stub. "
            "Implement with your GPS receiver (pyserial + NMEA parsing)."
        )

    def navigate_to(self, goal: WorldPosition) -> None:
        """STUB: Navigate to a game-world position using GPS."""
        raise NotImplementedError(
            "GpsNavigator.navigate_to() is a stub. "
            "Implement GPS waypoint following with heading correction."
        )
