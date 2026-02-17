"""Simulated hardware backend — no real hardware required.

Simulates an RC car moving on a 2D plane. Position updates based on
motor commands and elapsed time. Battery drains slowly. Useful for
testing the full MQTT pipeline without any physical hardware.
"""

from __future__ import annotations

import math
import threading
import time

from .base import HardwareInterface


class SimulatedHardware(HardwareInterface):
    """Simulated robot hardware for testing."""

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

    def _physics_loop(self) -> None:
        """Simple differential drive physics at 50Hz."""
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
                self._x += math.sin(rad) * forward * self._max_speed * dt
                self._y += math.cos(rad) * forward * self._max_speed * dt

                # Battery drain when moving
                if abs(forward) > 0.05:
                    self._battery = max(0, self._battery - self._battery_drain * dt)
