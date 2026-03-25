# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Request audit logging middleware — logs every API request for compliance.

Logs method, path, status code, duration_ms, and client IP to the
AuditStore (SQLite-backed). Exempt paths include static files,
WebSocket upgrades, and high-frequency health checks to avoid
log bloat.
"""

import time
from pathlib import Path

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# Paths that generate too much noise to log every request
_EXEMPT_PREFIXES = (
    "/static/",
    "/frontend/",
    "/ws/",
)
_EXEMPT_EXACT = {
    "/health",
    "/favicon.ico",
}

# Lazy-init singleton
_audit_store = None
_DB_PATH = Path("data/audit.db")


def _get_audit_store():
    """Lazy-initialise the AuditStore singleton."""
    global _audit_store
    if _audit_store is None:
        try:
            from tritium_lib.store.audit_log import AuditStore
            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _audit_store = AuditStore(_DB_PATH)
        except Exception as e:
            logger.warning(f"AuditStore init failed: {e}")
    return _audit_store


def get_audit_store():
    """Public accessor for the audit store singleton."""
    return _get_audit_store()


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every API request with method, path, status, duration, client IP."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip noisy paths
        if path in _EXEMPT_EXACT or path.startswith(_EXEMPT_PREFIXES):
            return await call_next(request)

        method = request.method
        client_ip = _get_client_ip(request)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Log the failure and re-raise
            duration_ms = (time.perf_counter() - start) * 1000
            _log_request(method, path, 500, duration_ms, client_ip)
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        status_code = response.status_code

        _log_request(method, path, status_code, duration_ms, client_ip)

        return response


def _get_client_ip(request: Request) -> str:
    """Get client IP from request using trusted proxy validation."""
    from app.client_ip import get_client_ip
    return get_client_ip(request)


def _log_request(method: str, path: str, status: int, duration_ms: float, client_ip: str) -> None:
    """Write request to audit store (fire-and-forget)."""
    store = _get_audit_store()
    if store is None:
        return

    severity = "info"
    if status >= 500:
        severity = "error"
    elif status >= 400:
        severity = "warning"

    try:
        store.log(
            actor=f"client:{client_ip}",
            action=f"{method} {path}",
            detail=f"{status} in {duration_ms:.0f}ms",
            severity=severity,
            resource="http_request",
            resource_id=path,
            ip_address=client_ip,
            metadata={
                "method": method,
                "path": path,
                "status_code": status,
                "duration_ms": round(duration_ms, 1),
            },
        )
    except Exception:
        pass  # Never let audit logging break the request
