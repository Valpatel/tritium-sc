# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""User session management — multiple operators with different roles.

Allows multiple operators to log in simultaneously, each seeing their own
panel layout and notification preferences. Sessions are tracked in-memory
with cursor positions for real-time sharing.

Endpoints:
    POST /api/sessions          — create a new session (login)
    GET  /api/sessions          — list active sessions
    GET  /api/sessions/{id}     — get session details
    DELETE /api/sessions/{id}   — end a session (logout)
    PUT  /api/sessions/{id}/layout   — update panel layout prefs
    PUT  /api/sessions/{id}/cursor   — update cursor position
    GET  /api/sessions/cursors       — get all active cursor positions
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel

from app.auth import require_auth
from tritium_lib.models.user import (
    Permission,
    ROLE_PERMISSIONS,
    User,
    UserRole,
    UserSession,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"], dependencies=[Depends(require_auth)])

# ---- In-memory session store -------------------------------------------------

_sessions: dict[str, UserSession] = {}
_users: dict[str, User] = {}  # user_id -> User
_lock = threading.Lock()

# Default operator colors for visual identification
_ROLE_COLORS = {
    UserRole.ADMIN: "#fcee0a",      # yellow
    UserRole.COMMANDER: "#ff2a6d",  # magenta
    UserRole.ANALYST: "#00f0ff",    # cyan
    UserRole.OPERATOR: "#05ffa1",   # green
    UserRole.OBSERVER: "#8888aa",   # muted
}

# Session timeout: 30 minutes of inactivity (configurable)
_SESSION_TIMEOUT_S = 1800
# Warn this many seconds before expiry
_SESSION_WARN_BEFORE_S = 300  # 5 minutes


# ---- Request models ----------------------------------------------------------

class CreateSessionRequest(BaseModel):
    username: str
    display_name: str = ""
    role: str = "observer"
    color: Optional[str] = None


class UpdateLayoutRequest(BaseModel):
    panel_layout: dict = {}
    notification_prefs: dict = {}


class UpdateCursorRequest(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None


# ---- Helpers -----------------------------------------------------------------

def _prune_stale_sessions() -> int:
    """Remove sessions inactive for longer than timeout. Returns count removed."""
    now = time.time()
    stale = []
    for sid, session in _sessions.items():
        age = now - session.last_activity.timestamp()
        if age > _SESSION_TIMEOUT_S:
            stale.append(sid)
    for sid in stale:
        del _sessions[sid]
    return len(stale)


def get_expiring_sessions() -> list[dict]:
    """Return sessions that will expire within _SESSION_WARN_BEFORE_S seconds.

    Used by the background sweep to send WebSocket warnings before disconnect.
    """
    now = time.time()
    results = []
    with _lock:
        for sid, session in _sessions.items():
            age = now - session.last_activity.timestamp()
            remaining = _SESSION_TIMEOUT_S - age
            if 0 < remaining <= _SESSION_WARN_BEFORE_S:
                results.append({
                    "session_id": sid,
                    "username": session.username,
                    "display_name": session.display_name,
                    "role": session.role.value,
                    "remaining_seconds": int(remaining),
                })
    return results


async def session_timeout_sweep(app) -> None:
    """Background coroutine that periodically checks for expiring sessions
    and broadcasts WebSocket warnings before disconnect.

    Started from the app lifespan. Runs every 30 seconds.
    """
    while True:
        await asyncio.sleep(30)
        try:
            # Warn sessions about to expire
            expiring = get_expiring_sessions()
            for info in expiring:
                _broadcast_session_warning(app, info)

            # Actually prune expired sessions
            with _lock:
                pruned = _prune_stale_sessions()
            if pruned:
                logger.info(f"Pruned {pruned} expired session(s)")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(f"Session sweep error: {exc}")


def _broadcast_session_warning(app, info: dict) -> None:
    """Send a WebSocket message warning an operator their session is about to expire."""
    try:
        ws_manager = getattr(app.state, "ws_manager", None)
        if ws_manager is None:
            return
        import json
        msg = json.dumps({
            "type": "session_expiring",
            "session_id": info["session_id"],
            "username": info["username"],
            "remaining_seconds": info["remaining_seconds"],
            "message": f"Session expires in {info['remaining_seconds']}s due to inactivity",
        })
        # Best-effort broadcast; ws_manager.broadcast is sync in our codebase
        if hasattr(ws_manager, "broadcast"):
            ws_manager.broadcast(msg)
    except Exception:
        pass


def _get_or_create_user(username: str, display_name: str, role: UserRole, color: str) -> User:
    """Get existing user by username or create a new one."""
    for uid, user in _users.items():
        if user.username == username:
            user.role = role
            user.display_name = display_name or user.display_name
            user.color = color
            user.last_action = datetime.now(timezone.utc)
            return user

    user = User(
        username=username,
        display_name=display_name or username,
        role=role,
        color=color,
    )
    _users[user.user_id] = user
    return user


def get_session_store() -> dict[str, UserSession]:
    """Public accessor for the session store (used by WS cursor sharing)."""
    return _sessions


def log_operator_action(session_id: str, action: str, detail: str = "") -> None:
    """Log an operator action to the audit store and update session activity."""
    with _lock:
        session = _sessions.get(session_id)
        if session:
            session.touch()

    # Write to audit store if available
    try:
        from app.audit_middleware import get_audit_store
        store = get_audit_store()
        if store is not None:
            username = session.username if session else "unknown"
            display = session.display_name if session else "unknown"
            role = session.role.value if session else "unknown"
            store.log(
                actor=f"operator:{username}",
                action=action,
                detail=f"[{role}] {display}: {detail}" if detail else f"[{role}] {display}",
                severity="info",
                resource="operator_action",
                resource_id=session_id,
                metadata={
                    "session_id": session_id,
                    "username": username,
                    "role": role,
                    "detail": detail,
                },
            )
    except Exception:
        pass


# ---- Endpoints ---------------------------------------------------------------

@router.post("")
async def create_session(req: CreateSessionRequest, request: Request):
    """Create a new operator session (login).

    Multiple sessions per username are allowed (e.g., same user on
    different devices).
    """
    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(400, f"Invalid role: {req.role}. Valid: {[r.value for r in UserRole]}")

    color = req.color or _ROLE_COLORS.get(role, "#00f0ff")
    from app.client_ip import get_client_ip
    client_ip = get_client_ip(request)

    with _lock:
        _prune_stale_sessions()

        user = _get_or_create_user(req.username, req.display_name, role, color)

        session = UserSession(
            user_id=user.user_id,
            username=user.username,
            display_name=user.display_name,
            role=role,
            color=color,
            ip_address=client_ip,
            user_agent=request.headers.get("User-Agent", ""),
        )
        _sessions[session.session_id] = session

    log_operator_action(session.session_id, "session.login", f"joined as {role.value}")
    logger.info(f"Session created: {session.display_name} ({role.value}) [{session.session_id[:8]}]")

    return {
        "session": session.to_dict(),
        "user": user.to_dict(),
        "permissions": sorted(user.get_effective_permissions()),
    }


@router.get("")
async def list_sessions():
    """List all active sessions."""
    with _lock:
        _prune_stale_sessions()
        sessions = [s.to_dict() for s in _sessions.values()]

    return {
        "sessions": sessions,
        "total": len(sessions),
    }


@router.get("/cursors")
async def get_cursors():
    """Get cursor positions for all active sessions (for map overlay)."""
    with _lock:
        cursors = []
        for s in _sessions.values():
            if s.cursor_lat is not None and s.cursor_lng is not None:
                cursors.append({
                    "session_id": s.session_id,
                    "username": s.username,
                    "display_name": s.display_name,
                    "role": s.role.value,
                    "color": s.color,
                    "lat": s.cursor_lat,
                    "lng": s.cursor_lng,
                })

    return {"cursors": cursors}


@router.get("/timeout")
async def get_timeout():
    """Get the current session timeout configuration."""
    return {
        "timeout_seconds": _SESSION_TIMEOUT_S,
        "warn_before_seconds": _SESSION_WARN_BEFORE_S,
    }


@router.put("/timeout")
async def set_timeout(timeout_seconds: int = Query(1800, ge=60, le=86400)):
    """Update the session inactivity timeout (admin only in production).

    Args:
        timeout_seconds: New timeout in seconds (60 - 86400).
    """
    global _SESSION_TIMEOUT_S
    _SESSION_TIMEOUT_S = timeout_seconds
    logger.info(f"Session timeout updated to {timeout_seconds}s")
    return {
        "status": "ok",
        "timeout_seconds": _SESSION_TIMEOUT_S,
        "warn_before_seconds": _SESSION_WARN_BEFORE_S,
    }


@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get details for a specific session."""
    with _lock:
        session = _sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        user = _users.get(session.user_id)

    return {
        "session": session.to_dict(),
        "user": user.to_dict() if user else None,
    }


@router.delete("/{session_id}")
async def end_session(session_id: str):
    """End a session (logout)."""
    with _lock:
        session = _sessions.pop(session_id, None)
        if not session:
            raise HTTPException(404, "Session not found")

    log_operator_action(session_id, "session.logout", f"{session.display_name} disconnected")
    logger.info(f"Session ended: {session.display_name} [{session_id[:8]}]")

    return {"status": "ended", "session_id": session_id}


@router.put("/{session_id}/layout")
async def update_layout(session_id: str, req: UpdateLayoutRequest):
    """Update panel layout and notification preferences for a session."""
    with _lock:
        session = _sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        session.panel_layout = req.panel_layout
        session.notification_prefs = req.notification_prefs
        session.touch()

    return {"status": "updated"}


@router.put("/{session_id}/cursor")
async def update_cursor(session_id: str, req: UpdateCursorRequest):
    """Update cursor position for real-time sharing on the map."""
    with _lock:
        session = _sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        session.cursor_lat = req.lat
        session.cursor_lng = req.lng
        session.touch()

    return {"status": "updated"}


@router.get("/users/list")
async def list_users():
    """List all known users (not just active sessions)."""
    with _lock:
        users = [u.to_dict() for u in _users.values()]

    return {"users": users, "total": len(users)}


@router.get("/roles/list")
async def list_roles():
    """List available roles and their default permissions."""
    roles = []
    for role in UserRole:
        perms = ROLE_PERMISSIONS.get(role, set())
        roles.append({
            "role": role.value,
            "permissions": sorted(p.value for p in perms),
            "color": _ROLE_COLORS.get(role, "#ffffff"),
        })
    return {"roles": roles}


@router.post("/{session_id}/touch")
async def touch_session(session_id: str):
    """Touch a session to reset the inactivity timer.

    Frontends should call this periodically (e.g. on user interaction)
    to prevent timeout.
    """
    with _lock:
        session = _sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Session not found")
        session.touch()
        remaining = _SESSION_TIMEOUT_S - (time.time() - session.last_activity.timestamp())

    return {
        "status": "ok",
        "remaining_seconds": int(max(0, remaining)),
    }
