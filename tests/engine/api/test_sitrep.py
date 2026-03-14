# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the SITREP API router."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Import the actual app instance."""
    from app.main import app as real_app
    return real_app


@pytest.fixture
def client(app):
    """TestClient that skips lifespan."""
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSitrepEndpoint:
    """Tests for GET /api/sitrep."""

    def test_sitrep_returns_json(self, client):
        """SITREP endpoint returns a valid JSON response."""
        resp = client.get("/api/sitrep")
        assert resp.status_code == 200
        data = resp.json()
        assert "sitrep_id" in data
        assert "timestamp" in data
        assert "threat_level" in data
        assert "targets" in data
        assert "fleet" in data
        assert "geofence" in data
        assert "system" in data

    def test_sitrep_id_format(self, client):
        """SITREP ID follows SITREP-YYYYMMDD-HHMMSS format."""
        resp = client.get("/api/sitrep")
        data = resp.json()
        assert data["sitrep_id"].startswith("SITREP-")

    def test_threat_level_green_no_targets(self, client):
        """Threat level is GREEN when no hostiles exist."""
        resp = client.get("/api/sitrep")
        data = resp.json()
        # Without Amy, there are no targets, so threat_level = GREEN
        assert data["threat_level"] == "GREEN"

    def test_target_summary_structure(self, client):
        """Target summary has expected fields."""
        resp = client.get("/api/sitrep")
        data = resp.json()
        t = data["targets"]
        assert "total" in t
        assert "by_alliance" in t
        assert "by_type" in t
        assert "by_source" in t
        assert "active_threats" in t
        assert "threat_count" in t

    def test_fleet_summary_structure(self, client):
        """Fleet summary has expected fields."""
        resp = client.get("/api/sitrep")
        data = resp.json()
        f = data["fleet"]
        assert "total_nodes" in f
        assert "online" in f
        assert "offline" in f


class TestSitrepText:
    """Tests for GET /api/sitrep/text."""

    def test_sitrep_text_returns_plaintext(self, client):
        """Text SITREP endpoint returns plain text."""
        resp = client.get("/api/sitrep/text")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_sitrep_text_contains_header(self, client):
        """Text SITREP contains the header line."""
        resp = client.get("/api/sitrep/text")
        text = resp.text
        assert "TRITIUM SITUATION REPORT" in text
        assert "THREAT LEVEL:" in text
        assert "TARGETS:" in text
        assert "END SITREP" in text
