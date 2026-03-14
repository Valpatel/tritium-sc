# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the operational briefing generator."""

import pytest
from unittest.mock import patch, MagicMock

# Mark all tests as unit tests
pytestmark = pytest.mark.unit


class TestBriefingRouter:
    """Test briefing generation endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked app state."""
        from fastapi.testclient import TestClient
        from app.routers.briefing import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        # Mock app state
        app.state.amy = None
        app.state.simulation_engine = None
        return TestClient(app)

    def test_get_briefing_json(self, client):
        resp = client.get("/api/briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert "briefing_id" in data
        assert data["briefing_id"].startswith("BRIEF-")
        assert "threat_level" in data
        assert "generated_at" in data
        assert "classification" in data
        assert "target_summary" in data
        assert "fleet" in data
        assert "system" in data

    def test_get_briefing_text(self, client):
        resp = client.get("/api/briefing/text")
        assert resp.status_code == 200
        text = resp.text
        assert "TRITIUM OPERATIONAL BRIEFING" in text
        assert "THREAT ASSESSMENT" in text
        assert "END BRIEFING" in text

    def test_get_briefing_html(self, client):
        resp = client.get("/api/briefing/html")
        assert resp.status_code == 200
        html = resp.text
        assert "<!DOCTYPE html>" in html
        assert "TRITIUM OPERATIONAL BRIEFING" in html
        assert "THREAT LEVEL:" in html

    def test_briefing_includes_system_info(self, client):
        resp = client.get("/api/briefing")
        data = resp.json()
        assert data["system"]["version"] == "0.1.0"
        assert "uptime_hours" in data["system"]

    def test_briefing_classification_default(self, client):
        resp = client.get("/api/briefing")
        assert resp.json()["classification"] == "UNCLASSIFIED"

    def test_briefing_html_printable(self, client):
        resp = client.get("/api/briefing/html")
        html = resp.text
        assert "@media print" in html  # Has print styles
