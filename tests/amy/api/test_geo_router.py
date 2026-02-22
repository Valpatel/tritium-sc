"""Unit tests for the geo router — geocoding, satellite tiles, building footprints.

Tests Pydantic models, cache logic, tile zoom validation, and endpoints
with mocked HTTP responses (no external API calls).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.routers.geo import (
    GeocodeRequest,
    GeocodeResponse,
    BuildingPolygon,
    SetReferenceRequest,
    router,
)


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGeoModels:
    """Validate geo request/response models."""

    def test_geocode_request(self):
        r = GeocodeRequest(address="123 Main St")
        assert r.address == "123 Main St"

    def test_geocode_request_missing(self):
        with pytest.raises(ValidationError):
            GeocodeRequest()

    def test_geocode_response(self):
        r = GeocodeResponse(
            lat=37.7749, lng=-122.4194,
            display_name="San Francisco, CA",
            bbox=[37.7, -122.5, 37.8, -122.4],
        )
        assert r.lat == pytest.approx(37.7749)
        assert len(r.bbox) == 4

    def test_building_polygon(self):
        b = BuildingPolygon(
            id=12345,
            polygon=[[37.77, -122.41], [37.77, -122.42], [37.78, -122.42]],
            tags={"building": "yes", "height": "10"},
        )
        assert b.id == 12345
        assert len(b.polygon) == 3

    def test_set_reference_request_defaults(self):
        r = SetReferenceRequest(lat=37.7749, lng=-122.4194)
        assert r.alt == 0.0

    def test_set_reference_request_with_alt(self):
        r = SetReferenceRequest(lat=37.7749, lng=-122.4194, alt=50.0)
        assert r.alt == 50.0


# ---------------------------------------------------------------------------
# Tile Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTileEndpoint:
    """GET /api/geo/tile/{z}/{x}/{y} — satellite tile proxy."""

    def test_invalid_zoom_low(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/tile/-1/0/0")
        assert resp.status_code == 400
        assert "Zoom" in resp.json()["detail"]

    def test_invalid_zoom_high(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/tile/23/0/0")
        assert resp.status_code == 400

    def test_cached_tile_served(self):
        """If tile is in disk cache, serve it directly."""
        with tempfile.TemporaryDirectory() as td:
            tile_cache = Path(td) / "tiles"
            tile_path = tile_cache / "10" / "163" / "395.jpg"
            tile_path.parent.mkdir(parents=True)
            tile_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)
            with patch("app.routers.geo._TILE_CACHE", tile_cache):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/tile/10/163/395")
                assert resp.status_code == 200
                assert resp.headers["content-type"] == "image/jpeg"

    def test_tile_fetch_failure(self):
        """When ESRI is down, return 502."""
        import httpx
        with tempfile.TemporaryDirectory() as td:
            tile_cache = Path(td) / "tiles"
            tile_cache.mkdir()
            mock_req = httpx.Request("GET", "https://example.com")
            mock_response = httpx.Response(503, request=mock_req)

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
                "503", request=mock_req, response=mock_response,
            ))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._TILE_CACHE", tile_cache), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/tile/10/163/395")
                assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Geocode Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGeocodeEndpoint:
    """POST /api/geo/geocode — address lookup."""

    def test_empty_address(self):
        client = TestClient(_make_app())
        resp = client.post("/api/geo/geocode", json={"address": ""})
        assert resp.status_code == 400

    def test_whitespace_address(self):
        client = TestClient(_make_app())
        resp = client.post("/api/geo/geocode", json={"address": "   "})
        assert resp.status_code == 400

    def test_cached_geocode(self):
        """Serve from disk cache if available."""
        with tempfile.TemporaryDirectory() as td:
            geocode_cache = Path(td) / "geocode"
            geocode_cache.mkdir()
            # Pre-populate cache
            import hashlib
            key = hashlib.sha256("123 main st".encode()).hexdigest()
            cache_data = {
                "lat": 37.7749, "lng": -122.4194,
                "display_name": "123 Main St, SF",
                "bbox": [37.7, -122.5, 37.8, -122.4],
            }
            (geocode_cache / f"{key}.json").write_text(json.dumps(cache_data))
            with patch("app.routers.geo._GEOCODE_CACHE", geocode_cache):
                client = TestClient(_make_app())
                resp = client.post("/api/geo/geocode", json={"address": "123 Main St"})
                assert resp.status_code == 200
                data = resp.json()
                assert data["lat"] == pytest.approx(37.7749)
                assert data["display_name"] == "123 Main St, SF"

    def test_geocode_not_found(self):
        """Nominatim returns empty results."""
        with tempfile.TemporaryDirectory() as td:
            geocode_cache = Path(td) / "geocode"
            geocode_cache.mkdir()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=[])  # No results

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            with patch("app.routers.geo._GEOCODE_CACHE", geocode_cache), \
                 patch("app.routers.geo.httpx.AsyncClient", return_value=mock_client):
                client = TestClient(_make_app())
                resp = client.post("/api/geo/geocode", json={"address": "ZZZZZZZ Nonexistent"})
                assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Reference Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestReferenceEndpoint:
    """GET/POST /api/geo/reference — map origin management."""

    def test_get_reference(self):
        mock_ref = MagicMock(lat=37.7749, lng=-122.4194, alt=0.0, initialized=True)
        # The function imports from amy.tactical.geo at call time
        with patch("amy.tactical.geo.get_reference", return_value=mock_ref):
            client = TestClient(_make_app())
            resp = client.get("/api/geo/reference")
            assert resp.status_code == 200
            data = resp.json()
            assert data["lat"] == pytest.approx(37.7749)
            assert data["initialized"] is True

    def test_set_reference(self):
        mock_ref = MagicMock(lat=40.7128, lng=-74.006, alt=10.0, initialized=True)
        with patch("amy.tactical.geo.init_reference", return_value=mock_ref):
            client = TestClient(_make_app())
            resp = client.post("/api/geo/reference", json={
                "lat": 40.7128, "lng": -74.006, "alt": 10.0,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["lat"] == pytest.approx(40.7128)


# ---------------------------------------------------------------------------
# Buildings Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuildingsEndpoint:
    """GET /api/geo/buildings — building footprints."""

    def test_buildings_cached(self):
        with tempfile.TemporaryDirectory() as td:
            buildings_cache = Path(td) / "buildings"
            buildings_cache.mkdir()
            # Pre-populate cache
            import hashlib
            cache_key = f"37.774900_-122.419400_200"
            cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
            buildings = [{"id": 1, "polygon": [[37.77, -122.41]], "tags": {"building": "yes"}}]
            (buildings_cache / f"{cache_hash}.json").write_text(json.dumps(buildings))
            with patch("app.routers.geo._BUILDINGS_CACHE", buildings_cache):
                client = TestClient(_make_app())
                resp = client.get("/api/geo/buildings?lat=37.7749&lng=-122.4194&radius=200")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data) == 1
                assert data[0]["id"] == 1

    def test_buildings_radius_validation(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/buildings?lat=37.77&lng=-122.42&radius=5")
        assert resp.status_code == 422  # Below ge=10

    def test_buildings_required_params(self):
        client = TestClient(_make_app())
        resp = client.get("/api/geo/buildings")
        assert resp.status_code == 422  # Missing lat/lng
