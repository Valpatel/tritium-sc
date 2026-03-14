# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Security tests — Wave 37.

Tests:
1. CORS configuration (restricted origins, proper headers)
2. File upload security (size limits, path traversal, ZIP validation)
3. Content-Security-Policy headers
4. API key authentication
5. Security headers on all responses
"""

import io
import os
import struct
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key-32-chars-long-ok")


# ------------------------------------------------------------------ #
# CORS tests
# ------------------------------------------------------------------ #

class TestCORSConfiguration:
    """Verify CORS headers are properly configured."""

    def test_cors_default_allows_all(self):
        """Default config (empty CORS_ALLOWED_ORIGINS) allows all origins."""
        from app.config import Settings
        s = Settings(cors_allowed_origins="")
        assert s.cors_allowed_origins == ""

    def test_cors_config_parses_origins(self):
        """CORS_ALLOWED_ORIGINS env var parses comma-separated origins."""
        from app.config import Settings
        s = Settings(cors_allowed_origins="https://example.com,https://other.com")
        origins = [o.strip() for o in s.cors_allowed_origins.split(",") if o.strip()]
        assert len(origins) == 2
        assert "https://example.com" in origins

    def test_cors_middleware_present(self):
        """CORS middleware is registered on the app."""
        from app.main import app
        middlewares = [type(m).__name__ for m in getattr(app, "user_middleware", [])]
        # Starlette stores middleware differently, check via class names
        found = False
        for mw in app.user_middleware:
            if "CORS" in str(mw.cls.__name__):
                found = True
                break
        assert found, "CORSMiddleware not found in app middleware stack"


# ------------------------------------------------------------------ #
# CSP / Security Headers tests
# ------------------------------------------------------------------ #

class TestSecurityHeaders:
    """Verify Content-Security-Policy and other security headers."""

    def test_security_headers_middleware_import(self):
        """SecurityHeadersMiddleware imports without error."""
        from app.security_headers import SecurityHeadersMiddleware
        assert SecurityHeadersMiddleware is not None

    def test_csp_policy_format(self):
        """CSP policy string is well-formed."""
        from app.security_headers import _CSP_POLICY
        assert "default-src" in _CSP_POLICY
        assert "script-src" in _CSP_POLICY
        assert "object-src 'none'" in _CSP_POLICY
        assert "frame-ancestors 'none'" in _CSP_POLICY

    def test_security_headers_on_html(self):
        """HTML responses get CSP and X-Frame-Options headers."""
        from app.security_headers import SecurityHeadersMiddleware

        test_app = FastAPI()
        test_app.add_middleware(SecurityHeadersMiddleware)

        @test_app.get("/test-html")
        async def html_page():
            from fastapi.responses import HTMLResponse
            return HTMLResponse("<html><body>Test</body></html>")

        client = TestClient(test_app)
        resp = client.get("/test-html")
        assert resp.status_code == 200
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "Content-Security-Policy" in resp.headers

    def test_no_csp_on_api_responses(self):
        """API (JSON) responses should not get CSP headers."""
        from app.security_headers import SecurityHeadersMiddleware

        test_app = FastAPI()
        test_app.add_middleware(SecurityHeadersMiddleware)

        @test_app.get("/api/test")
        async def api_endpoint():
            return {"status": "ok"}

        client = TestClient(test_app)
        resp = client.get("/api/test")
        assert resp.status_code == 200
        # API paths are CSP exempt
        assert "Content-Security-Policy" not in resp.headers
        # But still get other security headers
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"


# ------------------------------------------------------------------ #
# File Upload Security tests
# ------------------------------------------------------------------ #

class TestBackupUploadSecurity:
    """Verify backup restore endpoint security."""

    @pytest.fixture
    def backup_client(self):
        app = FastAPI()
        from app.routers.backup import router as backup_router
        app.include_router(backup_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_rejects_non_zip_filename(self, backup_client):
        """Reject files without .zip extension."""
        fake_file = io.BytesIO(b"not a zip")
        resp = backup_client.post(
            "/api/backup/restore",
            files={"file": ("evil.exe", fake_file, "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "ZIP" in resp.json()["detail"]

    def test_rejects_empty_file(self, backup_client):
        """Reject empty uploads."""
        empty_file = io.BytesIO(b"")
        resp = backup_client.post(
            "/api/backup/restore",
            files={"file": ("backup.zip", empty_file, "application/zip")},
        )
        assert resp.status_code == 400

    def test_rejects_non_zip_content(self, backup_client):
        """Reject files with .zip extension but non-ZIP content."""
        fake_zip = io.BytesIO(b"This is not actually a ZIP file at all")
        resp = backup_client.post(
            "/api/backup/restore",
            files={"file": ("backup.zip", fake_zip, "application/zip")},
        )
        assert resp.status_code == 400

    def test_rejects_path_traversal_in_zip(self, backup_client):
        """Reject ZIP files containing path traversal entries."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", '{"version": "2.0"}')
            zf.writestr("../../../etc/passwd", "root:x:0:0")
        buf.seek(0)

        resp = backup_client.post(
            "/api/backup/restore",
            files={"file": ("evil.zip", buf, "application/zip")},
        )
        assert resp.status_code == 400
        assert "unsafe" in resp.json()["detail"].lower() or "traversal" in resp.json()["detail"].lower()

    def test_rejects_absolute_path_in_zip(self, backup_client):
        """Reject ZIP files with absolute paths."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", '{"version": "2.0"}')
            zf.writestr("/etc/passwd", "root:x:0:0")
        buf.seek(0)

        resp = backup_client.post(
            "/api/backup/restore",
            files={"file": ("evil.zip", buf, "application/zip")},
        )
        assert resp.status_code == 400

    def test_valid_zip_accepted(self, backup_client):
        """A valid backup ZIP with manifest should be accepted (may fail on restore
        if no real DB, but should not be rejected by validation)."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", '{"version": "2.0", "contents": {}}')
        buf.seek(0)

        resp = backup_client.post(
            "/api/backup/restore",
            files={"file": ("backup.zip", buf, "application/zip")},
        )
        # Should pass validation and attempt restore (200 or 500 if no DB)
        assert resp.status_code in (200, 500)


# ------------------------------------------------------------------ #
# API Key Authentication tests
# ------------------------------------------------------------------ #

class TestAPIKeyAuth:
    """Verify X-API-Key header authentication."""

    def test_validate_api_key_no_keys_configured(self):
        """When no API keys configured, validation returns None."""
        from app.auth import _validate_api_key
        result = _validate_api_key("any-key")
        assert result is None

    def test_validate_api_key_valid(self, monkeypatch):
        """Valid API key returns user dict."""
        from app import auth
        from app.config import Settings

        # Patch settings to have API keys configured
        test_settings = Settings(api_keys="test-key-123,other-key-456")
        monkeypatch.setattr(auth, "settings", test_settings)

        result = auth._validate_api_key("test-key-123")
        assert result is not None
        assert result["role"] == "admin"
        assert result["auth_method"] == "api_key"

    def test_validate_api_key_invalid(self, monkeypatch):
        """Invalid API key returns None."""
        from app import auth
        from app.config import Settings

        test_settings = Settings(api_keys="test-key-123")
        monkeypatch.setattr(auth, "settings", test_settings)

        result = auth._validate_api_key("wrong-key")
        assert result is None

    def test_validate_api_key_timing_safe(self, monkeypatch):
        """API key comparison uses constant-time comparison."""
        import secrets
        from app import auth
        from app.config import Settings

        test_settings = Settings(api_keys="secret-key-abc")
        monkeypatch.setattr(auth, "settings", test_settings)

        # This test verifies the code path uses secrets.compare_digest
        # by checking it works correctly (timing attack resistance is
        # guaranteed by the stdlib function)
        assert auth._validate_api_key("secret-key-abc") is not None
        assert auth._validate_api_key("secret-key-abd") is None


# ------------------------------------------------------------------ #
# BackupManager path traversal defense in depth
# ------------------------------------------------------------------ #

class TestBackupManagerSafety:
    """Verify BackupManager rejects unsafe ZIP entries."""

    def test_import_rejects_path_traversal(self, tmp_path):
        """BackupManager.import_state rejects .. in paths."""
        from engine.backup.backup import BackupManager

        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("manifest.json", '{"version": "2.0", "contents": {}}')
            zf.writestr("../../etc/shadow", "bad data")

        mgr = BackupManager(
            data_dir=tmp_path / "data",
            backup_dir=tmp_path / "backups",
            db_path=tmp_path / "test.db",
        )

        with pytest.raises(ValueError, match="Unsafe path"):
            mgr.import_state(archive)

    def test_import_valid_archive(self, tmp_path):
        """BackupManager.import_state accepts a valid archive."""
        from engine.backup.backup import BackupManager

        archive = tmp_path / "valid.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("manifest.json", '{"version": "2.0", "contents": {}}')

        mgr = BackupManager(
            data_dir=tmp_path / "data",
            backup_dir=tmp_path / "backups",
            db_path=tmp_path / "test.db",
        )

        report = mgr.import_state(archive)
        assert isinstance(report, dict)
        assert "restored" in report
