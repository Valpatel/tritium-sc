# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Export Layer to GeoJSON dict (RFC 7946 compliant).

Uses only stdlib json. GeoJSON coordinates are [lng, lat] (already the
internal storage convention).
"""

from __future__ import annotations

from engine.layers.layer import Layer, LayerFeature


def export_geojson(layer: Layer) -> dict:
    """Export a Layer to a GeoJSON FeatureCollection dict.

    Args:
        layer: The Layer to export.

    Returns:
        Dict representing a valid GeoJSON FeatureCollection.
    """
    features = []
    for feature in layer.features:
        gj_feature = _feature_to_geojson(feature)
        features.append(gj_feature)

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def _feature_to_geojson(feature: LayerFeature) -> dict:
    """Convert a LayerFeature to a GeoJSON Feature dict."""
    return {
        "type": "Feature",
        "id": feature.feature_id,
        "geometry": {
            "type": feature.geometry_type,
            "coordinates": feature.coordinates,
        },
        "properties": dict(feature.properties),
    }
