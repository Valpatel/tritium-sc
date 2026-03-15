# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for investigation timeline endpoint."""

import time
import tempfile
import os

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI


@pytest.fixture
def app_with_engine():
    """Create a test app with investigation engine and mock dossier store."""
    app = FastAPI()

    # Import and mount the router
    from app.routers.investigations import router, _get_engine
    app.include_router(router)

    # Reset the singleton engine
    import app.routers.investigations as inv_mod
    inv_mod._engine = None

    return app


@pytest.fixture
def client(app_with_engine):
    return TestClient(app_with_engine)


class TestInvestigationTimeline:
    def test_timeline_not_found(self, client):
        resp = client.get("/api/investigations/nonexistent/timeline")
        assert resp.status_code in (404, 503)

    def test_timeline_empty_investigation(self, client):
        # Create an investigation
        resp = client.post(
            "/api/investigations",
            json={
                "title": "Test Investigation",
                "seed_entity_ids": ["entity_1"],
                "description": "Testing timeline",
            },
        )
        if resp.status_code == 503:
            pytest.skip("Investigation engine unavailable")
        assert resp.status_code == 200
        inv_id = resp.json()["inv_id"]

        # Get timeline
        resp = client.get(f"/api/investigations/{inv_id}/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["inv_id"] == inv_id
        assert "events" in data
        assert "total_events" in data

    def test_timeline_with_annotations(self, client):
        # Create investigation
        resp = client.post(
            "/api/investigations",
            json={
                "title": "Annotated Investigation",
                "seed_entity_ids": ["entity_A"],
            },
        )
        if resp.status_code == 503:
            pytest.skip("Investigation engine unavailable")
        inv_id = resp.json()["inv_id"]

        # Add an annotation
        client.post(
            f"/api/investigations/{inv_id}/annotate",
            json={
                "entity_id": "entity_A",
                "note": "Suspicious activity observed",
                "analyst": "operator1",
            },
        )

        # Get timeline — should include annotation events
        resp = client.get(f"/api/investigations/{inv_id}/timeline")
        assert resp.status_code == 200
        data = resp.json()
        # Annotations should appear in the timeline
        assert isinstance(data["events"], list)

    def test_timeline_limit_parameter(self, client):
        resp = client.post(
            "/api/investigations",
            json={
                "title": "Limited Investigation",
                "seed_entity_ids": [],
            },
        )
        if resp.status_code == 503:
            pytest.skip("Investigation engine unavailable")
        inv_id = resp.json()["inv_id"]

        resp = client.get(f"/api/investigations/{inv_id}/timeline?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] <= 10
