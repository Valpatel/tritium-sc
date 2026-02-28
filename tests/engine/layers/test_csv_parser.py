# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for CSV parser — basic CSV, missing columns, extra columns."""

import pytest
from engine.layers.parsers.csv_import import parse_csv


class TestCSVParser:
    """Parse CSV with lat,lng columns to point Layer."""

    def test_parse_basic_csv(self):
        """CSV with lat,lng columns becomes point features."""
        csv_text = "name,lat,lng\nAlpha,37.7749,-122.4194\nBravo,37.7850,-122.4095\n"
        layer = parse_csv(csv_text)
        assert layer is not None
        assert layer.source_format == "csv"
        assert len(layer.features) == 2
        f = layer.features[0]
        assert f.geometry_type == "Point"
        # Stored as [lng, lat]
        assert f.coordinates[0] == pytest.approx(-122.4194)
        assert f.coordinates[1] == pytest.approx(37.7749)
        assert f.properties["name"] == "Alpha"

    def test_missing_lat_lng_columns(self):
        """CSV without lat/lng columns returns empty layer."""
        csv_text = "x,y,z\n1,2,3\n"
        layer = parse_csv(csv_text)
        assert layer is not None
        assert len(layer.features) == 0

    def test_extra_columns_preserved(self):
        """Extra CSV columns are preserved in properties dict."""
        csv_text = "lat,lng,name,status,priority\n37.7749,-122.4194,HQ,active,high\n"
        layer = parse_csv(csv_text)
        assert len(layer.features) == 1
        props = layer.features[0].properties
        assert props["name"] == "HQ"
        assert props["status"] == "active"
        assert props["priority"] == "high"
