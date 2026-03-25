# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Rate limiting middleware for production deployment.

Uses a sliding window counter per IP address AND per authenticated user.
Only active when rate_limit_enabled=True in config. Exempt paths include
WebSocket and health check endpoints.

When auth is enabled, authenticated users are rate-limited by their user
identity (JWT sub or API key name) instead of IP. Different roles get
different rate limits:

    admin:    unlimited (no rate limit)
    operator: 100 requests/minute
    observer: 30 requests/minute
    default:  same as config rate_limit_requests/window
"""

import time
from collections import defaultdict
from typing import Optional

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import settings


# Exempt paths — never rate limited
EXEMPT_PATHS = {
    "/ws/live",
    "/api/auth/status",
    "/health",
    "/",
}

# Exempt prefixes
EXEMPT_PREFIXES = (
    "/static/",
    "/frontend/",
    "/ws/",
)

# Per-role rate limits (requests per minute). None = unlimited.
ROLE_RATE_LIMITS: dict[str, Optional[int]] = {
    "admin": None,       # Unlimited
    "operator": 100,     # 100/min
    "observer": 30,      # 30/min
}


class RateLimitEntry:
    """Sliding window rate limit tracker for a single key (IP or user)."""

    __slots__ = ("requests", "window_start")

    def __init__(self) -> None:
        self.requests: int = 0
        self.window_start: float = time.monotonic()

    def check(self, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, remaining)."""
        now = time.monotonic()
        elapsed = now - self.window_start

        if elapsed > window_seconds:
            # Window expired — reset
            self.requests = 1
            self.window_start = now
            return True, max_requests - 1

        self.requests += 1
        remaining = max(0, max_requests - self.requests)
        return self.requests <= max_requests, remaining


def _extract_user_from_request(request: Request) -> Optional[dict]:
    """Try to extract authenticated user info from the request without
    full auth dependency resolution. Checks JWT and API key headers.

    Returns dict with 'sub' and 'role' keys, or None if unauthenticated.
    This is a lightweight check — it does NOT enforce auth, just peeks
    at credentials for rate-limit keying purposes.
    """
    if not settings.auth_enabled:
        return None

    # Check API key header
    api_key = request.headers.get("X-API-Key")
    if api_key:
        try:
            from app.auth import _validate_api_key
            user = _validate_api_key(api_key)
            if user:
                return user
        except Exception:
            pass

    # Check Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            from app.auth import decode_token
            payload = decode_token(token)
            return {"sub": payload.get("sub", ""), "role": payload.get("role", "user")}
        except Exception:
            pass

    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using per-IP and per-user sliding window counters.

    When auth is enabled and a valid token/API key is present:
      - Rate limit key = "user:{sub}" instead of IP
      - Rate limit = role-based (admin=unlimited, operator=100/min, observer=30/min)

    When auth is disabled or request is unauthenticated:
      - Rate limit key = IP address (original behavior)
      - Rate limit = configured default
    """

    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._entries: dict[str, RateLimitEntry] = defaultdict(RateLimitEntry)
        self._cleanup_counter = 0

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip if rate limiting disabled
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # Check exempt paths
        path = request.url.path
        if path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES):
            return await call_next(request)

        # Determine rate limit key and max requests
        rate_key, max_reqs = self._resolve_rate_key(request)

        # Admin role = unlimited
        if max_reqs is None:
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = "unlimited"
            response.headers["X-RateLimit-Remaining"] = "unlimited"
            return response

        entry = self._entries[rate_key]
        allowed, remaining = entry.check(max_reqs, self.window_seconds)

        if not allowed:
            logger.warning(f"Rate limit exceeded for {rate_key} on {path}")
            return Response(
                content='{"detail": "Rate limit exceeded. Try again later."}',
                status_code=429,
                media_type="application/json",
                headers={
                    "X-RateLimit-Limit": str(max_reqs),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(entry.window_start + self.window_seconds)),
                    "Retry-After": str(self.window_seconds),
                },
            )

        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(max_reqs)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        # Periodic cleanup of stale entries
        self._cleanup_counter += 1
        if self._cleanup_counter >= 1000:
            self._cleanup()
            self._cleanup_counter = 0

        return response

    def _resolve_rate_key(self, request: Request) -> tuple[str, Optional[int]]:
        """Determine rate limit key and max requests for this request.

        Returns:
            (rate_key, max_requests) where max_requests=None means unlimited.
        """
        # Try to extract authenticated user
        user = _extract_user_from_request(request)

        if user and user.get("sub"):
            role = user.get("role", "user")
            sub = user["sub"]
            rate_key = f"user:{sub}"

            # Role-based rate limit
            role_limit = ROLE_RATE_LIMITS.get(role)
            if role in ROLE_RATE_LIMITS:
                return rate_key, role_limit  # None for admin = unlimited
            else:
                # Unknown role — use default
                return rate_key, self.max_requests

        # Fall back to IP-based
        client_ip = self._get_client_ip(request)
        return f"ip:{client_ip}", self.max_requests

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP from request using trusted proxy validation."""
        from app.client_ip import get_client_ip
        return get_client_ip(request)

    def _cleanup(self) -> None:
        """Remove stale rate limit entries."""
        now = time.monotonic()
        stale = [
            key for key, entry in self._entries.items()
            if (now - entry.window_start) > self.window_seconds * 2
        ]
        for key in stale:
            del self._entries[key]
