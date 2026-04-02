# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Security audit trail API — recent security events for operator awareness.

Aggregates security-relevant events from the audit store:
- Failed auth attempts (401/403 responses)
- Rate limit hits (429 responses)
- CSP/CORS events (from audit log metadata)
- High-severity entries

Endpoints:
    GET /api/security/audit-trail   — Recent security events
    GET /api/security/audit-stats   — Security event statistics
"""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.audit_middleware import get_audit_store
from app.auth import require_auth

router = APIRouter(prefix="/api/security", tags=["security"])


_SECURITY_STATUS_CODES = {401, 403, 429}


@router.get("/audit-trail")
async def security_audit_trail(
    event_type: Optional[str] = Query(None, description="Filter: auth_failure, rate_limit, forbidden, all"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_auth),
):
    """GET /api/security/audit-trail — recent security events.

    Returns audit log entries filtered to security-relevant events:
    - 401 responses (failed auth)
    - 403 responses (forbidden/CORS)
    - 429 responses (rate limit)
    - Entries with severity >= warning

    Requires authentication.
    """
    store = get_audit_store()
    if store is None:
        return {"events": [], "total": 0, "source": "unavailable"}

    # Query based on event type filter
    if event_type == "auth_failure":
        severity = "warning"
        entries = _query_by_status(store, 401, limit, offset)
    elif event_type == "rate_limit":
        entries = _query_by_status(store, 429, limit, offset)
    elif event_type == "forbidden":
        entries = _query_by_status(store, 403, limit, offset)
    else:
        # Get all security events: severity >= warning
        entries = store.query(severity="warning", limit=limit, offset=offset)
        # Also grab errors and criticals
        errors = store.query(severity="error", limit=limit, offset=offset)
        criticals = store.query(severity="critical", limit=limit, offset=offset)
        # Merge, dedup by id, sort by timestamp desc
        seen = set()
        merged = []
        for e in entries + errors + criticals:
            eid = getattr(e, "id", id(e))
            if eid not in seen:
                seen.add(eid)
                merged.append(e)
        merged.sort(key=lambda e: getattr(e, "timestamp", 0), reverse=True)
        entries = merged[:limit]

    events = []
    for entry in entries:
        d = entry.to_dict() if hasattr(entry, "to_dict") else {}
        # Classify the event type
        meta = d.get("metadata", {})
        status_code = meta.get("status_code", 0) if isinstance(meta, dict) else 0
        d["event_type"] = _classify_event(status_code, d.get("severity", "info"))
        events.append(d)

    total = store.count(severity="warning") + store.count(severity="error") + store.count(severity="critical")

    return {
        "events": events,
        "total": total,
        "count": len(events),
        "source": "live",
    }


@router.get("/audit-stats")
async def security_audit_stats(
    user: dict = Depends(require_auth),
):
    """GET /api/security/audit-stats — security event statistics.

    Returns counts of security events by type and severity,
    plus recent activity trends.
    """
    store = get_audit_store()
    if store is None:
        return {
            "total_security_events": 0,
            "by_severity": {},
            "by_type": {},
            "source": "unavailable",
        }

    now = time.time()
    one_hour_ago = now - 3600
    one_day_ago = now - 86400

    # Get overall stats
    stats = store.get_stats()

    # Count security events by type
    warnings = store.count(severity="warning")
    errors = store.count(severity="error")
    criticals = store.count(severity="critical")

    # Recent security events (last hour)
    recent_entries = store.query(severity="warning", limit=500)
    recent_hour = sum(1 for e in recent_entries if getattr(e, "timestamp", 0) > one_hour_ago)

    recent_errors = store.query(severity="error", limit=500)
    recent_hour += sum(1 for e in recent_errors if getattr(e, "timestamp", 0) > one_hour_ago)

    # Classify into types
    type_counts: dict[str, int] = {
        "auth_failure": 0,
        "rate_limit": 0,
        "forbidden": 0,
        "server_error": 0,
        "other_warning": 0,
    }

    all_security = store.query(severity="warning", limit=1000) + store.query(severity="error", limit=1000)
    for entry in all_security:
        d = entry.to_dict() if hasattr(entry, "to_dict") else {}
        meta = d.get("metadata", {})
        sc = meta.get("status_code", 0) if isinstance(meta, dict) else 0
        etype = _classify_event(sc, d.get("severity", "info"))
        type_counts[etype] = type_counts.get(etype, 0) + 1

    return {
        "total_security_events": warnings + errors + criticals,
        "by_severity": {
            "warning": warnings,
            "error": errors,
            "critical": criticals,
        },
        "by_type": type_counts,
        "recent_hour": recent_hour,
        "total_entries": stats.get("total_entries", 0),
        "source": "live",
    }


def _query_by_status(store: Any, status_code: int, limit: int, offset: int) -> list:
    """Query audit entries that match a specific HTTP status code.

    Since the store doesn't directly filter by metadata fields,
    we query by severity and post-filter.
    """
    severity = "warning" if status_code < 500 else "error"
    # Fetch more than needed since we'll filter
    entries = store.query(severity=severity, limit=limit * 3, offset=0)
    filtered = []
    for entry in entries:
        d = entry.to_dict() if hasattr(entry, "to_dict") else {}
        meta = d.get("metadata", {})
        sc = meta.get("status_code", 0) if isinstance(meta, dict) else 0
        if sc == status_code:
            filtered.append(entry)

    return filtered[offset:offset + limit]


def _classify_event(status_code: int, severity: str) -> str:
    """Classify a security event by HTTP status code."""
    if status_code == 401:
        return "auth_failure"
    elif status_code == 429:
        return "rate_limit"
    elif status_code == 403:
        return "forbidden"
    elif status_code >= 500:
        return "server_error"
    else:
        return "other_warning"
