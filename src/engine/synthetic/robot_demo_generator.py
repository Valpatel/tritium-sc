# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Robot demo generator — synthetic robot telemetry for demo mode.

Creates 3 simulated robots (rover, drone, scout) that move along patrol
routes, drain battery, and update the TargetTracker every 5 seconds.
Robots appear as friendly assets on the tactical map.

Usage::

    from engine.synthetic.robot_demo_generator import RobotDemoGenerator

    gen = RobotDemoGenerator(interval=5.0)
    gen.start(event_bus, target_tracker)
    gen.stop()
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from engine.tactical.target_tracker import TargetTracker

logger = logging.getLogger("synthetic.robot_demo")

# Reference coordinates — same neighborhood as Meshtastic demo nodes
_CENTER_LAT = 37.7749
_CENTER_LNG = -122.4194


@dataclass
class _DemoRobot:
    """State for a simulated robot."""
    robot_id: str
    name: str
    robot_type: str  # rover, drone, scout
    lat: float
    lng: float
    heading: float = 0.0  # degrees
    speed: float = 0.0  # m/s
    battery: float = 1.0  # 0-1
    patrol_waypoints: list = field(default_factory=list)
    waypoint_idx: int = 0
    status: str = "active"


# Three demo robots with patrol routes around the demo neighborhood
_DEMO_ROBOTS = [
    _DemoRobot(
        robot_id="rover_01",
        name="Rover-01",
        robot_type="rover",
        lat=_CENTER_LAT + 0.0005,
        lng=_CENTER_LNG + 0.0005,
        speed=1.2,  # walking speed
        battery=0.92,
        patrol_waypoints=[
            (_CENTER_LAT + 0.0005, _CENTER_LNG + 0.0005),
            (_CENTER_LAT + 0.0010, _CENTER_LNG - 0.0003),
            (_CENTER_LAT + 0.0002, _CENTER_LNG - 0.0008),
            (_CENTER_LAT - 0.0003, _CENTER_LNG + 0.0002),
        ],
    ),
    _DemoRobot(
        robot_id="drone_01",
        name="Drone-01",
        robot_type="drone",
        lat=_CENTER_LAT - 0.0003,
        lng=_CENTER_LNG - 0.0005,
        speed=3.5,  # faster aerial movement
        battery=0.78,
        patrol_waypoints=[
            (_CENTER_LAT - 0.0003, _CENTER_LNG - 0.0005),
            (_CENTER_LAT + 0.0008, _CENTER_LNG + 0.0008),
            (_CENTER_LAT - 0.0006, _CENTER_LNG + 0.0010),
            (_CENTER_LAT - 0.0010, _CENTER_LNG - 0.0003),
        ],
    ),
    _DemoRobot(
        robot_id="scout_01",
        name="Scout-01",
        robot_type="scout",
        lat=_CENTER_LAT + 0.0008,
        lng=_CENTER_LNG - 0.0010,
        speed=2.0,
        battery=0.85,
        patrol_waypoints=[
            (_CENTER_LAT + 0.0008, _CENTER_LNG - 0.0010),
            (_CENTER_LAT + 0.0012, _CENTER_LNG + 0.0005),
            (_CENTER_LAT - 0.0002, _CENTER_LNG + 0.0012),
            (_CENTER_LAT - 0.0008, _CENTER_LNG - 0.0008),
        ],
    ),
]


class RobotDemoGenerator:
    """Generates synthetic robot telemetry for demo mode.

    Three robots patrol predefined waypoint routes, updating positions
    via the TargetTracker and publishing MQTT-style telemetry events
    via the EventBus.
    """

    def __init__(self, interval: float = 5.0) -> None:
        self._interval = interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._event_bus: EventBus | None = None
        self._target_tracker: TargetTracker | None = None
        self._robots: list[_DemoRobot] = []
        self._rng = random.Random(2026)
        self._tick_count = 0

    @property
    def running(self) -> bool:
        return self._running

    @property
    def tick_count(self) -> int:
        return self._tick_count

    def start(
        self,
        event_bus: EventBus,
        target_tracker: TargetTracker | None = None,
    ) -> None:
        """Start generating robot telemetry."""
        if self._running:
            return
        self._event_bus = event_bus
        self._target_tracker = target_tracker
        # Deep-copy robot state so restarts get fresh state
        self._robots = []
        for template in _DEMO_ROBOTS:
            r = _DemoRobot(
                robot_id=template.robot_id,
                name=template.name,
                robot_type=template.robot_type,
                lat=template.lat,
                lng=template.lng,
                heading=self._rng.uniform(0, 360),
                speed=template.speed,
                battery=template.battery,
                patrol_waypoints=list(template.patrol_waypoints),
                waypoint_idx=0,
                status="active",
            )
            self._robots.append(r)
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="robot-demo-gen",
        )
        self._thread.start()
        logger.info(
            "Robot demo generator started: %d robots, %.1fs interval",
            len(self._robots), self._interval,
        )

    def stop(self) -> None:
        """Stop generating robot telemetry."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1)
            self._thread = None
        logger.info("Robot demo generator stopped")

    def _loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.debug("RobotDemoGenerator tick error: %s", e)
            time.sleep(self._interval)

    def _tick(self) -> None:
        assert self._event_bus is not None
        self._tick_count += 1

        for robot in self._robots:
            self._move_robot(robot)
            self._drain_battery(robot)
            self._publish_telemetry(robot)
            self._update_tracker(robot)

    def _move_robot(self, robot: _DemoRobot) -> None:
        """Move robot toward its next waypoint."""
        if not robot.patrol_waypoints:
            return

        target_lat, target_lng = robot.patrol_waypoints[robot.waypoint_idx]
        dlat = target_lat - robot.lat
        dlng = target_lng - robot.lng

        # Distance in degrees (approximate)
        dist = math.sqrt(dlat ** 2 + dlng ** 2)

        # ~111320 meters per degree latitude
        # Move speed * interval meters worth of degrees per tick
        step_deg = (robot.speed * self._interval) / 111320.0

        if dist < step_deg * 1.5:
            # Arrived at waypoint — advance to next
            robot.waypoint_idx = (robot.waypoint_idx + 1) % len(robot.patrol_waypoints)
            robot.lat = target_lat
            robot.lng = target_lng
        else:
            # Move toward waypoint
            ratio = step_deg / dist
            robot.lat += dlat * ratio
            robot.lng += dlng * ratio

        # Update heading (degrees, 0=north, clockwise)
        robot.heading = (math.degrees(math.atan2(dlng, dlat)) + 360) % 360

        # Add small drift for realism
        robot.lat += self._rng.gauss(0, 0.000001)
        robot.lng += self._rng.gauss(0, 0.000001)

    def _drain_battery(self, robot: _DemoRobot) -> None:
        """Slowly drain battery."""
        drain = self._rng.uniform(0.0002, 0.0008)
        robot.battery = max(0.05, robot.battery - drain)

    def _publish_telemetry(self, robot: _DemoRobot) -> None:
        """Publish robot telemetry via EventBus (mirrors MQTT robot format)."""
        assert self._event_bus is not None
        telemetry = {
            "robot_id": robot.robot_id,
            "name": robot.name,
            "type": robot.robot_type,
            "position": {
                "lat": robot.lat,
                "lng": robot.lng,
            },
            "heading": robot.heading,
            "speed": robot.speed,
            "battery": robot.battery,
            "status": robot.status,
            "patrol_active": True,
            "waypoint_idx": robot.waypoint_idx,
            "waypoint_count": len(robot.patrol_waypoints),
            "source": "demo",
        }
        self._event_bus.publish("robot:telemetry", telemetry)

    def _update_tracker(self, robot: _DemoRobot) -> None:
        """Update the TargetTracker with robot position."""
        if self._target_tracker is None:
            return
        # Use update_from_simulation which handles the dict format we need
        self._target_tracker.update_from_simulation({
            "target_id": f"robot_{robot.robot_id}",
            "name": robot.name,
            "alliance": "friendly",
            "asset_type": robot.robot_type,
            "position": {"x": 0.0, "y": 0.0},  # Will be overridden by lat/lng
            "heading": robot.heading,
            "speed": robot.speed,
            "battery": robot.battery,
            "status": robot.status,
        })

        # Also publish as a target update with lat/lng for the map
        if self._event_bus is not None:
            self._event_bus.publish("target:updated", {
                "target_id": f"robot_{robot.robot_id}",
                "name": robot.name,
                "alliance": "friendly",
                "asset_type": robot.robot_type,
                "lat": robot.lat,
                "lng": robot.lng,
                "heading": robot.heading,
                "speed": robot.speed,
                "battery": robot.battery,
                "status": robot.status,
                "source": "demo_robot",
            })

    def get_stats(self) -> dict:
        """Return generator statistics."""
        return {
            "running": self._running,
            "tick_count": self._tick_count,
            "robots": [
                {
                    "robot_id": r.robot_id,
                    "name": r.name,
                    "type": r.robot_type,
                    "lat": round(r.lat, 6),
                    "lng": round(r.lng, 6),
                    "heading": round(r.heading, 1),
                    "battery": round(r.battery, 3),
                    "status": r.status,
                }
                for r in self._robots
            ],
        }
