# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unified event feed — merges all event sources into one chronological stream.

Combines:
  - Tactical events (target created/updated/correlated/lost)
  - Notifications (alerts, info, warnings)
  - Audit log entries (API requests, admin actions)
  - Amy thoughts (inner monologue, decisions)
  - System events (plugin start/stop, demo start, etc.)

API:
  GET /api/events/unified?limit=100&since=<unix_ts>&source=<filter>
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_auth

router = APIRouter(tags=["events"])


def _gather_tactical_events(
    request: Request,
    since: float,
    limit: int,
) -> list[dict[str, Any]]:
    """Gather recent tactical events from EventBus history."""
    events: list[dict[str, Any]] = []
    event_bus = getattr(request.app.state, "event_bus", None)
    if event_bus is None:
        return events

    history = getattr(event_bus, "history", None)
    if history is None:
        # Try get_history method
        get_hist = getattr(event_bus, "get_history", None)
        if get_hist is not None:
            try:
                history = get_hist(limit=limit)
            except Exception:
                return events
        else:
            return events

    if callable(history):
        try:
            history = history()
        except Exception:
            return events

    for entry in (history if isinstance(history, list) else []):
        ts = 0.0
        if isinstance(entry, dict):
            ts = entry.get("timestamp", entry.get("ts", 0.0))
            if ts < since:
                continue
            events.append({
                "source": "tactical",
                "type": entry.get("event_type", entry.get("type", "event")),
                "timestamp": ts,
                "data": entry,
            })
        elif hasattr(entry, "timestamp"):
            ts = getattr(entry, "timestamp", 0.0)
            if ts < since:
                continue
            events.append({
                "source": "tactical",
                "type": getattr(entry, "event_type", "event"),
                "timestamp": ts,
                "data": entry if isinstance(entry, dict) else (
                    entry.to_dict() if hasattr(entry, "to_dict") else str(entry)
                ),
            })

    return events[:limit]


def _gather_notifications(
    request: Request,
    since: float,
    limit: int,
) -> list[dict[str, Any]]:
    """Gather recent notifications."""
    events: list[dict[str, Any]] = []
    try:
        from app.routers.notifications import get_manager
        mgr = get_manager()
        if mgr is None:
            return events

        all_notifs = mgr.list(limit=limit)
        for n in all_notifs:
            nd = n if isinstance(n, dict) else (
                n.to_dict() if hasattr(n, "to_dict") else
                {"message": str(n)}
            )
            ts = nd.get("timestamp", nd.get("created_at", 0.0))
            if isinstance(ts, str):
                try:
                    import datetime
                    dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    ts = dt.timestamp()
                except Exception:
                    ts = 0.0
            if ts < since:
                continue
            events.append({
                "source": "notification",
                "type": nd.get("level", nd.get("severity", "info")),
                "timestamp": ts,
                "data": nd,
            })
    except Exception:
        pass
    return events[:limit]


def _gather_audit_entries(
    request: Request,
    since: float,
    limit: int,
) -> list[dict[str, Any]]:
    """Gather recent audit log entries."""
    events: list[dict[str, Any]] = []
    try:
        from app.audit_middleware import get_audit_store
        store = get_audit_store()
        if store is None:
            return events

        entries = store.query(limit=limit)
        for e in entries:
            ed = e.to_dict() if hasattr(e, "to_dict") else e
            ts = ed.get("timestamp", 0.0)
            if isinstance(ts, str):
                try:
                    import datetime
                    dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    ts = dt.timestamp()
                except Exception:
                    ts = 0.0
            if ts < since:
                continue
            events.append({
                "source": "audit",
                "type": ed.get("action", "request"),
                "timestamp": ts,
                "data": ed,
            })
    except Exception:
        pass
    return events[:limit]


def _gather_amy_thoughts(
    request: Request,
    since: float,
    limit: int,
) -> list[dict[str, Any]]:
    """Gather recent Amy thoughts/decisions."""
    events: list[dict[str, Any]] = []
    amy = getattr(request.app.state, "amy", None)
    if amy is None:
        return events

    # Try to get thought history
    brain = getattr(amy, "brain", None)
    thinking = getattr(brain, "thinking", None) if brain else None
    if thinking is None:
        thinking = getattr(amy, "thinking", None)

    if thinking is not None:
        history = getattr(thinking, "history", None)
        if history is None:
            get_hist = getattr(thinking, "get_history", None)
            if get_hist:
                try:
                    history = get_hist(limit=limit)
                except Exception:
                    history = []

        if callable(history) and not isinstance(history, list):
            try:
                history = history()
            except Exception:
                history = []

        for thought in (history if isinstance(history, list) else []):
            td = thought if isinstance(thought, dict) else (
                thought.to_dict() if hasattr(thought, "to_dict") else
                {"text": str(thought)}
            )
            ts = td.get("timestamp", td.get("ts", 0.0))
            if ts < since:
                continue
            events.append({
                "source": "amy",
                "type": td.get("type", "thought"),
                "timestamp": ts,
                "data": td,
            })

    return events[:limit]


@router.get("/api/events/unified")
async def unified_event_feed(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    since: Optional[float] = Query(None, description="Unix timestamp filter"),
    source: Optional[str] = Query(None, description="Filter by source: tactical, notification, audit, amy"),
    user: dict = Depends(require_auth),
):
    """Unified event feed — all event sources merged chronologically.

    Combines tactical events, notifications, audit log, and Amy thoughts
    into a single time-ordered feed. Useful for activity dashboards and
    operational awareness.
    """
    since_ts = since or 0.0
    all_events: list[dict[str, Any]] = []

    # Gather from each source (skip filtered sources)
    sources_to_query = (
        [source] if source else ["tactical", "notification", "audit", "amy"]
    )

    if "tactical" in sources_to_query:
        all_events.extend(_gather_tactical_events(request, since_ts, limit))

    if "notification" in sources_to_query:
        all_events.extend(_gather_notifications(request, since_ts, limit))

    if "audit" in sources_to_query:
        all_events.extend(_gather_audit_entries(request, since_ts, limit))

    if "amy" in sources_to_query:
        all_events.extend(_gather_amy_thoughts(request, since_ts, limit))

    # Sort by timestamp descending (newest first)
    all_events.sort(key=lambda e: e.get("timestamp", 0.0), reverse=True)

    # Apply limit
    all_events = all_events[:limit]

    # Redact sensitive fields from audit entries (IPs, raw actor strings)
    _REDACT_KEYS = {"ip_address", "client_ip", "remote_addr"}
    for ev in all_events:
        data = ev.get("data")
        if isinstance(data, dict):
            for key in _REDACT_KEYS:
                if key in data:
                    data[key] = "REDACTED"
            meta = data.get("metadata")
            if isinstance(meta, dict):
                for key in _REDACT_KEYS:
                    if key in meta:
                        meta[key] = "REDACTED"

    # Count by source
    source_counts: dict[str, int] = {}
    for e in all_events:
        s = e.get("source", "unknown")
        source_counts[s] = source_counts.get(s, 0) + 1

    return {
        "events": all_events,
        "total": len(all_events),
        "sources": source_counts,
        "since": since_ts,
        "limit": limit,
    }
