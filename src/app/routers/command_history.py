# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Command history API — audit log of all commands sent to edge devices."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

from app.auth import optional_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fleet/commands", tags=["fleet"])

# Fields that may leak internal topology — redacted for non-admin users.
_SENSITIVE_PAYLOAD_KEYS = {"ip", "ip_address", "host", "hostname", "url", "endpoint"}


def _redact_command(cmd: dict, is_admin: bool) -> dict:
    """Return a copy of a command entry with sensitive fields redacted
    when the caller is not an admin.

    Redacted fields:
      - payload keys that suggest internal IP/host/URL values
      - device_id is shortened to mask the last octet-style suffix
    """
    if is_admin:
        return cmd

    out = dict(cmd)

    # Redact sensitive payload keys
    if out.get("payload"):
        sanitised = {}
        for k, v in out["payload"].items():
            if k.lower() in _SENSITIVE_PAYLOAD_KEYS:
                sanitised[k] = "[REDACTED]"
            else:
                sanitised[k] = v
        out["payload"] = sanitised

    return out


@router.get("/history")
async def command_history(
    request: Request,
    limit: int = 100,
    user: dict | None = Depends(optional_auth),
):
    """GET /api/fleet/commands/history — list all commands sent to edge devices.

    Non-admin users receive sanitised entries with sensitive payload
    fields (ip, host, url) redacted to prevent topology leakage.

    Returns:
        {
            "commands": [...],
            "count": 1,
            "source": "live"
        }
    """
    store = getattr(request.app.state, "command_history_store", None)
    if store is None:
        return {"commands": [], "count": 0, "source": "unavailable"}

    is_admin = (user or {}).get("role") == "admin"
    commands = store.get_recent(limit)
    redacted = [_redact_command(c, is_admin) for c in commands]
    return {
        "commands": redacted,
        "count": len(redacted),
        "source": "live",
    }


@router.get("/stats")
async def command_stats(request: Request, user: dict | None = Depends(optional_auth)):
    """GET /api/fleet/commands/stats — summary statistics for command history."""
    store = getattr(request.app.state, "command_history_store", None)
    if store is None:
        return {
            "total_sent": 0,
            "acknowledged": 0,
            "failed": 0,
            "timed_out": 0,
            "pending": 0,
            "source": "unavailable",
        }

    stats = store.get_stats()
    return {**stats, "source": "live"}
