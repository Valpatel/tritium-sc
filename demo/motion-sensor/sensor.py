# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Detection state machine for the demo motion sensor.

States: idle -> triggered -> cooldown -> idle
Cooldown per sensor type:
  pir: 5s, microwave: 0.5s, acoustic: 1s, tripwire: 2s
"""

import random
import time
from datetime import datetime, timezone
from enum import Enum


class SensorState(Enum):
    IDLE = "idle"
    TRIGGERED = "triggered"
    COOLDOWN = "cooldown"


# Cooldown durations in seconds per sensor type
COOLDOWN_DURATIONS: dict[str, float] = {
    "pir": 5.0,
    "microwave": 0.5,
    "acoustic": 1.0,
    "tripwire": 2.0,
}

DEFAULT_COOLDOWN = 2.0


class MotionSensor:
    """Three-state detection machine: idle, triggered, cooldown."""

    def __init__(
        self,
        sensor_id: str,
        sensor_type: str,
        zone: str = "default",
        position_x: float = 0.0,
        position_y: float = 0.0,
    ):
        self.sensor_id = sensor_id
        self.sensor_type = sensor_type
        self.zone = zone
        self.position_x = position_x
        self.position_y = position_y

        self.state = SensorState.IDLE
        self.enabled = True
        self.cooldown_seconds = COOLDOWN_DURATIONS.get(sensor_type, DEFAULT_COOLDOWN)
        self._cooldown_start: float | None = None

    def trigger(self) -> dict | None:
        """Attempt to trigger the sensor.

        Returns a detection event dict if successful, None if the sensor
        is disabled, already triggered, or in cooldown.
        """
        if not self.enabled:
            return None
        if self.state != SensorState.IDLE:
            return None

        self.state = SensorState.TRIGGERED
        confidence = round(random.uniform(0.7, 1.0), 2)
        duration_ms = random.randint(100, 5000)
        peak_amplitude = round(random.uniform(0.3, 1.0), 2)

        event = {
            "sensor_id": self.sensor_id,
            "sensor_type": self.sensor_type,
            "event": "motion_detected",
            "confidence": confidence,
            "position": {"x": self.position_x, "y": self.position_y},
            "zone": self.zone,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "metadata": {
                "duration_ms": duration_ms,
                "peak_amplitude": peak_amplitude,
            },
        }
        return event

    def clear(self) -> None:
        """Clear the trigger -- transitions from triggered to cooldown.

        No-op if not in triggered state.
        """
        if self.state == SensorState.TRIGGERED:
            self.state = SensorState.COOLDOWN
            self._cooldown_start = time.monotonic()

    def tick(self) -> None:
        """Advance the state machine clock.

        Checks if cooldown has expired and transitions back to idle.
        """
        if self.state == SensorState.COOLDOWN and self._cooldown_start is not None:
            elapsed = time.monotonic() - self._cooldown_start
            if elapsed >= self.cooldown_seconds:
                self.state = SensorState.IDLE
                self._cooldown_start = None
