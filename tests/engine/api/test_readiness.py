# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for GET /api/system/readiness endpoint."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.readiness import router


@pytest.fixture
def bare_app():
    """Minimal app with no subsystems."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def bare_client(bare_app):
    return TestClient(bare_app, raise_server_exceptions=False)


@pytest.fixture
def full_app():
    """App with simulated subsystems."""
    app = FastAPI()
    app.include_router(router)

    app.state.mqtt_bridge = SimpleNamespace(connected=True)
    app.state.demo_controller = SimpleNamespace(active=False)
    app.state.plugin_manager = SimpleNamespace(
        list_plugins=lambda: [
            {"name": "a", "status": "running"},
            {"name": "b", "status": "running"},
        ],
    )
    app.state.target_tracker = SimpleNamespace()
    app.state.training_store = SimpleNamespace()
    app.state.dossier_manager = SimpleNamespace()
    app.state.meshtastic_bridge = SimpleNamespace()
    app.state.amy = SimpleNamespace()
    return app


@pytest.fixture
def full_client(full_app):
    return TestClient(full_app, raise_server_exceptions=False)


class TestReadinessEndpoint:
    """Tests for /api/system/readiness."""

    @pytest.mark.unit
    def test_readiness_returns_200(self, bare_client):
        resp = bare_client.get("/api/system/readiness")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_readiness_has_overall(self, bare_client):
        data = bare_client.get("/api/system/readiness").json()
        assert "overall" in data
        assert data["overall"] in ("ready", "partially_ready", "not_ready")

    @pytest.mark.unit
    def test_readiness_has_items(self, bare_client):
        data = bare_client.get("/api/system/readiness").json()
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) >= 5

    @pytest.mark.unit
    def test_readiness_items_have_status(self, bare_client):
        data = bare_client.get("/api/system/readiness").json()
        for item in data["items"]:
            assert "name" in item
            assert "status" in item
            assert item["status"] in ("green", "yellow", "red")

    @pytest.mark.unit
    def test_readiness_has_score(self, bare_client):
        data = bare_client.get("/api/system/readiness").json()
        assert "score" in data
        assert "/" in data["score"]

    @pytest.mark.unit
    def test_readiness_has_checked_at(self, bare_client):
        data = bare_client.get("/api/system/readiness").json()
        assert "checked_at" in data
        assert isinstance(data["checked_at"], float)

    @pytest.mark.unit
    def test_full_subsystems_more_green(self, full_client):
        """With subsystems attached, more items should be green."""
        data = full_client.get("/api/system/readiness").json()
        green_count = sum(1 for i in data["items"] if i["status"] == "green")
        # At least stores, plugins, meshtastic, amy should be green
        assert green_count >= 4

    @pytest.mark.unit
    def test_checklist_includes_mqtt(self, bare_client):
        data = bare_client.get("/api/system/readiness").json()
        names = [i["name"] for i in data["items"]]
        assert "mqtt_broker" in names

    @pytest.mark.unit
    def test_checklist_includes_plugins(self, bare_client):
        data = bare_client.get("/api/system/readiness").json()
        names = [i["name"] for i in data["items"]]
        assert "plugins" in names

    @pytest.mark.unit
    def test_checklist_includes_ollama(self, bare_client):
        data = bare_client.get("/api/system/readiness").json()
        names = [i["name"] for i in data["items"]]
        assert "ollama" in names
