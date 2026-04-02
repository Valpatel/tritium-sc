# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Rate limit dashboard API — shows which endpoints are being hit hardest.

Uses the existing AuditStore request logs to compute per-endpoint request
counts, average latencies, and proximity to rate limits. Intended for the
operator dashboard so admins can spot abuse or bottlenecks.

Endpoints:
    GET /api/rate-limits/dashboard    — top endpoints by request count
    GET /api/rate-limits/status       — current rate limit config + live counters
"""

from __future__ import annotations

import time
from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_auth

router = APIRouter(prefix="/api/rate-limits", tags=["rate-limits"])


@router.get("/dashboard")
async def rate_limit_dashboard(
    minutes: int = Query(15, ge=1, le=1440, description="Look-back window in minutes"),
    limit: int = Query(30, ge=1, le=200, description="Max endpoints to return"),
    user: dict = Depends(require_auth),
):
    """Return the busiest API endpoints within the look-back window.

    For each endpoint, returns:
      - path and HTTP method
      - total request count
      - average response time (ms)
      - error count (4xx/5xx)
      - percentage of rate limit consumed (if rate limiting is enabled)

    Data comes from the AuditStore (audit_middleware logs every request).
    """
    try:
        from app.audit_middleware import get_audit_store
        store = get_audit_store()
    except Exception:
        store = None

    if store is None:
        return {"endpoints": [], "window_minutes": minutes, "total_requests": 0}

    since = time.time() - (minutes * 60)
    entries = store.query(
        resource="http_request",
        start_time=since,
        limit=10000,
    )

    # Aggregate per endpoint (method + path)
    agg: dict[str, dict] = {}
    for e in entries:
        meta = e.metadata if isinstance(e.metadata, dict) else {}
        method = meta.get("method", "?")
        path = meta.get("path", e.resource_id or "?")
        key = f"{method} {path}"

        if key not in agg:
            agg[key] = {
                "method": method,
                "path": path,
                "count": 0,
                "total_duration_ms": 0.0,
                "errors_4xx": 0,
                "errors_5xx": 0,
                "last_seen": 0.0,
            }

        bucket = agg[key]
        bucket["count"] += 1
        bucket["total_duration_ms"] += meta.get("duration_ms", 0.0)
        status_code = meta.get("status_code", 200)
        if 400 <= status_code < 500:
            bucket["errors_4xx"] += 1
        elif status_code >= 500:
            bucket["errors_5xx"] += 1
        if e.timestamp > bucket["last_seen"]:
            bucket["last_seen"] = e.timestamp

    # Sort by count descending
    sorted_endpoints = sorted(agg.values(), key=lambda x: x["count"], reverse=True)[:limit]

    # Compute averages and rate limit proximity
    from app.config import settings
    rate_limit_per_min = settings.rate_limit_requests if settings.rate_limit_enabled else None

    results = []
    for ep in sorted_endpoints:
        avg_ms = ep["total_duration_ms"] / ep["count"] if ep["count"] else 0.0
        req_per_min = ep["count"] / max(1, minutes)

        entry = {
            "method": ep["method"],
            "path": ep["path"],
            "request_count": ep["count"],
            "requests_per_minute": round(req_per_min, 1),
            "avg_response_ms": round(avg_ms, 1),
            "errors_4xx": ep["errors_4xx"],
            "errors_5xx": ep["errors_5xx"],
            "last_seen": ep["last_seen"],
        }

        if rate_limit_per_min is not None:
            entry["rate_limit_pct"] = round(
                min(100.0, (req_per_min / rate_limit_per_min) * 100), 1
            )
        else:
            entry["rate_limit_pct"] = None

        results.append(entry)

    return {
        "endpoints": results,
        "window_minutes": minutes,
        "total_requests": sum(ep["request_count"] for ep in results),
        "rate_limit_enabled": settings.rate_limit_enabled,
        "rate_limit_per_minute": rate_limit_per_min,
    }


@router.get("/status")
async def rate_limit_status(
    request: Request,
    user: dict = Depends(require_auth),
):
    """Return current rate limiting configuration and live counter state.

    Shows per-key counters from the RateLimitMiddleware if rate limiting
    is enabled. Useful for debugging 429 responses.
    """
    from app.config import settings

    status = {
        "enabled": settings.rate_limit_enabled,
        "max_requests_per_window": settings.rate_limit_requests,
        "window_seconds": settings.rate_limit_window_seconds,
        "role_limits": {},
        "active_keys": 0,
    }

    if settings.rate_limit_enabled:
        from app.rate_limit import ROLE_RATE_LIMITS
        status["role_limits"] = {
            k: v if v is not None else "unlimited"
            for k, v in ROLE_RATE_LIMITS.items()
        }

        # Try to read live counters from middleware
        for mw in getattr(request.app, "middleware_stack", []):
            inner = getattr(mw, "app", None)
            if hasattr(inner, "_entries"):
                status["active_keys"] = len(inner._entries)
                break

    return status
