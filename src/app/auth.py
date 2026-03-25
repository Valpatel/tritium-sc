# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Authentication & authorization middleware for production deployment.

Provides JWT-based authentication when `auth_enabled=True` in config.
In development mode (auth_enabled=False), all requests pass through.

Usage:
    from app.auth import require_auth, optional_auth, create_access_token

    @router.get("/protected")
    async def protected_endpoint(user: dict = Depends(require_auth)):
        return {"user": user["sub"]}
"""

import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

# JWT support — use tritium-lib if available, fall back to PyJWT
try:
    import jwt
    HAS_JWT = True
except ImportError:
    HAS_JWT = False

from app.config import settings


# Security scheme — optional so Swagger UI works without auth
_security = HTTPBearer(auto_error=False)


# In-memory user store for MVP (replace with database in production)
_users: dict[str, dict] = {}
_refresh_tokens: dict[str, dict] = {}  # token -> {sub, exp}


# ---------------------------------------------------------------------------
# API Key Store — supports dynamic key management and rotation with grace
# ---------------------------------------------------------------------------

class APIKeyStore:
    """Thread-safe in-memory store for API keys with rotation and scoping.

    Keys can be created, rotated, and revoked.  On rotation, the old key
    remains valid for a configurable grace period (default 1 hour).
    All mutations are logged to an in-memory audit trail.

    Scoping: Each API key can be assigned a scope that restricts which
    endpoints it can access:
        - "full"      — all endpoints (default, backward compatible)
        - "read-only" — only GET/HEAD/OPTIONS requests
        - "admin"     — all endpoints including admin-only routes
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key_id -> {key_id, key_hash, name, role, created_at, expires_at, revoked}
        self._keys: dict[str, dict] = {}
        # Plaintext key -> key_id (for fast lookup; only live keys)
        self._key_index: dict[str, str] = {}
        # Grace-period keys: plaintext -> {key_id, expires_at}
        self._grace_keys: dict[str, dict] = {}
        # Audit log: list of {ts, action, key_id, detail}
        self._audit: list[dict] = []
        self._max_audit = 1000

    def _audit_log(self, action: str, key_id: str, detail: str = "") -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "key_id": key_id,
            "detail": detail,
        }
        self._audit.append(entry)
        if len(self._audit) > self._max_audit:
            self._audit = self._audit[-self._max_audit:]
        logger.info("API key audit: %s key_id=%s %s", action, key_id, detail)

    # Valid scopes for API keys
    VALID_SCOPES = ("full", "read-only", "admin")

    def create_key(self, name: str = "default", role: str = "admin",
                   expires_in_days: int = 0,
                   scope: str = "full") -> dict:
        """Create a new API key. Returns dict with plaintext key (shown once).

        Args:
            name: Human-readable name for the key.
            role: Role assigned to requests using this key.
            expires_in_days: Key expiry (0 = no expiry).
            scope: Access scope — "full" (all endpoints), "read-only"
                   (GET/HEAD/OPTIONS only), or "admin" (all + admin routes).
        """
        if scope not in self.VALID_SCOPES:
            scope = "full"

        key_id = f"ak_{secrets.token_hex(8)}"
        plaintext = f"trk_{secrets.token_urlsafe(32)}"
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(days=expires_in_days)).isoformat() if expires_in_days > 0 else None

        entry = {
            "key_id": key_id,
            "name": name,
            "role": role,
            "scope": scope,
            "created_at": now.isoformat(),
            "expires_at": expires_at,
            "revoked": False,
            "prefix": plaintext[:8],  # For identification without exposing full key
        }

        with self._lock:
            self._keys[key_id] = entry
            self._key_index[plaintext] = key_id
            self._audit_log("create", key_id, f"name={name} scope={scope}")

        return {"key_id": key_id, "api_key": plaintext, "name": name,
                "expires_at": expires_at, "scope": scope}

    def rotate_key(self, key_id: str, grace_period_seconds: int = 3600) -> Optional[dict]:
        """Rotate an API key: generate new key, old key valid for grace period.

        Returns dict with new plaintext key, or None if key_id not found.
        """
        with self._lock:
            old_entry = self._keys.get(key_id)
            if old_entry is None or old_entry["revoked"]:
                return None

            # Find old plaintext key
            old_plaintext = None
            for pt, kid in self._key_index.items():
                if kid == key_id:
                    old_plaintext = pt
                    break

            # Generate new key
            new_plaintext = f"trk_{secrets.token_urlsafe(32)}"
            now = datetime.now(timezone.utc)

            # Move old key to grace period
            if old_plaintext:
                del self._key_index[old_plaintext]
                grace_expires = now + timedelta(seconds=grace_period_seconds)
                self._grace_keys[old_plaintext] = {
                    "key_id": key_id,
                    "expires_at": grace_expires.isoformat(),
                    "expires_ts": grace_expires.timestamp(),
                }

            # Install new key
            self._key_index[new_plaintext] = key_id
            old_entry["prefix"] = new_plaintext[:8]
            old_entry["rotated_at"] = now.isoformat()
            self._audit_log("rotate", key_id,
                            f"grace_period={grace_period_seconds}s")

        return {"key_id": key_id, "api_key": new_plaintext,
                "grace_period_seconds": grace_period_seconds}

    def revoke_key(self, key_id: str) -> bool:
        """Revoke an API key immediately (no grace period)."""
        with self._lock:
            entry = self._keys.get(key_id)
            if entry is None:
                return False
            entry["revoked"] = True
            # Remove from active index
            to_remove = [pt for pt, kid in self._key_index.items() if kid == key_id]
            for pt in to_remove:
                del self._key_index[pt]
            # Remove from grace keys
            to_remove_grace = [pt for pt, g in self._grace_keys.items() if g["key_id"] == key_id]
            for pt in to_remove_grace:
                del self._grace_keys[pt]
            self._audit_log("revoke", key_id)
            return True

    def validate(self, api_key: str) -> Optional[dict]:
        """Validate an API key. Returns user dict or None.

        Checks active keys first, then grace-period keys.
        Expired grace keys are cleaned up lazily.
        """
        with self._lock:
            # Check active keys
            key_id = self._key_index.get(api_key)
            if key_id:
                entry = self._keys.get(key_id, {})
                if entry.get("revoked"):
                    return None
                # Check expiry
                if entry.get("expires_at"):
                    exp = datetime.fromisoformat(entry["expires_at"])
                    if datetime.now(timezone.utc) > exp:
                        entry["revoked"] = True
                        return None
                return {"sub": f"apikey:{entry.get('name', key_id)}",
                        "role": entry.get("role", "admin"),
                        "key_id": key_id,
                        "scope": entry.get("scope", "full"),
                        "auth_method": "api_key"}

            # Check grace-period keys
            grace = self._grace_keys.get(api_key)
            if grace:
                now = time.time()
                if now > grace["expires_ts"]:
                    del self._grace_keys[api_key]
                    return None
                entry = self._keys.get(grace["key_id"], {})
                if entry.get("revoked"):
                    return None
                return {"sub": f"apikey:{entry.get('name', grace['key_id'])}",
                        "role": entry.get("role", "admin"),
                        "key_id": grace["key_id"],
                        "scope": entry.get("scope", "full"),
                        "auth_method": "api_key_grace"}

        return None

    def list_keys(self) -> list[dict]:
        """List all API keys (without plaintext values)."""
        with self._lock:
            return [
                {k: v for k, v in entry.items()}
                for entry in self._keys.values()
            ]

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """Return recent audit log entries."""
        return self._audit[-limit:]


# Singleton instance
api_key_store = APIKeyStore()


def _get_secret_key() -> str:
    """Get JWT secret key, generating one if not configured."""
    if settings.auth_secret_key:
        return settings.auth_secret_key
    # Generate ephemeral key (valid only for this server session)
    if not hasattr(_get_secret_key, "_ephemeral"):
        _get_secret_key._ephemeral = secrets.token_hex(32)
        logger.warning("No auth_secret_key configured — using ephemeral key (tokens won't survive restart)")
    return _get_secret_key._ephemeral


def create_access_token(subject: str, role: str = "user", extra: dict | None = None) -> str:
    """Create a JWT access token."""
    if not HAS_JWT:
        raise HTTPException(status_code=500, detail="JWT library not installed")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.auth_access_token_expire_minutes),
        "jti": secrets.token_hex(16),
    }
    if extra:
        payload.update(extra)

    return jwt.encode(payload, _get_secret_key(), algorithm=settings.auth_algorithm)


def create_refresh_token(subject: str) -> str:
    """Create a refresh token for long-lived sessions."""
    if not HAS_JWT:
        raise HTTPException(status_code=500, detail="JWT library not installed")

    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=settings.auth_refresh_token_expire_days)
    payload = {
        "sub": subject,
        "type": "refresh",
        "iat": now,
        "exp": exp,
        "jti": secrets.token_hex(16),
    }
    token = jwt.encode(payload, _get_secret_key(), algorithm=settings.auth_algorithm)
    _refresh_tokens[payload["jti"]] = {"sub": subject, "exp": exp.timestamp()}
    return token


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    if not HAS_JWT:
        raise HTTPException(status_code=500, detail="JWT library not installed")

    try:
        payload = jwt.decode(
            token,
            _get_secret_key(),
            algorithms=[settings.auth_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


def _validate_api_key(api_key: str) -> Optional[dict]:
    """Validate an API key against configured keys and the dynamic key store.

    Returns user dict if valid, None otherwise.
    Checks:
    1. Dynamic API key store (supports rotation with grace periods)
    2. Static keys from API_KEYS env var (comma-separated, legacy support)
    """
    # Check dynamic key store first
    result = api_key_store.validate(api_key)
    if result is not None:
        return result

    # Fall back to static env-var keys
    if not settings.api_keys:
        return None

    configured_keys = [k.strip() for k in settings.api_keys.split(",") if k.strip()]
    if not configured_keys:
        return None

    # Constant-time comparison to prevent timing attacks
    for key in configured_keys:
        if secrets.compare_digest(api_key, key):
            return {"sub": "api_key_user", "role": "admin", "auth_method": "api_key"}

    return None


# HTTP methods allowed for read-only scoped API keys
READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}


def _check_api_key_scope(user: dict, request: Request) -> None:
    """Enforce API key scope restrictions.

    Raises HTTPException if the request method is not allowed by the
    key's scope. Only applies to API key auth (scope field present).
    """
    scope = user.get("scope")
    if scope is None or scope == "full" or scope == "admin":
        return  # No restriction

    if scope == "read-only" and request.method not in READ_ONLY_METHODS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key scope '{scope}' does not allow {request.method} requests",
        )


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    """Dependency that requires valid authentication.

    Supports two authentication methods:
    1. JWT Bearer token (Authorization: Bearer <token>)
    2. API key (X-API-Key: <key>)

    When auth_enabled=False, returns a default admin user.
    API key scope is enforced: read-only keys cannot make write requests.
    """
    if not settings.auth_enabled:
        return {"sub": "admin", "role": "admin"}

    # Try API key first (stateless, for scripts/integrations)
    api_key = request.headers.get("X-API-Key")
    if api_key:
        user = _validate_api_key(api_key)
        if user:
            _check_api_key_scope(user, request)
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # Fall back to JWT Bearer token
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (use Bearer token or X-API-Key header)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return decode_token(credentials.credentials)


async def optional_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> Optional[dict]:
    """Dependency that optionally authenticates.

    Returns user dict if valid token/API key provided, None otherwise.
    Never raises — useful for endpoints that work with or without auth.
    """
    if not settings.auth_enabled:
        return {"sub": "admin", "role": "admin"}

    # Try API key
    api_key = request.headers.get("X-API-Key")
    if api_key:
        user = _validate_api_key(api_key)
        if user:
            return user

    # Try JWT
    if not credentials:
        return None

    try:
        return decode_token(credentials.credentials)
    except HTTPException:
        return None


async def require_admin(user: dict = Depends(require_auth)) -> dict:
    """Dependency that requires admin role."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


def require_role(*allowed_roles: str):
    """Factory that returns a dependency requiring one of the specified roles.

    Usage::

        @router.put("/sensitive")
        async def sensitive_endpoint(user: dict = Depends(require_role("admin", "commander"))):
            ...
    """

    async def _check_role(user: dict = Depends(require_auth)) -> dict:
        role = user.get("role", "")
        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(allowed_roles)}",
            )
        return user

    return _check_role


def init_default_admin() -> None:
    """Initialize the default admin user if auth is enabled and password is set."""
    if not settings.auth_enabled:
        return
    if not settings.auth_admin_password:
        logger.warning("auth_enabled=True but no auth_admin_password set — auth is effectively disabled")
        return

    _users[settings.auth_admin_username] = {
        "username": settings.auth_admin_username,
        "password_hash": _hash_password(settings.auth_admin_password),
        "role": "admin",
    }
    logger.info(f"Default admin user '{settings.auth_admin_username}' initialized")


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Authenticate a user by username and password."""
    user = _users.get(username)
    if not user:
        return None
    if not _verify_password(password, user["password_hash"]):
        return None
    return {"sub": username, "role": user["role"]}


def _hash_password(password: str) -> str:
    """Hash password using bcrypt with 12 rounds of key stretching."""
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def _is_legacy_sha256_hash(stored_hash: str) -> bool:
    """Detect legacy SHA-256 hashes (format: 32-hex-salt:64-hex-digest)."""
    if ":" not in stored_hash:
        return False
    parts = stored_hash.split(":", 1)
    # Legacy format: 32 hex chars salt + 64 hex chars SHA-256 digest
    return len(parts) == 2 and len(parts[0]) == 32 and len(parts[1]) == 64


def _verify_legacy_sha256(password: str, stored_hash: str) -> bool:
    """Verify password against legacy SHA-256 hash."""
    import hashlib
    salt, expected = stored_hash.split(":", 1)
    actual = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return secrets.compare_digest(actual, expected)


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash (bcrypt or legacy SHA-256)."""
    if _is_legacy_sha256_hash(stored_hash):
        logger.warning(
            "Legacy SHA-256 password hash detected — rehash with bcrypt recommended"
        )
        return _verify_legacy_sha256(password, stored_hash)
    # bcrypt hash (starts with $2b$ or $2a$)
    try:
        import bcrypt
        return bcrypt.checkpw(password.encode(), stored_hash.encode())
    except Exception:
        return False
