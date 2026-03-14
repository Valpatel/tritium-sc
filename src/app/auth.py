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
    """Validate an API key against configured keys.

    Returns user dict if valid, None otherwise.
    API keys are configured via API_KEYS env var (comma-separated).
    """
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


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    """Dependency that requires valid authentication.

    Supports two authentication methods:
    1. JWT Bearer token (Authorization: Bearer <token>)
    2. API key (X-API-Key: <key>)

    When auth_enabled=False, returns a default admin user.
    """
    if not settings.auth_enabled:
        return {"sub": "admin", "role": "admin"}

    # Try API key first (stateless, for scripts/integrations)
    api_key = request.headers.get("X-API-Key")
    if api_key:
        user = _validate_api_key(api_key)
        if user:
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
    """Hash password using SHA-256 with salt (MVP — use bcrypt in production)."""
    import hashlib
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash."""
    import hashlib
    if ":" not in stored_hash:
        return False
    salt, expected = stored_hash.split(":", 1)
    actual = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return secrets.compare_digest(actual, expected)
