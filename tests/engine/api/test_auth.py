# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for authentication module."""

import os
import pytest


# Ensure auth is disabled by default for tests
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key-32-chars-long-ok")


class TestAuthModule:
    """Test auth module imports and basic functions."""

    def test_import(self):
        from app.auth import (
            authenticate_user,
            create_access_token,
            create_refresh_token,
            decode_token,
            init_default_admin,
            optional_auth,
            require_auth,
        )
        assert callable(create_access_token)
        assert callable(decode_token)
        assert callable(init_default_admin)

    def test_password_hashing_bcrypt(self):
        from app.auth import _hash_password, _verify_password
        hashed = _hash_password("test123")
        # bcrypt hashes start with $2b$
        assert hashed.startswith("$2b$")
        assert _verify_password("test123", hashed)
        assert not _verify_password("wrong", hashed)

    def test_legacy_sha256_backward_compat(self):
        """Old SHA-256 hashes should still verify (with deprecation warning)."""
        import hashlib
        import secrets as _secrets
        from app.auth import _verify_password, _is_legacy_sha256_hash
        salt = _secrets.token_hex(16)
        legacy_hash = f"{salt}:{hashlib.sha256(f'{salt}mypass'.encode()).hexdigest()}"
        assert _is_legacy_sha256_hash(legacy_hash)
        assert _verify_password("mypass", legacy_hash)
        assert not _verify_password("wrong", legacy_hash)

    def test_bcrypt_hash_not_detected_as_legacy(self):
        from app.auth import _hash_password, _is_legacy_sha256_hash
        hashed = _hash_password("test123")
        assert not _is_legacy_sha256_hash(hashed)

    def test_create_access_token(self):
        from app.auth import create_access_token, decode_token
        token = create_access_token("testuser", "admin")
        assert isinstance(token, str)
        assert len(token) > 20

        payload = decode_token(token)
        assert payload["sub"] == "testuser"
        assert payload["role"] == "admin"
        assert "jti" in payload
        assert "exp" in payload

    def test_create_refresh_token(self):
        from app.auth import create_refresh_token, decode_token
        token = create_refresh_token("testuser")
        payload = decode_token(token)
        assert payload["sub"] == "testuser"
        assert payload["type"] == "refresh"

    def test_authenticate_user_no_users(self):
        from app.auth import authenticate_user
        result = authenticate_user("nobody", "nopass")
        assert result is None

    def test_init_default_admin(self):
        from app.auth import _users, authenticate_user, init_default_admin
        from app.config import settings

        # Save original values
        orig_enabled = settings.auth_enabled
        orig_password = settings.auth_admin_password

        try:
            settings.auth_enabled = True
            settings.auth_admin_password = "testpass"
            init_default_admin()

            result = authenticate_user("admin", "testpass")
            assert result is not None
            assert result["sub"] == "admin"
            assert result["role"] == "admin"

            # Wrong password should fail
            assert authenticate_user("admin", "wrong") is None
        finally:
            settings.auth_enabled = orig_enabled
            settings.auth_admin_password = orig_password
            _users.clear()


class TestAPIKeyStore:
    """Test the in-memory API key store with rotation and grace periods."""

    def test_create_key(self):
        from app.auth import APIKeyStore
        store = APIKeyStore()
        result = store.create_key(name="test-key", role="admin")
        assert result["key_id"].startswith("ak_")
        assert result["api_key"].startswith("trk_")
        assert result["name"] == "test-key"

    def test_validate_key(self):
        from app.auth import APIKeyStore
        store = APIKeyStore()
        result = store.create_key(name="validate-test")
        user = store.validate(result["api_key"])
        assert user is not None
        assert user["role"] == "admin"
        assert user["key_id"] == result["key_id"]

    def test_validate_invalid_key(self):
        from app.auth import APIKeyStore
        store = APIKeyStore()
        assert store.validate("trk_nonexistent") is None

    def test_rotate_key(self):
        from app.auth import APIKeyStore
        store = APIKeyStore()
        created = store.create_key(name="rotate-test")
        old_key = created["api_key"]

        rotated = store.rotate_key(created["key_id"], grace_period_seconds=3600)
        assert rotated is not None
        new_key = rotated["api_key"]
        assert new_key != old_key

        # New key works
        assert store.validate(new_key) is not None
        # Old key still works during grace period
        assert store.validate(old_key) is not None

    def test_rotate_key_not_found(self):
        from app.auth import APIKeyStore
        store = APIKeyStore()
        assert store.rotate_key("ak_nonexistent") is None

    def test_rotate_expired_grace(self):
        from app.auth import APIKeyStore
        store = APIKeyStore()
        created = store.create_key(name="grace-test")
        old_key = created["api_key"]

        # Rotate with 0-second grace period (immediately expired)
        rotated = store.rotate_key(created["key_id"], grace_period_seconds=0)
        assert rotated is not None
        # Old key should be expired immediately
        assert store.validate(old_key) is None

    def test_revoke_key(self):
        from app.auth import APIKeyStore
        store = APIKeyStore()
        created = store.create_key(name="revoke-test")
        assert store.validate(created["api_key"]) is not None

        ok = store.revoke_key(created["key_id"])
        assert ok is True
        assert store.validate(created["api_key"]) is None

    def test_revoke_nonexistent(self):
        from app.auth import APIKeyStore
        store = APIKeyStore()
        assert store.revoke_key("ak_nonexistent") is False

    def test_list_keys(self):
        from app.auth import APIKeyStore
        store = APIKeyStore()
        store.create_key(name="key-1")
        store.create_key(name="key-2")
        keys = store.list_keys()
        assert len(keys) == 2
        names = {k["name"] for k in keys}
        assert names == {"key-1", "key-2"}

    def test_audit_log(self):
        from app.auth import APIKeyStore
        store = APIKeyStore()
        created = store.create_key(name="audit-test")
        store.rotate_key(created["key_id"])
        store.revoke_key(created["key_id"])

        log = store.get_audit_log()
        actions = [e["action"] for e in log]
        assert "create" in actions
        assert "rotate" in actions
        assert "revoke" in actions

    def test_key_with_expiry(self):
        from app.auth import APIKeyStore
        store = APIKeyStore()
        result = store.create_key(name="expiry-test", expires_in_days=30)
        assert result["expires_at"] is not None
        # Key should be valid now
        assert store.validate(result["api_key"]) is not None


class TestAuthRouter:
    """Test auth API router."""

    def test_import(self):
        from app.routers.auth import router
        assert router is not None

    def test_auth_status_endpoint(self):
        """Auth status endpoint should be available."""
        from app.routers.auth import auth_status
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(auth_status())
        assert "auth_enabled" in result


class TestAPIKeyEndpoints:
    """Test the API key management HTTP endpoints."""

    def _make_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers.auth import router
        from app.auth import require_admin

        app = FastAPI()
        # Override auth to always return admin
        app.dependency_overrides[require_admin] = lambda: {"sub": "admin", "role": "admin"}
        app.include_router(router)
        return TestClient(app)

    def test_create_api_key(self):
        client = self._make_client()
        resp = client.post("/api/auth/api-keys", json={"name": "test-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["key_id"].startswith("ak_")
        assert data["api_key"].startswith("trk_")

    def test_list_api_keys(self):
        client = self._make_client()
        client.post("/api/auth/api-keys", json={"name": "list-test"})
        resp = client.get("/api/auth/api-keys")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 0

    def test_rotate_api_key(self):
        client = self._make_client()
        created = client.post("/api/auth/api-keys", json={"name": "rotate-ep"}).json()
        resp = client.post("/api/auth/api-keys/rotate", json={
            "key_id": created["key_id"],
            "grace_period_seconds": 3600,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_key"] != created["api_key"]
        assert data["grace_period_seconds"] == 3600

    def test_rotate_nonexistent_key(self):
        client = self._make_client()
        resp = client.post("/api/auth/api-keys/rotate", json={
            "key_id": "ak_nonexistent",
        })
        assert resp.status_code == 404

    def test_revoke_api_key(self):
        client = self._make_client()
        created = client.post("/api/auth/api-keys", json={"name": "revoke-ep"}).json()
        resp = client.post("/api/auth/api-keys/revoke", json={
            "key_id": created["key_id"],
        })
        assert resp.status_code == 200
        assert resp.json()["revoked"] is True

    def test_audit_log_endpoint(self):
        client = self._make_client()
        client.post("/api/auth/api-keys", json={"name": "audit-ep"})
        resp = client.get("/api/auth/api-keys/audit")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 0
