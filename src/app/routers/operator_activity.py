# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Operator activity log — real-time feed of who is doing what.

Shows operator actions like "Commander marked target X as hostile",
"Analyst opened investigation Y", "Observer joined at 14:32".
Queries the AuditStore filtered to operator_action entries.

Endpoints:
    GET /api/operator-activity        — recent operator actions
    GET /api/operator-activity/feed   — SSE stream of operator actions
    GET /api/operator-activity/stats  — per-operator action counts
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger

router = APIRouter(prefix="/api/operator-activity", tags=["operator-activity"])


def _get_operator_entries(
    actor: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    since: Optional[float] = None,
) -> list[dict]:
    """Query audit store for operator action entries."""
    try:
        from app.audit_middleware import get_audit_store
        store = get_audit_store()
        if store is None:
            return []

        entries = store.query(
            resource="operator_action",
            actor=f"operator:{actor}" if actor else None,
            limit=limit,
            offset=offset,
        )

        results = []
        for e in entries:
            if since and e.timestamp < since:
                continue
            meta = e.metadata if isinstance(e.metadata, dict) else {}
            results.append({
                "id": e.id,
                "timestamp": e.timestamp,
                "username": meta.get("username", ""),
                "role": meta.get("role", ""),
                "action": e.action,
                "detail": meta.get("detail", e.detail),
                "session_id": meta.get("session_id", ""),
            })
        return results

    except Exception as exc:
        logger.warning(f"Operator activity query failed: {exc}")
        return []


@router.get("")
async def list_operator_activity(
    actor: Optional[str] = Query(None, description="Filter by username"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    since: Optional[float] = Query(None, description="Unix timestamp filter"),
):
    """Get recent operator actions.

    Returns actions like session logins, target updates, investigation
    openings, etc. Filterable by operator username.
    """
    entries = _get_operator_entries(actor=actor, limit=limit, offset=offset, since=since)
    return {
        "activities": entries,
        "total": len(entries),
    }


@router.get("/stats")
async def operator_activity_stats():
    """Get per-operator action counts and last-seen timestamps."""
    try:
        from app.audit_middleware import get_audit_store
        store = get_audit_store()
        if store is None:
            return {"operators": []}

        # Get recent operator actions and aggregate
        entries = store.query(resource="operator_action", limit=1000)
        operator_stats: dict[str, dict] = {}
        for e in entries:
            meta = e.metadata if isinstance(e.metadata, dict) else {}
            username = meta.get("username", "unknown")
            if username not in operator_stats:
                operator_stats[username] = {
                    "username": username,
                    "role": meta.get("role", ""),
                    "action_count": 0,
                    "last_action_ts": 0.0,
                    "last_action": "",
                }
            operator_stats[username]["action_count"] += 1
            if e.timestamp > operator_stats[username]["last_action_ts"]:
                operator_stats[username]["last_action_ts"] = e.timestamp
                operator_stats[username]["last_action"] = e.action

        return {
            "operators": list(operator_stats.values()),
        }

    except Exception as exc:
        logger.warning(f"Operator stats query failed: {exc}")
        return {"operators": []}


@router.get("/feed")
async def operator_activity_feed(request: Request):
    """SSE stream of operator actions in real time.

    Clients connect and receive new operator actions as they happen.
    Polls the audit store every 2 seconds for new entries.
    """
    async def event_generator():
        last_ts = time.time()
        yield "data: {\"type\":\"connected\"}\n\n"

        while True:
            if await request.is_disconnected():
                break

            entries = _get_operator_entries(since=last_ts, limit=20)
            for entry in entries:
                if entry["timestamp"] > last_ts:
                    last_ts = entry["timestamp"]
                yield f"data: {json.dumps(entry)}\n\n"

            await asyncio.sleep(2.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
