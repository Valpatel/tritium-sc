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

    Returns stub/mock building polygons within the requested bounding box
    for development and testing. In production this would query an
    Overpass API or a local PostGIS database.
    """

    @property
    def layer_id(self) -> str:
        return "buildings"

    @property
    def layer_name(self) -> str:
        return "Building Footprints"

    @property
    def attribution(self) -> str:
        return "OpenStreetMap (stub data)"

    @property
    def description(self) -> str:
        return "Building footprint polygons for the visible area"

    def query(self, bounds: BBox) -> dict[str, Any]:
        """Generate deterministic mock building footprints within bounds."""
        features: list[dict[str, Any]] = []

        # Seed from bounds center for deterministic output
        cx = (bounds.west + bounds.east) / 2.0
        cy = (bounds.south + bounds.north) / 2.0
        rng = random.Random(int(cx * 1000) ^ int(cy * 1000))

        dx = bounds.east - bounds.west
        dy = bounds.north - bounds.south

        # Generate 5-15 buildings
        count = rng.randint(5, 15)
        for i in range(count):
            lon = bounds.west + rng.random() * dx
            lat = bounds.south + rng.random() * dy
            w = rng.uniform(0.0002, 0.0008)
            h = rng.uniform(0.0002, 0.0008)
            height = rng.uniform(3.0, 25.0)

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
                    "id": f"bldg-{i}",
                    "height": round(height, 1),
                    "levels": max(1, int(height / 3)),
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


# Registry of all built-in providers
BUILTIN_PROVIDERS: list[type[LayerProvider]] = [
    OSMTileProvider,
    SatelliteProvider,
    BuildingFootprintProvider,
    TerrainProvider,
]
