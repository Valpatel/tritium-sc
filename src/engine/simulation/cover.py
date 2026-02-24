"""CoverSystem -- per-unit cover state and damage reduction.

Units positioned near cover objects (walls, vehicles, buildings) receive
a damage reduction bonus.  The cover bonus depends on the angle between
the attacker and the cover object relative to the target.

Cover bonus ranges from 0.0 (no cover) to 0.8 (heavy cover).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .target import SimulationTarget


@dataclass
class CoverObject:
    """A cover-providing object on the map."""

    position: tuple[float, float]
    radius: float = 2.0  # how far the cover effect extends
    cover_value: float = 0.5  # base damage reduction (0.0-0.8)


class CoverSystem:
    """Tracks cover objects and computes damage reduction for targets."""

    def __init__(self) -> None:
        self._cover_objects: list[CoverObject] = []
        self._unit_cover: dict[str, float] = {}  # target_id -> cover bonus
        self._cover_points: list[CoverObject] = []
        self._assignments: dict[str, CoverObject] = {}  # target_id -> assigned cover point

    def add_cover(self, cover: CoverObject) -> None:
        """Add a cover object to the system."""
        self._cover_objects.append(cover)

    def add_cover_point(self, position: tuple[float, float]) -> CoverObject:
        """Add a cover point at the given position.

        Returns the created CoverObject.
        """
        cp = CoverObject(position=position)
        self._cover_points.append(cp)
        self._cover_objects.append(cp)
        return cp

    def get_cover_reduction(self, target_id: str) -> float:
        """Return the cover damage reduction for a unit (0.0 to 1.0).

        Returns 0.0 if the unit has no cover assignment.
        """
        if target_id in self._assignments:
            return self._unit_cover.get(target_id, 0.0)
        return 0.0

    def clear_cover(self) -> None:
        """Remove all cover objects."""
        self._cover_objects.clear()
        self._unit_cover.clear()

    def tick(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """Update cover state for all targets based on proximity to cover objects."""
        for tid, t in targets.items():
            if t.status in ("eliminated", "destroyed"):
                continue
            best_cover = 0.0
            best_cover_obj = None
            for cover in self._cover_objects:
                dx = t.position[0] - cover.position[0]
                dy = t.position[1] - cover.position[1]
                dist = math.hypot(dx, dy)
                if dist <= cover.radius:
                    # Closer to cover center = better bonus
                    proximity_factor = 1.0 - (dist / cover.radius)
                    bonus = cover.cover_value * proximity_factor
                    if bonus > best_cover:
                        best_cover = bonus
                        best_cover_obj = cover
            self._unit_cover[tid] = min(best_cover, 0.8)
            # Track cover assignments for cover points
            if best_cover_obj is not None and best_cover > 0.0:
                self._assignments[tid] = best_cover_obj
            else:
                self._assignments.pop(tid, None)

    def get_cover_bonus(
        self,
        target_pos: tuple[float, float],
        attacker_pos: tuple[float, float],
        target_id: str | None = None,
    ) -> float:
        """Return the cover bonus (0.0-0.8) for a target being attacked.

        If *target_id* is provided and has a cached cover value, return that.
        Otherwise compute from cover objects.
        """
        if target_id is not None and target_id in self._unit_cover:
            return self._unit_cover[target_id]

        # Compute from cover objects
        best_cover = 0.0
        for cover in self._cover_objects:
            dx = target_pos[0] - cover.position[0]
            dy = target_pos[1] - cover.position[1]
            dist = math.hypot(dx, dy)
            if dist <= cover.radius:
                # Check if cover is between target and attacker
                ax = attacker_pos[0] - target_pos[0]
                ay = attacker_pos[1] - target_pos[1]
                cx = cover.position[0] - target_pos[0]
                cy = cover.position[1] - target_pos[1]
                # Dot product: cover is effective if roughly between target and attacker
                dot = ax * cx + ay * cy
                if dot > 0:
                    proximity_factor = 1.0 - (dist / cover.radius)
                    bonus = cover.cover_value * proximity_factor
                    best_cover = max(best_cover, bonus)
        return min(best_cover, 0.8)

    def reset(self) -> None:
        """Clear all cover state."""
        self._cover_objects.clear()
        self._unit_cover.clear()
        self._cover_points.clear()
        self._assignments.clear()
