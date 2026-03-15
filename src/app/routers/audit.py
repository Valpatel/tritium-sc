# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Audit log API — query request audit trail for compliance review."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.audit_middleware import get_audit_store
from app.auth import require_auth

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def list_audit_entries(
    actor: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    resource: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_auth),
):
    """Query audit log entries with optional filters."""
    store = get_audit_store()
    if store is None:
        return {"entries": [], "total": 0}

    entries = store.query(
        actor=actor,
        action=action,
        severity=severity,
        resource=resource,
        limit=limit,
        offset=offset,
    )
    return {
        "entries": [e.to_dict() for e in entries],
        "total": store.count(actor=actor, action=action, severity=severity),
    }


@router.get("/stats")
async def audit_stats(user: dict = Depends(require_auth)):
    """Get aggregate audit log statistics."""
    store = get_audit_store()
    if store is None:
        return {"total_entries": 0}
    return store.get_stats()
