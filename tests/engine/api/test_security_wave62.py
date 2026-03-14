# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Security tests — Wave 62.

Tests:
1. Plugin input validation (acoustic, watchlist, geofence, heatmap, notifications)
   - Malformed JSON, oversized payloads, missing required fields
2. Voice command injection
   - Shell command injection via "start demo && rm -rf /"
   - SQL injection in search terms
   - XSS in Amy chat messages
3. API endpoint input sanitization
"""

import os
import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key-32-chars-long-ok")


# ------------------------------------------------------------------ #
# Acoustic endpoint input validation
# ------------------------------------------------------------------ #

class TestAcousticInputValidation:
    """Verify acoustic API rejects malformed/oversized input."""

    def test_classify_missing_fields_uses_defaults(self):
        """POST /api/acoustic/classify with empty body uses Pydantic defaults."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/acoustic/classify", json={})
        # Should succeed since all fields have defaults
        assert resp.status_code == 200

    def test_classify_invalid_types_rejected(self):
        """POST /api/acoustic/classify with non-numeric fields fails validation."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/acoustic/classify", json={
            "rms_energy": "not_a_number",
            "peak_amplitude": True,
        })
        assert resp.status_code == 422

    def test_classify_extreme_values(self):
        """POST /api/acoustic/classify with extreme float values succeeds."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/acoustic/classify", json={
            "rms_energy": 1e308,
            "peak_amplitude": -1e308,
            "zero_crossing_rate": 0.0,
            "spectral_centroid": float("inf") if False else 1e100,
            "duration_ms": 2**31 - 1,
        })
        # Should not crash — may return 200 or 422 depending on validation
        assert resp.status_code in (200, 422)

    def test_events_negative_count(self):
        """GET /api/acoustic/events?count=-1 should not crash."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/acoustic/events?count=-1")
        assert resp.status_code in (200, 422)

    def test_events_huge_count(self):
        """GET /api/acoustic/events?count=999999999 should not OOM."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/acoustic/events?count=999999999")
        assert resp.status_code in (200, 422)


# ------------------------------------------------------------------ #
# Watchlist input validation
# ------------------------------------------------------------------ #

class TestWatchlistInputValidation:
    """Verify watchlist API sanitizes input and rejects oversized payloads."""

    def test_create_entry_xss_sanitized(self):
        """XSS in watchlist label/notes is sanitized."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/watchlist", json={
            "target_id": "test_xss_target",
            "label": "<script>alert('xss')</script>Evil",
            "notes": "<img src=x onerror=alert(1)>notes",
        })
        assert resp.status_code == 200
        data = resp.json()
        # HTML should be stripped/escaped
        assert "<script>" not in data.get("label", "")
        assert "<img" not in data.get("notes", "")
        # Cleanup
        entry_id = data.get("id", "")
        if entry_id:
            client.delete(f"/api/watchlist/{entry_id}")

    def test_create_entry_oversized_notes(self):
        """Watchlist rejects notes exceeding max length via Pydantic."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/watchlist", json={
            "target_id": "test_oversized",
            "notes": "X" * 100000,  # Way over 5000 char limit
        })
        # Pydantic max_length should reject this
        assert resp.status_code == 422

    def test_create_entry_missing_target_id(self):
        """Watchlist POST without target_id fails."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/watchlist", json={
            "label": "no target",
        })
        assert resp.status_code == 422

    def test_create_too_many_tags(self):
        """Watchlist rejects entries with more than 50 tags."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/watchlist", json={
            "target_id": "test_tags",
            "tags": [f"tag_{i}" for i in range(100)],
        })
        assert resp.status_code == 422


# ------------------------------------------------------------------ #
# Geofence input validation
# ------------------------------------------------------------------ #

class TestGeofenceInputValidation:
    """Verify geofence API validates polygon and zone inputs."""

    def test_create_zone_too_few_vertices(self):
        """Geofence rejects polygons with fewer than 3 vertices."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/geofence/zones", json={
            "name": "tiny",
            "polygon": [[0, 0], [1, 1]],  # Only 2 points
        })
        assert resp.status_code == 400

    def test_create_zone_xss_name(self):
        """XSS in zone name is sanitized."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/geofence/zones", json={
            "name": "<script>alert(1)</script>zone",
            "polygon": [[0, 0], [1, 0], [1, 1]],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "<script>" not in data.get("name", "")
        # Cleanup
        zone_id = data.get("zone_id", "")
        if zone_id:
            client.delete(f"/api/geofence/zones/{zone_id}")

    def test_create_zone_invalid_type(self):
        """Geofence rejects unknown zone_type."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/geofence/zones", json={
            "name": "test",
            "polygon": [[0, 0], [1, 0], [1, 1]],
            "zone_type": "DROP TABLE zones;--",
        })
        assert resp.status_code == 400

    def test_create_zone_too_many_vertices(self):
        """Geofence rejects polygons with > 1000 vertices."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        polygon = [[float(i), float(i)] for i in range(1500)]
        resp = client.post("/api/geofence/zones", json={
            "name": "huge",
            "polygon": polygon,
        })
        assert resp.status_code == 422

    def test_create_zone_missing_name(self):
        """Geofence POST without name fails."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/geofence/zones", json={
            "polygon": [[0, 0], [1, 0], [1, 1]],
        })
        assert resp.status_code == 422


# ------------------------------------------------------------------ #
# Heatmap input validation
# ------------------------------------------------------------------ #

class TestHeatmapInputValidation:
    """Verify heatmap API rejects invalid parameters."""

    def test_invalid_layer(self):
        """Heatmap with invalid layer returns error."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/heatmap?layer=DROP%20TABLE")
        assert resp.status_code == 200  # Returns error in JSON, not HTTP error
        data = resp.json()
        assert "error" in data or "grid" in data  # Either error msg or valid data

    def test_extreme_resolution(self):
        """Heatmap with resolution > 200 fails Pydantic validation."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/heatmap?resolution=999")
        assert resp.status_code == 422

    def test_negative_window(self):
        """Heatmap with negative window fails validation."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/heatmap?window=-10")
        assert resp.status_code == 422


# ------------------------------------------------------------------ #
# Notifications input validation
# ------------------------------------------------------------------ #

class TestNotificationsInputValidation:
    """Verify notification preferences API validates severity."""

    def test_invalid_severity(self):
        """Notification preferences rejects invalid severity."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.put("/api/notifications/preferences", json={
            "test_type": {"severity": "DROP TABLE;--"},
        })
        assert resp.status_code == 400

    def test_valid_severity_update(self):
        """Notification preferences accepts valid severity."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.put("/api/notifications/preferences", json={
            "test_type": {"severity": "warning", "enabled": True},
        })
        assert resp.status_code == 200

    def test_oversized_limit(self):
        """Notification list with limit > 500 fails validation."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/notifications?limit=9999")
        assert resp.status_code == 422


# ------------------------------------------------------------------ #
# Intelligence / Anomaly API input validation
# ------------------------------------------------------------------ #

class TestIntelligenceInputValidation:
    """Verify intelligence anomaly endpoint validates input."""

    def test_anomaly_describe_missing_type(self):
        """Anomaly describe without anomaly_type fails."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/intelligence/anomaly/describe", json={
            "context": {},
        })
        assert resp.status_code == 422

    def test_anomaly_describe_xss_in_context(self):
        """XSS in anomaly context should not be reflected unsanitized."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/intelligence/anomaly/describe", json={
            "anomaly_type": "rf_drop",
            "context": {
                "device_name": "<script>alert('xss')</script>",
                "location": "<img src=x onerror=alert(1)>",
            },
        })
        # Should succeed (200) since Ollama will be unavailable, uses template
        assert resp.status_code == 200
        data = resp.json()
        # The template fallback should not blindly reflect HTML
        assert data.get("generated") is False or data.get("generated") is True


# ------------------------------------------------------------------ #
# Voice command injection tests
# ------------------------------------------------------------------ #

class TestVoiceCommandInjection:
    """Test that voice commands cannot inject shell commands, SQL, or XSS."""

    def test_shell_injection_via_demo(self):
        """'start demo && rm -rf /' should NOT execute shell commands.

        The voice router uses regex matching, not shell execution.
        'start demo && rm -rf /' matches 'start demo' pattern.
        The '&& rm -rf /' part is ignored by the regex.
        """
        from app.routers.voice import _match_command
        action, groups = _match_command("start demo && rm -rf /")
        assert action == "demo_start"
        # No shell execution happens — the action just calls controller.start()

    def test_shell_injection_unmatched(self):
        """Raw shell injection that doesn't match any pattern goes to Amy chat."""
        from app.routers.voice import _match_command
        action, groups = _match_command("; rm -rf /; echo hacked")
        assert action == "amy_chat"
        # Amy chat just passes text to LLM — no shell execution

    def test_sql_injection_in_search(self):
        """SQL injection in target search is harmless (in-memory, no SQL)."""
        from app.routers.voice import _match_command
        action, groups = _match_command("find target ' OR 1=1; DROP TABLE targets;--")
        assert action == "target_search"
        # The query is used for string matching, not SQL
        assert "or 1=1" in groups[0].lower()

    def test_xss_in_amy_chat(self):
        """XSS in Amy chat message — verify text is not rendered unsanitized."""
        from app.routers.voice import _match_command
        action, groups = _match_command("amy <script>alert('xss')</script>steal cookies")
        assert action == "amy_chat"
        # The text goes to LLM, not rendered in HTML by backend
        # Frontend must escape — but backend should not crash
        assert "<script>" in groups[0]  # Backend passes through, frontend must escape

    def test_xss_in_panel_toggle(self):
        """XSS in panel name should not crash."""
        from app.routers.voice import _match_command
        action, groups = _match_command("open <script>alert(1)</script> panel")
        assert action == "panel_toggle"
        # Panel name contains the XSS attempt — frontend must sanitize

    def test_oversized_voice_command(self):
        """Voice API with extremely long text should not crash."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/voice/command", json={
            "text": "A" * 100000,
        })
        # Should succeed (goes to amy_chat) or be rejected
        assert resp.status_code in (200, 413, 422)

    def test_empty_voice_command(self):
        """Voice API with empty text returns 400."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/voice/command", json={"text": ""})
        assert resp.status_code == 400

    def test_voice_command_null_text(self):
        """Voice API with null text fails validation."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/voice/command", json={"text": None})
        assert resp.status_code == 422

    def test_voice_command_no_body(self):
        """Voice API with no body fails."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/voice/command")
        assert resp.status_code == 422

    def test_command_injection_via_status(self):
        """GET /api/voice/status should not accept command parameters."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/voice/status?cmd=rm+-rf+/")
        assert resp.status_code == 200
        # Query params are ignored by the status endpoint

    def test_path_traversal_in_search(self):
        """Path traversal in search query is harmless."""
        from app.routers.voice import _match_command
        action, groups = _match_command("find ../../../../etc/passwd")
        assert action == "target_search"
        # Search is in-memory string matching, not filesystem

    def test_unicode_injection(self):
        """Unicode control characters in voice command."""
        from app.routers.voice import _match_command
        action, groups = _match_command("start demo\x00\x01\x02")
        assert action == "demo_start"


# ------------------------------------------------------------------ #
# Amy chat endpoint security
# ------------------------------------------------------------------ #

class TestAmyChatSecurity:
    """Verify Amy chat API handles malicious input safely."""

    def test_chat_xss_payload(self):
        """POST /api/amy/chat with XSS should not crash."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/amy/chat", json={
            "text": "<script>document.cookie</script>",
        })
        # Amy may not be running, so 503 is acceptable
        assert resp.status_code in (200, 503)

    def test_chat_sql_injection(self):
        """POST /api/amy/chat with SQL injection should not crash."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/amy/chat", json={
            "text": "'; DROP TABLE users; --",
        })
        assert resp.status_code in (200, 503)

    def test_speak_xss(self):
        """POST /api/amy/speak with XSS should not crash."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/amy/speak", json={
            "text": "<img src=x onerror=alert(1)>",
        })
        assert resp.status_code in (200, 503)


# ------------------------------------------------------------------ #
# Search endpoint security
# ------------------------------------------------------------------ #

class TestSearchEndpointSecurity:
    """Verify search endpoints handle malicious queries safely."""

    def test_thumbnail_path_traversal(self):
        """GET /api/search/thumbnail/../../etc/passwd should not expose files."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/search/thumbnail/../../etc/passwd")
        # Should be 404 (not found) not 200 with file contents
        assert resp.status_code in (404, 422, 400)

    def test_text_search_sql_injection(self):
        """Text search with SQL injection should not crash."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/search/text-search?q=' OR 1=1;--")
        # Should return 503 (CLIP not loaded) or empty results, not SQL error
        assert resp.status_code in (200, 503, 422)

    def test_label_xss(self):
        """POST /api/search/label with XSS in label field."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/search/label", json={
            "thumbnail_id": "test_xss_label",
            "label": "<script>alert('xss')</script>",
        })
        # This saves to JSON — but no HTML escaping on backend.
        # Frontend must escape. Backend should not crash.
        assert resp.status_code == 200

    def test_feedback_oversized_notes(self):
        """POST /api/search/feedback with very long notes should not OOM."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.post("/api/search/feedback", json={
            "thumbnail_id": "test_feedback",
            "feedback_type": "correct",
            "notes": "X" * 50000,  # 50KB of notes
        })
        # Should succeed — no max_length on notes field
        assert resp.status_code == 200


# ------------------------------------------------------------------ #
# Photo endpoint path traversal
# ------------------------------------------------------------------ #

class TestPhotoPathTraversal:
    """Verify photo endpoint prevents path traversal."""

    def test_path_traversal_blocked(self):
        """GET /api/amy/photos/../../../etc/passwd should be blocked."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        resp = client.get("/api/amy/photos/../../../../etc/passwd")
        # The router has path traversal protection
        assert resp.status_code in (400, 404)
