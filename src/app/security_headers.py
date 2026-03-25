# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Security headers middleware — CSP, X-Frame-Options, HSTS, etc.

Adds Content-Security-Policy and other security headers to all HTML
responses. Only active when csp_enabled=True in config. API JSON
responses get a subset of headers (no CSP needed for JSON).

HSTS (Strict-Transport-Security) is added only when tls_enabled=True
to avoid breaking plain HTTP development servers.

CSP script-src drops 'unsafe-inline' when auth_enabled=True (production
posture).  In dev mode (auth_enabled=False) 'unsafe-inline' is kept for
convenience.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import settings


# ------------------------------------------------------------------ #
# CSP policy builder
# ------------------------------------------------------------------ #

def _build_csp_policy(*, strict: bool = False) -> str:
    """Build a Content-Security-Policy string.

    Args:
        strict: When True, omit 'unsafe-inline' from script-src.
                When False (dev mode), keep it for convenience.
    """
    script_src = (
        "script-src 'self' https://unpkg.com https://cdnjs.cloudflare.com"
        if strict
        else "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com"
    )
    return (
        "default-src 'self'; "
        f"{script_src}; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org https://*.basemaps.cartocdn.com; "
        "font-src 'self' data: https://fonts.gstatic.com https://demotiles.maplibre.org; "
        "connect-src 'self' ws: wss: https://*.tile.openstreetmap.org https://*.basemaps.cartocdn.com "
        "https://tiles.openfreemap.org https://demotiles.maplibre.org; "
        "worker-src 'self' blob:; "
        "media-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )


# Dev-mode CSP (unsafe-inline allowed in script-src)
_CSP_POLICY = _build_csp_policy(strict=False)

# Production CSP (no unsafe-inline in script-src)
_CSP_POLICY_STRICT = _build_csp_policy(strict=True)

# HSTS header value — 2 years, include subdomains
_HSTS_VALUE = "max-age=63072000; includeSubDomains"

# Paths that should NOT get CSP (binary streams, SSE, etc.)
_CSP_EXEMPT_PREFIXES = (
    "/api/",
    "/ws/",
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # Always add these security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(self), payment=()"
        )

        # HSTS — only when TLS is enabled (never on plain HTTP dev servers)
        if settings.tls_enabled:
            response.headers["Strict-Transport-Security"] = _HSTS_VALUE

        # CSP only for HTML responses (not API/WebSocket/binary)
        if settings.csp_enabled:
            path = request.url.path
            content_type = response.headers.get("content-type", "")
            if (
                not path.startswith(_CSP_EXEMPT_PREFIXES)
                and "text/html" in content_type
            ):
                # Use strict CSP (no unsafe-inline) when auth is enabled
                policy = _CSP_POLICY_STRICT if settings.auth_enabled else _CSP_POLICY
                response.headers["Content-Security-Policy"] = policy

        return response
