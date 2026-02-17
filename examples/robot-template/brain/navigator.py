"""Waypoint navigator — converts positions into motor commands."""

from __future__ import annotations

import math
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hardware.base import HardwareInterface


class Navigator:
    """Drives the robot toward waypoints using the hardware interface."""

    ARRIVAL_THRESHOLD = 1.0  # units
    TICK_RATE = 10  # Hz

    def __init__(self, hardware: HardwareInterface, config: dict) -> None:
        self._hw = hardware
        self._waypoints: list[tuple[float, float]] = []
        self._waypoint_index: int = 0
        self._patrol_loop: bool = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._status = "idle"

    @property
    def status(self) -> str:
        return self._status

    @property
    def current_waypoint(self) -> tuple[float, float] | None:
        with self._lock:
            if self._waypoints and self._waypoint_index < len(self._waypoints):
                return self._waypoints[self._waypoint_index]
            return None

    def go_to(self, x: float, y: float) -> None:
        """Navigate to a single point."""
        with self._lock:
            self._waypoints = [(x, y)]
            self._waypoint_index = 0
            self._patrol_loop = False
            self._status = "active"

    def patrol(self, waypoints: list[tuple[float, float]]) -> None:
        """Loop through waypoints continuously."""
        if not waypoints:
            return  # Ignore empty patrol
        with self._lock:
            self._waypoints = list(waypoints)
            self._waypoint_index = 0
            self._patrol_loop = True
            self._status = "active"

    def stop(self) -> None:
        """Stop moving."""
        with self._lock:
            self._waypoints = []
            self._waypoint_index = 0
            self._status = "idle"
        self._hw.set_motors(0, 0)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._nav_loop, daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._hw.set_motors(0, 0)

    def _nav_loop(self) -> None:
        while self._running:
            time.sleep(1.0 / self.TICK_RATE)

            with self._lock:
                if not self._waypoints or self._waypoint_index >= len(self._waypoints):
                    if self._status == "active":
                        self._status = "idle"
                    continue

                target = self._waypoints[self._waypoint_index]

            pos = self._hw.get_position()
            dx = target[0] - pos[0]
            dy = target[1] - pos[1]
            dist = math.hypot(dx, dy)

            if dist < self.ARRIVAL_THRESHOLD:
                with self._lock:
                    if self._waypoint_index < len(self._waypoints) - 1:
                        self._waypoint_index += 1
                    elif self._patrol_loop:
                        self._waypoint_index = 0
                    else:
                        self._status = "arrived"
                        self._hw.set_motors(0, 0)
                continue

            # Calculate heading to target
            target_heading = math.degrees(math.atan2(dx, dy)) % 360
            current_heading = self._hw.get_heading() % 360

            # Heading error
            error = (target_heading - current_heading + 180) % 360 - 180

            # Simple proportional steering
            turn = max(-1.0, min(1.0, error / 45.0))
            speed = max(0.3, min(1.0, dist / 10.0))

            left = speed + turn * 0.5
            right = speed - turn * 0.5
            left = max(-1.0, min(1.0, left))
            right = max(-1.0, min(1.0, right))

            self._hw.set_motors(left, right)
