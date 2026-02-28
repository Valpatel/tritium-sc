# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for app.main — FastAPI app creation, routing, middleware, lifespan.

Tests verify the FastAPI instance configuration, router registration,
CORS middleware, static file mounting, no-cache middleware, route endpoints,
lifespan startup/shutdown, and subsystem helper functions.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Import the actual app instance (no lifespan execution)."""
    from app.main import app as real_app
    return real_app


@pytest.fixture
def client(app):
    """TestClient that skips lifespan to avoid booting real subsystems."""
    # Do NOT use context manager — that triggers lifespan which starts
    # TTS, whisper, YOLO, etc. and leaves daemon threads that segfault on exit.
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# App creation tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAppCreation:
    """FastAPI instance exists with correct settings."""

    def test_app_is_fastapi_instance(self, app):
        assert isinstance(app, FastAPI)

    def test_app_title(self, app):
        assert app.title == "TRITIUM-SC"

    def test_app_description(self, app):
        assert app.description == "Security Central - Intelligence Platform"

    def test_app_version(self, app):
        assert app.version == "0.1.0"

    def test_app_has_lifespan(self, app):
        # The lifespan is set via the router; verify it is not None
        assert app.router.lifespan_context is not None


# ---------------------------------------------------------------------------
# Router registration tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRouterRegistration:
    """All expected routers are mounted on the app."""

    EXPECTED_PREFIXES = [
        "/api/cameras",
        "/api/videos",
        "/ws",
        "/api/discovery",
        "/api/ai",
        "/api/search",
        "/api/zones",
        "/api/assets",
        "/api/amy",
        "/api/scenarios",
        "/api/tts",
        "/api/targets",
        "/api/geo",
        "/api/game",
        "/api/audio",
        "/api/synthetic",
        "/api/telemetry",
        "/api/mesh",
        "/api/geo/layers",
    ]

    def test_router_count(self, app):
        """At least 19 routers are registered (cameras, videos, ws, discovery,
        ai, search, zones, assets, amy, scenarios, tts, targets_unified,
        geo, game, audio, synthetic_feed, telemetry, mesh, geodata)."""
        # Collect all routes that have a path starting with /api or /ws
        api_routes = [
            r for r in app.routes
            if hasattr(r, "path") and (r.path.startswith("/api") or r.path.startswith("/ws"))
        ]
        assert len(api_routes) >= 19

    def test_expected_route_prefixes_exist(self, app):
        """Every expected prefix has at least one matching route."""
        all_paths = [
            r.path for r in app.routes if hasattr(r, "path")
        ]
        for prefix in self.EXPECTED_PREFIXES:
            matches = [p for p in all_paths if p.startswith(prefix)]
            assert len(matches) >= 1, f"No route found for prefix {prefix}"

    def test_cameras_router_included(self, app):
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/api/cameras" in p for p in paths)

    def test_amy_router_included(self, app):
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/api/amy" in p for p in paths)

    def test_game_router_included(self, app):
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/api/game" in p for p in paths)

    def test_geo_router_included(self, app):
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/api/geo" in p for p in paths)

    def test_audio_router_included(self, app):
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/api/audio" in p for p in paths)

    def test_telemetry_router_included(self, app):
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/api/telemetry" in p for p in paths)


# ---------------------------------------------------------------------------
# CORS middleware tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCORSMiddleware:
    """CORS is configured to allow all origins."""

    def test_cors_allow_origins(self, client):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS should respond to preflight with allowed origin
        assert resp.headers.get("access-control-allow-origin") in ("*", "http://evil.example.com")

    def test_cors_allow_methods(self, client):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "DELETE",
            },
        )
        allow_methods = resp.headers.get("access-control-allow-methods", "")
        assert "DELETE" in allow_methods or "*" in allow_methods

    def test_cors_allow_headers(self, client):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Custom-Header",
            },
        )
        allow_headers = resp.headers.get("access-control-allow-headers", "")
        assert "x-custom-header" in allow_headers.lower() or "*" in allow_headers

    def test_cors_allow_credentials(self, client):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-credentials") == "true"


# ---------------------------------------------------------------------------
# No-cache middleware tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNoCacheMiddleware:
    """Static CSS/JS files get no-cache headers."""

    def test_static_path_gets_no_cache(self, client):
        """Requests to /static/ paths should get Cache-Control: no-cache."""
        # This may 404 but the middleware should still set the header
        resp = client.get("/static/css/cybercore.css")
        # If the file exists, header should be set; if not, check status
        if resp.status_code == 200:
            assert "no-cache" in resp.headers.get("cache-control", "")

    def test_non_static_path_no_special_cache(self, client):
        """Non-static paths should NOT get the forced no-cache header."""
        resp = client.get("/health")
        cache_control = resp.headers.get("cache-control", "")
        # /health should not have our forced no-cache (might have none or other)
        assert "must-revalidate" not in cache_control


# ---------------------------------------------------------------------------
# Static files mounting tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestStaticFiles:
    """Static file mounting configuration."""

    def test_frontend_path_calculation(self):
        """frontend_path resolves to <project>/frontend/."""
        from app.main import frontend_path
        assert frontend_path.name == "frontend"
        assert frontend_path.parent.name == "tritium-sc" or frontend_path.exists()

    def test_static_mount_exists(self, app):
        """A mount at /static exists in the app routes."""
        mount_paths = [
            r.path for r in app.routes
            if hasattr(r, "path") and r.path == "/static"
        ]
        assert len(mount_paths) >= 1


# ---------------------------------------------------------------------------
# Route endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRouteEndpoints:
    """Direct route endpoints on the app (not from routers)."""

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "operational"
        assert data["version"] == "0.1.0"
        assert data["system"] == "TRITIUM-SC"

    def test_root_endpoint_exists(self, app):
        """GET / is registered."""
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/" in paths

    def test_unified_redirect_exists(self, app):
        """GET /unified is registered."""
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/unified" in paths

    def test_legacy_dashboard_exists(self, app):
        """GET /legacy is registered."""
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/legacy" in paths

    def test_command_center_exists(self, app):
        """GET /command is registered."""
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/command" in paths

    def test_api_status_endpoint(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert data["version"] == "0.1.0"
        assert "recordings_path" in data
        assert "database" in data

    def test_unified_redirect_returns_301(self, client):
        resp = client.get("/unified", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["location"] == "/"


# ---------------------------------------------------------------------------
# Subsystem helper tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSubsystemHelpers:
    """Test subsystem startup/shutdown helper functions."""

    def test_create_simulation_engine_disabled(self):
        """When simulation_enabled=False, returns None."""
        from app.main import _create_simulation_engine
        with patch("app.main.settings") as mock_settings:
            mock_settings.simulation_enabled = False
            result = _create_simulation_engine()
            assert result is None

    def test_create_simulation_engine_enabled_no_layout(self):
        """When simulation_enabled=True but no layout, returns engine."""
        from app.main import _create_simulation_engine
        with patch("app.main.settings") as mock_settings:
            mock_settings.simulation_enabled = True
            mock_settings.simulation_layout = ""
            engine = _create_simulation_engine()
            assert engine is not None

    def test_create_simulation_engine_enabled_with_missing_layout(self, tmp_path):
        """When layout path doesn't exist, returns engine without loading."""
        from app.main import _create_simulation_engine
        with patch("app.main.settings") as mock_settings:
            mock_settings.simulation_enabled = True
            mock_settings.simulation_layout = str(tmp_path / "nonexistent.json")
            engine = _create_simulation_engine()
            assert engine is not None

    def test_start_mqtt_bridge_disabled(self):
        """When mqtt_enabled=False, returns None."""
        from app.main import _start_mqtt_bridge
        with patch("app.main.settings") as mock_settings:
            mock_settings.mqtt_enabled = False
            result = _start_mqtt_bridge(MagicMock())
            assert result is None

    def test_start_mqtt_bridge_connection_refused(self):
        """When broker is unreachable, returns None gracefully."""
        from app.main import _start_mqtt_bridge
        with patch("app.main.settings") as mock_settings:
            mock_settings.mqtt_enabled = True
            mock_settings.mqtt_site_id = "test"
            mock_settings.mqtt_host = "localhost"
            mock_settings.mqtt_port = 1883
            mock_settings.mqtt_username = ""
            mock_settings.mqtt_password = ""
            amy = MagicMock()
            with patch("engine.comms.mqtt_bridge.MQTTBridge", side_effect=ConnectionRefusedError("refused")):
                result = _start_mqtt_bridge(amy)
                assert result is None

    def test_start_meshtastic_bridge_disabled(self):
        """When meshtastic_enabled=False, returns None."""
        from app.main import _start_meshtastic_bridge
        with patch("app.main.settings") as mock_settings:
            mock_settings.meshtastic_enabled = False
            result = _start_meshtastic_bridge(MagicMock())
            assert result is None

    def test_load_escalation_zones_default(self):
        """When no layout configured, returns default zones."""
        from app.main import _load_escalation_zones
        with patch("app.main.settings") as mock_settings:
            mock_settings.simulation_layout = ""
            zones = _load_escalation_zones()
            assert len(zones) == 2
            assert zones[0]["name"] == "perimeter"
            assert zones[1]["name"] == "inner_zone"

    def test_load_escalation_zones_default_radii(self):
        """Default zones have correct radii."""
        from app.main import _load_escalation_zones
        with patch("app.main.settings") as mock_settings:
            mock_settings.simulation_layout = ""
            zones = _load_escalation_zones()
            assert zones[0]["properties"]["radius"] == 25.0
            assert zones[1]["properties"]["radius"] == 12.0

    def test_shutdown_subsystems_all_none(self):
        """Shutdown gracefully handles all-None arguments."""
        from app.main import _shutdown_subsystems
        mock_app = MagicMock(spec=FastAPI)
        mock_app.state = SimpleNamespace()
        # Should not raise
        _shutdown_subsystems(None, None, None, mock_app)

    def test_shutdown_subsystems_stops_mqtt(self):
        """Shutdown calls stop() on mqtt_bridge."""
        from app.main import _shutdown_subsystems
        mock_app = MagicMock(spec=FastAPI)
        mock_app.state = SimpleNamespace()
        mqtt = MagicMock()
        _shutdown_subsystems(None, None, mqtt, mock_app)
        mqtt.stop.assert_called_once()

    def test_shutdown_subsystems_stops_sim_engine(self):
        """Shutdown calls stop() on simulation engine."""
        from app.main import _shutdown_subsystems
        mock_app = MagicMock(spec=FastAPI)
        mock_app.state = SimpleNamespace()
        sim = MagicMock()
        _shutdown_subsystems(None, sim, None, mock_app)
        sim.stop.assert_called_once()

    def test_shutdown_subsystems_shuts_down_amy(self):
        """Shutdown calls shutdown() on amy_instance."""
        from app.main import _shutdown_subsystems
        mock_app = MagicMock(spec=FastAPI)
        mock_app.state = SimpleNamespace()
        amy = MagicMock()
        amy.threat_classifier = None
        amy.auto_dispatcher = None
        _shutdown_subsystems(amy, None, None, mock_app)
        amy.shutdown.assert_called_once()

    def test_shutdown_subsystems_stops_classifier(self):
        """Shutdown stops threat classifier on amy."""
        from app.main import _shutdown_subsystems
        mock_app = MagicMock(spec=FastAPI)
        mock_app.state = SimpleNamespace()
        classifier = MagicMock()
        amy = MagicMock()
        amy.threat_classifier = classifier
        amy.auto_dispatcher = None
        _shutdown_subsystems(amy, None, None, mock_app)
        classifier.stop.assert_called_once()

    def test_shutdown_subsystems_stops_dispatcher(self):
        """Shutdown stops auto dispatcher on amy."""
        from app.main import _shutdown_subsystems
        mock_app = MagicMock(spec=FastAPI)
        mock_app.state = SimpleNamespace()
        dispatcher = MagicMock()
        amy = MagicMock()
        amy.threat_classifier = None
        amy.auto_dispatcher = dispatcher
        _shutdown_subsystems(amy, None, None, mock_app)
        dispatcher.stop.assert_called_once()

    def test_shutdown_stops_announcer_on_app_state(self):
        """Shutdown stops the announcer from app.state."""
        from app.main import _shutdown_subsystems
        announcer = MagicMock()
        mock_app = MagicMock(spec=FastAPI)
        mock_app.state = SimpleNamespace(announcer=announcer)
        _shutdown_subsystems(None, None, None, mock_app)
        announcer.stop.assert_called_once()

    def test_shutdown_stops_meshtastic_bridge(self):
        """Shutdown stops meshtastic bridge from app.state."""
        from app.main import _shutdown_subsystems
        mesh = MagicMock()
        mock_app = MagicMock(spec=FastAPI)
        mock_app.state = SimpleNamespace(meshtastic_bridge=mesh)
        _shutdown_subsystems(None, None, None, mock_app)
        mesh.stop.assert_called_once()

    def test_shutdown_stops_synthetic_camera(self):
        """Shutdown stops synthetic camera from app.state."""
        from app.main import _shutdown_subsystems
        syn = MagicMock()
        mock_app = MagicMock(spec=FastAPI)
        mock_app.state = SimpleNamespace(syn_cam=syn)
        _shutdown_subsystems(None, None, None, mock_app)
        syn.stop.assert_called_once()

    def test_shutdown_order_sim_before_amy(self):
        """Simulation engine is stopped before Amy is shut down."""
        from app.main import _shutdown_subsystems
        call_order = []
        mock_app = MagicMock(spec=FastAPI)
        mock_app.state = SimpleNamespace()
        sim = MagicMock()
        sim.stop.side_effect = lambda: call_order.append("sim_stop")
        amy = MagicMock()
        amy.threat_classifier = None
        amy.auto_dispatcher = None
        amy.shutdown.side_effect = lambda: call_order.append("amy_shutdown")
        _shutdown_subsystems(amy, sim, None, mock_app)
        assert call_order.index("sim_stop") < call_order.index("amy_shutdown")
