"""WorldModel — unified spatial queries for NPC decision-making.

Aggregates building obstacle data, street graph, and derived features
(doors, crosswalks, POIs) into a single queryable model that NPC brains
use for spatial awareness.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import networkx as nx
    from engine.tactical.obstacles import BuildingObstacles
    from engine.tactical.street_graph import StreetGraph


# ============================================================================
# Data structures
# ============================================================================


@dataclass
class DoorPoint:
    """An entry/exit point on a building."""
    position: tuple[float, float]
    facing: float              # heading the door faces outward (degrees, 0=north)
    building_idx: int
    accessible: bool = True


@dataclass
class BuildingInfo:
    """Enriched building data with doors and classification."""
    polygon: list[tuple[float, float]]
    center: tuple[float, float]
    building_type: str         # home, commercial, school, etc.
    doors: list[DoorPoint]
    area_m2: float
    idx: int = 0


@dataclass
class CrosswalkPoint:
    """A pedestrian crossing point at a road intersection."""
    position: tuple[float, float]
    road_node_a: int
    road_node_b: int
    width: float = 3.0


@dataclass
class POI:
    """A point of interest in the neighborhood."""
    position: tuple[float, float]
    poi_type: str              # home, work, shop, park, school
    name: str
    building_idx: int | None = None
    capacity: int = 10


# Road classes that are sidewalk/pedestrian
_SIDEWALK_CLASSES = {"footway", "pedestrian", "path", "cycleway"}

# Road classes for vehicle traffic
_ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary",
                 "unclassified", "residential", "service", "living_street"}

# Large building threshold for extra doors
_LARGE_BUILDING_M2 = 200.0


# ============================================================================
# WorldModel
# ============================================================================


class WorldModel:
    """Unified spatial model for NPC decision-making.

    Provides fast queries for buildings, doors, roads, crosswalks, and POIs.
    """

    def __init__(self) -> None:
        self._buildings: list[BuildingInfo] = []
        self._doors: list[DoorPoint] = []
        self._crosswalks: list[CrosswalkPoint] = []
        self._pois: list[POI] = []

        # Raw data references
        self._polygons: list[list[tuple[float, float]]] = []
        self._graph: Optional[object] = None  # nx.Graph
        self._node_positions: dict[int, tuple[float, float]] = {}
        self._edge_classes: dict[tuple[int, int], str] = {}

    # -- Factory methods --

    @classmethod
    def from_raw(
        cls,
        building_polygons: list[list[tuple[float, float]]],
        street_graph: Optional[object] = None,
        node_positions: Optional[dict[int, tuple[float, float]]] = None,
    ) -> WorldModel:
        """Create a WorldModel from raw polygon and graph data."""
        world = cls()
        world._polygons = building_polygons
        world._graph = street_graph
        world._node_positions = node_positions or {}

        # Extract edge classes
        if street_graph is not None:
            for n1, n2, data in street_graph.edges(data=True):
                rc = data.get("road_class", "residential")
                world._edge_classes[(n1, n2)] = rc
                world._edge_classes[(n2, n1)] = rc

        # Build enriched data
        world._build_buildings()
        world._generate_doors()
        world._generate_crosswalks()
        world._generate_pois()

        return world

    @classmethod
    def from_loaded(
        cls,
        buildings: BuildingObstacles,
        street_graph: StreetGraph,
    ) -> WorldModel:
        """Create from existing BuildingObstacles and StreetGraph objects."""
        polys = buildings.polygons if buildings else []
        graph = street_graph.graph if street_graph else None
        positions = street_graph._node_positions if street_graph else {}
        return cls.from_raw(polys, graph, positions)

    # -- Building queries --

    def is_inside_building(self, x: float, y: float) -> bool:
        """Check if point is inside any building."""
        for poly in self._polygons:
            if _point_in_polygon(x, y, poly):
                return True
        return False

    def nearest_building(self, x: float, y: float) -> BuildingInfo | None:
        """Find the nearest building by center distance."""
        if not self._buildings:
            return None
        best = None
        best_dist = float("inf")
        for b in self._buildings:
            d = math.hypot(x - b.center[0], y - b.center[1])
            if d < best_dist:
                best_dist = d
                best = b
        return best

    def buildings_in_radius(self, x: float, y: float, r: float) -> list[BuildingInfo]:
        """Find all buildings whose center is within radius r."""
        return [
            b for b in self._buildings
            if math.hypot(x - b.center[0], y - b.center[1]) <= r
        ]

    # -- Door queries --

    def nearest_door(self, x: float, y: float) -> DoorPoint | None:
        """Find the nearest door point."""
        if not self._doors:
            return None
        best = None
        best_dist = float("inf")
        for d in self._doors:
            dist = math.hypot(x - d.position[0], y - d.position[1])
            if dist < best_dist:
                best_dist = dist
                best = d
        return best

    # -- Road queries --

    def nearest_sidewalk_node(self, x: float, y: float) -> tuple[float, float] | None:
        """Find the nearest street graph node on a sidewalk/footway."""
        if not self._node_positions:
            return None
        best_pos = None
        best_dist = float("inf")
        for nid, pos in self._node_positions.items():
            # Check if this node has any sidewalk edges
            if self._node_has_class(nid, _SIDEWALK_CLASSES):
                d = math.hypot(x - pos[0], y - pos[1])
                if d < best_dist:
                    best_dist = d
                    best_pos = pos
        return best_pos

    def is_on_road(self, x: float, y: float, tolerance: float = 3.0) -> bool:
        """Check if point is near a road-class edge."""
        return self._near_edge_class(x, y, _ROAD_CLASSES, tolerance)

    def is_on_sidewalk(self, x: float, y: float, tolerance: float = 3.0) -> bool:
        """Check if point is near a sidewalk/footway edge."""
        return self._near_edge_class(x, y, _SIDEWALK_CLASSES, tolerance)

    def road_type_at(self, x: float, y: float, tolerance: float = 5.0) -> str | None:
        """Get the road type at a position, or None if not near a road."""
        if not self._node_positions or self._graph is None:
            return None
        for n1, n2, data in self._graph.edges(data=True):
            rc = data.get("road_class", "residential")
            p1 = self._node_positions.get(n1)
            p2 = self._node_positions.get(n2)
            if p1 is None or p2 is None:
                continue
            dist = _point_to_segment_dist(x, y, p1[0], p1[1], p2[0], p2[1])
            if dist <= tolerance:
                return rc
        return None

    # -- Crosswalk queries --

    def nearest_crosswalk(self, x: float, y: float) -> CrosswalkPoint | None:
        """Find the nearest crosswalk point."""
        if not self._crosswalks:
            return None
        best = None
        best_dist = float("inf")
        for cw in self._crosswalks:
            d = math.hypot(x - cw.position[0], y - cw.position[1])
            if d < best_dist:
                best_dist = d
                best = cw
        return best

    # -- POI queries --

    def nearest_poi(
        self, x: float, y: float, poi_type: str | None = None
    ) -> POI | None:
        """Find the nearest POI, optionally filtered by type."""
        best = None
        best_dist = float("inf")
        for p in self._pois:
            if poi_type is not None and p.poi_type != poi_type:
                continue
            d = math.hypot(x - p.position[0], y - p.position[1])
            if d < best_dist:
                best_dist = d
                best = p
        return best

    def pois_in_radius(
        self, x: float, y: float, r: float, poi_type: str | None = None
    ) -> list[POI]:
        """Find all POIs within radius, optionally filtered by type."""
        return [
            p for p in self._pois
            if (poi_type is None or p.poi_type == poi_type) and
            math.hypot(x - p.position[0], y - p.position[1]) <= r
        ]

    # -- Safety queries --

    def nearest_cover(
        self, x: float, y: float, threat_pos: tuple[float, float]
    ) -> tuple[float, float] | None:
        """Find nearest position that provides cover from threat.

        Looks for building corners/edges that block line of sight to threat.
        """
        if not self._buildings:
            return None

        # Find the nearest building that's between us and the threat
        # or that we can get behind
        best_pos = None
        best_dist = float("inf")

        for b in self._buildings:
            # Check each vertex of the building polygon
            for vx, vy in b.polygon:
                # Is this vertex accessible (not inside another building)?
                if self.is_inside_building(vx, vy):
                    continue

                # Is this vertex "behind" the building relative to threat?
                # Simple check: vertex should be farther from threat than building center
                d_vertex_threat = math.hypot(vx - threat_pos[0], vy - threat_pos[1])
                d_center_threat = math.hypot(b.center[0] - threat_pos[0],
                                             b.center[1] - threat_pos[1])
                if d_vertex_threat < d_center_threat:
                    continue  # This vertex faces the threat, not good cover

                d_to_us = math.hypot(vx - x, vy - y)
                if d_to_us < best_dist:
                    best_dist = d_to_us
                    # Offset slightly away from building edge
                    dx_off = vx - b.center[0]
                    dy_off = vy - b.center[1]
                    off_len = math.hypot(dx_off, dy_off)
                    if off_len > 0.1:
                        best_pos = (
                            vx + dx_off / off_len * 2.0,
                            vy + dy_off / off_len * 2.0,
                        )
                    else:
                        best_pos = (vx, vy)

        return best_pos

    def safe_direction(
        self, x: float, y: float, threat_pos: tuple[float, float]
    ) -> tuple[float, float]:
        """Get a normalized direction vector pointing away from threat.

        Avoids directing into buildings.
        """
        # Base direction: directly away from threat
        dx = x - threat_pos[0]
        dy = y - threat_pos[1]
        dist = math.hypot(dx, dy)
        if dist < 0.01:
            # On top of threat — pick arbitrary direction
            return (1.0, 0.0)

        dx /= dist
        dy /= dist

        # Check if this direction leads into a building
        test_x = x + dx * 10.0
        test_y = y + dy * 10.0
        if not self.is_inside_building(test_x, test_y):
            return (dx, dy)

        # Try rotating in 30-degree increments to find a clear direction
        for angle_deg in [30, -30, 60, -60, 90, -90, 120, -120, 150, -150, 180]:
            rad = math.radians(angle_deg)
            rx = dx * math.cos(rad) - dy * math.sin(rad)
            ry = dx * math.sin(rad) + dy * math.cos(rad)
            test_x = x + rx * 10.0
            test_y = y + ry * 10.0
            if not self.is_inside_building(test_x, test_y):
                return (rx, ry)

        # Fallback: just go away from threat
        return (dx, dy)

    # -- Internal: building enrichment --

    def _build_buildings(self) -> None:
        """Create BuildingInfo objects from raw polygons."""
        self._buildings = []
        for idx, poly in enumerate(self._polygons):
            if len(poly) < 3:
                continue
            cx = sum(p[0] for p in poly) / len(poly)
            cy = sum(p[1] for p in poly) / len(poly)
            area = _polygon_area(poly)
            btype = self._classify_building(cx, cy, area)
            self._buildings.append(BuildingInfo(
                polygon=poly,
                center=(cx, cy),
                building_type=btype,
                doors=[],
                area_m2=area,
                idx=idx,
            ))

    def _classify_building(self, cx: float, cy: float, area: float) -> str:
        """Classify a building by size and location."""
        if area < 100:
            return "home"
        elif area < 300:
            # Check if near a major road
            if self._near_road_class(cx, cy, {"secondary", "tertiary"}, 30.0):
                return "commercial"
            return "home"
        else:
            if self._near_road_class(cx, cy, {"secondary", "tertiary"}, 50.0):
                return "commercial"
            return "home"

    def _near_road_class(
        self, x: float, y: float, classes: set, radius: float
    ) -> bool:
        """Check if point is near an edge of given road classes."""
        if not self._node_positions or self._graph is None:
            return False
        for n1, n2, data in self._graph.edges(data=True):
            rc = data.get("road_class", "")
            if rc not in classes:
                continue
            p1 = self._node_positions.get(n1)
            p2 = self._node_positions.get(n2)
            if p1 is None or p2 is None:
                continue
            d = _point_to_segment_dist(x, y, p1[0], p1[1], p2[0], p2[1])
            if d <= radius:
                return True
        return False

    # -- Internal: door generation --

    def _generate_doors(self) -> None:
        """Generate door points for all buildings."""
        self._doors = []
        for b in self._buildings:
            doors = self._doors_for_building(b)
            b.doors = doors
            self._doors.extend(doors)

    def _doors_for_building(self, building: BuildingInfo) -> list[DoorPoint]:
        """Generate door(s) for a single building.

        Places doors on edges closest to roads/footways.
        Large buildings get multiple doors.
        """
        poly = building.polygon
        n = len(poly)
        if n < 3:
            return []

        # Score each edge by proximity to nearest road/footway node
        edge_scores: list[tuple[int, float]] = []
        for i in range(n):
            ax, ay = poly[i]
            bx, by = poly[(i + 1) % n]
            mx, my = (ax + bx) / 2, (ay + by) / 2
            # Distance to nearest road/footway node
            min_dist = self._dist_to_nearest_node(mx, my)
            edge_scores.append((i, min_dist))

        # Sort by distance (closest road first)
        edge_scores.sort(key=lambda x: x[1])

        # How many doors?
        num_doors = 1
        if building.area_m2 >= _LARGE_BUILDING_M2:
            num_doors = min(4, max(2, n // 2))

        doors = []
        used_edges: set[int] = set()
        for edge_idx, _ in edge_scores:
            if len(doors) >= num_doors:
                break
            if edge_idx in used_edges:
                continue

            ax, ay = poly[edge_idx]
            bx, by = poly[(edge_idx + 1) % n]

            # Door at midpoint of edge
            dx, dy = (ax + bx) / 2, (ay + by) / 2

            # Facing: outward perpendicular to edge
            edge_dx = bx - ax
            edge_dy = by - ay
            # Outward normal (perpendicular, pointing away from center)
            nx_out = -edge_dy
            ny_out = edge_dx
            # Check if this normal points away from center
            to_center_x = building.center[0] - dx
            to_center_y = building.center[1] - dy
            if nx_out * to_center_x + ny_out * to_center_y > 0:
                nx_out, ny_out = -nx_out, -ny_out

            facing = math.degrees(math.atan2(nx_out, ny_out)) % 360

            doors.append(DoorPoint(
                position=(dx, dy),
                facing=facing,
                building_idx=building.idx,
            ))
            used_edges.add(edge_idx)
            # Skip adjacent edges for multi-door buildings
            used_edges.add((edge_idx - 1) % n)
            used_edges.add((edge_idx + 1) % n)

        # Guarantee at least one door even without road data
        if not doors and n >= 3:
            ax, ay = poly[0]
            bx, by = poly[1]
            dx, dy = (ax + bx) / 2, (ay + by) / 2
            doors.append(DoorPoint(
                position=(dx, dy),
                facing=0.0,
                building_idx=building.idx,
            ))

        return doors

    def _dist_to_nearest_node(self, x: float, y: float) -> float:
        """Distance to nearest street graph node."""
        if not self._node_positions:
            return float("inf")
        return min(
            math.hypot(x - px, y - py)
            for px, py in self._node_positions.values()
        )

    # -- Internal: crosswalk generation --

    def _generate_crosswalks(self) -> None:
        """Generate crosswalk points at road/footway intersections."""
        self._crosswalks = []
        if self._graph is None or not self._node_positions:
            return

        # Find nodes where footway meets road
        for nid, pos in self._node_positions.items():
            has_road = False
            has_footway = False
            road_neighbor = None
            footway_neighbor = None

            for neighbor in self._graph.neighbors(nid):
                edge_data = self._graph.get_edge_data(nid, neighbor)
                if edge_data is None:
                    continue
                rc = edge_data.get("road_class", "")
                if rc in _ROAD_CLASSES:
                    has_road = True
                    road_neighbor = neighbor
                if rc in _SIDEWALK_CLASSES:
                    has_footway = True
                    footway_neighbor = neighbor

            if has_road and has_footway and road_neighbor is not None:
                self._crosswalks.append(CrosswalkPoint(
                    position=pos,
                    road_node_a=nid,
                    road_node_b=road_neighbor,
                ))

        # Also find high-degree road intersections (>= 3 road edges)
        for nid, pos in self._node_positions.items():
            road_count = 0
            road_neighbors = []
            for neighbor in self._graph.neighbors(nid):
                edge_data = self._graph.get_edge_data(nid, neighbor)
                if edge_data is None:
                    continue
                rc = edge_data.get("road_class", "")
                if rc in _ROAD_CLASSES:
                    road_count += 1
                    road_neighbors.append(neighbor)

            if road_count >= 3:
                # Check if we already have a crosswalk here
                already = any(
                    math.hypot(cw.position[0] - pos[0], cw.position[1] - pos[1]) < 5.0
                    for cw in self._crosswalks
                )
                if not already and len(road_neighbors) >= 2:
                    self._crosswalks.append(CrosswalkPoint(
                        position=pos,
                        road_node_a=road_neighbors[0],
                        road_node_b=road_neighbors[1],
                    ))

    # -- Internal: POI generation --

    def _generate_pois(self) -> None:
        """Generate POIs from buildings."""
        self._pois = []
        for b in self._buildings:
            # Use first door as POI position, or building center
            pos = b.doors[0].position if b.doors else b.center
            capacity = max(2, int(b.area_m2 / 20))  # rough: 20m2 per person
            self._pois.append(POI(
                position=pos,
                poi_type=b.building_type,
                name=f"{b.building_type.title()} {b.idx + 1}",
                building_idx=b.idx,
                capacity=capacity,
            ))

    # -- Internal: helpers --

    def _node_has_class(self, nid: int, classes: set) -> bool:
        """Check if a node has any edge of given road classes."""
        if self._graph is None:
            return False
        for neighbor in self._graph.neighbors(nid):
            edge_data = self._graph.get_edge_data(nid, neighbor)
            if edge_data is None:
                continue
            rc = edge_data.get("road_class", "")
            if rc in classes:
                return True
        return False

    def _near_edge_class(
        self, x: float, y: float, classes: set, tolerance: float
    ) -> bool:
        """Check if point is near an edge of given road classes."""
        if self._graph is None or not self._node_positions:
            return False
        for n1, n2, data in self._graph.edges(data=True):
            rc = data.get("road_class", "")
            if rc not in classes:
                continue
            p1 = self._node_positions.get(n1)
            p2 = self._node_positions.get(n2)
            if p1 is None or p2 is None:
                continue
            d = _point_to_segment_dist(x, y, p1[0], p1[1], p2[0], p2[1])
            if d <= tolerance:
                return True
        return False


# ============================================================================
# Geometry utilities
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


def _polygon_area(polygon: list[tuple[float, float]]) -> float:
    """Shoelace formula for polygon area."""
    n = len(polygon)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += polygon[i][0] * polygon[j][1]
        area -= polygon[j][0] * polygon[i][1]
    return abs(area) / 2.0


def _point_to_segment_dist(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> float:
    """Distance from point (px,py) to line segment (ax,ay)-(bx,by)."""
    seg_len_sq = (bx - ax) ** 2 + (by - ay) ** 2
    if seg_len_sq < 0.0001:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / seg_len_sq))
    proj_x = ax + t * (bx - ax)
    proj_y = ay + t * (by - ay)
    return math.hypot(px - proj_x, py - proj_y)
