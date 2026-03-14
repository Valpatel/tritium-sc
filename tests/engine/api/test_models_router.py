# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the intelligence models API router."""
import io
import os
import sys
import tempfile

import pytest

# Ensure src is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


@pytest.fixture
def temp_db(tmp_path):
    """Set MODEL_REGISTRY_DB to a temp file."""
    db_path = str(tmp_path / "test_models.db")
    os.environ["MODEL_REGISTRY_DB"] = db_path
    # Reset singleton
    from app.routers import models as models_mod
    if hasattr(models_mod._get_registry, "_instance"):
        delattr(models_mod._get_registry, "_instance")
    yield db_path
    if hasattr(models_mod._get_registry, "_instance"):
        try:
            models_mod._get_registry._instance.close()
        except Exception:
            pass
        delattr(models_mod._get_registry, "_instance")
    os.environ.pop("MODEL_REGISTRY_DB", None)


@pytest.fixture
def client(temp_db):
    """Create test client with temp DB."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.models import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestListModels:
    def test_list_empty(self, client):
        resp = client.get("/api/intelligence/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["models"] == []
        assert data["total"] == 0


class TestImportModel:
    def test_import_model(self, client):
        resp = client.post(
            "/api/intelligence/models/import",
            data={
                "name": "test_model",
                "version": "1.0.0",
                "accuracy": "0.95",
                "training_count": "100",
                "description": "test model",
            },
            files={"file": ("test.pkl", b"model-data-here", "application/octet-stream")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["name"] == "test_model"
        assert data["version"] == "1.0.0"
        assert data["size_bytes"] == len(b"model-data-here")

    def test_import_empty_file(self, client):
        resp = client.post(
            "/api/intelligence/models/import",
            data={"name": "test", "version": "1.0.0"},
            files={"file": ("empty.pkl", b"", "application/octet-stream")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    def test_import_then_list(self, client):
        client.post(
            "/api/intelligence/models/import",
            data={"name": "model_a", "version": "1.0.0"},
            files={"file": ("a.pkl", b"data-a", "application/octet-stream")},
        )
        client.post(
            "/api/intelligence/models/import",
            data={"name": "model_b", "version": "1.0.0"},
            files={"file": ("b.pkl", b"data-b", "application/octet-stream")},
        )
        resp = client.get("/api/intelligence/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2


class TestExportModel:
    def test_export_nonexistent(self, client):
        resp = client.get("/api/intelligence/models/nonexistent/export")
        assert resp.status_code == 404

    def test_import_then_export(self, client):
        model_bytes = b"pickle-model-data-12345"
        client.post(
            "/api/intelligence/models/import",
            data={"name": "exportable", "version": "2.0.0"},
            files={"file": ("model.pkl", model_bytes, "application/octet-stream")},
        )

        resp = client.get("/api/intelligence/models/exportable/export?version=2.0.0")
        assert resp.status_code == 200
        assert resp.content == model_bytes
        assert "attachment" in resp.headers.get("content-disposition", "")


class TestDeleteModel:
    def test_delete_nonexistent(self, client):
        resp = client.delete("/api/intelligence/models/nope/1.0.0")
        assert resp.status_code == 404

    def test_delete_existing(self, client):
        client.post(
            "/api/intelligence/models/import",
            data={"name": "deleteme", "version": "1.0.0"},
            files={"file": ("d.pkl", b"data", "application/octet-stream")},
        )
        resp = client.delete("/api/intelligence/models/deleteme/1.0.0")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify gone
        resp = client.get("/api/intelligence/models/deleteme/export?version=1.0.0")
        assert resp.status_code == 404


class TestModelStats:
    def test_empty_stats(self, client):
        resp = client.get("/api/intelligence/models/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_models"] == 0

    def test_stats_after_import(self, client):
        client.post(
            "/api/intelligence/models/import",
            data={"name": "m", "version": "1.0.0"},
            files={"file": ("m.pkl", b"12345", "application/octet-stream")},
        )
        resp = client.get("/api/intelligence/models/stats")
        data = resp.json()
        assert data["total_models"] == 1
        assert data["total_size_bytes"] == 5
