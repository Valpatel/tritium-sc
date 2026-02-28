# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Layer and LayerFeature dataclasses for the map data layer system.

All coordinates are stored in GeoJSON convention: [lng, lat] or [lng, lat, alt].
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LayerFeature:
    """A single feature (point, line, polygon) within a layer.

    Attributes:
        feature_id: Unique identifier for this feature.
        geometry_type: One of "Point", "LineString", "Polygon".
        coordinates: GeoJSON-style coordinate arrays.
            Point: [lng, lat] or [lng, lat, alt]
            LineString: [[lng, lat], [lng, lat], ...]
            Polygon: [[[lng, lat], [lng, lat], ...]]  (list of rings)
        properties: Arbitrary key-value metadata.
        style: Optional rendering hints (color, lineWidth, fillColor, opacity).
        timestamp: Optional ISO8601 timestamp for time-series data.
    """

    feature_id: str
    geometry_type: str
    coordinates: list
    properties: dict
    style: dict | None = None
    timestamp: str | None = None


@dataclass
class Layer:
    """A named collection of geographic features.

    Attributes:
        layer_id: Unique identifier for this layer.
        name: Human-readable display name.
        source_format: Original format ("kml", "geojson", "gpx", "cot", "csv").
        features: List of LayerFeature instances.
        visible: Whether the layer is currently rendered.
        opacity: Rendering opacity (0.0 to 1.0).
        z_index: Draw order (higher = on top).
        metadata: Arbitrary key-value metadata about the layer.
        created_at: ISO8601 creation timestamp.
        updated_at: ISO8601 last-update timestamp.
    """

    layer_id: str
    name: str
    source_format: str
    features: list[LayerFeature]
    visible: bool = True
    opacity: float = 1.0
    z_index: int = 0
    metadata: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
