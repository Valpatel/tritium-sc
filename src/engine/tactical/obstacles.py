# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Building obstacle detection from OpenStreetMap Overpass API.

Pulls building footprints and stores them as polygons in local (x, z)
coordinates for collision detection. Uses ray-casting for
point-in-polygon (no Shapely dependency).

Coordinate convention:
    +X = East, +Y = North (same as geo.py — Y in comments here means
    the second coordinate, labeled "z" in the 3D layout convention).
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_USER_AGENT = "TRITIUM-SC/0.1.0"
_DEFAULT_CACHE_DIR = "~/.cache/tritium-sc"

# Meters per degree latitude (constant)
_METERS_PER_DEG_LAT = 111_320.0


def _latlng_to_local(
    lat: float, lng: float, ref_lat: float, ref_lng: float
) -> tuple[float, float]:
    """Convert lat/lng to local (x, y) meters relative to reference point."""
    y = (lat - ref_lat) * _METERS_PER_DEG_LAT
    meters_per_deg_lng = _METERS_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    x = (lng - ref_lng) * meters_per_deg_lng
    return (x, y)


def _fetch_buildings(
    lat: float, lng: float, radius_m: float
) -> list[dict]:
    """Fetch building footprints from Overpass API (synchronous).

    Returns a list of OSM way elements with geometry.
    """
    query = f'[out:json];way["building"](around:{radius_m},{lat},{lng});out geom;'
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            _OVERPASS_URL,
            data={"data": query},
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
    data = resp.json()
    return data.get("elements", [])


def _point_in_polygon(
    px: float, py: float, polygon: list[tuple[float, float]]
) -> bool:
    """Ray-casting point-in-polygon test.

    Casts a horizontal ray from (px, py) to +infinity and counts
    how many polygon edges it crosses. Odd count = inside.
    """
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


def _segments_intersect(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, dx: float, dy: float,
) -> bool:
    """Check if line segment AB intersects line segment CD.

    Uses the cross-product orientation test.
    """
    def cross(ox: float, oy: float, px: float, py: float, qx: float, qy: float) -> float:
        return (px - ox) * (qy - oy) - (py - oy) * (qx - ox)

    d1 = cross(cx, cy, dx, dy, ax, ay)
    d2 = cross(cx, cy, dx, dy, bx, by)
    d3 = cross(ax, ay, bx, by, cx, cy)
    d4 = cross(ax, ay, bx, by, dx, dy)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    # Collinear cases (not needed for building detection — skip for simplicity)
    return False


class BuildingObstacles:
    """Building footprints for collision/obstacle detection.

    Stores building polygons in local (x, y) coordinates.
    Uses AABB bounding boxes for fast pre-filtering (~95% rejection
    in 4 float comparisons before full ray-cast).

    Usage:
        obs = BuildingObstacles()
        obs.load(lat, lng, radius_m=300)
        if obs.point_in_building(x, y):
            ...
    """

    def __init__(self) -> None:
        self.polygons: list[list[tuple[float, float]]] = []
        # Per-building roof heights (meters), parallel to self.polygons
        self._heights: list[float] = []
        # AABB bounding boxes: (min_x, min_y, max_x, max_y) per polygon
        self._aabbs: list[tuple[float, float, float, float]] = []

    def load(
        self,
        lat: float,
        lng: float,
        radius_m: float = 300,
        cache_dir: str = _DEFAULT_CACHE_DIR,
    ) -> None:
        """Load building footprints for the area around (lat, lng).

        Tries cache first, then Overpass API. On failure, polygons is empty.
        """
        cache_path = self._cache_path(lat, lng, radius_m, cache_dir)

        # Try loading from cache
        if cache_path.exists():
            try:
                with open(cache_path, "r") as f:
                    self.polygons = json.load(f)
                # Convert inner lists back to tuples
                self.polygons = [
                    [(pt[0], pt[1]) for pt in poly]
                    for poly in self.polygons
                ]
                # Cache doesn't store heights — default all to 8m
                self._heights = [8.0] * len(self.polygons)
                self._compute_aabbs()
                logger.info(f"Building obstacles loaded from cache: {len(self.polygons)} buildings")
                return
            except Exception as e:
                logger.warning(f"Cache load failed: {e}")

        # Fetch from Overpass API
        try:
            elements = _fetch_buildings(lat, lng, radius_m)
        except Exception as e:
            logger.warning(f"Overpass building fetch failed: {e}")
            self.polygons = []
            return

        if not elements:
            self.polygons = []
            return

        # Convert building footprints to local polygons
        self._build_polygons(elements, lat, lng)
        self._compute_aabbs()

        # Save to cache
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            # Store as list of lists for JSON serialization
            serializable = [
                [[pt[0], pt[1]] for pt in poly]
                for poly in self.polygons
            ]
            with open(cache_path, "w") as f:
                json.dump(serializable, f)
        except Exception as e:
            logger.warning(f"Cache save failed: {e}")

    def point_in_building(self, x: float, y: float) -> bool:
        """Check if the point (x, y) in local meters is inside any building.

        Uses AABB pre-filter to skip polygons whose bounding box doesn't
        contain the point.  ~95% of polygons are rejected in 4 float
        comparisons, reducing full ray-casts to ~10 per call for 227 buildings.
        """
        if self._aabbs:
            for i, (min_x, min_y, max_x, max_y) in enumerate(self._aabbs):
                if x < min_x or x > max_x or y < min_y or y > max_y:
                    continue
                if _point_in_polygon(x, y, self.polygons[i]):
                    return True
            return False
        # Fallback: no AABBs computed (shouldn't happen after load)
        for poly in self.polygons:
            if _point_in_polygon(x, y, poly):
                return True
        return False

    def building_height_at(self, x: float, y: float) -> float | None:
        """Return the roof height of the building containing (x, y), or None.

        Uses AABB pre-filter then ray-casting, same as point_in_building().
        Returns the height from ``_heights`` for the first containing polygon.
        """
        if not self._heights:
            return None
        if self._aabbs:
            for i, (min_x, min_y, max_x, max_y) in enumerate(self._aabbs):
                if x < min_x or x > max_x or y < min_y or y > max_y:
                    continue
                if _point_in_polygon(x, y, self.polygons[i]):
                    return self._heights[i]
            return None
        for i, poly in enumerate(self.polygons):
            if _point_in_polygon(x, y, poly):
                return self._heights[i]
        return None

    def path_crosses_building(
        self, waypoints: list[tuple[float, float]]
    ) -> bool:
        """Check if any segment of the path crosses a building polygon.

        Tests both: (a) segment-edge intersection, and
        (b) midpoint inside a building (catches paths entirely inside).
        """
        if len(waypoints) < 2:
            return False

        for i in range(len(waypoints) - 1):
            ax, ay = waypoints[i]
            bx, by = waypoints[i + 1]

            # Check midpoint of the segment
            mx = (ax + bx) / 2
            my = (ay + by) / 2
            if self.point_in_building(mx, my):
                return True

            # Check segment against all building polygon edges
            for poly in self.polygons:
                n = len(poly)
                for j in range(n):
                    cx, cy = poly[j]
                    dx, dy = poly[(j + 1) % n]
                    if _segments_intersect(ax, ay, bx, by, cx, cy, dx, dy):
                        return True

        return False

    def load_from_overture(self, building_dicts: list[dict]) -> None:
        """Load building polygons from pre-fetched data.

        Accepts a list of dicts with "polygon" key containing
        [(x, y), ...] tuples in local meters coordinates, and
        optional "height" key (default 8m).

        This allows the overlay API to pass pre-computed local-coordinate
        polygons without re-fetching from Overpass.
        """
        self.polygons = []
        self._heights = []
        for bldg in building_dicts:
            poly = bldg.get("polygon", [])
            if len(poly) < 3:
                continue
            # Ensure tuples
            self.polygons.append([(pt[0], pt[1]) for pt in poly])
            self._heights.append(bldg.get("height", 8.0))
        self._compute_aabbs()
        logger.info(f"Building obstacles: loaded {len(self.polygons)} buildings from overture data")

    def to_dicts(self, default_height: float = 8.0) -> list[dict]:
        """Export building polygons as a list of dicts for the frontend.

        Returns: [{"polygon": [[x, y], ...], "height": <h>}, ...]
        Uses per-building heights from ``_heights`` when available,
        otherwise falls back to *default_height*.
        """
        result = []
        for i, poly in enumerate(self.polygons):
            h = self._heights[i] if i < len(self._heights) else default_height
            result.append({"polygon": [list(pt) for pt in poly], "height": h})
        return result

    def _compute_aabbs(self) -> None:
        """Compute axis-aligned bounding boxes for all polygons."""
        self._aabbs = []
        for poly in self.polygons:
            if not poly:
                self._aabbs.append((0.0, 0.0, 0.0, 0.0))
                continue
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            self._aabbs.append((min(xs), min(ys), max(xs), max(ys)))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_polygons(
        self, elements: list[dict], ref_lat: float, ref_lng: float
    ) -> None:
        """Convert Overpass way elements to local-coordinate polygons."""
        self.polygons = []
        self._heights = []
        for el in elements:
            if el.get("type") != "way":
                continue
            geometry = el.get("geometry", [])
            if len(geometry) < 3:
                continue

            poly = []
            for pt in geometry:
                local = _latlng_to_local(pt["lat"], pt["lon"], ref_lat, ref_lng)
                poly.append(local)

            self.polygons.append(poly)

            # Extract height from OSM tags
            tags = el.get("tags", {})
            height = tags.get("height")
            if height is not None:
                try:
                    self._heights.append(float(height))
                    continue
                except (ValueError, TypeError):
                    pass
            levels = tags.get("building:levels")
            if levels is not None:
                try:
                    self._heights.append(float(levels) * 3.0)
                    continue
                except (ValueError, TypeError):
                    pass
            self._heights.append(8.0)

        logger.info(f"Building obstacles: {len(self.polygons)} buildings loaded")

    @staticmethod
    def _cache_path(
        lat: float, lng: float, radius_m: float, cache_dir: str
    ) -> Path:
        """Return the cache file path for these parameters."""
        key = f"buildings_{lat:.6f}_{lng:.6f}_{radius_m:.0f}"
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        base = Path(cache_dir).expanduser()
        return base / f"{h}.json"
