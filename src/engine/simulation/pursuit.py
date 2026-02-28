# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""PursuitSystem -- intercept waypoint computation for rovers.

When a hostile is detected, the pursuit system computes an intercept
waypoint that a rover can navigate to in order to cut off the hostile's
projected path.  This is more effective than simply chasing a target's
current position.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .target import SimulationTarget


class PursuitSystem:
    """Computes intercept waypoints for pursuing units."""

    def __init__(self) -> None:
        self._intercept_points: dict[str, tuple[float, float]] = {}
        self._pursuit_assignments: dict[str, str] = {}  # pursuer_id -> target_id

    def assign(self, pursuer_id: str, target_id: str) -> None:
        """Manually assign a pursuer to a target."""
        self._pursuit_assignments[pursuer_id] = target_id

    def get_assignment(self, pursuer_id: str) -> str | None:
        """Get the target_id that a pursuer is assigned to chase."""
        return self._pursuit_assignments.get(pursuer_id)

    def tick(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """Recompute intercept points for all active hostiles.

        Also auto-assign mobile friendlies to nearest hostiles if not
        already assigned.
        """
        self._intercept_points.clear()
        hostiles = {
            tid: t for tid, t in targets.items()
            if t.alliance == "hostile" and t.status == "active"
        }
        for tid, hostile in hostiles.items():
            intercept = self._compute_intercept(hostile)
            if intercept is not None:
                self._intercept_points[tid] = intercept

        # Auto-assign mobile friendlies to nearest hostiles
        if hostiles:
            mobile_friendlies = {
                tid: t for tid, t in targets.items()
                if t.alliance == "friendly" and t.status == "active" and t.speed > 0
            }
            for fid, friendly in mobile_friendlies.items():
                if fid in self._pursuit_assignments:
                    # Already assigned -- check target still valid
                    existing = self._pursuit_assignments[fid]
                    if existing in hostiles:
                        continue
                    # Target gone, clear assignment
                    del self._pursuit_assignments[fid]
                # Find nearest hostile
                best_dist = float("inf")
                best_hid = None
                for hid, hostile in hostiles.items():
                    dx = hostile.position[0] - friendly.position[0]
                    dy = hostile.position[1] - friendly.position[1]
                    dist = math.hypot(dx, dy)
                    if dist < best_dist:
                        best_dist = dist
                        best_hid = hid
                if best_hid is not None:
                    self._pursuit_assignments[fid] = best_hid

    def get_intercept_point(self, hostile_id: str) -> tuple[float, float] | None:
        """Return the computed intercept point for a hostile, or None."""
        return self._intercept_points.get(hostile_id)

    def assign_pursuit(self, pursuer_id: str, hostile_id: str) -> None:
        """Assign a pursuer to chase a specific hostile."""
        self._pursuit_assignments[pursuer_id] = hostile_id

    def get_pursuit_target(self, pursuer_id: str) -> str | None:
        """Return the hostile ID that a pursuer is assigned to chase."""
        return self._pursuit_assignments.get(pursuer_id)

    def get_pursuit_waypoint(self, pursuer_id: str) -> tuple[float, float] | None:
        """Return the intercept waypoint for a pursuer's assigned target."""
        target_id = self._pursuit_assignments.get(pursuer_id)
        if target_id is None:
            return None
        return self._intercept_points.get(target_id)

    def _compute_intercept(self, hostile: SimulationTarget) -> tuple[float, float] | None:
        """Compute where the hostile will be in a few seconds based on waypoints.

        Uses the hostile's current heading and speed to predict position.
        Returns the predicted position 3 seconds ahead.
        """
        if hostile.speed <= 0:
            return hostile.position

        # Predict position 3 seconds ahead along current heading
        look_ahead = 3.0
        heading_rad = math.radians(hostile.heading)
        # heading 0 = north (+y), atan2(dx, dy) convention
        predicted_x = hostile.position[0] + math.sin(heading_rad) * hostile.speed * look_ahead
        predicted_y = hostile.position[1] + math.cos(heading_rad) * hostile.speed * look_ahead
        return (predicted_x, predicted_y)

    def reset(self) -> None:
        """Clear all pursuit state."""
        self._intercept_points.clear()
        self._pursuit_assignments.clear()
