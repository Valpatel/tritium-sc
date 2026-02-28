# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Layer and LayerFeature dataclasses."""

import pytest
from engine.layers import Layer, LayerFeature


class TestLayerFeature:
    """Test LayerFeature creation and properties."""

    def test_create_point_feature(self):
        """Point feature with coordinates [lng, lat]."""
        f = LayerFeature(
            feature_id="pt-1",
            geometry_type="Point",
            coordinates=[-122.4194, 37.7749],
            properties={"name": "HQ"},
        )
        assert f.feature_id == "pt-1"
        assert f.geometry_type == "Point"
        assert f.coordinates == [-122.4194, 37.7749]
        assert f.properties["name"] == "HQ"
        assert f.style is None
        assert f.timestamp is None

    def test_create_linestring_feature(self):
        """LineString feature with nested coordinate arrays."""
        coords = [[-122.4, 37.77], [-122.41, 37.78], [-122.42, 37.79]]
        f = LayerFeature(
            feature_id="line-1",
            geometry_type="LineString",
            coordinates=coords,
            properties={"name": "Patrol Route"},
            style={"color": "#ff0000", "lineWidth": 2.0},
        )
        assert f.geometry_type == "LineString"
        assert len(f.coordinates) == 3
        assert f.style["lineWidth"] == 2.0

    def test_create_polygon_feature(self):
        """Polygon feature with ring coordinate array."""
        ring = [[-122.4, 37.77], [-122.41, 37.78], [-122.42, 37.77], [-122.4, 37.77]]
        f = LayerFeature(
            feature_id="poly-1",
            geometry_type="Polygon",
            coordinates=[ring],
            properties={"name": "Zone Alpha"},
            style={"fillColor": "#00ff00", "opacity": 0.5},
        )
        assert f.geometry_type == "Polygon"
        assert len(f.coordinates[0]) == 4


class TestLayer:
    """Test Layer creation and properties."""

    def test_create_layer_with_features(self):
        """Layer holds features and metadata."""
        f1 = LayerFeature("f1", "Point", [-122.4, 37.7], {"name": "A"})
        f2 = LayerFeature("f2", "Point", [-122.5, 37.8], {"name": "B"})
        layer = Layer(
            layer_id="layer-1",
            name="Test Layer",
            source_format="geojson",
            features=[f1, f2],
        )
        assert layer.layer_id == "layer-1"
        assert layer.name == "Test Layer"
        assert layer.source_format == "geojson"
        assert len(layer.features) == 2
        assert layer.visible is True
        assert layer.opacity == 1.0
        assert layer.z_index == 0

    def test_layer_defaults(self):
        """Layer defaults are sane."""
        layer = Layer(
            layer_id="empty",
            name="Empty",
            source_format="kml",
            features=[],
        )
        assert layer.visible is True
        assert layer.opacity == 1.0
        assert layer.z_index == 0
        assert layer.metadata == {}
        assert layer.features == []
