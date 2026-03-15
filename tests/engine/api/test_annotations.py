# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for map annotations API — uses TestClient for actual endpoint testing.

Wave 93: upgraded from model-only tests to full API endpoint tests using
FastAPI TestClient. Covers CRUD, validation, layers, and edge cases.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.annotations import router, _annotations


@pytest.fixture
def client():
    """Create a TestClient with the annotations router and clean store."""
    _annotations.clear()
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    yield c
    _annotations.clear()


class TestAnnotationsAPI:
    """Test annotation CRUD via actual HTTP endpoints."""

    @pytest.mark.unit
    def test_create_text_annotation(self, client):
        resp = client.post("/api/annotations", json={
            "type": "text",
            "lat": 33.12,
            "lng": -97.45,
            "text": "Rally point Alpha",
            "color": "#ff2a6d",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "text"
        assert data["lat"] == 33.12
        assert data["text"] == "Rally point Alpha"
        assert data["id"].startswith("ann_")

    @pytest.mark.unit
    def test_create_circle_annotation(self, client):
        resp = client.post("/api/annotations", json={
            "type": "circle",
            "lat": 33.12,
            "lng": -97.45,
            "radius_m": 100.0,
            "fill": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "circle"
        assert data["radius_m"] == 100.0
        assert data["fill"] is True

    @pytest.mark.unit
    def test_create_arrow_annotation(self, client):
        resp = client.post("/api/annotations", json={
            "type": "arrow",
            "lat": 33.12,
            "lng": -97.45,
            "end_lat": 33.13,
            "end_lng": -97.44,
            "color": "#05ffa1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "arrow"
        assert data["end_lat"] == 33.13

    @pytest.mark.unit
    def test_create_freehand_annotation(self, client):
        resp = client.post("/api/annotations", json={
            "type": "freehand",
            "lat": 33.12,
            "lng": -97.45,
            "points": [[33.12, -97.45], [33.13, -97.44], [33.14, -97.43]],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "freehand"
        assert len(data["points"]) == 3

    @pytest.mark.unit
    def test_annotation_defaults(self, client):
        resp = client.post("/api/annotations", json={
            "type": "text", "lat": 0, "lng": 0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["color"] == "#00f0ff"
        assert data["stroke_width"] == 2.0
        assert data["opacity"] == 0.8
        assert data["layer"] == "default"
        assert data["locked"] is False

    @pytest.mark.unit
    def test_list_annotations(self, client):
        # Start empty
        resp = client.get("/api/annotations")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

        # Create two
        client.post("/api/annotations", json={"type": "text", "lat": 1, "lng": 1})
        client.post("/api/annotations", json={"type": "circle", "lat": 2, "lng": 2})
        resp = client.get("/api/annotations")
        assert resp.json()["count"] == 2

    @pytest.mark.unit
    def test_get_annotation_by_id(self, client):
        create_resp = client.post("/api/annotations", json={
            "type": "text", "lat": 10, "lng": 20, "text": "Test",
        })
        ann_id = create_resp.json()["id"]

        resp = client.get(f"/api/annotations/{ann_id}")
        assert resp.status_code == 200
        assert resp.json()["text"] == "Test"

    @pytest.mark.unit
    def test_get_annotation_not_found(self, client):
        resp = client.get("/api/annotations/ann_nonexistent")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_update_annotation(self, client):
        create_resp = client.post("/api/annotations", json={
            "type": "text", "lat": 10, "lng": 20, "text": "Original",
        })
        ann_id = create_resp.json()["id"]

        resp = client.put(f"/api/annotations/{ann_id}", json={
            "text": "Updated text", "color": "#ff00ff",
        })
        assert resp.status_code == 200
        assert resp.json()["text"] == "Updated text"
        assert resp.json()["color"] == "#ff00ff"

    @pytest.mark.unit
    def test_update_locked_annotation_rejected(self, client):
        create_resp = client.post("/api/annotations", json={
            "type": "text", "lat": 10, "lng": 20, "locked": True,
        })
        ann_id = create_resp.json()["id"]

        resp = client.put(f"/api/annotations/{ann_id}", json={"text": "Hacked"})
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_update_nonexistent_annotation(self, client):
        resp = client.put("/api/annotations/ann_nope", json={"text": "x"})
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_delete_annotation(self, client):
        create_resp = client.post("/api/annotations", json={
            "type": "text", "lat": 10, "lng": 20,
        })
        ann_id = create_resp.json()["id"]

        resp = client.delete(f"/api/annotations/{ann_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == ann_id

        # Verify gone
        resp = client.get(f"/api/annotations/{ann_id}")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_delete_nonexistent_annotation(self, client):
        resp = client.delete("/api/annotations/ann_nope")
        assert resp.status_code == 404

    @pytest.mark.unit
    def test_clear_all_annotations(self, client):
        client.post("/api/annotations", json={"type": "text", "lat": 1, "lng": 1})
        client.post("/api/annotations", json={"type": "text", "lat": 2, "lng": 2})

        resp = client.delete("/api/annotations")
        assert resp.status_code == 200
        assert resp.json()["deleted_count"] == 2

        resp = client.get("/api/annotations")
        assert resp.json()["count"] == 0

    @pytest.mark.unit
    def test_layer_filtering(self, client):
        client.post("/api/annotations", json={
            "type": "text", "lat": 1, "lng": 1, "layer": "ops",
        })
        client.post("/api/annotations", json={
            "type": "text", "lat": 2, "lng": 2, "layer": "intel",
        })
        client.post("/api/annotations", json={
            "type": "text", "lat": 3, "lng": 3, "layer": "ops",
        })

        resp = client.get("/api/annotations", params={"layer": "ops"})
        assert resp.json()["count"] == 2

        resp = client.get("/api/annotations", params={"layer": "intel"})
        assert resp.json()["count"] == 1

    @pytest.mark.unit
    def test_clear_by_layer(self, client):
        client.post("/api/annotations", json={
            "type": "text", "lat": 1, "lng": 1, "layer": "ops",
        })
        client.post("/api/annotations", json={
            "type": "text", "lat": 2, "lng": 2, "layer": "intel",
        })

        resp = client.delete("/api/annotations", params={"layer": "ops"})
        assert resp.json()["deleted_count"] == 1

        # intel still there
        resp = client.get("/api/annotations")
        assert resp.json()["count"] == 1

    @pytest.mark.unit
    def test_list_layers(self, client):
        client.post("/api/annotations", json={
            "type": "text", "lat": 1, "lng": 1, "layer": "alpha",
        })
        client.post("/api/annotations", json={
            "type": "text", "lat": 2, "lng": 2, "layer": "bravo",
        })

        resp = client.get("/api/annotations/layers/list")
        assert resp.status_code == 200
        assert set(resp.json()["layers"]) == {"alpha", "bravo"}

    @pytest.mark.unit
    def test_invalid_type_rejected(self, client):
        resp = client.post("/api/annotations", json={
            "type": "invalid_type", "lat": 1, "lng": 1,
        })
        assert resp.status_code == 422

    @pytest.mark.unit
    def test_invalid_lat_rejected(self, client):
        resp = client.post("/api/annotations", json={
            "type": "text", "lat": 999, "lng": 1,
        })
        assert resp.status_code == 422

    @pytest.mark.unit
    def test_empty_update_succeeds(self, client):
        create_resp = client.post("/api/annotations", json={
            "type": "text", "lat": 10, "lng": 20, "text": "Keep me",
        })
        ann_id = create_resp.json()["id"]

        resp = client.put(f"/api/annotations/{ann_id}", json={})
        assert resp.status_code == 200
        assert resp.json()["text"] == "Keep me"


class TestAnnotationUpdate:
    """Test annotation update model validation."""

    @pytest.mark.unit
    def test_partial_update(self):
        from app.routers.annotations import AnnotationUpdate

        body = AnnotationUpdate(text="Updated text", color="#ff00ff")
        updates = body.model_dump(exclude_none=True)
        assert updates == {"text": "Updated text", "color": "#ff00ff"}

    @pytest.mark.unit
    def test_empty_update(self):
        from app.routers.annotations import AnnotationUpdate

        body = AnnotationUpdate()
        updates = body.model_dump(exclude_none=True)
        assert updates == {}
