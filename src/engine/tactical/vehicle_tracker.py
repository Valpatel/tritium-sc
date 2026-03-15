# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Vehicle behavior tracking — speed, direction, and suspicious scoring.

When YOLO detects a vehicle, consecutive frame positions are used to compute
speed and heading. Vehicles moving >30mph on roads are normal; vehicles
stopping in unusual locations are flagged as suspicious.

Integrates with the TargetTracker to process vehicle-class detections and
maintain per-vehicle behavior profiles.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Optional

logger = logging.getLogger("vehicle_tracker")

# Vehicle YOLO class names
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle"}

# Speed thresholds
STOPPED_SPEED_MPH = 2.0
NORMAL_ROAD_SPEED_MPH = 30.0
PARKED_DURATION_S = 60.0
MAX_TRAIL_LENGTH = 20


class VehicleBehavior:
    """Tracks a single vehicle's behavior over time.

    Maintains a position history and computes speed, heading, stopped
    duration, and suspicious score from consecutive observations.
    """

    def __init__(self, target_id: str, vehicle_class: str = "car") -> None:
        self.target_id = target_id
        self.vehicle_class = vehicle_class
        self.positions: list[tuple[float, float, float]] = []  # (x, y, timestamp)
        self.speed_mph: float = 0.0
        self.heading: float = 0.0
        self.stopped_since: Optional[float] = None
        self.speed_history: list[float] = []  # Recent speed samples
        self.heading_history: list[float] = []  # Recent heading samples
        self._max_history = 50

    @property
    def stopped_duration_s(self) -> float:
        """How long the vehicle has been stopped."""
        if self.stopped_since is None:
            return 0.0
        return time.monotonic() - self.stopped_since

    @property
    def is_parked(self) -> bool:
        """True if stopped for more than PARKED_DURATION_S."""
        return self.stopped_duration_s > PARKED_DURATION_S

    @property
    def is_moving(self) -> bool:
        """True if speed is above STOPPED_SPEED_MPH."""
        return self.speed_mph >= STOPPED_SPEED_MPH

    @property
    def direction_label(self) -> str:
        """Compass direction label."""
        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        idx = int((self.heading % 360 + 22.5) / 45.0) % 8
        return directions[idx]

    @property
    def speed_variance(self) -> float:
        """Variance of recent speed samples."""
        if len(self.speed_history) < 2:
            return 0.0
        avg = sum(self.speed_history) / len(self.speed_history)
        return sum((s - avg) ** 2 for s in self.speed_history) / len(self.speed_history)

    @property
    def heading_change_rate(self) -> float:
        """Rate of heading change in degrees/second from recent history."""
        if len(self.positions) < 2:
            return 0.0
        if len(self.heading_history) < 2:
            return 0.0
        # Compute average heading change rate
        total_change = 0.0
        for i in range(1, len(self.heading_history)):
            delta = abs(self.heading_history[i] - self.heading_history[i - 1])
            if delta > 180:
                delta = 360 - delta
            total_change += delta

        time_span = self.positions[-1][2] - self.positions[max(0, len(self.positions) - len(self.heading_history))][2]
        if time_span <= 0:
            return 0.0
        return total_change / time_span

    def update(self, x: float, y: float, timestamp: Optional[float] = None) -> None:
        """Record a new position observation.

        Computes speed and heading from the previous position.

        Args:
            x: X coordinate (meters or local units).
            y: Y coordinate (meters or local units).
            timestamp: Observation time (monotonic). Defaults to now.
        """
        ts = timestamp or time.monotonic()

        if self.positions:
            prev_x, prev_y, prev_ts = self.positions[-1]
            dt = ts - prev_ts

            if dt > 0.01:  # Avoid division by very small time deltas
                # Compute distance and speed
                dx = x - prev_x
                dy = y - prev_y
                distance_m = math.hypot(dx, dy)
                speed_mps = distance_m / dt
                self.speed_mph = speed_mps * 2.23694  # m/s to mph

                # Compute heading (0=north, clockwise)
                if dx != 0 or dy != 0:
                    self.heading = math.degrees(math.atan2(dx, dy)) % 360

                # Record history
                self.speed_history.append(self.speed_mph)
                if len(self.speed_history) > self._max_history:
                    self.speed_history = self.speed_history[-self._max_history:]

                self.heading_history.append(self.heading)
                if len(self.heading_history) > self._max_history:
                    self.heading_history = self.heading_history[-self._max_history:]

                # Update stopped tracking
                if self.speed_mph < STOPPED_SPEED_MPH:
                    if self.stopped_since is None:
                        self.stopped_since = ts
                else:
                    self.stopped_since = None

        # Record position
        self.positions.append((x, y, ts))
        if len(self.positions) > MAX_TRAIL_LENGTH:
            self.positions = self.positions[-MAX_TRAIL_LENGTH:]

    def get_suspicious_score(self, is_unusual_location: bool = False) -> float:
        """Compute suspicious behavior score.

        Args:
            is_unusual_location: Whether this vehicle is stopped in an
                unusual location (not a parking area, intersection, etc.).

        Returns:
            Score between 0.0 and 1.0.
        """
        score = 0.0

        # Loitering
        stopped = self.stopped_duration_s
        if stopped > 300:
            score += 0.3
        elif stopped > 60:
            score += 0.15

        # Unusual location amplifier
        if is_unusual_location and stopped > 30:
            score += 0.25

        # Slow crawling (possible surveillance)
        if STOPPED_SPEED_MPH < self.speed_mph < 10.0:
            score += 0.15

        # Erratic speed
        sv = self.speed_variance
        if sv > 100:
            score += 0.15
        elif sv > 25:
            score += 0.08

        # Erratic heading
        hcr = self.heading_change_rate
        if hcr > 30:
            score += 0.15
        elif hcr > 10:
            score += 0.08

        return min(1.0, max(0.0, round(score, 3)))

    def to_dict(self) -> dict:
        """Export vehicle behavior as a dictionary."""
        return {
            "target_id": self.target_id,
            "vehicle_class": self.vehicle_class,
            "speed_mph": round(self.speed_mph, 1),
            "heading": round(self.heading, 1),
            "direction": self.direction_label,
            "stopped_duration_s": round(self.stopped_duration_s, 1),
            "is_parked": self.is_parked,
            "is_moving": self.is_moving,
            "suspicious_score": self.get_suspicious_score(),
            "speed_variance": round(self.speed_variance, 2),
            "heading_change_rate": round(self.heading_change_rate, 2),
            "trail": [(x, y) for x, y, _ in self.positions],
            "position_count": len(self.positions),
        }


class VehicleTrackingManager:
    """Manages behavior tracking for all detected vehicles.

    Maintains VehicleBehavior instances keyed by target_id. Provides
    methods to update from YOLO detections and query vehicle states.
    """

    def __init__(self, max_vehicles: int = 200) -> None:
        self._vehicles: dict[str, VehicleBehavior] = {}
        self._max_vehicles = max_vehicles

    @property
    def count(self) -> int:
        return len(self._vehicles)

    def update_vehicle(
        self,
        target_id: str,
        x: float,
        y: float,
        vehicle_class: str = "car",
        timestamp: Optional[float] = None,
    ) -> VehicleBehavior:
        """Update or create a vehicle behavior tracker.

        Args:
            target_id: Unique target ID.
            x: X position.
            y: Y position.
            vehicle_class: YOLO class name.
            timestamp: Observation time.

        Returns:
            The updated VehicleBehavior instance.
        """
        if target_id not in self._vehicles:
            if len(self._vehicles) >= self._max_vehicles:
                self._evict_oldest()
            self._vehicles[target_id] = VehicleBehavior(target_id, vehicle_class)

        vb = self._vehicles[target_id]
        vb.update(x, y, timestamp)
        return vb

    def get_vehicle(self, target_id: str) -> Optional[VehicleBehavior]:
        """Get a vehicle behavior tracker by ID."""
        return self._vehicles.get(target_id)

    def get_all(self) -> list[VehicleBehavior]:
        """Get all tracked vehicles."""
        return list(self._vehicles.values())

    def get_suspicious(self, threshold: float = 0.3) -> list[VehicleBehavior]:
        """Get vehicles with suspicious score above threshold."""
        return [
            v for v in self._vehicles.values()
            if v.get_suspicious_score() >= threshold
        ]

    def get_stopped(self) -> list[VehicleBehavior]:
        """Get all stopped vehicles."""
        return [v for v in self._vehicles.values() if not v.is_moving]

    def get_parked(self) -> list[VehicleBehavior]:
        """Get all parked vehicles (stopped > 60s)."""
        return [v for v in self._vehicles.values() if v.is_parked]

    def remove(self, target_id: str) -> None:
        """Remove a vehicle from tracking."""
        self._vehicles.pop(target_id, None)

    def get_summary(self) -> dict:
        """Get summary statistics."""
        vehicles = list(self._vehicles.values())
        moving = [v for v in vehicles if v.is_moving]
        stopped = [v for v in vehicles if not v.is_moving]
        parked = [v for v in vehicles if v.is_parked]
        suspicious = self.get_suspicious()

        return {
            "total": len(vehicles),
            "moving": len(moving),
            "stopped": len(stopped),
            "parked": len(parked),
            "suspicious": len(suspicious),
            "avg_speed_mph": (
                round(sum(v.speed_mph for v in moving) / len(moving), 1)
                if moving else 0.0
            ),
        }

    def _evict_oldest(self) -> None:
        """Remove the vehicle with the oldest last observation."""
        if not self._vehicles:
            return
        oldest_id = min(
            self._vehicles,
            key=lambda k: self._vehicles[k].positions[-1][2] if self._vehicles[k].positions else 0,
        )
        del self._vehicles[oldest_id]
