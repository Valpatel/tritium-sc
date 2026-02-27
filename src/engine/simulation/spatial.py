"""SpatialGrid — grid-based spatial partitioning for O(1) neighbor queries.

Used by the SimulationEngine to replace O(n^2) scans in combat,
behaviors, and FSM context enrichment.  Rebuilt once per tick from
the target list, then queried many times.

Cell size of 50m means most weapon/vision ranges (25-100m) require
checking at most a 3x3 neighbourhood of cells.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .target import SimulationTarget


class SpatialGrid:
    """Grid-based spatial partitioning for O(1) neighbor queries."""

    def __init__(self, cell_size: float = 50.0) -> None:
        self._cell_size = cell_size
        self._inv_cell_size = 1.0 / cell_size
        self._cells: dict[tuple[int, int], list[SimulationTarget]] = {}

    def _cell_key(self, x: float, y: float) -> tuple[int, int]:
        """Convert world position to cell key."""
        return (int(math.floor(x * self._inv_cell_size)),
                int(math.floor(y * self._inv_cell_size)))

    def rebuild(self, targets: list[SimulationTarget]) -> None:
        """Rebuild the entire grid from scratch (once per tick)."""
        cells: dict[tuple[int, int], list[SimulationTarget]] = {}
        for t in targets:
            key = self._cell_key(t.position[0], t.position[1])
            bucket = cells.get(key)
            if bucket is None:
                bucket = []
                cells[key] = bucket
            bucket.append(t)
        self._cells = cells

    def query_radius(self, pos: tuple[float, float], radius: float) -> list[SimulationTarget]:
        """Return all targets within radius of pos. O(k) where k = nearby targets."""
        px, py = pos
        r2 = radius * radius

        # Determine which cells overlap the query circle
        min_cx = int(math.floor((px - radius) * self._inv_cell_size))
        max_cx = int(math.floor((px + radius) * self._inv_cell_size))
        min_cy = int(math.floor((py - radius) * self._inv_cell_size))
        max_cy = int(math.floor((py + radius) * self._inv_cell_size))

        result: list[SimulationTarget] = []
        cells = self._cells
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                bucket = cells.get((cx, cy))
                if bucket is None:
                    continue
                for t in bucket:
                    dx = t.position[0] - px
                    dy = t.position[1] - py
                    if dx * dx + dy * dy <= r2:
                        result.append(t)
        return result

    def query_rect(self, min_xy: tuple[float, float], max_xy: tuple[float, float]) -> list[SimulationTarget]:
        """Return all targets in bounding box [min_xy, max_xy]."""
        x_min, y_min = min_xy
        x_max, y_max = max_xy

        min_cx = int(math.floor(x_min * self._inv_cell_size))
        max_cx = int(math.floor(x_max * self._inv_cell_size))
        min_cy = int(math.floor(y_min * self._inv_cell_size))
        max_cy = int(math.floor(y_max * self._inv_cell_size))

        result: list[SimulationTarget] = []
        cells = self._cells
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                bucket = cells.get((cx, cy))
                if bucket is None:
                    continue
                for t in bucket:
                    tx, ty = t.position
                    if x_min <= tx <= x_max and y_min <= ty <= y_max:
                        result.append(t)
        return result
