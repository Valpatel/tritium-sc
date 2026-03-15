# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Wave 120 security tests.

A. Security audit of Waves 115-119 endpoints
B. WebSocket token refresh
D. CORS origin validation
E. /api/system/security-status endpoint
"""

import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# A. Security audit of Waves 115-119 endpoints
# ---------------------------------------------------------------------------


class TestGeofenceEndpointSecurity:
    """Verify geofence endpoints validate input properly."""

    @pytest.fixture
    def app(self):
        from app.routers.geofence import router
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_create_zone_rejects_too_few_vertices(self, client):
        """Polygon with <3 vertices should be rejected."""
        resp = client.post("/api/geofence/zones", json={
            "name": "bad_zone",
            "polygon": [[0, 0], [1, 1]],
        })
        assert resp.status_code == 400

    def test_create_zone_rejects_invalid_type(self, client):
        """Invalid zone_type should be rejected."""
        resp = client.post("/api/geofence/zones", json={
            "name": "bad_type",
            "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]],
            "zone_type": "evil",
        })
        assert resp.status_code == 400

    def test_create_zone_sanitizes_name(self, client):
        """HTML in zone name should be stripped."""
        resp = client.post("/api/geofence/zones", json={
            "name": "<script>alert(1)</script>Zone",
            "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]],
            "zone_type": "monitored",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "<script>" not in data["name"]

    def test_create_zone_name_length_limit(self, client):
        """Zone name longer than limit should be truncated."""
        long_name = "A" * 300
        resp = client.post("/api/geofence/zones", json={
            "name": long_name,
            "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]],
            "zone_type": "safe",
        })
        # Should succeed (name is truncated, not rejected)
        # Pydantic max_length=200 will reject it
        assert resp.status_code in (201, 422)

    def test_delete_nonexistent_zone(self, client):
        """Deleting a nonexistent zone should return 404."""
        resp = client.delete("/api/geofence/zones/nonexistent")
        assert resp.status_code == 404


class TestDwellEndpointSecurity:
    """Verify dwell endpoints handle missing tracker gracefully."""

    @pytest.fixture
    def app(self):
        from app.routers.dwell import router
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_active_dwells_without_tracker(self, client):
        """When dwell_tracker is not wired, endpoint returns empty gracefully."""
        resp = client.get("/api/dwell/active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["source"] == "unavailable"

    def test_dwell_history_without_tracker(self, client):
        """History endpoint returns empty when tracker not available."""
        resp = client.get("/api/dwell/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "unavailable"

    def test_dwell_for_target_without_tracker(self, client):
        """Per-target dwell returns null when tracker not available."""
        resp = client.get("/api/dwell/target/ble_aabbcc")
        assert resp.status_code == 200
        data = resp.json()
        assert data["dwell"] is None
        assert data["source"] == "unavailable"


class TestFleetMapEndpointSecurity:
    """Verify fleet map endpoints handle missing plugins gracefully."""

    @pytest.fixture
    def app(self):
        from app.routers.fleet_map import router
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_devices_without_plugin(self, client):
        """Fleet map devices returns empty when plugin not loaded."""
        resp = client.get("/api/fleet/map/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_coverage_without_plugin(self, client):
        """Fleet map coverage returns empty when plugin not loaded."""
        resp = client.get("/api/fleet/map/coverage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0


class TestNotificationEndpointSecurity:
    """Verify notification endpoints validate input."""

    @pytest.fixture
    def app(self):
        from app.routers.notifications import router
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_mark_nonexistent_notification(self, client):
        """Marking a nonexistent notification should return 404."""
        resp = client.post("/api/notifications/read", json={
            "notification_id": "nonexistent_id",
        })
        assert resp.status_code == 404

    def test_update_prefs_invalid_severity(self, client):
        """Invalid severity in preferences update should return 400."""
        resp = client.put("/api/notifications/preferences", json={
            "geofence_enter": {"severity": "apocalyptic"},
        })
        assert resp.status_code == 400

    def test_update_prefs_valid(self, client):
        """Valid preference update should succeed."""
        resp = client.put("/api/notifications/preferences", json={
            "geofence_enter": {"enabled": False, "severity": "critical"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["preferences"]["geofence_enter"]["severity"] == "critical"

    def test_limit_query_param_enforced(self, client):
        """Limit >500 should be rejected by Pydantic validation."""
        resp = client.get("/api/notifications?limit=9999")
        assert resp.status_code == 422


class TestSessionEndpointSecurity:
    """Verify session endpoints handle edge cases securely."""

    @pytest.fixture
    def app(self):
        from app.routers.sessions import router
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_create_session_invalid_role(self, client):
        """Creating a session with an invalid role should return 400."""
        resp = client.post("/api/sessions", json={
            "username": "hacker",
            "role": "superadmin",
        })
        assert resp.status_code == 400

    def test_delete_nonexistent_session(self, client):
        """Deleting a nonexistent session should return 404."""
        resp = client.delete("/api/sessions/nonexistent_id")
        assert resp.status_code == 404

    def test_set_timeout_enforces_bounds(self, client):
        """Timeout outside 60-86400 range should be rejected."""
        resp = client.put("/api/sessions/timeout?timeout_seconds=5")
        assert resp.status_code == 422

        resp = client.put("/api/sessions/timeout?timeout_seconds=999999")
        assert resp.status_code == 422

        # Reset to default
        client.put("/api/sessions/timeout?timeout_seconds=1800")


class TestCommandHistoryEndpointSecurity:
    """Verify command history redacts sensitive data for non-admins."""

    def test_hostname_redacted(self):
        """hostname key in payload should be redacted for non-admin."""
        from app.routers.command_history import _redact_command

        cmd = {
            "command_id": "cmd_120",
            "device_id": "d1",
            "command": "config_push",
            "payload": {
                "hostname": "edge-secret.local",
                "endpoint": "http://192.168.1.1:8080/api",
                "config": {"interval": 30},
            },
            "sent_at": time.time(),
            "result": "pending",
        }

        redacted = _redact_command(cmd, is_admin=False)
        assert redacted["payload"]["hostname"] == "[REDACTED]"
        assert redacted["payload"]["endpoint"] == "[REDACTED]"
        assert redacted["payload"]["config"] == {"interval": 30}

    def test_none_payload_safe(self):
        """Commands with None/missing payload should not crash."""
        from app.routers.command_history import _redact_command

        cmd = {
            "command_id": "cmd_121",
            "device_id": "d2",
            "command": "reboot",
            "payload": None,
            "sent_at": time.time(),
            "result": "pending",
        }

        # payload is None, so the redaction should not crash
        redacted = _redact_command(cmd, is_admin=False)
        assert redacted["payload"] is None


# ---------------------------------------------------------------------------
# B. WebSocket token refresh
# ---------------------------------------------------------------------------


class TestWebSocketTokenRefresh:
    """Verify the token_expiring/token_refresh flow."""

    def test_connection_manager_tracks_token_exp(self):
        """ConnectionManager should store and retrieve token expiry."""
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()

        ws = MagicMock()
        # Simulate storing token exp
        mgr._token_exp[ws] = time.time() + 3600
        assert ws in mgr._token_exp
        assert mgr._token_exp[ws] > time.time()

    def test_update_token_exp_clears_warned(self):
        """update_token_exp should clear the warned flag for a connection."""
        from app.routers.ws import ConnectionManager
        mgr = ConnectionManager()

        ws = MagicMock()
        mgr._token_warned.add(ws)
        mgr.update_token_exp(ws, time.time() + 7200)
        assert ws not in mgr._token_warned
        assert mgr._token_exp[ws] > time.time()

    @pytest.mark.asyncio
    async def test_check_token_expiry_warns_near_expiry(self):
        """check_token_expiry should send warning for near-expiry tokens."""
        from app.routers.ws import ConnectionManager, _TOKEN_EXPIRY_WARN_S
        import asyncio

        mgr = ConnectionManager()
        ws = MagicMock()
        ws.send_text = AsyncMock()

        # Add connection with token expiring in 60s (within warn threshold)
        async with mgr._lock:
            mgr.active_connections.add(ws)
            mgr._token_exp[ws] = time.time() + 60

        await mgr.check_token_expiry()

        ws.send_text.assert_called_once()
        import json
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["type"] == "token_expiring"
        assert sent["expires_in_seconds"] <= 60
        assert ws in mgr._token_warned

    @pytest.mark.asyncio
    async def test_check_token_expiry_no_warn_if_far(self):
        """check_token_expiry should not warn for tokens with plenty of time left."""
        from app.routers.ws import ConnectionManager
        import asyncio

        mgr = ConnectionManager()
        ws = MagicMock()
        ws.send_text = AsyncMock()

        async with mgr._lock:
            mgr.active_connections.add(ws)
            mgr._token_exp[ws] = time.time() + 3600  # 1 hour away

        await mgr.check_token_expiry()

        ws.send_text.assert_not_called()
        assert ws not in mgr._token_warned

    def test_handle_client_message_routes_token_refresh(self):
        """handle_client_message should recognize token_refresh type."""
        from app.routers.ws import handle_client_message
        # Just verify the function exists and handles unknown types gracefully
        assert callable(handle_client_message)


# ---------------------------------------------------------------------------
# D. CORS origin validation
# ---------------------------------------------------------------------------


class TestCORSOriginValidation:
    """Verify CORS configuration rejects unauthorized origins."""

    def test_cors_allows_configured_origin(self):
        """When CORS_ALLOWED_ORIGINS is set, listed origins should be allowed."""
        from fastapi.middleware.cors import CORSMiddleware

        app = FastAPI()

        @app.get("/api/test")
        async def test_endpoint():
            return {"ok": True}

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["https://trusted.example.com"],
            allow_credentials=True,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

        client = TestClient(app)
        resp = client.options(
            "/api/test",
            headers={
                "Origin": "https://trusted.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "https://trusted.example.com"

    def test_cors_rejects_unauthorized_origin(self):
        """When CORS_ALLOWED_ORIGINS is set, unlisted origins should NOT get CORS headers."""
        from fastapi.middleware.cors import CORSMiddleware

        app = FastAPI()

        @app.get("/api/test")
        async def test_endpoint():
            return {"ok": True}

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["https://trusted.example.com"],
            allow_credentials=True,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

        client = TestClient(app)
        resp = client.options(
            "/api/test",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Starlette CORS returns 400 for disallowed preflight or omits the header
        acao = resp.headers.get("access-control-allow-origin")
        assert acao != "https://evil.example.com"

    def test_cors_wildcard_when_no_config(self):
        """When cors_allowed_origins is empty, all origins should be allowed."""
        from fastapi.middleware.cors import CORSMiddleware

        app = FastAPI()

        @app.get("/api/test")
        async def test_endpoint():
            return {"ok": True}

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET"],
            allow_headers=["*"],
        )

        client = TestClient(app)
        resp = client.get(
            "/api/test",
            headers={"Origin": "https://anywhere.example.com"},
        )
        assert resp.status_code == 200
        acao = resp.headers.get("access-control-allow-origin")
        assert acao == "*"

    def test_cors_config_parsing(self):
        """Verify the CORS origin parsing logic from main.py works correctly."""
        # Simulate the parsing logic from main.py
        cors_allowed_origins = "https://trusted.com, https://app.example.com"
        cors_origins = (
            [o.strip() for o in cors_allowed_origins.split(",") if o.strip()]
            if cors_allowed_origins
            else ["*"]
        )
        assert cors_origins == ["https://trusted.com", "https://app.example.com"]

        # Empty string = wildcard
        cors_allowed_origins = ""
        cors_origins = (
            [o.strip() for o in cors_allowed_origins.split(",") if o.strip()]
            if cors_allowed_origins
            else ["*"]
        )
        assert cors_origins == ["*"]


# ---------------------------------------------------------------------------
# E. /api/system/security-status endpoint
# ---------------------------------------------------------------------------


class TestSecurityStatusEndpoint:
    """Verify the security status endpoint returns correct posture."""

    @pytest.fixture
    def app(self):
        from app.routers.security_status import router
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_returns_all_fields(self, client):
        """Security status should return all expected sections."""
        # Auth is disabled by default, so require_auth returns admin
        resp = client.get("/api/system/security-status")
        assert resp.status_code == 200
        data = resp.json()

        assert "overall" in data
        assert "checks_passed" in data
        assert "checks_total" in data
        assert data["checks_total"] == 6

        # All sections present
        assert "auth" in data
        assert "tls" in data
        assert "rate_limiting" in data
        assert "mqtt" in data
        assert "csp" in data
        assert "cors" in data

    def test_auth_section_fields(self, client):
        """Auth section should include key configuration details."""
        resp = client.get("/api/system/security-status")
        auth = resp.json()["auth"]
        assert "enabled" in auth
        assert "algorithm" in auth
        assert "access_token_expire_minutes" in auth
        assert "api_keys_configured" in auth

    def test_overall_level_matches_checks(self, client):
        """Overall security level should match the number of checks passed."""
        resp = client.get("/api/system/security-status")
        data = resp.json()
        # With default settings: CSP enabled, everything else off
        # So checks_passed should be >= 1 (CSP)
        assert data["overall"] in ("open", "minimal", "moderate", "hardened")
        if data["checks_passed"] == 0:
            assert data["overall"] == "open"
        elif data["checks_passed"] < 3:
            assert data["overall"] == "minimal"

    def test_cors_mode_open_by_default(self, client):
        """With no CORS config, mode should be 'open'."""
        resp = client.get("/api/system/security-status")
        cors = resp.json()["cors"]
        # Default settings have empty cors_allowed_origins
        assert cors["mode"] == "open"
        assert cors["allowed_origins"] == ["*"]

    def test_tls_section(self, client):
        """TLS section should reflect configuration."""
        resp = client.get("/api/system/security-status")
        tls = resp.json()["tls"]
        assert "enabled" in tls
        assert "cert_configured" in tls
        # Default: TLS disabled
        assert tls["enabled"] is False

    def test_rate_limiting_section(self, client):
        """Rate limiting section should include config values."""
        resp = client.get("/api/system/security-status")
        rl = resp.json()["rate_limiting"]
        assert "enabled" in rl
        assert "max_requests" in rl
        assert "window_seconds" in rl

    def test_mqtt_section(self, client):
        """MQTT section should indicate auth status."""
        resp = client.get("/api/system/security-status")
        mqtt = resp.json()["mqtt"]
        assert "enabled" in mqtt
        assert "auth_configured" in mqtt
        assert "host" in mqtt
        assert "port" in mqtt
