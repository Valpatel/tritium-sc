# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Parse GeoJSON (RFC 7946) to Layer using stdlib json.

Handles FeatureCollection, Feature, Point/LineString/Polygon geometries.
Passes through properties dict. Coordinates are already in [lng, lat] order.
"""

from __future__ import annotations

import json
import uuid

from engine.layers.layer import Layer, LayerFeature


def parse_geojson(geojson_string: str) -> Layer:
    """Parse a GeoJSON string into a Layer.

    Args:
        geojson_string: Raw GeoJSON content (string).

    Returns:
        Layer with parsed features. Returns empty layer on parse errors.
    """
    try:
        data = json.loads(geojson_string)
    except (json.JSONDecodeError, TypeError):
        return Layer(
            layer_id=f"layer-{uuid.uuid4().hex[:8]}",
            name="",
            source_format="geojson",
            features=[],
        )

    features: list[LayerFeature] = []

    if data.get("type") == "FeatureCollection":
        raw_features = data.get("features", [])
        for idx, raw in enumerate(raw_features):
            feature = _parse_feature(raw, idx)
            if feature is not None:
                features.append(feature)
    elif data.get("type") == "Feature":
        feature = _parse_feature(data, 0)
        if feature is not None:
            features.append(feature)

    layer_name = data.get("name", "")
    if not layer_name and features:
        # Try to derive name from first feature
        first_name = features[0].properties.get("name", "")
        if first_name:
            layer_name = f"GeoJSON ({first_name}...)"

    return Layer(
        layer_id=f"layer-{uuid.uuid4().hex[:8]}",
        name=layer_name,
        source_format="geojson",
        features=features,
    )


def _parse_feature(raw: dict, idx: int) -> LayerFeature | None:
    """Parse a single GeoJSON Feature dict into a LayerFeature."""
    if not isinstance(raw, dict):
        return None

    geometry = raw.get("geometry")
    if not isinstance(geometry, dict):
        return None

    geom_type = geometry.get("type", "")
    coordinates = geometry.get("coordinates")

    if geom_type not in ("Point", "LineString", "Polygon") or coordinates is None:
        return None

    properties = raw.get("properties") or {}
    if not isinstance(properties, dict):
        properties = {}

    feature_id = raw.get("id", f"geojson-{idx}")
    if not isinstance(feature_id, str):
        feature_id = str(feature_id)

    return LayerFeature(
        feature_id=feature_id,
        geometry_type=geom_type,
        coordinates=coordinates,
        properties=properties,
    )
