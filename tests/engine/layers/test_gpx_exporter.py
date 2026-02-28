# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for GPX exporter — export to valid GPX, roundtrip."""

import pytest
from engine.layers import Layer, LayerFeature
from engine.layers.exporters.gpx import export_gpx
from engine.layers.parsers.gpx import parse_gpx


@pytest.fixture
def waypoint_layer():
    return Layer(
        layer_id="gpx-export",
        name="GPX Export Test",
        source_format="gpx",
        features=[
            LayerFeature(
                "wpt-1", "Point", [-122.4194, 37.7749, 10.5],
                {"name": "Alpha", "description": "Start"},
            ),
            LayerFeature(
                "wpt-2", "Point", [-122.4095, 37.7850, 5.0],
                {"name": "Bravo"},
            ),
        ],
    )


@pytest.fixture
def track_layer():
    return Layer(
        layer_id="gpx-track",
        name="Track Export",
        source_format="gpx",
        features=[
            LayerFeature(
                "trk-1", "LineString",
                [[-122.4194, 37.7749, 10], [-122.4180, 37.7760, 12], [-122.4170, 37.7770, 15]],
                {"name": "Morning Patrol"},
            ),
        ],
    )


class TestGPXExporter:
    """Export Layer to GPX XML."""

    def test_export_produces_valid_xml(self, waypoint_layer):
        """Export produces parseable GPX XML."""
        import xml.etree.ElementTree as ET
        gpx_str = export_gpx(waypoint_layer)
        assert isinstance(gpx_str, str)
        root = ET.fromstring(gpx_str)
        assert "gpx" in root.tag.lower()

    def test_export_roundtrip_waypoints(self, waypoint_layer):
        """Export waypoints then re-import preserves count and coordinates."""
        gpx_str = export_gpx(waypoint_layer)
        reimported = parse_gpx(gpx_str)
        assert len(reimported.features) == 2
        f = reimported.features[0]
        assert f.geometry_type == "Point"
        assert f.coordinates[0] == pytest.approx(-122.4194)
        assert f.coordinates[1] == pytest.approx(37.7749)

    def test_export_roundtrip_tracks(self, track_layer):
        """Export track then re-import preserves LineString coordinates."""
        gpx_str = export_gpx(track_layer)
        reimported = parse_gpx(gpx_str)
        assert len(reimported.features) == 1
        f = reimported.features[0]
        assert f.geometry_type == "LineString"
        assert len(f.coordinates) == 3
