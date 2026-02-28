# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Street graph extraction from OpenStreetMap Overpass API.

Builds a NetworkX graph from road segments: intersections as nodes,
road segments as weighted edges (weight = distance in meters).

The graph is used by the pathfinder to route units along real streets
instead of cutting through buildings.

Coordinate convention:
    +X = East, +Y = North, origin = geo-reference point.
    Same as src/amy/tactical/geo.py.
"""

from __future__ import annotations

import hashlib
import math
import pickle
import time
from pathlib import Path
from typing import Optional

import httpx
import networkx as nx
from loguru import logger

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_USER_AGENT = "TRITIUM-SC/0.1.0"
_CACHE_EXPIRY_S = 24 * 3600  # 24 hours
_DEFAULT_CACHE_DIR = "~/.cache/tritium-sc"

# Meters per degree latitude (constant)
_METERS_PER_DEG_LAT = 111_320.0


def _latlng_to_local(
    lat: float, lng: float, ref_lat: float, ref_lng: float
) -> tuple[float, float]:
    """Convert lat/lng to local (x, y) meters relative to reference point.

    Uses the same math as amy.tactical.geo but without depending on the
    module-level singleton, so the graph builder is self-contained.
    """
    y = (lat - ref_lat) * _METERS_PER_DEG_LAT
    meters_per_deg_lng = _METERS_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    x = (lng - ref_lng) * meters_per_deg_lng
    return (x, y)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Euclidean distance between two 2D points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _node_key(x: float, y: float) -> tuple[float, float]:
    """Round coordinates to 0.1m precision to merge nearby points."""
    return (round(x, 1), round(y, 1))


def _fetch_roads(
    lat: float, lng: float, radius_m: float
) -> list[dict]:
    """Fetch road segments from Overpass API (synchronous).

    Returns a list of OSM way elements with geometry.
    """
    query = (
        f'[out:json];'
        f'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|'
        f'unclassified|residential|service|living_street|pedestrian|'
        f'footway|cycleway|path)$"]'
        f'(around:{radius_m},{lat},{lng});'
        f'out geom;'
    )
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            _OVERPASS_URL,
            data={"data": query},
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()

    data = resp.json()
    return data.get("elements", [])


class StreetGraph:
    """A street network graph built from OpenStreetMap road data.

    Nodes are road points (intersections and endpoints) in local (x, y) meters.
    Edges are road segments weighted by distance in meters.

    Usage:
        sg = StreetGraph()
        sg.load(lat, lng, radius_m=300)
        path = sg.shortest_path((start_x, start_y), (end_x, end_y))
    """

    def __init__(self) -> None:
        self.graph: Optional[nx.Graph] = None
        self._node_positions: dict[int, tuple[float, float]] = {}
        # Spatial index: sorted list of (x, y, node_id) for nearest-node queries
        self._spatial_index: list[tuple[float, float, int]] = []

    def load(
        self,
        lat: float,
        lng: float,
        radius_m: float = 300,
        cache_dir: str = _DEFAULT_CACHE_DIR,
    ) -> None:
        """Load street graph for the area around (lat, lng).

        Attempts cache first; falls back to Overpass API.
        If Overpass is unreachable or returns no data, self.graph stays None.
        """
        cache_path = self._cache_path(lat, lng, radius_m, cache_dir)

        # Try loading from cache
        if cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < _CACHE_EXPIRY_S:
                try:
                    with open(cache_path, "rb") as f:
                        cached = pickle.load(f)
                    self.graph = cached["graph"]
                    self._node_positions = cached["positions"]
                    self._build_spatial_index()
                    logger.info(
                        f"Street graph loaded from cache: {len(self.graph.nodes)} nodes, "
                        f"{len(self.graph.edges)} edges"
                    )
                    return
                except Exception as e:
                    logger.warning(f"Cache load failed: {e}")

        # Fetch from Overpass API
        try:
            elements = _fetch_roads(lat, lng, radius_m)
        except Exception as e:
            logger.warning(f"Overpass road fetch failed: {e}")
            return

        if not elements:
            logger.info("No road data from Overpass — street graph not available")
            return

        # Build the graph
        self._build_graph(elements, lat, lng)

        if self.graph is None or len(self.graph.nodes) == 0:
            self.graph = None
            return

        # Save to cache
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "wb") as f:
                pickle.dump(
                    {"graph": self.graph, "positions": self._node_positions},
                    f,
                )
            logger.info(f"Street graph cached: {cache_path}")
        except Exception as e:
            logger.warning(f"Cache save failed: {e}")

    def nearest_node(
        self, x: float, y: float
    ) -> tuple[Optional[int], float]:
        """Find the nearest graph node to local point (x, y).

        Returns (node_id, distance_meters).
        If graph is not loaded, returns (None, inf).
        """
        if self.graph is None or not self._node_positions:
            return (None, float("inf"))

        best_id: Optional[int] = None
        best_dist = float("inf")
        for nid, pos in self._node_positions.items():
            d = _distance((x, y), pos)
            if d < best_dist:
                best_dist = d
                best_id = nid
        return (best_id, best_dist)

    def shortest_path(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> Optional[list[tuple[float, float]]]:
        """Find shortest path between two local (x, y) points.

        Snaps start and end to nearest graph nodes, then runs A* (or
        Dijkstra if A* heuristic is not needed). Returns a list of
        (x, y) waypoints, or None if no path exists.
        """
        if self.graph is None:
            return None

        start_node, start_dist = self.nearest_node(start[0], start[1])
        end_node, end_dist = self.nearest_node(end[0], end[1])

        if start_node is None or end_node is None:
            return None

        if start_node == end_node:
            pos = self._node_positions[start_node]
            return [pos]

        try:
            node_path = nx.astar_path(
                self.graph,
                start_node,
                end_node,
                heuristic=self._heuristic,
                weight="weight",
            )
        except nx.NetworkXNoPath:
            return None

        # Convert node IDs to (x, y) waypoints
        waypoints = [self._node_positions[nid] for nid in node_path]
        return waypoints

    def to_polylines(self) -> list[dict]:
        """Export road segments as polylines for frontend rendering.

        Walks NetworkX edges and returns a list of dicts:
            [{"points": [(x, y), ...], "class": "residential"}, ...]

        Each edge becomes a two-point line segment. Adjacent edges on the
        same road are not merged (that would require OSM way tracking).
        """
        if self.graph is None:
            return []

        polylines: list[dict] = []
        for n1, n2, data in self.graph.edges(data=True):
            p1 = self._node_positions.get(n1)
            p2 = self._node_positions.get(n2)
            if p1 is None or p2 is None:
                continue
            road_class = data.get("road_class", "residential")
            polylines.append({
                "points": [list(p1), list(p2)],
                "class": road_class,
            })
        return polylines

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_graph(
        self, elements: list[dict], ref_lat: float, ref_lng: float
    ) -> None:
        """Build NetworkX graph from Overpass way elements."""
        G = nx.Graph()
        positions: dict[int, tuple[float, float]] = {}
        # Map (rounded_x, rounded_y) -> node_id for intersection detection
        coord_to_node: dict[tuple[float, float], int] = {}
        next_id = 0

        for el in elements:
            if el.get("type") != "way":
                continue
            geometry = el.get("geometry", [])
            if len(geometry) < 2:
                continue

            # Convert geometry points to local coords and create/reuse nodes
            segment_nodes: list[int] = []
            for pt in geometry:
                local = _latlng_to_local(pt["lat"], pt["lon"], ref_lat, ref_lng)
                key = _node_key(local[0], local[1])

                if key in coord_to_node:
                    nid = coord_to_node[key]
                else:
                    nid = next_id
                    next_id += 1
                    coord_to_node[key] = nid
                    positions[nid] = local
                    G.add_node(nid, x=local[0], y=local[1])

                segment_nodes.append(nid)

            # Create edges between consecutive nodes on this road
            road_class = (el.get("tags") or {}).get("highway", "residential")
            for i in range(len(segment_nodes) - 1):
                n1 = segment_nodes[i]
                n2 = segment_nodes[i + 1]
                if n1 == n2:
                    continue
                dist = _distance(positions[n1], positions[n2])
                if dist < 0.1:
                    continue  # Skip degenerate edges
                # If edge already exists, keep the shorter one
                if G.has_edge(n1, n2):
                    if G[n1][n2]["weight"] <= dist:
                        continue
                G.add_edge(n1, n2, weight=dist, road_class=road_class)

        self.graph = G
        self._node_positions = positions
        self._build_spatial_index()

        logger.info(
            f"Street graph built: {len(G.nodes)} nodes, {len(G.edges)} edges "
            f"from {len(elements)} road segments"
        )

    def _build_spatial_index(self) -> None:
        """Build a flat spatial index for nearest-node queries."""
        self._spatial_index = [
            (pos[0], pos[1], nid)
            for nid, pos in self._node_positions.items()
        ]

    def _heuristic(self, n1: int, n2: int) -> float:
        """A* heuristic: straight-line distance between nodes."""
        p1 = self._node_positions.get(n1)
        p2 = self._node_positions.get(n2)
        if p1 is None or p2 is None:
            return 0.0
        return _distance(p1, p2)

    @staticmethod
    def _cache_path(
        lat: float, lng: float, radius_m: float, cache_dir: str
    ) -> Path:
        """Return the cache file path for these parameters."""
        key = f"street_{lat:.6f}_{lng:.6f}_{radius_m:.0f}"
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        base = Path(cache_dir).expanduser()
        return base / f"{h}.pkl"
