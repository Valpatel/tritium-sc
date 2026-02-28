# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for GeoJSON parser — FeatureCollection, all geometry types, properties."""

import json
import pytest
from engine.layers.parsers.geojson import parse_geojson


FEATURE_COLLECTION = json.dumps({
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-122.4194, 37.7749]},
            "properties": {"name": "HQ", "status": "active"},
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-122.4, 37.77], [-122.41, 37.78], [-122.42, 37.79]],
            },
            "properties": {"name": "Patrol Route"},
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-122.4, 37.77], [-122.41, 37.78], [-122.42, 37.77], [-122.4, 37.77]]],
            },
            "properties": {"name": "Zone Alpha"},
        },
    ],
})


class TestGeoJSONParser:
    """Parse GeoJSON to Layer."""

    def test_parse_feature_collection(self):
        """FeatureCollection produces a layer with all features."""
        layer = parse_geojson(FEATURE_COLLECTION)
        assert layer is not None
        assert layer.source_format == "geojson"
        assert len(layer.features) == 3

    def test_parse_point_geometry(self):
        """Point geometry preserves [lng, lat] coordinates."""
        layer = parse_geojson(FEATURE_COLLECTION)
        point = [f for f in layer.features if f.geometry_type == "Point"][0]
        assert point.coordinates[0] == pytest.approx(-122.4194)
        assert point.coordinates[1] == pytest.approx(37.7749)

    def test_parse_linestring_geometry(self):
        """LineString geometry preserves coordinate array."""
        layer = parse_geojson(FEATURE_COLLECTION)
        line = [f for f in layer.features if f.geometry_type == "LineString"][0]
        assert len(line.coordinates) == 3

    def test_parse_polygon_geometry(self):
        """Polygon geometry preserves ring structure."""
        layer = parse_geojson(FEATURE_COLLECTION)
        poly = [f for f in layer.features if f.geometry_type == "Polygon"][0]
        assert len(poly.coordinates) == 1  # one ring
        assert len(poly.coordinates[0]) == 4

    def test_properties_passthrough(self):
        """Feature properties are passed through to LayerFeature.properties."""
        layer = parse_geojson(FEATURE_COLLECTION)
        point = [f for f in layer.features if f.geometry_type == "Point"][0]
        assert point.properties["name"] == "HQ"
        assert point.properties["status"] == "active"

    def test_malformed_json_returns_empty_layer(self):
        """Malformed JSON returns empty layer, not crash."""
        layer = parse_geojson("not valid json {{{")
        assert layer is not None
        assert len(layer.features) == 0
