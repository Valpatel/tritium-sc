# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for annotation persistence and GeoJSON import/export."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

_tmpdir = tempfile.mkdtemp()
os.environ["TRITIUM_DATA_DIR"] = _tmpdir

from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.routers.annotations import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_db():
    import app.routers.annotations as ann
    ann._db_initialized = False
    ann._DB_PATH = None
    os.environ["TRITIUM_DATA_DIR"] = tempfile.mkdtemp()
    yield


class TestAnnotationPersistence:
    def test_create_and_list(self):
        resp = client.post("/api/annotations", json={
            "type": "text",
            "lat": 30.0,
            "lng": -97.0,
            "text": "Test marker",
        })
        assert resp.status_code == 200
        ann = resp.json()
        assert ann["id"].startswith("ann_")
        assert ann["text"] == "Test marker"

        resp = client.get("/api/annotations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_update_annotation(self):
        create = client.post("/api/annotations", json={
            "type": "text", "lat": 30.0, "lng": -97.0, "text": "Original",
        }).json()
        aid = create["id"]
        resp = client.put(f"/api/annotations/{aid}", json={"text": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["text"] == "Updated"

    def test_delete_annotation(self):
        create = client.post("/api/annotations", json={
            "type": "circle", "lat": 30.0, "lng": -97.0, "radius_m": 50,
        }).json()
        aid = create["id"]
        resp = client.delete(f"/api/annotations/{aid}")
        assert resp.status_code == 200
        resp = client.get(f"/api/annotations/{aid}")
        assert resp.status_code == 404

    def test_locked_annotation_cannot_update(self):
        create = client.post("/api/annotations", json={
            "type": "text", "lat": 30.0, "lng": -97.0, "locked": True,
        }).json()
        aid = create["id"]
        resp = client.put(f"/api/annotations/{aid}", json={"text": "Nope"})
        assert resp.status_code == 403

    def test_filter_by_layer(self):
        client.post("/api/annotations", json={
            "type": "text", "lat": 30.0, "lng": -97.0, "layer": "ops",
        })
        client.post("/api/annotations", json={
            "type": "text", "lat": 31.0, "lng": -98.0, "layer": "intel",
        })
        resp = client.get("/api/annotations?layer=ops")
        assert resp.json()["count"] == 1

    def test_clear_layer(self):
        client.post("/api/annotations", json={
            "type": "text", "lat": 30.0, "lng": -97.0, "layer": "temp",
        })
        client.post("/api/annotations", json={
            "type": "text", "lat": 31.0, "lng": -98.0, "layer": "keep",
        })
        resp = client.delete("/api/annotations?layer=temp")
        assert resp.json()["deleted_count"] == 1
        resp = client.get("/api/annotations")
        assert resp.json()["count"] == 1


class TestGeoJSONExportImport:
    def test_export_geojson(self):
        client.post("/api/annotations", json={
            "type": "text", "lat": 30.0, "lng": -97.0, "text": "HQ",
        })
        client.post("/api/annotations", json={
            "type": "circle", "lat": 30.1, "lng": -97.1, "radius_m": 100,
        })
        resp = client.get("/api/annotations/export/geojson")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 2
        # Text annotation should be a Point
        text_feat = [f for f in data["features"] if f["properties"]["annotation_type"] == "text"][0]
        assert text_feat["geometry"]["type"] == "Point"
        assert text_feat["geometry"]["coordinates"] == [-97.0, 30.0]

    def test_import_geojson(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-97.0, 30.0]},
                    "properties": {
                        "annotation_type": "text",
                        "text": "Imported marker",
                        "color": "#ff2a6d",
                        "layer": "imported",
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-97.0, 30.0], [-97.1, 30.1]],
                    },
                    "properties": {
                        "annotation_type": "arrow",
                    },
                },
            ],
        }
        content = json.dumps(geojson).encode()
        resp = client.post(
            "/api/annotations/import/geojson",
            files={"file": ("test.geojson", content, "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 2

        # Verify imported annotations exist
        resp = client.get("/api/annotations")
        assert resp.json()["count"] == 2

    def test_roundtrip_geojson(self):
        """Export then import should preserve annotations."""
        client.post("/api/annotations", json={
            "type": "text", "lat": 30.0, "lng": -97.0, "text": "HQ",
            "color": "#05ffa1",
        })
        # Export
        exported = client.get("/api/annotations/export/geojson").json()
        # Clear
        client.delete("/api/annotations")
        assert client.get("/api/annotations").json()["count"] == 0
        # Import
        content = json.dumps(exported).encode()
        resp = client.post(
            "/api/annotations/import/geojson",
            files={"file": ("test.geojson", content, "application/json")},
        )
        assert resp.json()["imported"] == 1
        # Verify
        anns = client.get("/api/annotations").json()["annotations"]
        assert len(anns) == 1
        assert anns[0]["text"] == "HQ"
