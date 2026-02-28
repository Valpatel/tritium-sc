# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for GeoJSON exporter — export to valid GeoJSON, roundtrip."""

import json
import pytest
from engine.layers import Layer, LayerFeature
from engine.layers.exporters.geojson import export_geojson
from engine.layers.parsers.geojson import parse_geojson


@pytest.fixture
def sample_layer():
    return Layer(
        layer_id="export-test",
        name="Export Test",
        source_format="kml",
        features=[
            LayerFeature("pt-1", "Point", [-122.4194, 37.7749], {"name": "HQ"}),
            LayerFeature(
                "line-1", "LineString",
                [[-122.4, 37.77], [-122.41, 37.78]],
                {"name": "Route"},
            ),
        ],
    )


class TestGeoJSONExporter:
    """Export Layer to GeoJSON."""

    def test_export_valid_geojson(self, sample_layer):
        """Export produces valid GeoJSON FeatureCollection."""
        result = export_geojson(sample_layer)
        assert isinstance(result, dict)
        assert result["type"] == "FeatureCollection"
        assert len(result["features"]) == 2

    def test_export_feature_structure(self, sample_layer):
        """Each exported feature has type, geometry, properties."""
        result = export_geojson(sample_layer)
        feat = result["features"][0]
        assert feat["type"] == "Feature"
        assert "geometry" in feat
        assert feat["geometry"]["type"] == "Point"
        assert feat["geometry"]["coordinates"] == [-122.4194, 37.7749]
        assert feat["properties"]["name"] == "HQ"

    def test_export_roundtrip(self, sample_layer):
        """Export then re-import produces equivalent features."""
        result = export_geojson(sample_layer)
        json_str = json.dumps(result)
        reimported = parse_geojson(json_str)
        assert len(reimported.features) == len(sample_layer.features)
        orig_types = {f.geometry_type for f in sample_layer.features}
        new_types = {f.geometry_type for f in reimported.features}
        assert orig_types == new_types
