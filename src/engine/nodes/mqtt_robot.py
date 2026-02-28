# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MQTTSensorNode — wraps an MQTT-connected robot as a SensorNode.

Bridges MQTT robot telemetry and commands into Amy's node system.
Auto-discovered by MQTTBridge when a robot first publishes telemetry.
"""
from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from engine.nodes.base import SensorNode

if TYPE_CHECKING:
    from engine.comms.mqtt_bridge import MQTTBridge

logger = logging.getLogger("amy.mqtt_robot")


class MQTTSensorNode(SensorNode):
    """A sensor node backed by an MQTT-connected robot."""

    def __init__(
        self,
        bridge: MQTTBridge,
        robot_id: str,
        site_id: str = "home",
    ):
        super().__init__(node_id=f"mqtt-{robot_id}", name=f"Robot {robot_id}")
        self._bridge = bridge
        self._robot_id = robot_id
        self._site = site_id
        self._position: tuple[float, float] = (0.0, 0.0)
        self._heading: float = 0.0
        self._battery: float = 1.0
        self._status: str = "unknown"
        self._last_telemetry: float = 0.0  # monotonic timestamp

    @property
    def is_stale(self) -> bool:
        """True if no telemetry received for 10+ seconds."""
        if self._last_telemetry == 0.0:
            return True
        return time.monotonic() - self._last_telemetry > 10.0

    @property
    def world_position(self) -> tuple[float, float]:
        """Cached world position from last telemetry."""
        return self._position

    def update_telemetry(self, data: dict) -> None:
        """Called by MQTTBridge when telemetry arrives."""
        self._position = (
            float(data.get("x", self._position[0])),
            float(data.get("y", self._position[1])),
        )
        self._heading = float(data.get("heading", self._heading))
        self._battery = float(data.get("battery", self._battery))
        self._status = data.get("status", self._status)
        self._last_telemetry = time.monotonic()

    def _publish_command(self, payload: dict) -> None:
        """Publish a command to this robot's MQTT command topic."""
        topic = f"tritium/{self._site}/robots/{self._robot_id}/command"
        payload["timestamp"] = time.time()
        self._bridge.publish(topic, json.dumps(payload))

    def dispatch_to(self, x: float, y: float) -> None:
        """Send dispatch command to robot."""
        self._publish_command({"action": "dispatch", "x": x, "y": y})
        logger.info(f"Dispatched {self._robot_id} to ({x:.1f}, {y:.1f})")

    def patrol(self, waypoints: list[dict]) -> None:
        """Send patrol command with waypoints."""
        self._publish_command({"action": "patrol", "waypoints": waypoints})
        logger.info(f"Patrol {self._robot_id}: {len(waypoints)} waypoints")

    def recall(self) -> None:
        """Recall robot to base."""
        self._publish_command({"action": "recall"})
        logger.info(f"Recalled {self._robot_id}")

    def move(self, pan_dir: int, tilt_dir: int, duration: float) -> tuple[bool, bool]:
        """Send turret aim command (if robot has turret)."""
        self._publish_command({
            "action": "turret_aim",
            "pan_dir": pan_dir,
            "tilt_dir": tilt_dir,
            "duration": duration,
        })
        return (True, True)
