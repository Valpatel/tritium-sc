# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for geo cache management: TTL expiry, .tmp cleanup, stats, and clear."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.geo import (
    _cache_fresh,
    _CACHE_TTL_S,
    cleanup_orphaned_tmp_files,
    router,
)


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# _cache_fresh helper
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCacheFresh:
    """Test the _cache_fresh TTL helper."""

    def test_missing_file_returns_false(self, tmp_path):
        assert _cache_fresh(tmp_path / "nonexistent.json") is False

    def test_fresh_file_returns_true(self, tmp_path):
        f = tmp_path / "fresh.json"
        f.write_text("{}")
        assert _cache_fresh(f) is True

    def test_expired_file_returns_false(self, tmp_path):
        f = tmp_path / "old.json"
        f.write_text("{}")
        # Set mtime to 25 hours ago
        expired_time = time.time() - (_CACHE_TTL_S + 3600)
        import os
        os.utime(f, (expired_time, expired_time))
        assert _cache_fresh(f) is False

    def test_boundary_fresh(self, tmp_path):
        f = tmp_path / "edge.json"
        f.write_text("{}")
        # Set mtime to 23 hours ago (within TTL)
        recent_time = time.time() - (_CACHE_TTL_S - 3600)
        import os
        os.utime(f, (recent_time, recent_time))
        assert _cache_fresh(f) is True


# ---------------------------------------------------------------------------
# cleanup_orphaned_tmp_files
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCleanupTmpFiles:
    """Test orphaned .tmp file cleanup."""

    def test_no_cache_dir(self, tmp_path):
        with patch("app.routers.geo._GIS_CACHE", tmp_path / "nonexistent"):
            assert cleanup_orphaned_tmp_files() == 0

    def test_no_tmp_files(self, tmp_path):
        cache_dir = tmp_path / "gis"
        cache_dir.mkdir()
        (cache_dir / "data.json").write_text("{}")
        with patch("app.routers.geo._GIS_CACHE", cache_dir):
            assert cleanup_orphaned_tmp_files() == 0

    def test_removes_tmp_files(self, tmp_path):
        cache_dir = tmp_path / "gis"
        cache_dir.mkdir()
        (cache_dir / "a.tmp").write_text("partial")
        (cache_dir / "b.tmp").write_text("partial")
        (cache_dir / "data.json").write_text("{}")
        with patch("app.routers.geo._GIS_CACHE", cache_dir):
            deleted = cleanup_orphaned_tmp_files()
        assert deleted == 2
        assert not (cache_dir / "a.tmp").exists()
        assert not (cache_dir / "b.tmp").exists()
        assert (cache_dir / "data.json").exists()


# ---------------------------------------------------------------------------
# Cache stats endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCacheStats:
    """Test GET /api/geo/cache/stats endpoint."""

    def test_empty_cache(self, tmp_path):
        with (
            patch("app.routers.geo._GEOCODE_CACHE", tmp_path / "geocode"),
            patch("app.routers.geo._BUILDINGS_CACHE", tmp_path / "buildings"),
            patch("app.routers.geo._GIS_CACHE", tmp_path / "gis"),
            patch("app.routers.geo._MSFT_CACHE", tmp_path / "msft"),
            patch("app.routers.geo._TILE_CACHE", tmp_path / "tiles"),
        ):
            client = TestClient(_make_app())
            resp = client.get("/api/geo/cache/stats")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_files"] == 0
            assert data["total_size_mb"] == 0.0
            assert data["expired_count"] == 0

    def test_with_files(self, tmp_path):
        gis = tmp_path / "gis"
        gis.mkdir()
        (gis / "a.json").write_text('{"test": true}')
        (gis / "b.json").write_text('{"test": false}')
        with (
            patch("app.routers.geo._GEOCODE_CACHE", tmp_path / "geocode"),
            patch("app.routers.geo._BUILDINGS_CACHE", tmp_path / "buildings"),
            patch("app.routers.geo._GIS_CACHE", gis),
            patch("app.routers.geo._MSFT_CACHE", tmp_path / "msft"),
            patch("app.routers.geo._TILE_CACHE", tmp_path / "tiles"),
        ):
            client = TestClient(_make_app())
            resp = client.get("/api/geo/cache/stats")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_files"] == 2
            assert data["total_size_mb"] >= 0

    def test_counts_expired(self, tmp_path):
        import os
        gis = tmp_path / "gis"
        gis.mkdir()
        f = gis / "expired.json"
        f.write_text("{}")
        expired_time = time.time() - (_CACHE_TTL_S + 3600)
        os.utime(f, (expired_time, expired_time))
        with (
            patch("app.routers.geo._GEOCODE_CACHE", tmp_path / "geocode"),
            patch("app.routers.geo._BUILDINGS_CACHE", tmp_path / "buildings"),
            patch("app.routers.geo._GIS_CACHE", gis),
            patch("app.routers.geo._MSFT_CACHE", tmp_path / "msft"),
            patch("app.routers.geo._TILE_CACHE", tmp_path / "tiles"),
        ):
            client = TestClient(_make_app())
            resp = client.get("/api/geo/cache/stats")
            data = resp.json()
            assert data["expired_count"] == 1


# ---------------------------------------------------------------------------
# Cache clear endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCacheClear:
    """Test POST /api/geo/cache/clear endpoint."""

    def test_clear_empty(self, tmp_path):
        with (
            patch("app.routers.geo._GEOCODE_CACHE", tmp_path / "geocode"),
            patch("app.routers.geo._BUILDINGS_CACHE", tmp_path / "buildings"),
            patch("app.routers.geo._GIS_CACHE", tmp_path / "gis"),
            patch("app.routers.geo._MSFT_CACHE", tmp_path / "msft"),
            patch("app.routers.geo._TILE_CACHE", tmp_path / "tiles"),
        ):
            client = TestClient(_make_app())
            resp = client.post("/api/geo/cache/clear")
            assert resp.status_code == 200
            data = resp.json()
            assert data["files_deleted"] == 0
            assert data["bytes_freed"] == 0

    def test_clear_removes_files(self, tmp_path):
        gis = tmp_path / "gis"
        gis.mkdir()
        (gis / "a.json").write_text('{"data": "test"}')
        (gis / "b.json").write_text('{"data": "test2"}')
        with (
            patch("app.routers.geo._GEOCODE_CACHE", tmp_path / "geocode"),
            patch("app.routers.geo._BUILDINGS_CACHE", tmp_path / "buildings"),
            patch("app.routers.geo._GIS_CACHE", gis),
            patch("app.routers.geo._MSFT_CACHE", tmp_path / "msft"),
            patch("app.routers.geo._TILE_CACHE", tmp_path / "tiles"),
        ):
            client = TestClient(_make_app())
            resp = client.post("/api/geo/cache/clear")
            data = resp.json()
            assert data["files_deleted"] == 2
            assert data["bytes_freed"] > 0
            # Verify files are gone
            assert len(list(gis.iterdir())) == 0
