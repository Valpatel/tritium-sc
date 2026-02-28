# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for LayerManager — add/remove/list/visibility/import/export."""

import os
import tempfile
import pytest
from engine.layers import Layer, LayerFeature, LayerManager


@pytest.fixture
def manager():
    return LayerManager()


@pytest.fixture
def sample_layer():
    return Layer(
        layer_id="test-1",
        name="Test Layer",
        source_format="geojson",
        features=[
            LayerFeature("f1", "Point", [-122.4, 37.7], {"name": "A"}),
        ],
    )


class TestLayerManager:
    """Test LayerManager operations."""

    def test_add_layer(self, manager, sample_layer):
        """Adding a layer stores it and returns the ID."""
        lid = manager.add_layer(sample_layer)
        assert lid == "test-1"
        assert manager.get_layer("test-1") is sample_layer

    def test_remove_layer(self, manager, sample_layer):
        """Removing a layer returns True; removing nonexistent returns False."""
        manager.add_layer(sample_layer)
        assert manager.remove_layer("test-1") is True
        assert manager.get_layer("test-1") is None
        assert manager.remove_layer("test-1") is False

    def test_get_nonexistent_layer(self, manager):
        """Getting a nonexistent layer returns None."""
        assert manager.get_layer("nope") is None

    def test_list_layers(self, manager):
        """list_layers returns all added layers."""
        l1 = Layer("a", "Alpha", "kml", [])
        l2 = Layer("b", "Bravo", "gpx", [])
        manager.add_layer(l1)
        manager.add_layer(l2)
        result = manager.list_layers()
        assert len(result) == 2
        ids = {l.layer_id for l in result}
        assert ids == {"a", "b"}

    def test_set_visibility(self, manager, sample_layer):
        """set_visibility toggles layer visibility."""
        manager.add_layer(sample_layer)
        manager.set_visibility("test-1", False)
        layer = manager.get_layer("test-1")
        assert layer.visible is False
        manager.set_visibility("test-1", True)
        assert manager.get_layer("test-1").visible is True

    def test_set_visibility_nonexistent_raises(self, manager):
        """set_visibility on nonexistent layer raises KeyError."""
        with pytest.raises(KeyError):
            manager.set_visibility("nope", False)

    def test_import_geojson_file(self, manager):
        """import_file loads a GeoJSON file into a new layer."""
        geojson = '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-122.4,37.7]},"properties":{"name":"HQ"}}]}'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".geojson", delete=False) as f:
            f.write(geojson)
            path = f.name
        try:
            layer = manager.import_file(path, format="geojson")
            assert layer is not None
            assert len(layer.features) == 1
            assert layer.source_format == "geojson"
            # Layer should be registered
            assert manager.get_layer(layer.layer_id) is layer
        finally:
            os.unlink(path)

    def test_export_layer_geojson(self, manager, sample_layer):
        """export_layer returns GeoJSON string."""
        manager.add_layer(sample_layer)
        result = manager.export_layer("test-1", "geojson")
        assert isinstance(result, str)
        import json
        data = json.loads(result)
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 1
