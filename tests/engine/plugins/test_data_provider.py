# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for DataProviderPlugin, LayerRegistry, and layers API router."""

import pytest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

from engine.plugins.data_provider import (
    Bounds,
    DataItem,
    DataProviderPlugin,
    EnrichmentResult,
    Subscription,
    TimeRange,
)
from engine.plugins.layer_registry import (
    LayerRegistry,
    RegisteredLayer,
    _data_item_to_feature,
)


# ---------------------------------------------------------------------------
# Concrete test provider
# ---------------------------------------------------------------------------

class MockProvider(DataProviderPlugin):
    """Minimal concrete DataProviderPlugin for testing."""

    plugin_id = "test.mock-provider"
    name = "Mock Provider"
    version = "0.1.0"
    provider_type = "feed"
    data_format = "geojson"

    def __init__(self, items: list[DataItem] | None = None):
        self._items = items or []
        self._started = False

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    async def query(
        self,
        bounds: Bounds | None = None,
        time_range: TimeRange | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[DataItem]:
        results = list(self._items)
        if bounds:
            results = [
                item for item in results
                if bounds.contains(
                    item.geometry.get("lat", 0),
                    item.geometry.get("lng", 0),
                )
            ]
        return results


# ---------------------------------------------------------------------------
# DataItem tests
# ---------------------------------------------------------------------------

class TestDataItem:
    """Test DataItem dataclass."""

    def test_create_minimal(self):
        item = DataItem(
            item_id="item-1",
            data_type="vessel",
            geometry={"lat": 37.7, "lng": -122.0},
        )
        assert item.item_id == "item-1"
        assert item.data_type == "vessel"
        assert item.geometry["lat"] == 37.7
        assert item.confidence == 1.0
        assert item.source == ""
        assert isinstance(item.timestamp, datetime)

    def test_create_full(self):
        ts = datetime(2026, 3, 13, tzinfo=timezone.utc)
        item = DataItem(
            item_id="item-2",
            data_type="aircraft",
            geometry={"lat": 37.7, "lng": -122.0},
            properties={"callsign": "UAL123", "altitude": 35000},
            timestamp=ts,
            source="test.adsb",
            confidence=0.95,
        )
        assert item.properties["callsign"] == "UAL123"
        assert item.source == "test.adsb"
        assert item.confidence == 0.95
        assert item.timestamp == ts


# ---------------------------------------------------------------------------
# EnrichmentResult tests
# ---------------------------------------------------------------------------

class TestEnrichmentResult:
    """Test EnrichmentResult dataclass."""

    def test_create(self):
        result = EnrichmentResult(
            target_id="tgt-1",
            enrichments=[{"type": "registration", "value": "ABC123"}],
            source="test.lpr",
        )
        assert result.target_id == "tgt-1"
        assert len(result.enrichments) == 1
        assert result.source == "test.lpr"

    def test_defaults(self):
        result = EnrichmentResult(target_id="tgt-2")
        assert result.enrichments == []
        assert result.source == ""
        assert isinstance(result.timestamp, datetime)


# ---------------------------------------------------------------------------
# Subscription tests
# ---------------------------------------------------------------------------

class TestSubscription:
    """Test Subscription dataclass."""

    def test_create(self):
        sub = Subscription()
        assert sub.active is True
        assert len(sub.sub_id) == 12

    def test_cancel(self):
        cancelled = False

        def on_cancel():
            nonlocal cancelled
            cancelled = True

        sub = Subscription(_cancel=on_cancel)
        assert sub.active is True
        sub.cancel()
        assert sub.active is False
        assert cancelled is True

    def test_cancel_without_callback(self):
        sub = Subscription()
        sub.cancel()
        assert sub.active is False


# ---------------------------------------------------------------------------
# Bounds tests
# ---------------------------------------------------------------------------

class TestBounds:
    """Test Bounds helper."""

    def test_contains(self):
        b = Bounds(south=37.0, west=-122.5, north=38.0, east=-121.5)
        assert b.contains(37.5, -122.0) is True
        assert b.contains(36.0, -122.0) is False
        assert b.contains(37.5, -123.0) is False

    def test_edge(self):
        b = Bounds(south=37.0, west=-122.0, north=38.0, east=-121.0)
        assert b.contains(37.0, -122.0) is True
        assert b.contains(38.0, -121.0) is True


# ---------------------------------------------------------------------------
# DataProviderPlugin abstract base tests
# ---------------------------------------------------------------------------

class TestDataProviderPlugin:
    """Test the abstract base class."""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            DataProviderPlugin()

    def test_concrete_provider(self):
        provider = MockProvider()
        assert provider.plugin_id == "test.mock-provider"
        assert provider.provider_type == "feed"
        assert provider.data_format == "geojson"

    @pytest.mark.asyncio
    async def test_query_returns_items(self):
        items = [
            DataItem(
                item_id="v1",
                data_type="vessel",
                geometry={"lat": 37.7, "lng": -122.0},
            )
        ]
        provider = MockProvider(items=items)
        result = await provider.query()
        assert len(result) == 1
        assert result[0].item_id == "v1"

    @pytest.mark.asyncio
    async def test_query_with_bounds_filter(self):
        items = [
            DataItem(
                item_id="in",
                data_type="vessel",
                geometry={"lat": 37.7, "lng": -122.0},
            ),
            DataItem(
                item_id="out",
                data_type="vessel",
                geometry={"lat": 40.0, "lng": -100.0},
            ),
        ]
        provider = MockProvider(items=items)
        bounds = Bounds(south=37.0, west=-123.0, north=38.0, east=-121.0)
        result = await provider.query(bounds=bounds)
        assert len(result) == 1
        assert result[0].item_id == "in"

    @pytest.mark.asyncio
    async def test_subscribe_not_implemented(self):
        provider = MockProvider()
        with pytest.raises(NotImplementedError):
            await provider.subscribe(AsyncMock())

    @pytest.mark.asyncio
    async def test_enrich_not_implemented(self):
        provider = MockProvider()
        with pytest.raises(NotImplementedError):
            await provider.enrich("tgt-1")

    def test_start_stop(self):
        provider = MockProvider()
        assert provider._started is False
        provider.start()
        assert provider._started is True
        provider.stop()
        assert provider._started is False


# ---------------------------------------------------------------------------
# LayerRegistry tests
# ---------------------------------------------------------------------------

class TestLayerRegistry:
    """Test the LayerRegistry."""

    def test_register_layer(self):
        reg = LayerRegistry()
        reg.register_layer("test.provider", "AIS Vessels", "point")
        layers = reg.list_layers()
        assert len(layers) == 1
        assert layers[0]["layer_name"] == "AIS Vessels"
        assert layers[0]["provider_id"] == "test.provider"
        assert layers[0]["layer_type"] == "point"
        assert layers[0]["visible"] is True

    def test_register_duplicate_raises(self):
        reg = LayerRegistry()
        reg.register_layer("p1", "Layer A", "point")
        with pytest.raises(ValueError, match="already registered"):
            reg.register_layer("p2", "Layer A", "line")

    def test_unregister_layer(self):
        reg = LayerRegistry()
        reg.register_layer("p1", "Layer A", "point")
        assert reg.unregister_layer("Layer A") is True
        assert reg.unregister_layer("Layer A") is False
        assert len(reg.list_layers()) == 0

    def test_toggle_layer(self):
        reg = LayerRegistry()
        reg.register_layer("p1", "Layer A", "point", default_visible=True)
        reg.toggle_layer("Layer A", False)
        layers = reg.list_layers()
        assert layers[0]["visible"] is False

    def test_toggle_missing_raises(self):
        reg = LayerRegistry()
        with pytest.raises(KeyError, match="Layer not found"):
            reg.toggle_layer("nonexistent", True)

    def test_list_multiple_layers(self):
        reg = LayerRegistry()
        reg.register_layer("p1", "Layer A", "point")
        reg.register_layer("p2", "Layer B", "polygon", default_visible=False)
        layers = reg.list_layers()
        assert len(layers) == 2
        names = {l["layer_name"] for l in layers}
        assert names == {"Layer A", "Layer B"}

    @pytest.mark.asyncio
    async def test_get_layer_data(self):
        items = [
            DataItem(
                item_id="v1",
                data_type="vessel",
                geometry={"lat": 37.7, "lng": -122.0},
                source="test.ais",
            )
        ]
        provider = MockProvider(items=items)
        reg = LayerRegistry()
        reg.register_layer(
            "test.mock-provider", "AIS", "point", provider=provider
        )
        data = await reg.get_layer_data("AIS")
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 1
        feat = data["features"][0]
        assert feat["type"] == "Feature"
        assert feat["geometry"]["type"] == "Point"
        assert feat["geometry"]["coordinates"] == [-122.0, 37.7]
        assert feat["properties"]["item_id"] == "v1"
        assert feat["properties"]["source"] == "test.ais"

    @pytest.mark.asyncio
    async def test_get_layer_data_missing_raises(self):
        reg = LayerRegistry()
        with pytest.raises(KeyError):
            await reg.get_layer_data("nonexistent")

    @pytest.mark.asyncio
    async def test_get_layer_data_no_provider_raises(self):
        reg = LayerRegistry()
        reg.register_layer("p1", "Layer A", "point", provider=None)
        with pytest.raises(RuntimeError, match="no provider"):
            await reg.get_layer_data("Layer A")

    @pytest.mark.asyncio
    async def test_get_layer_data_with_bounds(self):
        items = [
            DataItem(
                item_id="in",
                data_type="vessel",
                geometry={"lat": 37.7, "lng": -122.0},
            ),
            DataItem(
                item_id="out",
                data_type="vessel",
                geometry={"lat": 40.0, "lng": -100.0},
            ),
        ]
        provider = MockProvider(items=items)
        reg = LayerRegistry()
        reg.register_layer(
            "test.mock-provider", "AIS", "point", provider=provider
        )
        bounds = Bounds(south=37.0, west=-123.0, north=38.0, east=-121.0)
        data = await reg.get_layer_data("AIS", bounds=bounds)
        assert len(data["features"]) == 1
        assert data["features"][0]["properties"]["item_id"] == "in"

    def test_get_layer(self):
        reg = LayerRegistry()
        reg.register_layer("p1", "Layer A", "point")
        layer = reg.get_layer("Layer A")
        assert layer is not None
        assert isinstance(layer, RegisteredLayer)
        assert reg.get_layer("nonexistent") is None

    def test_register_with_metadata(self):
        reg = LayerRegistry()
        reg.register_layer(
            "p1", "Layer A", "point",
            metadata={"color": "#ff0000", "icon": "ship"},
        )
        layers = reg.list_layers()
        assert layers[0]["metadata"]["color"] == "#ff0000"


# ---------------------------------------------------------------------------
# GeoJSON conversion tests
# ---------------------------------------------------------------------------

class TestDataItemToFeature:
    """Test _data_item_to_feature helper."""

    def test_point_feature(self):
        item = DataItem(
            item_id="p1",
            data_type="vessel",
            geometry={"lat": 37.7, "lng": -122.0},
            source="test",
            confidence=0.9,
        )
        feat = _data_item_to_feature(item)
        assert feat["type"] == "Feature"
        assert feat["geometry"]["type"] == "Point"
        assert feat["geometry"]["coordinates"] == [-122.0, 37.7]
        assert feat["properties"]["confidence"] == 0.9

    def test_polygon_feature(self):
        item = DataItem(
            item_id="poly1",
            data_type="zone",
            geometry={
                "polygon": [[37.0, -122.0], [37.1, -122.0], [37.1, -121.9]],
            },
        )
        feat = _data_item_to_feature(item)
        assert feat["geometry"]["type"] == "Polygon"
        # Polygon coords are [lng, lat] in GeoJSON
        assert feat["geometry"]["coordinates"][0][0] == [-122.0, 37.0]

    def test_empty_geometry(self):
        item = DataItem(
            item_id="empty",
            data_type="unknown",
            geometry={},
        )
        feat = _data_item_to_feature(item)
        assert feat["geometry"]["coordinates"] == [0, 0]


# ---------------------------------------------------------------------------
# Layers API router tests
# ---------------------------------------------------------------------------

class TestLayersAPI:
    """Test the /api/layers FastAPI router."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers.layers import router, set_registry

        app = FastAPI()
        app.include_router(router)

        # Fresh registry for each test
        reg = LayerRegistry()
        items = [
            DataItem(
                item_id="v1",
                data_type="vessel",
                geometry={"lat": 37.7, "lng": -122.0},
                source="test.ais",
            )
        ]
        provider = MockProvider(items=items)
        reg.register_layer(
            "test.ais", "AIS Vessels", "point", provider=provider
        )
        reg.register_layer(
            "test.weather", "Weather", "polygon", default_visible=False
        )
        set_registry(reg)

        yield TestClient(app)

    def test_list_layers(self, client):
        resp = client.get("/api/layers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {l["layer_name"] for l in data}
        assert "AIS Vessels" in names

    def test_toggle_layer(self, client):
        resp = client.post(
            "/api/layers/AIS Vessels/toggle",
            json={"visible": False},
        )
        assert resp.status_code == 200
        assert resp.json()["visible"] is False

    def test_toggle_missing_layer(self, client):
        resp = client.post(
            "/api/layers/nonexistent/toggle",
            json={"visible": True},
        )
        assert resp.status_code == 404

    def test_get_layer_data(self, client):
        resp = client.get("/api/layers/AIS Vessels/data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 1

    def test_get_layer_data_with_bounds(self, client):
        resp = client.get(
            "/api/layers/AIS Vessels/data",
            params={"south": 37.0, "west": -123.0, "north": 38.0, "east": -121.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["features"]) == 1

    def test_get_layer_data_bounds_filter_out(self, client):
        resp = client.get(
            "/api/layers/AIS Vessels/data",
            params={"south": 40.0, "west": -80.0, "north": 41.0, "east": -79.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["features"]) == 0

    def test_get_missing_layer_data(self, client):
        resp = client.get("/api/layers/nonexistent/data")
        assert resp.status_code == 404

    def test_get_layer_data_no_provider(self, client):
        # Weather layer has no provider attached
        resp = client.get("/api/layers/Weather/data")
        assert resp.status_code == 500
