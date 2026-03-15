# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Security headers middleware — CSP, X-Frame-Options, etc.

Adds Content-Security-Policy and other security headers to all HTML
responses. Only active when csp_enabled=True in config. API JSON
responses get a subset of headers (no CSP needed for JSON).
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import settings


# CSP policy — restrictive but compatible with vanilla JS + inline styles.
# self for scripts/styles, blob: for MJPEG camera feeds, data: for inline
# images, ws:/wss: for WebSocket, connect-src for API calls.
_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com; "
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

        # CSP only for HTML responses (not API/WebSocket/binary)
        if settings.csp_enabled:
            path = request.url.path
            content_type = response.headers.get("content-type", "")
            if (
                not path.startswith(_CSP_EXEMPT_PREFIXES)
                and "text/html" in content_type
            ):
                response.headers["Content-Security-Policy"] = _CSP_POLICY

        return response
