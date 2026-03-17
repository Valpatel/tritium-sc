# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Speed tagger processor addon example.

Subscribes to target updates and tags each target with a speed
classification based on its velocity: stationary, walking, vehicle, or fast.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from tritium_lib.sdk import ProcessorAddon, AddonInfo

log = logging.getLogger("addon.speed-tagger")

# Speed thresholds in meters per second
SPEED_CLASSES = [
    (0.5, "stationary"),
    (2.0, "walking"),
    (15.0, "vehicle"),
    (float("inf"), "fast"),
]


def classify_speed(speed_mps: float) -> str:
    """Classify a speed in m/s into a human-readable category.

    Args:
        speed_mps: Speed in meters per second (must be >= 0).

    Returns:
        One of: "stationary", "walking", "vehicle", "fast".
    """
    if speed_mps < 0:
        speed_mps = 0.0
    for threshold, label in SPEED_CLASSES:
        if speed_mps < threshold:
            return label
    return "fast"


def compute_speed(target: dict) -> float | None:
    """Extract or compute speed from a target dict.

    Looks for explicit speed fields first, then falls back to computing
    from velocity components if available.

    Args:
        target: Target dict that may contain speed or velocity fields.

    Returns:
        Speed in m/s, or None if not determinable.
    """
    # Explicit speed field
    speed = target.get("speed_mps")
    if speed is not None:
        return float(speed)

    speed = target.get("speed")
    if speed is not None:
        return float(speed)

    # Velocity components (vx, vy in m/s)
    vx = target.get("vx")
    vy = target.get("vy")
    if vx is not None and vy is not None:
        return math.sqrt(float(vx) ** 2 + float(vy) ** 2)

    # Velocity dict
    vel = target.get("velocity")
    if isinstance(vel, dict):
        vx = vel.get("x", vel.get("vx", 0))
        vy = vel.get("y", vel.get("vy", 0))
        vz = vel.get("z", vel.get("vz", 0))
        return math.sqrt(float(vx) ** 2 + float(vy) ** 2 + float(vz) ** 2)

    return None


class SpeedTaggerAddon(ProcessorAddon):
    """Tags targets with speed_class based on their velocity."""

    info = AddonInfo(
        id="processor-speed-tagger",
        name="Speed Tagger",
        version="1.0.0",
        description="Classifies targets by speed: stationary, walking, vehicle, fast",
        author="Valpatel Software LLC",
        category="intelligence",
    )

    def __init__(self):
        super().__init__()
        self._tagged_count: int = 0

    async def register(self, app: Any) -> None:
        await super().register(app)
        self._tagged_count = 0
        log.info("Speed tagger registered")

    async def unregister(self, app: Any) -> None:
        log.info(f"Speed tagger unregistered (tagged {self._tagged_count} targets)")
        await super().unregister(app)

    async def process(self, target: dict) -> dict:
        """Add speed_class field to the target based on its velocity.

        If the target has no speed or velocity information, speed_class
        is set to "unknown".

        Args:
            target: Target dict from the tracker.

        Returns:
            Target dict with speed_class and speed_mps added.
        """
        speed = compute_speed(target)
        if speed is not None:
            target["speed_mps"] = round(speed, 3)
            target["speed_class"] = classify_speed(speed)
        else:
            target["speed_class"] = "unknown"

        self._tagged_count += 1
        return target

    def health_check(self) -> dict:
        if not self._registered:
            return {"status": "not_registered"}
        return {
            "status": "ok",
            "tagged_count": self._tagged_count,
        }
