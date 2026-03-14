# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the /api/system/self-test endpoint."""

import os
import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key-32-chars-long-ok")


class TestSelfTestEndpoint:
    """Verify self-test endpoint returns subsystem health."""

    def test_self_test_returns_200(self):
        """GET /api/system/self-test returns 200."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/system/self-test")
        assert resp.status_code == 200

    def test_self_test_structure(self):
        """Response contains expected top-level fields."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/system/self-test")
        data = resp.json()
        assert "overall" in data
        assert "passed" in data
        assert "failed" in data
        assert "total" in data
        assert "elapsed_ms" in data
        assert "subsystems" in data
        assert "timestamp" in data

    def test_self_test_subsystem_format(self):
        """Each subsystem entry has name, status, elapsed_ms."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/system/self-test")
        data = resp.json()
        for sub in data["subsystems"]:
            assert "name" in sub
            assert "status" in sub
            assert sub["status"] in ("pass", "fail")
            assert "elapsed_ms" in sub

    def test_self_test_core_imports_pass(self):
        """core_imports subsystem should always pass."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/system/self-test")
        data = resp.json()
        imports = next(
            (s for s in data["subsystems"] if s["name"] == "core_imports"),
            None,
        )
        assert imports is not None
        assert imports["status"] == "pass"

    def test_self_test_total_matches_count(self):
        """total field matches len(subsystems)."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/system/self-test")
        data = resp.json()
        assert data["total"] == len(data["subsystems"])
        assert data["passed"] + data["failed"] == data["total"]

    def test_self_test_overall_status(self):
        """Overall status is pass, degraded, or fail."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/system/self-test")
        data = resp.json()
        assert data["overall"] in ("pass", "degraded", "fail")

    def test_self_test_has_12_subsystems(self):
        """Self-test checks at least 12 subsystems."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/system/self-test")
        data = resp.json()
        assert data["total"] >= 12
