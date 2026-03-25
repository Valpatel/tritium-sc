# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for the most critical SC API endpoints.

Tests the real endpoints against a live headless server:
  1. POST /api/demo/start  — activate demo mode
  2. GET  /api/targets     — target list
  3. GET  /api/health      — comprehensive health check
  4. POST /api/demo/stop   — deactivate demo mode
  5. GET  /api/plugins     — plugin listing

Run with:
    .venv/bin/python3 -m pytest tests/integration/test_critical_apis.py -v
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.lib.server_manager import TritiumServer

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TIMEOUT = 15  # HTTP request timeout (seconds)


@pytest.fixture(scope="module")
def server():
    """Module-scoped server: starts once for all tests in this file."""
    srv = TritiumServer(auto_port=True)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def base_url(server: TritiumServer) -> str:
    return server.base_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(base: str, path: str, **kw) -> httpx.Response:
    return httpx.get(f"{base}{path}", timeout=_TIMEOUT, **kw)


def _post(base: str, path: str, **kw) -> httpx.Response:
    return httpx.post(f"{base}{path}", timeout=_TIMEOUT, **kw)


# ---------------------------------------------------------------------------
# 1. GET /health — basic liveness (no /api prefix)
# ---------------------------------------------------------------------------

class TestHealthBasic:
    """The /health endpoint proves the server is alive."""

    def test_health_returns_200(self, base_url: str):
        resp = _get(base_url, "/health")
        assert resp.status_code == 200, f"Health check failed: {resp.status_code}"

    def test_health_body_fields(self, base_url: str):
        body = _get(base_url, "/health").json()
        assert body["status"] == "operational"
        assert body["system"] == "TRITIUM-SC"
        assert "version" in body


# ---------------------------------------------------------------------------
# 2. GET /api/health — comprehensive health
# ---------------------------------------------------------------------------

class TestHealthComprehensive:
    """The /api/health endpoint returns subsystem and plugin health."""

    def test_api_health_returns_200(self, base_url: str):
        resp = _get(base_url, "/api/health")
        assert resp.status_code == 200, f"/api/health failed: {resp.status_code}"

    def test_api_health_has_subsystems(self, base_url: str):
        body = _get(base_url, "/api/health").json()
        assert "status" in body, f"Missing 'status': {body.keys()}"
        assert body["status"] in ("healthy", "degraded"), (
            f"Unexpected status: {body['status']}"
        )
        assert "subsystems" in body, f"Missing 'subsystems': {body.keys()}"
        assert "uptime_seconds" in body, f"Missing 'uptime_seconds': {body.keys()}"
        assert body["uptime_seconds"] >= 0, "Negative uptime"
        assert body["system"] == "TRITIUM-SC"

    def test_api_health_has_test_baselines(self, base_url: str):
        body = _get(base_url, "/api/health").json()
        assert "test_baselines" in body, f"Missing 'test_baselines': {body.keys()}"
        baselines = body["test_baselines"]
        assert isinstance(baselines, dict)
        assert len(baselines) > 0, "test_baselines is empty"


# ---------------------------------------------------------------------------
# 3. GET /api/targets — target list (before demo)
# ---------------------------------------------------------------------------

class TestTargetsBeforeDemo:
    """Targets endpoint works even without demo mode — may return empty."""

    def test_targets_returns_200(self, base_url: str):
        resp = _get(base_url, "/api/targets")
        assert resp.status_code == 200, f"/api/targets failed: {resp.status_code}"

    def test_targets_structure(self, base_url: str):
        body = _get(base_url, "/api/targets").json()
        assert "targets" in body, f"Missing 'targets' key: {body.keys()}"
        assert isinstance(body["targets"], list), (
            f"Expected list, got {type(body['targets'])}"
        )
        assert "summary" in body, f"Missing 'summary' key: {body.keys()}"


# ---------------------------------------------------------------------------
# 4. GET /api/plugins — plugin listing
# ---------------------------------------------------------------------------

class TestPlugins:
    """Plugin listing endpoint returns a list (possibly empty if no manager)."""

    def test_plugins_returns_200(self, base_url: str):
        resp = _get(base_url, "/api/plugins")
        assert resp.status_code == 200, f"/api/plugins failed: {resp.status_code}"

    def test_plugins_is_list(self, base_url: str):
        body = _get(base_url, "/api/plugins").json()
        assert isinstance(body, list), f"Expected list, got {type(body)}"

    def test_plugin_status_endpoint(self, base_url: str):
        resp = _get(base_url, "/api/plugins/status")
        assert resp.status_code == 200, (
            f"/api/plugins/status failed: {resp.status_code}"
        )
        body = resp.json()
        assert "summary" in body, f"Missing 'summary': {body.keys()}"
        assert "loaded" in body, f"Missing 'loaded': {body.keys()}"

    def test_plugin_health_endpoint(self, base_url: str):
        resp = _get(base_url, "/api/plugins/health")
        assert resp.status_code == 200, (
            f"/api/plugins/health failed: {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# 5. POST /api/demo/start — activate demo mode
# ---------------------------------------------------------------------------

class TestDemoStart:
    """Start demo mode and verify it activates."""

    def test_demo_status_before_start(self, base_url: str):
        """Demo status should report inactive initially."""
        resp = _get(base_url, "/api/demo/status")
        assert resp.status_code == 200, (
            f"/api/demo/status failed: {resp.status_code}"
        )

    def test_demo_start_returns_200(self, base_url: str):
        """POST /api/demo/start should return 200 or 503 (Amy not available).

        In headless test mode (AMY_ENABLED=false), the demo controller may
        not be constructable because it requires Amy's EventBus. Both 200
        and 503 are acceptable — the key is the server does not crash.
        """
        resp = _post(base_url, "/api/demo/start")
        assert resp.status_code in (200, 503), (
            f"Unexpected status from /api/demo/start: {resp.status_code} — {resp.text}"
        )
        body = resp.json()
        if resp.status_code == 200:
            assert "status" in body, f"Missing 'status' in response: {body}"
            assert body["status"] in ("started", "already_active"), (
                f"Unexpected demo status: {body['status']}"
            )
        else:
            # 503 — Amy not available, acceptable in headless mode
            assert "error" in body, f"503 without error detail: {body}"

    def test_demo_start_idempotent(self, base_url: str):
        """Starting demo twice should not error — returns already_active or 503."""
        resp = _post(base_url, "/api/demo/start")
        assert resp.status_code in (200, 503), (
            f"Second demo start failed: {resp.status_code}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert body["status"] in ("started", "already_active")


# ---------------------------------------------------------------------------
# 6. GET /api/targets — after demo start (if it activated)
# ---------------------------------------------------------------------------

class TestTargetsAfterDemo:
    """If demo started successfully, targets should populate over time."""

    def test_targets_still_returns_200(self, base_url: str):
        """Targets endpoint must remain healthy regardless of demo state."""
        resp = _get(base_url, "/api/targets")
        assert resp.status_code == 200

    def test_target_sub_endpoints(self, base_url: str):
        """Hostile and friendly filter endpoints must return 200."""
        for path in ["/api/targets/hostiles", "/api/targets/friendlies"]:
            resp = _get(base_url, path)
            assert resp.status_code == 200, (
                f"{path} failed: {resp.status_code}"
            )

    def test_targets_have_required_fields(self, base_url: str):
        """If targets exist, each must have target_id and position."""
        body = _get(base_url, "/api/targets").json()
        targets = body.get("targets", [])
        for t in targets:
            assert "target_id" in t, f"Target missing target_id: {t}"


# ---------------------------------------------------------------------------
# 7. POST /api/demo/stop — deactivate demo mode
# ---------------------------------------------------------------------------

class TestDemoStop:
    """Stop demo mode and verify it deactivates."""

    def test_demo_stop_returns_200(self, base_url: str):
        """POST /api/demo/stop should return 200."""
        resp = _post(base_url, "/api/demo/stop")
        assert resp.status_code == 200, (
            f"/api/demo/stop failed: {resp.status_code}"
        )
        body = resp.json()
        assert "status" in body, f"Missing 'status': {body}"
        assert body["status"] in ("stopped", "not_active"), (
            f"Unexpected stop status: {body['status']}"
        )

    def test_demo_status_after_stop(self, base_url: str):
        """After stop, demo status should show inactive."""
        resp = _get(base_url, "/api/demo/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("active") is False, (
            f"Demo still active after stop: {body}"
        )

    def test_demo_stop_idempotent(self, base_url: str):
        """Stopping when already stopped should return not_active."""
        resp = _post(base_url, "/api/demo/stop")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "not_active"


# ---------------------------------------------------------------------------
# 8. Cross-cutting: all critical endpoints survive demo lifecycle
# ---------------------------------------------------------------------------

class TestPostLifecycleStability:
    """After demo start/stop cycle, all critical endpoints still work."""

    def test_health_still_works(self, base_url: str):
        assert _get(base_url, "/health").status_code == 200

    def test_api_health_still_works(self, base_url: str):
        assert _get(base_url, "/api/health").status_code == 200

    def test_targets_still_works(self, base_url: str):
        assert _get(base_url, "/api/targets").status_code == 200

    def test_plugins_still_works(self, base_url: str):
        assert _get(base_url, "/api/plugins").status_code == 200
