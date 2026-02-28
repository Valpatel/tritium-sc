# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shared helpers for behavior classes."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..target import SimulationTarget


def nearest_in_range(
    unit: SimulationTarget,
    enemies: dict[str, SimulationTarget],
) -> SimulationTarget | None:
    """Find the nearest enemy within weapon_range."""
    best: SimulationTarget | None = None
    best_dist = float("inf")
    for enemy in enemies.values():
        dx = enemy.position[0] - unit.position[0]
        dy = enemy.position[1] - unit.position[1]
        dist = math.hypot(dx, dy)
        if dist <= unit.weapon_range and dist < best_dist:
            best_dist = dist
            best = enemy
    return best
