"""NPCRouter — NPC-type-aware pathfinding that respects spatial rules.

Pedestrians walk on sidewalks, cross roads at crosswalks, and avoid buildings.
Vehicles follow road-class edges only.  Flee routing provides emergency
escape paths that still respect building boundaries.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from engine.simulation.npc_intelligence.world_model import (
        BuildingInfo,
        WorldModel,
    )


# Road classes that pedestrians may use
_PEDESTRIAN_CLASSES = {"footway", "pedestrian", "path", "cycleway"}

# Road classes vehicles may use
_VEHICLE_CLASSES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service", "living_street",
}

# Speed limits by road class (m/s)
_SPEED_LIMITS: dict[str, float] = {
    "motorway": 31.0,    # ~70 mph
    "trunk": 27.0,       # ~60 mph
    "primary": 22.0,     # ~50 mph
    "secondary": 16.0,   # ~35 mph
    "tertiary": 16.0,    # ~35 mph
    "residential": 11.0, # ~25 mph
    "service": 7.0,      # ~15 mph
    "living_street": 4.5, # ~10 mph
    "unclassified": 11.0,
}

_DEFAULT_SPEED = 11.0  # m/s

# Number of interpolation samples for building-crossing checks
_COLLISION_SAMPLES = 5

# Flee distance (how far to run)
_FLEE_DISTANCE = 50.0


class NPCRouter:
    """NPC-aware pathfinding that respects spatial rules."""

    def __init__(self, world: WorldModel) -> None:
        self._world = world
        # Build sub-graphs lazily
        self._pedestrian_graph: Optional[object] = None
        self._vehicle_graph: Optional[object] = None

    # -- Public API --

    def route_pedestrian(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        urgent: bool = False,
    ) -> list[tuple[float, float]]:
        """Route a pedestrian using sidewalks and crosswalks.

        Normal mode: walk on footway/pedestrian paths, cross at crosswalks,
        avoid walking through buildings.

        Urgent mode (fleeing): can cross roads anywhere, can cut through
        yards, but still not through buildings.
        """
        graph = self._world._graph
        if graph is None or not self._world._node_positions:
            return [start, end]

        if urgent:
            # Urgent: use full graph (any edge) but validate no building crossing
            path = self._a_star_on_graph(start, end, allowed_classes=None)
            if path is None or len(path) < 2:
                # No graph path — go direct (emergency)
                path = [start, end]
            return self._ensure_no_building_crossing(path)

        # Normal: prefer pedestrian paths
        path = self._a_star_on_graph(
            start, end,
            allowed_classes=_PEDESTRIAN_CLASSES,
        )

        # If no pedestrian-only path found, try all edges with penalty on roads
        if path is None or len(path) < 2:
            path = self._a_star_on_graph(start, end, allowed_classes=None)

        if path is None or len(path) < 2:
            path = [start, end]

        return self._ensure_no_building_crossing(path)

    def route_vehicle(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        vehicle_type: str = "sedan",
    ) -> list[tuple[float, float]]:
        """Route a vehicle on road-class edges only.

        Never uses footway/pedestrian/cycleway edges.
        """
        graph = self._world._graph
        if graph is None or not self._world._node_positions:
            return [start, end]

        path = self._a_star_on_graph(
            start, end,
            allowed_classes=_VEHICLE_CLASSES,
        )

        if path is None or len(path) < 2:
            # Fallback: direct, but snap to road nodes
            road_start = self._nearest_node_of_class(start, _VEHICLE_CLASSES)
            road_end = self._nearest_node_of_class(end, _VEHICLE_CLASSES)
            s = road_start if road_start else start
            e = road_end if road_end else end
            return [s, e]

        return path

    def route_to_building(
        self,
        start: tuple[float, float],
        building: BuildingInfo,
    ) -> list[tuple[float, float]]:
        """Route to the nearest door of a building."""
        if not building.doors:
            return [start, building.center]

        # Find the nearest door
        best_door = min(
            building.doors,
            key=lambda d: math.hypot(
                start[0] - d.position[0], start[1] - d.position[1]
            ),
        )

        path = self.route_pedestrian(start, best_door.position)

        # Make sure path ends at the door
        if path and math.hypot(
            path[-1][0] - best_door.position[0],
            path[-1][1] - best_door.position[1],
        ) > 3.0:
            path.append(best_door.position)

        return path

    def route_from_building(
        self,
        building: BuildingInfo,
        end: tuple[float, float],
    ) -> list[tuple[float, float]]:
        """Route from inside a building (start at door) to destination."""
        if not building.doors:
            return [building.center, end]

        # Find the nearest door to the destination
        best_door = min(
            building.doors,
            key=lambda d: math.hypot(
                end[0] - d.position[0], end[1] - d.position[1]
            ),
        )

        path = self.route_pedestrian(best_door.position, end)

        # Ensure path starts at the door
        if path and math.hypot(
            path[0][0] - best_door.position[0],
            path[0][1] - best_door.position[1],
        ) > 3.0:
            path.insert(0, best_door.position)

        return path

    def route_flee(
        self,
        position: tuple[float, float],
        threat_pos: tuple[float, float],
        npc_type: str,
    ) -> list[tuple[float, float]]:
        """Emergency flee route away from threat.

        Pedestrians: run to nearest building door, or away on sidewalks.
        Vehicles: speed away on roads (opposite direction from threat).
        Animals: bolt in a random safe direction (not through buildings).
        """
        if npc_type == "vehicle":
            return self._flee_vehicle(position, threat_pos)
        elif npc_type == "animal":
            return self._flee_animal(position, threat_pos)
        else:
            return self._flee_pedestrian(position, threat_pos)

    def speed_limit_for_road(self, road_class: str) -> float:
        """Get speed limit in m/s for a road class."""
        return _SPEED_LIMITS.get(road_class, _DEFAULT_SPEED)

    def validate_path(self, path: list[tuple[float, float]]) -> bool:
        """Check that no segment of path crosses through a building."""
        if not path or len(path) < 2:
            return True
        for i in range(len(path) - 1):
            if self._segment_crosses_building(
                path[i][0], path[i][1],
                path[i + 1][0], path[i + 1][1],
            ):
                return False
        return True

    # -- Internal: A* --

    def _a_star_on_graph(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        allowed_classes: set[str] | None,
    ) -> list[tuple[float, float]] | None:
        """Run A* on the street graph, optionally filtering by edge class.

        Returns a list of (x, y) waypoints, or None if no path found.
        """
        graph = self._world._graph
        if graph is None:
            return None

        import networkx as nx

        positions = self._world._node_positions

        # Snap start/end to nearest allowed node
        start_node = self._nearest_node_of_class(start, allowed_classes)
        end_node = self._nearest_node_of_class(end, allowed_classes)

        if start_node is None or end_node is None:
            return None

        # Find node IDs for snapped positions
        start_nid = self._pos_to_nid(start_node)
        end_nid = self._pos_to_nid(end_node)

        if start_nid is None or end_nid is None:
            return None

        # Build subgraph if class filtering
        if allowed_classes is not None:
            subgraph = nx.Graph()
            for n1, n2, data in graph.edges(data=True):
                rc = data.get("road_class", "")
                if rc in allowed_classes:
                    subgraph.add_edge(n1, n2, **data)
            # Add nodes with position data
            for nid in subgraph.nodes():
                if nid in positions:
                    subgraph.nodes[nid]["x"] = positions[nid][0]
                    subgraph.nodes[nid]["y"] = positions[nid][1]
            work_graph = subgraph
        else:
            work_graph = graph

        if start_nid not in work_graph or end_nid not in work_graph:
            return None

        try:
            node_path = nx.shortest_path(
                work_graph, start_nid, end_nid, weight="weight"
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

        # Convert node IDs to positions
        waypoints = [start]
        for nid in node_path:
            pos = positions.get(nid)
            if pos:
                waypoints.append(pos)
        waypoints.append(end)

        return waypoints

    def _nearest_node_of_class(
        self,
        pos: tuple[float, float],
        allowed_classes: set[str] | None,
    ) -> tuple[float, float] | None:
        """Find the nearest graph node that has an edge of allowed class."""
        positions = self._world._node_positions
        graph = self._world._graph

        if not positions or graph is None:
            return None

        best_pos = None
        best_dist = float("inf")

        for nid, npos in positions.items():
            if allowed_classes is not None:
                # Check if this node has any edge of the allowed class
                has_allowed = False
                for neighbor in graph.neighbors(nid):
                    edge_data = graph.get_edge_data(nid, neighbor)
                    if edge_data and edge_data.get("road_class", "") in allowed_classes:
                        has_allowed = True
                        break
                if not has_allowed:
                    continue

            d = math.hypot(pos[0] - npos[0], pos[1] - npos[1])
            if d < best_dist:
                best_dist = d
                best_pos = npos

        return best_pos

    def _pos_to_nid(self, pos: tuple[float, float]) -> int | None:
        """Find the node ID for a position (exact match or closest)."""
        positions = self._world._node_positions
        best_nid = None
        best_dist = float("inf")
        for nid, npos in positions.items():
            d = math.hypot(pos[0] - npos[0], pos[1] - npos[1])
            if d < best_dist:
                best_dist = d
                best_nid = nid
        return best_nid

    # -- Internal: building avoidance --

    def _ensure_no_building_crossing(
        self, path: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        """If any segment crosses a building, try to reroute around it."""
        if not path or len(path) < 2:
            return path

        result = [path[0]]
        for i in range(len(path) - 1):
            if self._segment_crosses_building(
                path[i][0], path[i][1],
                path[i + 1][0], path[i + 1][1],
            ):
                # Insert detour waypoints around the building
                detour = self._detour_around_building(
                    path[i], path[i + 1]
                )
                result.extend(detour)
            else:
                result.append(path[i + 1])

        return result

    def _segment_crosses_building(
        self, x1: float, y1: float, x2: float, y2: float,
    ) -> bool:
        """Check if a line segment passes through any building."""
        for poly in self._world._polygons:
            for t_num in range(_COLLISION_SAMPLES):
                t = (t_num + 1) / (_COLLISION_SAMPLES + 1)
                px = x1 + t * (x2 - x1)
                py = y1 + t * (y2 - y1)
                if _point_in_polygon(px, py, poly):
                    return True
        return False

    def _detour_around_building(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> list[tuple[float, float]]:
        """Generate detour waypoints that go around a blocking building."""
        # Find which building is blocking
        mx = (start[0] + end[0]) / 2
        my = (start[1] + end[1]) / 2
        blocking = self._world.nearest_building(mx, my)
        if blocking is None:
            return [end]

        # Try going around each side of the building
        cx, cy = blocking.center
        poly = blocking.polygon

        # Find the two vertices farthest from the line start->end
        # that would form a clear path
        best_detour = None
        best_len = float("inf")

        for vx, vy in poly:
            # Offset slightly away from building
            dx_off = vx - cx
            dy_off = vy - cy
            off_len = math.hypot(dx_off, dy_off)
            if off_len < 0.1:
                continue
            # Push 3m away from building edge
            wp = (
                vx + dx_off / off_len * 3.0,
                vy + dy_off / off_len * 3.0,
            )

            # Check if this detour waypoint creates a clear path
            seg1_clear = not self._segment_crosses_building(
                start[0], start[1], wp[0], wp[1]
            )
            seg2_clear = not self._segment_crosses_building(
                wp[0], wp[1], end[0], end[1]
            )

            if seg1_clear and seg2_clear:
                detour_len = (
                    math.hypot(wp[0] - start[0], wp[1] - start[1]) +
                    math.hypot(end[0] - wp[0], end[1] - wp[1])
                )
                if detour_len < best_len:
                    best_len = detour_len
                    best_detour = [wp, end]

        if best_detour:
            return best_detour

        # Multi-vertex detour: try pairs of adjacent vertices
        n = len(poly)
        for i in range(n):
            v1x, v1y = poly[i]
            v2x, v2y = poly[(i + 1) % n]
            dx1 = v1x - cx
            dy1 = v1y - cy
            len1 = math.hypot(dx1, dy1)
            dx2 = v2x - cx
            dy2 = v2y - cy
            len2 = math.hypot(dx2, dy2)
            if len1 < 0.1 or len2 < 0.1:
                continue

            wp1 = (v1x + dx1 / len1 * 3.0, v1y + dy1 / len1 * 3.0)
            wp2 = (v2x + dx2 / len2 * 3.0, v2y + dy2 / len2 * 3.0)

            s1 = not self._segment_crosses_building(start[0], start[1], wp1[0], wp1[1])
            s2 = not self._segment_crosses_building(wp1[0], wp1[1], wp2[0], wp2[1])
            s3 = not self._segment_crosses_building(wp2[0], wp2[1], end[0], end[1])

            if s1 and s2 and s3:
                return [wp1, wp2, end]

        # Last resort: return the end (may still cross, but we tried)
        return [end]

    # -- Internal: flee routing --

    def _flee_pedestrian(
        self,
        position: tuple[float, float],
        threat_pos: tuple[float, float],
    ) -> list[tuple[float, float]]:
        """Pedestrian flee: run to nearest building door or away on paths."""
        # First try: nearest building door
        door = self._world.nearest_door(position[0], position[1])
        if door is not None:
            dist_to_door = math.hypot(
                position[0] - door.position[0],
                position[1] - door.position[1],
            )
            if dist_to_door < _FLEE_DISTANCE:
                path = self.route_pedestrian(position, door.position, urgent=True)
                if path and len(path) >= 2:
                    return path

        # Fallback: run away from threat on any path
        safe_dir = self._world.safe_direction(
            position[0], position[1], threat_pos
        )
        flee_target = (
            position[0] + safe_dir[0] * _FLEE_DISTANCE,
            position[1] + safe_dir[1] * _FLEE_DISTANCE,
        )
        path = self.route_pedestrian(position, flee_target, urgent=True)
        return path if path else [position, flee_target]

    def _flee_vehicle(
        self,
        position: tuple[float, float],
        threat_pos: tuple[float, float],
    ) -> list[tuple[float, float]]:
        """Vehicle flee: speed away on roads."""
        # Direction away from threat
        dx = position[0] - threat_pos[0]
        dy = position[1] - threat_pos[1]
        dist = math.hypot(dx, dy)
        if dist < 0.01:
            dx, dy = 1.0, 0.0
            dist = 1.0

        # Target point far away on roads
        flee_target = (
            position[0] + (dx / dist) * _FLEE_DISTANCE,
            position[1] + (dy / dist) * _FLEE_DISTANCE,
        )

        path = self.route_vehicle(position, flee_target)
        return path if path else [position, flee_target]

    def _flee_animal(
        self,
        position: tuple[float, float],
        threat_pos: tuple[float, float],
    ) -> list[tuple[float, float]]:
        """Animal flee: bolt in safe direction, avoid buildings."""
        safe_dir = self._world.safe_direction(
            position[0], position[1], threat_pos
        )
        flee_target = (
            position[0] + safe_dir[0] * _FLEE_DISTANCE,
            position[1] + safe_dir[1] * _FLEE_DISTANCE,
        )

        path = [position, flee_target]
        return self._ensure_no_building_crossing(path)


# ============================================================================
# Geometry utility (local copy for independence)
# ============================================================================


def _point_in_polygon(
    px: float, py: float, polygon: list[tuple[float, float]]
) -> bool:
    """Ray-casting point-in-polygon test."""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside
