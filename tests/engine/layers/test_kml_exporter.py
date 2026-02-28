# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for KML exporter — export to valid KML, roundtrip."""

import pytest
from engine.layers import Layer, LayerFeature
from engine.layers.exporters.kml import export_kml
from engine.layers.parsers.kml import parse_kml


@pytest.fixture
def sample_layer():
    return Layer(
        layer_id="export-test",
        name="Export Test",
        source_format="geojson",
        features=[
            LayerFeature(
                "pt-1", "Point", [-122.4194, 37.7749, 10.0],
                {"name": "HQ", "description": "Command Post"},
                style={"color": "#ff0000"},
            ),
            LayerFeature(
                "line-1", "LineString",
                [[-122.4, 37.77, 0], [-122.41, 37.78, 0], [-122.42, 37.79, 0]],
                {"name": "Route Alpha"},
            ),
            LayerFeature(
                "poly-1", "Polygon",
                [[[-122.4, 37.77, 0], [-122.41, 37.78, 0], [-122.42, 37.77, 0], [-122.4, 37.77, 0]]],
                {"name": "Zone Alpha"},
                style={"fillColor": "#00ff00"},
            ),
        ],
    )


class TestKMLExporter:
    """Export Layer to KML XML."""

    def test_export_produces_valid_xml(self, sample_layer):
        """Export produces parseable XML with kml root element."""
        import xml.etree.ElementTree as ET
        kml_str = export_kml(sample_layer)
        assert isinstance(kml_str, str)
        root = ET.fromstring(kml_str)
        # Root should be kml element
        assert "kml" in root.tag.lower()

    def test_export_contains_all_placemarks(self, sample_layer):
        """Exported KML contains one Placemark per feature."""
        kml_str = export_kml(sample_layer)
        assert kml_str.count("Placemark") >= 6  # open + close tags for 3 features

    def test_export_roundtrip(self, sample_layer):
        """Export then re-import produces equivalent features."""
        kml_str = export_kml(sample_layer)
        reimported = parse_kml(kml_str)
        assert len(reimported.features) == len(sample_layer.features)
        # Check geometry types preserved
        orig_types = {f.geometry_type for f in sample_layer.features}
        new_types = {f.geometry_type for f in reimported.features}
        assert orig_types == new_types

    def test_export_coordinate_order(self, sample_layer):
        """KML coordinates are in lng,lat,alt order."""
        kml_str = export_kml(sample_layer)
        # The point HQ at [-122.4194, 37.7749, 10.0] should appear as "-122.4194,37.7749,10.0"
        assert "-122.4194,37.7749,10.0" in kml_str or "-122.4194,37.7749,10" in kml_str
