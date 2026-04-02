# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Voice command API router — text command dispatch.

Accepts text commands (from browser SpeechRecognition or typed input)
and dispatches them to the appropriate subsystem:
  - Amy chat messages
  - Panel toggle commands
  - Target search
  - Demo start/stop
  - System controls

Endpoints:
  POST /api/voice/command  — dispatch a text command
  GET  /api/voice/status   — voice subsystem status
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


class VoiceCommandRequest(BaseModel):
    """Request body for voice command dispatch."""
    text: str
    source: str = "speech"  # speech, typed, hotkey


class VoiceCommandResponse(BaseModel):
    """Response from voice command dispatch."""
    status: str = "ok"
    action: str = ""
    detail: str = ""
    data: dict = {}


# -- Command patterns ----------------------------------------------------------

# Each pattern maps a regex to (action_name, handler_function_name)
COMMAND_PATTERNS: list[tuple[str, str]] = [
    # Demo controls
    (r"(?:start|begin|launch)\s+demo", "demo_start"),
    (r"(?:stop|end|halt)\s+demo", "demo_stop"),

    # Panel controls
    (r"(?:open|show|toggle)\s+(.+?)\s*panel", "panel_toggle"),
    (r"(?:close|hide)\s+(.+?)\s*panel", "panel_close"),

    # Target search
    (r"(?:find|search|locate)\s+(?:target\s+)?(.+)", "target_search"),
    (r"(?:where\s+is|track)\s+(.+)", "target_search"),

    # Amy interaction
    (r"(?:amy|hey amy|ask amy)\s*[,:]?\s*(.+)", "amy_chat"),

    # Map controls
    (r"(?:zoom\s+in|closer)", "map_zoom_in"),
    (r"(?:zoom\s+out|farther)", "map_zoom_out"),
    (r"(?:center|focus)\s+(?:on\s+)?(?:map|action|targets?)", "map_center"),

    # System controls
    (r"(?:status|system status|sitrep)", "system_status"),
    (r"(?:alert|threat)\s+(?:level|status)", "threat_status"),
    (r"(?:mute|silence)", "audio_mute"),
    (r"(?:unmute|sound on)", "audio_unmute"),
]


def _match_command(text: str) -> tuple[str, list[str]]:
    """Match text against command patterns.

    Returns:
        Tuple of (action_name, captured_groups).
    """
    text_lower = text.strip().lower()

    for pattern, action in COMMAND_PATTERNS:
        match = re.match(pattern, text_lower)
        if match:
            return action, list(match.groups())

    # If no pattern matched, treat as Amy chat
    return "amy_chat", [text.strip()]


@router.post("/command")
async def voice_command(request: Request, body: VoiceCommandRequest):
    """Dispatch a text command to the appropriate subsystem."""
    text = body.text.strip()
    if not text:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "detail": "Empty command text"},
        )

    action, groups = _match_command(text)
    logger.info("Voice command: '%s' -> action=%s groups=%s", text, action, groups)

    try:
        result = await _dispatch(request, action, groups, text)
        return result
    except Exception as exc:
        logger.error("Voice command dispatch error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(exc)},
        )


@router.get("/status")
async def voice_status():
    """Return voice subsystem status."""
    return {
        "status": "ok",
        "available_commands": [action for _, action in COMMAND_PATTERNS],
        "speech_recognition": "browser_api",
        "note": "Voice input uses browser SpeechRecognition API",
    }


# -- Dispatch logic ------------------------------------------------------------

async def _dispatch(
    request: Request, action: str, groups: list[str], original_text: str
) -> dict[str, Any]:
    """Dispatch a parsed command to the appropriate handler."""

    if action == "demo_start":
        return await _handle_demo(request, start=True)

    elif action == "demo_stop":
        return await _handle_demo(request, start=False)

    elif action == "panel_toggle":
        panel_name = groups[0] if groups else ""
        return {"status": "ok", "action": "panel_toggle", "detail": f"Toggle panel: {panel_name}", "data": {"panel": panel_name}}

    elif action == "panel_close":
        panel_name = groups[0] if groups else ""
        return {"status": "ok", "action": "panel_close", "detail": f"Close panel: {panel_name}", "data": {"panel": panel_name}}

    elif action == "target_search":
        query = groups[0] if groups else ""
        return await _handle_target_search(request, query)

    elif action == "amy_chat":
        message = groups[0] if groups else original_text
        return await _handle_amy_chat(request, message)

    elif action == "map_zoom_in":
        return {"status": "ok", "action": "map_zoom_in", "detail": "Zoom in", "data": {"delta": 1}}

    elif action == "map_zoom_out":
        return {"status": "ok", "action": "map_zoom_out", "detail": "Zoom out", "data": {"delta": -1}}

    elif action == "map_center":
        return {"status": "ok", "action": "map_center", "detail": "Center on action", "data": {}}

    elif action == "system_status":
        return await _handle_system_status(request)

    elif action == "threat_status":
        return {"status": "ok", "action": "threat_status", "detail": "Threat status query", "data": {}}

    elif action in ("audio_mute", "audio_unmute"):
        muted = action == "audio_mute"
        return {"status": "ok", "action": action, "detail": f"Audio {'muted' if muted else 'unmuted'}", "data": {"muted": muted}}

    return {"status": "ok", "action": "unknown", "detail": f"Unrecognized: {original_text}", "data": {}}


async def _handle_demo(request: Request, start: bool) -> dict[str, Any]:
    """Start or stop demo mode."""
    controller = getattr(request.app.state, "demo_controller", None)
    action_word = "start" if start else "stop"

    if controller is None:
        return {"status": "ok", "action": f"demo_{action_word}", "detail": "Demo controller not available", "data": {"available": False}}

    try:
        if start:
            controller.start()
        else:
            controller.stop()
        return {"status": "ok", "action": f"demo_{action_word}", "detail": f"Demo {action_word}ed", "data": {"running": start}}
    except Exception as exc:
        return {"status": "error", "action": f"demo_{action_word}", "detail": str(exc), "data": {}}


async def _handle_target_search(request: Request, query: str) -> dict[str, Any]:
    """Search for targets matching the query."""
    amy = getattr(request.app.state, "amy", None)
    tracker = getattr(amy, "target_tracker", None) if amy else None

    results: list[dict] = []
    if tracker:
        for target in tracker.get_all():
            if query.lower() in target.name.lower() or query.lower() in target.target_id.lower():
                results.append({
                    "target_id": target.target_id,
                    "name": target.name,
                    "alliance": target.alliance,
                    "asset_type": target.asset_type,
                })

    return {
        "status": "ok",
        "action": "target_search",
        "detail": f"Found {len(results)} target(s) matching '{query}'",
        "data": {"query": query, "results": results, "count": len(results)},
    }


async def _handle_amy_chat(request: Request, message: str) -> dict[str, Any]:
    """Send a message to Amy."""
    amy = getattr(request.app.state, "amy", None)

    if amy is None:
        return {"status": "ok", "action": "amy_chat", "detail": "Amy not available", "data": {"available": False}}

    try:
        response = await amy.chat(message) if hasattr(amy, "chat") else "Amy is thinking..."
        return {
            "status": "ok",
            "action": "amy_chat",
            "detail": str(response)[:500],
            "data": {"message": message, "response": str(response)[:500]},
        }
    except Exception as exc:
        return {"status": "error", "action": "amy_chat", "detail": str(exc), "data": {}}


async def _handle_system_status(request: Request) -> dict[str, Any]:
    """Get system status summary."""
    amy = getattr(request.app.state, "amy", None)
    tracker = getattr(amy, "target_tracker", None) if amy else None

    data: dict[str, Any] = {"timestamp": time.time()}
    if tracker:
        all_targets = tracker.get_all()
        data["targets"] = {
            "total": len(all_targets),
            "hostile": sum(1 for t in all_targets if t.alliance == "hostile"),
            "friendly": sum(1 for t in all_targets if t.alliance == "friendly"),
            "unknown": sum(1 for t in all_targets if t.alliance == "unknown"),
        }

    return {
        "status": "ok",
        "action": "system_status",
        "detail": f"Tracking {data.get('targets', {}).get('total', 0)} target(s)",
        "data": data,
    }
