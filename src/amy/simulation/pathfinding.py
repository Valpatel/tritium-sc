"""A* pathfinder — plan_path() routes units based on type and available data.

Routing rules by unit type:
    - Rover/Tank/APC: snap to nearest road node, A* on street graph, road waypoints
    - Drone/Scout drone: straight line (ignores roads and buildings)
    - Hostile person: A* on roads for approach, then direct for last 30m
    - Turret (all types): no path (stationary)
    - Unknown: direct fallback (start -> end)

If street_graph is None (Overpass unavailable), all ground units fall back to
direct waypoint paths.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from amy.tactical.obstacles import BuildingObstacles
    from amy.tactical.street_graph import StreetGraph

# Unit types that are stationary (no path needed)
_STATIONARY_TYPES = {"turret", "heavy_turret", "missile_turret"}

# Unit types that fly (ignore roads and buildings)
_FLYING_TYPES = {"drone", "scout_drone"}

# Unit types that follow roads
_ROAD_TYPES = {"rover", "tank", "apc"}

# Distance threshold for hostile direct approach (meters)
_HOSTILE_DIRECT_RANGE = 30.0


def plan_path(
    start: tuple[float, float],
    end: tuple[float, float],
    unit_type: str,
    street_graph: Optional[StreetGraph],
    obstacles: Optional[BuildingObstacles],
    alliance: str = "friendly",
) -> Optional[list[tuple[float, float]]]:
    """Plan a path from start to end based on unit type and available data.

    Args:
        start: (x, y) in local meters
        end: (x, y) in local meters
        unit_type: asset_type from SimulationTarget
        street_graph: loaded StreetGraph (or None if unavailable)
        obstacles: loaded BuildingObstacles (or None if unavailable)
        alliance: "friendly", "hostile", or "neutral"

    Returns:
        List of (x, y) waypoints, or None for stationary units.
    """
    # Stationary units don't move
    if unit_type in _STATIONARY_TYPES:
        return None

    # Flying units go in a straight line
    if unit_type in _FLYING_TYPES:
        return [start, end]

    # Hostile persons: road approach then direct last 30m
    if alliance == "hostile" and unit_type == "person":
        return _hostile_path(start, end, street_graph)

    # Road-following ground units
    if unit_type in _ROAD_TYPES:
        return _road_path(start, end, street_graph)

    # Unknown or other unit types: direct fallback
    return [start, end]


def _road_path(
    start: tuple[float, float],
    end: tuple[float, float],
    street_graph: Optional[StreetGraph],
) -> list[tuple[float, float]]:
    """Route along roads via street graph. Fallback to direct if unavailable."""
    if street_graph is None or street_graph.graph is None:
        return [start, end]

    path = street_graph.shortest_path(start, end)
    if path is None or len(path) == 0:
        return [start, end]

    return path


def _hostile_path(
    start: tuple[float, float],
    end: tuple[float, float],
    street_graph: Optional[StreetGraph],
) -> list[tuple[float, float]]:
    """Hostile approach: follow roads to get close, then cut through for last 30m.

    If the total distance is < 30m, just go direct.
    If no street graph, go direct.
    """
    total_dist = math.hypot(end[0] - start[0], end[1] - start[1])

    # Short distance — just go direct
    if total_dist <= _HOSTILE_DIRECT_RANGE:
        return [start, end]

    if street_graph is None or street_graph.graph is None:
        return [start, end]

    # Find a road waypoint about 30m from the objective
    # Use the vector from end to start, normalized, to find the "peel off" point
    dx = start[0] - end[0]
    dy = start[1] - end[1]
    dist = math.hypot(dx, dy)
    if dist < 1.0:
        return [start, end]

    # Point 30m from objective along the approach direction
    peel_off = (
        end[0] + (dx / dist) * _HOSTILE_DIRECT_RANGE,
        end[1] + (dy / dist) * _HOSTILE_DIRECT_RANGE,
    )

    # A* from start to peel_off on roads
    road_path = street_graph.shortest_path(start, peel_off)
    if road_path is None or len(road_path) == 0:
        return [start, end]

    # Append the objective as the final direct waypoint
    road_path.append(end)
    return road_path
