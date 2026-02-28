# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the geodata router -- GIS layer proxy with disk cache.

Tests all /api/geo/layers/* endpoints, cache helpers, fetch logic,
catalog endpoint, and error paths.  Uses mocked HTTP and tempfile caches
so no external network calls are made.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.geodata import (
    _LAYERS,
    _cache_is_fresh,
    _cache_path,
    _read_cache,
    _write_cache,
    router,
)


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


# Reusable fake GeoJSON feature collections
_FAKE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-121.9, 37.7]},
            "properties": {"name": "Test Feature"},
        }
    ],
}

_EMPTY_FC = {"type": "FeatureCollection", "features": []}


def _mock_httpx_client(response_json=None, status_code=200, raise_error=None):
    """Create a mock httpx.AsyncClient with controllable responses."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=response_json or _FAKE_GEOJSON)

    mock_client = AsyncMock()
    if raise_error:
        mock_client.get = AsyncMock(side_effect=raise_error)
    else:
        mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCacheHelpers:
    """Test the disk-cache helper functions directly."""

    def test_cache_path_returns_geojson_file(self):
        """_cache_path returns a .geojson file inside the cache dir."""
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            with patch("app.routers.geodata._CACHE_DIR", cache_dir):
                p = _cache_path("streams")
                assert p.name == "streams.geojson"
                assert "geodata" in str(p) or str(p).startswith(str(cache_dir))

    def test_cache_is_fresh_missing_file(self):
        """Non-existent file is not fresh."""
        p = Path("/tmp/nonexistent_test_geodata_xyz.geojson")
        assert _cache_is_fresh(p) is False

    def test_cache_is_fresh_recent_file(self):
        """Recently written file is fresh."""
        with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as f:
            f.write(b"{}")
            path = Path(f.name)
        try:
            assert _cache_is_fresh(path) is True
        finally:
            path.unlink()

    def test_cache_is_fresh_stale_file(self):
        """File older than 24h is NOT fresh."""
        with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as f:
            f.write(b"{}")
            path = Path(f.name)
        try:
            # Backdate the file by 25 hours
            import os
            old_time = time.time() - 90000
            os.utime(path, (old_time, old_time))
            assert _cache_is_fresh(path) is False
        finally:
            path.unlink()

    def test_read_cache_valid_json(self):
        """_read_cache returns parsed dict for valid JSON."""
        with tempfile.NamedTemporaryFile(
            suffix=".geojson", mode="w", delete=False
        ) as f:
            json.dump(_FAKE_GEOJSON, f)
            path = Path(f.name)
        try:
            result = _read_cache(path)
            assert result is not None
            assert result["type"] == "FeatureCollection"
            assert len(result["features"]) == 1
        finally:
            path.unlink()

    def test_read_cache_corrupt_json(self):
        """_read_cache returns None for corrupt JSON."""
        with tempfile.NamedTemporaryFile(
            suffix=".geojson", mode="w", delete=False
        ) as f:
            f.write("NOT VALID JSON {{{")
            path = Path(f.name)
        try:
            assert _read_cache(path) is None
        finally:
            path.unlink()

    def test_read_cache_missing_file(self):
        """_read_cache returns None for non-existent file."""
        path = Path("/tmp/nonexistent_test_geodata_read_xyz.geojson")
        assert _read_cache(path) is None

    def test_write_cache_creates_dirs(self):
        """_write_cache creates parent directories if needed."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sub" / "dir" / "test.geojson"
            _write_cache(path, _FAKE_GEOJSON)
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["type"] == "FeatureCollection"

    def test_write_cache_overwrites(self):
        """_write_cache overwrites existing file."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.geojson"
            _write_cache(path, {"type": "FeatureCollection", "features": []})
            _write_cache(path, _FAKE_GEOJSON)
            data = json.loads(path.read_text())
            assert len(data["features"]) == 1


# ---------------------------------------------------------------------------
# Layer catalog
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLayerDefinitions:
    """Verify the _LAYERS constant is well-formed."""

    def test_all_layers_have_required_keys(self):
        for layer_id, defn in _LAYERS.items():
            assert "name" in defn, f"{layer_id} missing 'name'"
            assert "type" in defn, f"{layer_id} missing 'type'"
            assert "color" in defn, f"{layer_id} missing 'color'"
            assert "urls" in defn, f"{layer_id} missing 'urls'"
            assert isinstance(defn["urls"], list)
            assert len(defn["urls"]) >= 1

    def test_known_layers_present(self):
        expected = {
            "streams", "water", "traffic-signals", "parks",
            "schools", "fire-stations", "street-lights", "trees", "parcels",
        }
        assert expected == set(_LAYERS.keys())

    def test_geometry_types_valid(self):
        valid_types = {"point", "line", "polygon"}
        for layer_id, defn in _LAYERS.items():
            assert defn["type"] in valid_types, f"{layer_id} has invalid type"

    def test_colors_are_hex(self):
        for layer_id, defn in _LAYERS.items():
            assert defn["color"].startswith("#"), f"{layer_id} color not hex"


# ---------------------------------------------------------------------------
# Catalog endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCatalogEndpoint:
    """GET /api/geo/layers/catalog — layer listing."""

    def test_catalog_returns_all_layers(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/catalog")
                assert resp.status_code == 200
                data = resp.json()
                assert isinstance(data, list)
                assert len(data) == len(_LAYERS)

    def test_catalog_entry_fields(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/catalog")
                data = resp.json()
                for entry in data:
                    assert "id" in entry
                    assert "name" in entry
                    assert "type" in entry
                    assert "color" in entry
                    assert "cached" in entry
                    assert "fresh" in entry
                    assert "feature_count" in entry
                    assert "endpoint" in entry

    def test_catalog_no_cache_shows_not_cached(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/catalog")
                data = resp.json()
                for entry in data:
                    assert entry["cached"] is False
                    assert entry["fresh"] is False
                    assert entry["feature_count"] == 0

    def test_catalog_with_cached_layer(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            # Pre-populate the streams cache
            cache_file = cache_dir / "streams.geojson"
            cache_file.write_text(json.dumps(_FAKE_GEOJSON))
            with patch("app.routers.geodata._CACHE_DIR", cache_dir):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/catalog")
                data = resp.json()
                streams = [e for e in data if e["id"] == "streams"][0]
                assert streams["cached"] is True
                assert streams["fresh"] is True
                assert streams["feature_count"] == 1

    def test_catalog_with_stale_cache(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            cache_file = cache_dir / "parks.geojson"
            cache_file.write_text(json.dumps(_FAKE_GEOJSON))
            # Backdate to make it stale
            old_time = time.time() - 90000
            os.utime(cache_file, (old_time, old_time))
            with patch("app.routers.geodata._CACHE_DIR", cache_dir):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/catalog")
                data = resp.json()
                parks = [e for e in data if e["id"] == "parks"][0]
                assert parks["cached"] is True
                assert parks["fresh"] is False
                assert parks["feature_count"] == 1

    def test_catalog_endpoints_match_layer_ids(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/catalog")
                data = resp.json()
                for entry in data:
                    expected_endpoint = f"/api/geo/layers/{entry['id']}"
                    assert entry["endpoint"] == expected_endpoint


# ---------------------------------------------------------------------------
# Individual layer endpoints — cache hit path
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLayerEndpointsCacheHit:
    """Each layer endpoint should serve from cache when fresh data exists."""

    _ALL_LAYER_ENDPOINTS = [
        "streams", "water", "traffic-signals", "parks",
        "schools", "fire-stations", "street-lights", "trees", "parcels",
    ]

    @pytest.mark.parametrize("layer_id", _ALL_LAYER_ENDPOINTS)
    def test_layer_served_from_cache(self, layer_id):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            cache_file = cache_dir / f"{layer_id}.geojson"
            cache_file.write_text(json.dumps(_FAKE_GEOJSON))
            with patch("app.routers.geodata._CACHE_DIR", cache_dir):
                client = TestClient(_make_app())
                resp = client.get(f"/api/geo/layers/{layer_id}")
                assert resp.status_code == 200
                data = resp.json()
                assert data["type"] == "FeatureCollection"
                assert len(data["features"]) == 1


# ---------------------------------------------------------------------------
# Individual layer endpoints — cache miss (fetch from ArcGIS)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLayerEndpointsCacheMiss:
    """When no cache exists, the endpoint fetches from ArcGIS and caches."""

    def test_streams_fetches_and_caches(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            mock_client = _mock_httpx_client(_FAKE_GEOJSON)
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/streams")
                assert resp.status_code == 200
                data = resp.json()
                assert data["type"] == "FeatureCollection"
                assert len(data["features"]) == 1
                # Verify data was cached
                cache_file = cache_dir / "streams.geojson"
                assert cache_file.exists()

    def test_water_fetches_multiple_urls(self):
        """Water layer has 2 URLs; both should be fetched and features merged."""
        feat1 = {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[-121.9, 37.7]]},
            "properties": {"name": "Stream A"},
        }
        feat2 = {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[-121.85, 37.72]]},
            "properties": {"name": "Lake B"},
        }
        fc1 = {"type": "FeatureCollection", "features": [feat1]}
        fc2 = {"type": "FeatureCollection", "features": [feat2]}

        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            if call_count == 0:
                mock_resp.json = MagicMock(return_value=fc1)
            else:
                mock_resp.json = MagicMock(return_value=fc2)
            call_count += 1
            return mock_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_side_effect)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/water")
                assert resp.status_code == 200
                data = resp.json()
                assert data["type"] == "FeatureCollection"
                # Should have merged features from both URLs
                assert len(data["features"]) == 2

    def test_stale_cache_triggers_refetch(self):
        """Stale cache (>24h) should trigger a fresh fetch."""
        import os
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            cache_file = cache_dir / "parks.geojson"
            cache_file.write_text(json.dumps(_EMPTY_FC))
            # Backdate
            old_time = time.time() - 90000
            os.utime(cache_file, (old_time, old_time))

            mock_client = _mock_httpx_client(_FAKE_GEOJSON)
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/parks")
                assert resp.status_code == 200
                data = resp.json()
                # Should have fetched new data (1 feature), not stale (0)
                assert len(data["features"]) == 1


# ---------------------------------------------------------------------------
# Fetch error handling
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFetchErrors:
    """Verify graceful degradation when ArcGIS is unreachable or returns errors."""

    def test_http_error_returns_empty_collection(self):
        """HTTP error from ArcGIS should return empty FeatureCollection."""
        import httpx
        mock_req = httpx.Request("GET", "https://example.com")
        mock_response = httpx.Response(503, request=mock_req)
        error = httpx.HTTPStatusError("503", request=mock_req, response=mock_response)

        mock_client = _mock_httpx_client(raise_error=error)
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/streams")
                assert resp.status_code == 200
                data = resp.json()
                assert data["type"] == "FeatureCollection"
                assert data["features"] == []

    def test_timeout_returns_empty_collection(self):
        """Network timeout should return empty FeatureCollection."""
        import httpx
        mock_req = httpx.Request("GET", "https://example.com")
        error = httpx.ReadTimeout("timed out", request=mock_req)

        mock_client = _mock_httpx_client(raise_error=error)
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/schools")
                assert resp.status_code == 200
                data = resp.json()
                assert data["features"] == []

    def test_arcgis_error_object_skipped(self):
        """ArcGIS sometimes returns an error object instead of GeoJSON."""
        error_response = {"error": {"code": 400, "message": "Invalid query"}}
        mock_client = _mock_httpx_client(error_response)
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/fire-stations")
                assert resp.status_code == 200
                data = resp.json()
                assert data["features"] == []

    def test_json_decode_error_returns_empty(self):
        """Invalid JSON response should not crash, returns empty collection."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(side_effect=json.JSONDecodeError("err", "", 0))

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/trees")
                assert resp.status_code == 200
                data = resp.json()
                assert data["features"] == []

    def test_unknown_layer_returns_empty(self):
        """Requesting a non-existent layer should return empty collection."""
        # _get_layer returns _EMPTY_FC for unknown layer IDs, but the
        # router only has specific endpoints.  However we test _get_layer
        # behavior directly through a known layer with missing definition.
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata._LAYERS", {}):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/streams")
                assert resp.status_code == 200
                data = resp.json()
                assert data["type"] == "FeatureCollection"
                assert data["features"] == []

    def test_partial_failure_keeps_good_features(self):
        """When one URL fails and another succeeds, keep the good features."""
        import httpx

        good_resp = MagicMock()
        good_resp.raise_for_status = MagicMock()
        good_resp.json = MagicMock(return_value=_FAKE_GEOJSON)

        mock_req = httpx.Request("GET", "https://example.com")
        error = httpx.ReadTimeout("timeout", request=mock_req)

        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise error
            return good_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_side_effect)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                # Water layer has 2 URLs
                resp = client.get("/api/geo/layers/water")
                assert resp.status_code == 200
                data = resp.json()
                # First URL failed, second succeeded: 1 feature
                assert len(data["features"]) == 1


# ---------------------------------------------------------------------------
# Cache miss writes to disk
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCacheWriteBehavior:
    """Verify that fetched data is written to the disk cache."""

    def test_empty_result_is_cached(self):
        """Even empty results should be cached to avoid hammering the server."""
        mock_client = _mock_httpx_client(_EMPTY_FC)
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/parcels")
                assert resp.status_code == 200
                cache_file = cache_dir / "parcels.geojson"
                assert cache_file.exists()
                cached_data = json.loads(cache_file.read_text())
                assert cached_data["features"] == []

    def test_cached_data_matches_response(self):
        """Data written to cache should match the API response."""
        mock_client = _mock_httpx_client(_FAKE_GEOJSON)
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/street-lights")
                response_data = resp.json()
                cache_file = cache_dir / "street-lights.geojson"
                cached_data = json.loads(cache_file.read_text())
                assert cached_data == response_data


# ---------------------------------------------------------------------------
# Corrupt cache handling
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCorruptCache:
    """Verify behavior when cache file exists but is corrupt."""

    def test_corrupt_cache_triggers_refetch(self):
        """Corrupt cached JSON should cause a refetch."""
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            cache_file = cache_dir / "trees.geojson"
            cache_file.write_text("NOT VALID JSON {{{")

            mock_client = _mock_httpx_client(_FAKE_GEOJSON)
            with patch("app.routers.geodata._CACHE_DIR", cache_dir), \
                 patch("app.routers.geodata.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/trees")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["features"]) == 1


# ---------------------------------------------------------------------------
# Response format
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestResponseFormat:
    """Verify GeoJSON response structure is correct."""

    def test_response_is_feature_collection(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            cache_file = cache_dir / "streams.geojson"
            cache_file.write_text(json.dumps(_FAKE_GEOJSON))
            with patch("app.routers.geodata._CACHE_DIR", cache_dir):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/streams")
                data = resp.json()
                assert data["type"] == "FeatureCollection"
                assert isinstance(data["features"], list)

    def test_catalog_is_list(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "geodata"
            cache_dir.mkdir()
            with patch("app.routers.geodata._CACHE_DIR", cache_dir):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/layers/catalog")
                data = resp.json()
                assert isinstance(data, list)
