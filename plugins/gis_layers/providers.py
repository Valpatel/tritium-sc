# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Concrete GIS layer providers.

Each provider knows how to produce tile URLs or GeoJSON features for a
given bounding box. They share a common ``query(bounds)`` interface that
returns a GeoJSON FeatureCollection dict.
"""

from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BBox:
    """Axis-aligned bounding box in WGS-84 (lon/lat)."""
    west: float
    south: float
    east: float
    north: float

    @classmethod
    def from_string(cls, bbox_str: str) -> "BBox":
        """Parse ``west,south,east,north`` string."""
        parts = [float(p) for p in bbox_str.split(",")]
        if len(parts) != 4:
            raise ValueError("bbox must have exactly 4 comma-separated values")
        return cls(west=parts[0], south=parts[1], east=parts[2], north=parts[3])


class LayerProvider(ABC):
    """Abstract base for all GIS layer providers."""

    @property
    @abstractmethod
    def layer_id(self) -> str:
        """Unique identifier for this layer."""

    @property
    @abstractmethod
    def layer_name(self) -> str:
        """Human-readable name."""

    @property
    def layer_type(self) -> str:
        """'tile' for raster tile layers, 'feature' for vector GeoJSON."""
        return "feature"

    @property
    def attribution(self) -> str:
        """Data source attribution text."""
        return ""

    @property
    def description(self) -> str:
        """Brief description of the layer."""
        return ""

    @property
    def min_zoom(self) -> int:
        return 0

    @property
    def max_zoom(self) -> int:
        return 19

    def tile_url(self, z: int, x: int, y: int) -> str | None:
        """Return a tile image URL, or None if not a tile layer."""
        return None

    def query(self, bounds: BBox) -> dict[str, Any]:
        """Return GeoJSON FeatureCollection for the given bounding box."""
        return {"type": "FeatureCollection", "features": []}

    def to_dict(self) -> dict[str, Any]:
        """Serialize layer metadata."""
        return {
            "id": self.layer_id,
            "name": self.layer_name,
            "type": self.layer_type,
            "attribution": self.attribution,
            "description": self.description,
            "min_zoom": self.min_zoom,
            "max_zoom": self.max_zoom,
        }


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------


class OSMTileProvider(LayerProvider):
    """OpenStreetMap raster tile provider (no API key required)."""

    URL_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

    @property
    def layer_id(self) -> str:
        return "osm"

    @property
    def layer_name(self) -> str:
        return "OpenStreetMap"

    @property
    def layer_type(self) -> str:
        return "tile"

    @property
    def attribution(self) -> str:
        return "© OpenStreetMap contributors"

    @property
    def description(self) -> str:
        return "Standard OpenStreetMap raster tiles"

    @property
    def max_zoom(self) -> int:
        return 19

    def tile_url(self, z: int, x: int, y: int) -> str:
        return self.URL_TEMPLATE.format(z=z, x=x, y=y)


class SatelliteProvider(LayerProvider):
    """Satellite imagery tile provider.

    Uses a configurable URL template. Defaults to Esri World Imagery
    (no API key required for limited use).
    """

    DEFAULT_URL = (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
    )

    def __init__(self, url_template: str | None = None) -> None:
        self._url_template = url_template or self.DEFAULT_URL

    @property
    def layer_id(self) -> str:
        return "satellite"

    @property
    def layer_name(self) -> str:
        return "Satellite Imagery"

    @property
    def layer_type(self) -> str:
        return "tile"

    @property
    def attribution(self) -> str:
        return "Esri, Maxar, Earthstar Geographics"

    @property
    def description(self) -> str:
        return "High-resolution satellite and aerial imagery"

    @property
    def max_zoom(self) -> int:
        return 18

    def tile_url(self, z: int, x: int, y: int) -> str:
        return self._url_template.format(z=z, x=x, y=y)


class BuildingFootprintProvider(LayerProvider):
    """Building footprint polygons as GeoJSON.

    Queries the Overpass API for real building data when available,
    falls back to deterministic stub data for development/testing.
    """

    @property
    def layer_id(self) -> str:
        return "buildings"

    @property
    def layer_name(self) -> str:
        return "Building Footprints"

    @property
    def attribution(self) -> str:
        return "OpenStreetMap"

    @property
    def description(self) -> str:
        return "Building footprint polygons with heights and types"

    def query(self, bounds: BBox) -> dict[str, Any]:
        """Fetch real building footprints from Overpass, fallback to stubs."""
        # Try real OSM data first
        try:
            return self._query_osm(bounds)
        except Exception:
            pass
        return self._query_stub(bounds)

    def _query_osm(self, bounds: BBox) -> dict[str, Any]:
        """Fetch building polygons from Overpass API with full geometry."""
        import requests

        bbox = f"{bounds.south},{bounds.west},{bounds.north},{bounds.east}"
        query = f'[out:json][timeout:30];way["building"]({bbox});out geom;'

        resp = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            headers={"User-Agent": "Tritium/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        elements = resp.json().get("elements", [])

        features: list[dict[str, Any]] = []
        for el in elements:
            if el.get("type") != "way":
                continue
            geometry = el.get("geometry", [])
            if len(geometry) < 3:
                continue

            tags = el.get("tags", {})
            coords = [[[pt["lon"], pt["lat"]] for pt in geometry]]

            # Height estimation from tags
            height = 8.0
            height_str = tags.get("height")
            if height_str:
                try:
                    height = float(height_str.replace("m", "").strip())
                except (ValueError, TypeError):
                    pass
            elif tags.get("building:levels"):
                try:
                    height = float(tags["building:levels"]) * 3.0 + 1.0
                except (ValueError, TypeError):
                    pass

            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": coords},
                "properties": {
                    "id": f"osm-{el['id']}",
                    "height": round(height, 1),
                    "levels": max(1, int(height / 3)),
                    "building_type": tags.get("building", "yes"),
                    "name": tags.get("name", ""),
                    "source": "osm",
                },
            })

        return {"type": "FeatureCollection", "features": features}

    @staticmethod
    def _query_stub(bounds: BBox) -> dict[str, Any]:
        """Generate deterministic mock building footprints within bounds."""
        features: list[dict[str, Any]] = []

        cx = (bounds.west + bounds.east) / 2.0
        cy = (bounds.south + bounds.north) / 2.0
        rng = random.Random(int(cx * 1000) ^ int(cy * 1000))

        dx = bounds.east - bounds.west
        dy = bounds.north - bounds.south

        btypes = ["residential", "apartments", "commercial", "office",
                   "industrial", "retail", "house", "garage"]

        count = rng.randint(5, 15)
        for i in range(count):
            lon = bounds.west + rng.random() * dx
            lat = bounds.south + rng.random() * dy
            w = rng.uniform(0.0002, 0.0008)
            h = rng.uniform(0.0002, 0.0008)
            btype = btypes[rng.randint(0, len(btypes) - 1)]
            # Height varies by type
            type_heights = {
                "residential": 8.0, "apartments": 15.0, "commercial": 12.0,
                "office": 18.0, "industrial": 8.0, "retail": 5.0,
                "house": 7.0, "garage": 3.0,
            }
            base_h = type_heights.get(btype, 8.0)
            height = base_h + rng.uniform(-2.0, 4.0)

            coords = [[
                [lon, lat],
                [lon + w, lat],
                [lon + w, lat + h],
                [lon, lat + h],
                [lon, lat],
            ]]

            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": coords},
                "properties": {
                    "id": f"stub-{i}",
                    "height": round(max(3.0, height), 1),
                    "levels": max(1, int(height / 3)),
                    "building_type": btype,
                    "source": "stub",
                },
            })

        return {"type": "FeatureCollection", "features": features}


class TerrainProvider(LayerProvider):
    """Elevation / terrain data provider.

    Returns stub elevation point features within the bounding box.
    In production this would query a DEM raster or Mapzen Terrain tiles.
    """

    @property
    def layer_id(self) -> str:
        return "terrain"

    @property
    def layer_name(self) -> str:
        return "Terrain Elevation"

    @property
    def attribution(self) -> str:
        return "Mapzen / USGS (stub data)"

    @property
    def description(self) -> str:
        return "Elevation data points and contour information"

    def query(self, bounds: BBox) -> dict[str, Any]:
        """Generate a grid of stub elevation points."""
        features: list[dict[str, Any]] = []

        cx = (bounds.west + bounds.east) / 2.0
        cy = (bounds.south + bounds.north) / 2.0

        # Generate a 5x5 grid of elevation points
        for ix in range(5):
            for iy in range(5):
                lon = bounds.west + (bounds.east - bounds.west) * (ix + 0.5) / 5
                lat = bounds.south + (bounds.north - bounds.south) * (iy + 0.5) / 5
                # Simple elevation model: distance from center creates a hill
                dist = math.sqrt((lon - cx) ** 2 + (lat - cy) ** 2)
                elev = max(0.0, 100.0 - dist * 50000.0) + 50.0

                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "elevation_m": round(elev, 1),
                        "source": "stub",
                    },
                })

        return {"type": "FeatureCollection", "features": features}


class SegmentedTerrainProvider(LayerProvider):
    """Segmented terrain polygons from geospatial intelligence pipeline.

    Serves cached terrain segmentation results (buildings, roads, water,
    vegetation, sidewalks, parking, bridges) as colored GeoJSON polygons
    for the tactical map.

    Colors:
        Buildings — dark gray (#404040)
        Water — blue (#0066cc, 0.4 opacity)
        Vegetation — green (#228B22, 0.3 opacity)
        Roads — dark gray (#333333)
        Sidewalks — light gray (#999999)
        Parking — hatched (#666666, 0.3 opacity)
        Bridges — steel blue (#4682B4)
        Barren — tan (#D2B48C)
        Rail — dark red (#8B0000)
    """

    _TERRAIN_COLORS = {
        "building": "#404040",
        "road": "#333333",
        "water": "#0066cc",
        "vegetation": "#228B22",
        "sidewalk": "#999999",
        "parking": "#666666",
        "bridge": "#4682B4",
        "barren": "#D2B48C",
        "rail": "#8B0000",
    }

    _TERRAIN_OPACITY = {
        "building": 0.6,
        "road": 0.4,
        "water": 0.4,
        "vegetation": 0.3,
        "sidewalk": 0.3,
        "parking": 0.3,
        "bridge": 0.5,
        "barren": 0.3,
        "rail": 0.5,
    }

    def __init__(self, ao_id: str | None = None, cache_dir: str = "data/cache/terrain") -> None:
        self._ao_id = ao_id
        self._cache_dir = cache_dir
        self._terrain_layer = None

    @property
    def layer_id(self) -> str:
        return "segmented_terrain"

    @property
    def layer_name(self) -> str:
        return "Segmented Terrain"

    @property
    def attribution(self) -> str:
        return "Tritium Geospatial Segmentation"

    @property
    def description(self) -> str:
        return "Classified terrain polygons from satellite/aerial imagery segmentation"

    def set_terrain_layer(self, terrain_layer: Any) -> None:
        """Directly set a TerrainLayer instance."""
        self._terrain_layer = terrain_layer

    def _ensure_loaded(self) -> bool:
        """Load terrain layer from cache if not already loaded."""
        if self._terrain_layer is not None:
            return True

        if self._ao_id is None:
            return False

        try:
            from tritium_lib.intelligence.geospatial.terrain_layer import TerrainLayer
            tl = TerrainLayer(cache_dir=self._cache_dir)
            if tl.load_cached(self._ao_id):
                self._terrain_layer = tl
                return True
        except Exception:
            pass

        return False

    def query(self, bounds: BBox) -> dict[str, Any]:
        """Return segmented terrain as GeoJSON with styling properties."""
        if not self._ensure_loaded():
            return {"type": "FeatureCollection", "features": []}

        # Get raw GeoJSON from terrain layer
        try:
            geojson = self._terrain_layer.to_geojson()
        except Exception:
            return {"type": "FeatureCollection", "features": []}

        # Filter to bounds and add styling properties
        filtered = []
        for feature in geojson.get("features", []):
            props = feature.get("properties", {})
            terrain_type = props.get("terrain_type", "unknown")

            # Filter by bounds if centroid is available
            centroid = props.get("centroid")
            if centroid and isinstance(centroid, (list, tuple)) and len(centroid) >= 2:
                lon, lat = centroid[0], centroid[1]
                if not (bounds.south <= lat <= bounds.north and bounds.west <= lon <= bounds.east):
                    continue

            # Add styling properties for frontend rendering
            props["fill_color"] = self._TERRAIN_COLORS.get(terrain_type, "#808080")
            props["fill_opacity"] = self._TERRAIN_OPACITY.get(terrain_type, 0.3)
            props["stroke_color"] = self._TERRAIN_COLORS.get(terrain_type, "#808080")
            props["stroke_width"] = 1

            filtered.append(feature)

        return {"type": "FeatureCollection", "features": filtered}


# Registry of all built-in providers
BUILTIN_PROVIDERS: list[type[LayerProvider]] = [
    OSMTileProvider,
    SatelliteProvider,
    BuildingFootprintProvider,
    TerrainProvider,
    SegmentedTerrainProvider,
]
