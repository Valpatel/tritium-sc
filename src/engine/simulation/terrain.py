# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TerrainMap -- spatial index for terrain features.

Architecture
------------
TerrainMap divides the battlespace into a grid of cells (default 5m resolution).
Each cell carries a terrain type with associated movement cost, cover value,
and visibility.  The grid provides O(1) lookup for any world position.

Terrain types and their properties:
  road:     movement_cost=0.7, cover=0.0, visibility=1.0  (fast travel, exposed)
  building: movement_cost=inf, cover=0.5, visibility=0.0  (impassable, hidden)
  yard:     movement_cost=1.0, cover=0.1, visibility=0.8  (normal, some concealment)
  open:     movement_cost=1.0, cover=0.0, visibility=1.0  (default, fully exposed)
  water:    movement_cost=inf, cover=0.0, visibility=1.0  (impassable, exposed)

Integration:
  - Engine creates TerrainMap on init, loads from layout
  - Combat checks line_of_sight() before resolving hits
  - Behaviors use get_speed_modifier() for terrain-aware movement
  - Pathfinder can query movement costs for weighted A*
  - Frontend receives terrain via to_telemetry() for map rendering

Line-of-sight uses Bresenham's line algorithm to walk cells between two
positions.  If any cell is a building, LOS is blocked.  This is O(n) where
n = distance / resolution, which at 5m resolution and 400m map is at most
~113 steps -- well within the 10Hz tick budget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from engine.units import get_type as _get_unit_type

# Terrain type -> (movement_cost, cover_value, visibility)
_TERRAIN_PROPERTIES: dict[str, tuple[float, float, float]] = {
    "road":     (0.7,          0.0, 1.0),
    "building": (float("inf"), 0.5, 0.0),
    "yard":     (1.0,          0.1, 0.8),
    "open":     (1.0,          0.0, 1.0),
    "water":    (float("inf"), 0.0, 1.0),
}

# Building types in TritiumLevelFormat
_BUILDING_TYPES = {"building", "house", "shed", "garage"}

# Flying unit types that ignore terrain
_FLYING_TYPES = {"drone", "scout_drone", "heavy_drone", "recon_drone"}


@dataclass
class TerrainCell:
    """Properties of a terrain cell.

    Attributes:
        x: World X coordinate (center of cell).
        y: World Y coordinate (center of cell).
        terrain_type: One of "road", "building", "yard", "open", "water".
        movement_cost: Multiplier on movement speed.  road=0.7 (faster),
                       building=inf (impassable), yard/open=1.0 (normal).
        cover_value: Natural cover provided.  building=0.5, yard=0.1, else 0.0.
        visibility: How visible a unit is.  building=0.0, yard=0.8, else 1.0.
        elevation: Height advantage in meters.
    """

    x: float
    y: float
    terrain_type: str
    movement_cost: float = 1.0
    cover_value: float = 0.0
    visibility: float = 1.0
    elevation: float = 0.0


class TerrainMap:
    """Grid-based terrain map with spatial queries.

    Divides the map into a grid of cells (default 5m resolution).
    Each cell has terrain type, movement cost, cover, visibility.
    Unset cells default to "open" terrain.
    """

    def __init__(self, map_bounds: float, resolution: float = 5.0) -> None:
        self._bounds = abs(map_bounds)
        self._resolution = resolution
        self._grid_size = int(2 * self._bounds / resolution) + 1
        self._cells: dict[tuple[int, int], TerrainCell] = {}

    # -- Grid coordinate conversion -------------------------------------------

    def _world_to_grid(self, x: float, y: float) -> tuple[int, int]:
        """Convert world (x, y) to grid (col, row) indices."""
        col = int((x + self._bounds) / self._resolution)
        row = int((y + self._bounds) / self._resolution)
        return (col, row)

    def _grid_to_world(self, col: int, row: int) -> tuple[float, float]:
        """Convert grid (col, row) to world (x, y) center of cell."""
        x = col * self._resolution - self._bounds + self._resolution * 0.5
        y = row * self._resolution - self._bounds + self._resolution * 0.5
        return (x, y)

    # -- Cell operations -------------------------------------------------------

    def set_cell(self, x: float, y: float, terrain_type: str) -> None:
        """Set terrain type at world position.

        Looks up terrain properties from _TERRAIN_PROPERTIES.
        Unknown terrain types default to "open" properties.
        """
        col, row = self._world_to_grid(x, y)
        props = _TERRAIN_PROPERTIES.get(terrain_type, _TERRAIN_PROPERTIES["open"])
        movement_cost, cover_value, visibility = props
        world_x, world_y = self._grid_to_world(col, row)
        self._cells[(col, row)] = TerrainCell(
            x=world_x,
            y=world_y,
            terrain_type=terrain_type,
            movement_cost=movement_cost,
            cover_value=cover_value,
            visibility=visibility,
        )

    def get_cell(self, x: float, y: float) -> TerrainCell:
        """Get terrain cell at world position.  Default: open terrain."""
        col, row = self._world_to_grid(x, y)
        cell = self._cells.get((col, row))
        if cell is not None:
            return cell
        # Return default open cell at this grid position
        world_x, world_y = self._grid_to_world(col, row)
        return TerrainCell(
            x=world_x,
            y=world_y,
            terrain_type="open",
            movement_cost=1.0,
            cover_value=0.0,
            visibility=1.0,
        )

    def reset(self) -> None:
        """Clear all terrain cells."""
        self._cells.clear()

    def set_terrain(self, x: float, y: float, terrain_type: str) -> None:
        """Set terrain type at world position (alias for set_cell)."""
        self.set_cell(x, y, terrain_type)

    def get_speed_multiplier(self, x: float, y: float) -> float:
        """Return a simplified speed multiplier for terrain at (x, y).

        Returns:
            1.2 for "road", 0.6 for "rough", 0.0 for "building", 1.0 for default.
        """
        terrain = self.get_terrain_type(x, y)
        if terrain == "road":
            return 1.2
        elif terrain == "rough":
            return 0.6
        elif terrain == "building":
            return 0.0
        return 1.0

    def get_terrain_type(self, x: float, y: float) -> str:
        """Get terrain type string at position."""
        return self.get_cell(x, y).terrain_type

    def get_movement_cost(self, x: float, y: float) -> float:
        """Get movement cost multiplier at position."""
        return self.get_cell(x, y).movement_cost

    def get_cover_value(self, x: float, y: float) -> float:
        """Get natural cover value at position."""
        return self.get_cell(x, y).cover_value

    def get_visibility(self, x: float, y: float) -> float:
        """Get visibility (how easy to spot a unit here)."""
        return self.get_cell(x, y).visibility

    # -- Layout loading --------------------------------------------------------

    def load_from_layout(self, layout: dict) -> None:
        """Initialize terrain from TritiumLevelFormat layout.

        Reads buildings from layout objects.
        Buildings -> terrain_type="building", movement_cost=inf
        """
        objects = layout.get("objects", [])
        buildings: list[dict] = []

        for obj in objects:
            obj_type = obj.get("type", "").lower()
            if obj_type in _BUILDING_TYPES:
                props = obj.get("properties", {})
                raw_footprint = props.get("footprint", [])
                footprint = [(float(p[0]), float(p[1])) for p in raw_footprint]
                pos_data = obj.get("position", {})
                position = (float(pos_data.get("x", 0)), float(pos_data.get("z", 0)))
                buildings.append({
                    "footprint": footprint,
                    "position": position,
                })

        if buildings:
            self.load_buildings(buildings)

    def load_roads(self, road_segments: list) -> None:
        """Load road segments and mark cells as road terrain.

        Each segment is a dict with:
          start: (x, y) start point
          end: (x, y) end point
          width: road width in meters (cells within half-width are road)
        """
        for seg in road_segments:
            start = seg.get("start", (0.0, 0.0))
            end = seg.get("end", (0.0, 0.0))
            width = seg.get("width", 6.0)
            half_w = width / 2.0

            # Walk along the road segment and mark cells within half-width
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = math.hypot(dx, dy)
            if length < 0.1:
                continue

            # Normal vector (perpendicular to road direction)
            nx_dir = -dy / length
            ny_dir = dx / length

            # Step along the road at resolution intervals
            steps = max(1, int(length / self._resolution))
            for i in range(steps + 1):
                t = i / max(steps, 1)
                cx = start[0] + dx * t
                cy = start[1] + dy * t

                # Mark cells across the road width
                width_steps = max(1, int(width / self._resolution))
                for w in range(width_steps + 1):
                    wt = (w / max(width_steps, 1)) - 0.5  # -0.5 to 0.5
                    px = cx + nx_dir * wt * width
                    py = cy + ny_dir * wt * width
                    self.set_cell(px, py, "road")

    def load_buildings(self, buildings: list) -> None:
        """Load building polygons.

        Each building is a dict with:
          footprint: list of (x, y) vertices
          position: (x, y) center (for reference)

        All grid cells whose centers fall inside the polygon are marked
        as building terrain.
        """
        for building in buildings:
            footprint = building.get("footprint", [])
            if len(footprint) < 3:
                continue

            # Find bounding box of the polygon
            xs = [p[0] for p in footprint]
            ys = [p[1] for p in footprint]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)

            # Iterate over grid cells within the bounding box
            # Start from the grid cell containing min_x, min_y
            col_start, row_start = self._world_to_grid(min_x, min_y)
            col_end, row_end = self._world_to_grid(max_x, max_y)

            for col in range(col_start, col_end + 1):
                for row in range(row_start, row_end + 1):
                    wx, wy = self._grid_to_world(col, row)
                    if _point_in_polygon(wx, wy, footprint):
                        self.set_cell(wx, wy, "building")

    # -- Terrain queries -------------------------------------------------------

    def find_terrain_of_type(
        self,
        terrain_type: str,
        near: Optional[tuple[float, float]] = None,
        radius: float = 50.0,
    ) -> list[tuple[float, float]]:
        """Find positions with given terrain type, optionally near a point.

        Args:
            terrain_type: The terrain type to search for.
            near: Optional (x, y) position to search near.
            radius: Maximum distance from *near* (ignored if near is None).

        Returns:
            List of (x, y) world positions matching the terrain type.
        """
        results: list[tuple[float, float]] = []
        for (col, row), cell in self._cells.items():
            if cell.terrain_type != terrain_type:
                continue
            if near is not None:
                dist = math.hypot(cell.x - near[0], cell.y - near[1])
                if dist > radius:
                    continue
            results.append((cell.x, cell.y))
        return results

    def get_speed_modifier(self, x: float, y: float, asset_type: str) -> float:
        """Speed modifier considering unit type and terrain.

        Drones ignore terrain (return 1.0 always).
        Other units: modifier = 1.0 / movement_cost.
          road (0.7) -> 1.0/0.7 ~ 1.43 (faster on roads)
          open/yard (1.0) -> 1.0 (normal speed)
          building/water (inf) -> 0.0 (impassable, but drones bypass)

        For hostiles (person type) on yard terrain, a slight penalty is
        applied (0.9x speed) to simulate movement through vegetation.
        """
        # Flying units ignore terrain completely
        if asset_type in _FLYING_TYPES:
            return 1.0

        # Also check registry for flying types
        type_def = _get_unit_type(asset_type)
        if type_def is not None and type_def.is_flying():
            return 1.0

        cost = self.get_movement_cost(x, y)
        if cost == float("inf"):
            return 0.0
        if cost <= 0:
            return 1.0

        modifier = 1.0 / cost

        # Hostile person penalty in yards
        terrain = self.get_terrain_type(x, y)
        if asset_type == "person" and terrain == "yard":
            modifier *= 0.9

        return modifier

    # -- Line of sight ---------------------------------------------------------

    def line_of_sight(self, pos_a: tuple, pos_b: tuple) -> bool:
        """Check if there's clear line of sight between two positions.

        Blocked by building cells.  Uses Bresenham's line algorithm
        to check all cells between the two positions.

        Args:
            pos_a: (x, y) start position.
            pos_b: (x, y) end position.

        Returns:
            True if clear LOS, False if blocked by a building.
        """
        col_a, row_a = self._world_to_grid(pos_a[0], pos_a[1])
        col_b, row_b = self._world_to_grid(pos_b[0], pos_b[1])

        # Bresenham's line algorithm
        for col, row in _bresenham(col_a, row_a, col_b, row_b):
            cell = self._cells.get((col, row))
            if cell is not None and cell.terrain_type == "building":
                return False

        return True

    # -- Telemetry -------------------------------------------------------------

    def to_telemetry(self) -> dict:
        """Serialize terrain data for frontend rendering.

        Returns:
            Dict with bounds, resolution, and list of non-default cells.
        """
        cells: list[dict] = []
        for (col, row), cell in self._cells.items():
            cells.append({
                "x": cell.x,
                "y": cell.y,
                "terrain_type": cell.terrain_type,
                "movement_cost": cell.movement_cost if cell.movement_cost != float("inf") else -1,
                "cover_value": cell.cover_value,
                "visibility": cell.visibility,
            })

        return {
            "bounds": self._bounds,
            "resolution": self._resolution,
            "cells": cells,
        }


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------

def _point_in_polygon(px: float, py: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test.

    Casts a ray from (px, py) in the +X direction and counts
    how many polygon edges it crosses.  Odd = inside, even = outside.
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _bresenham(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Bresenham's line algorithm.  Returns list of (x, y) grid cells.

    Handles all octants (steep, shallow, negative directions).
    """
    cells: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    while True:
        cells.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy

    return cells
