# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Amy daily briefing — natural language summary of the last 24 hours.

Generates a narrative briefing from picture-of-day data, Amy's sensorium,
target activity, fleet health, and threat assessment.  Uses local Ollama
LLM if available, otherwise falls back to a structured template.

Endpoints:
    POST /api/amy/briefing        — generate a daily briefing
    GET  /api/amy/briefing        — get most recent cached briefing
    GET  /api/amy/briefing/config — get morning auto-trigger config
    POST /api/amy/briefing/config — set morning auto-trigger config

Morning briefing auto-trigger:
    At a configurable hour (default 8 AM local), Amy automatically generates
    and caches a daily briefing. Shown in the ops dashboard when operators
    log in. Only one briefing per calendar day.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/amy", tags=["amy-briefing"])

# Cache for the most recent briefing
_cached_briefing: dict | None = None
_cached_at: float = 0.0
_CACHE_TTL_S = 300.0  # 5 minutes

# Morning briefing auto-trigger configuration
_morning_briefing_hour: int = 8  # Default 8 AM local time
_morning_briefing_enabled: bool = True
_morning_briefing_task: asyncio.Task | None = None
_last_morning_briefing_date: str = ""  # YYYY-MM-DD of last auto-generated


def _gather_context(request) -> dict:
    """Gather all context data for the briefing."""
    context: dict = {}

    # Picture of day
    try:
        from app.routers.picture_of_day import _build_picture_of_day
        context["picture_of_day"] = _build_picture_of_day(request)
    except Exception:
        context["picture_of_day"] = None

    # Briefing data (existing operational briefing)
    try:
        from app.routers.briefing import _build_briefing
        context["briefing"] = _build_briefing(request)
    except Exception:
        context["briefing"] = None

    # Amy sensorium
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        try:
            context["sensorium"] = {
                "narrative": amy.sensorium.narrative(),
                "summary": amy.sensorium.summary(),
                "mood": amy.sensorium.mood,
                "event_count": amy.sensorium.event_count,
            }
        except Exception:
            context["sensorium"] = None

        # Target tracker summary
        try:
            targets = amy.target_tracker.get_all()
            by_alliance = {}
            by_type = {}
            for t in targets:
                by_alliance[t.alliance] = by_alliance.get(t.alliance, 0) + 1
                by_type[t.asset_type] = by_type.get(t.asset_type, 0) + 1
            context["targets"] = {
                "total": len(targets),
                "by_alliance": by_alliance,
                "by_type": by_type,
            }
        except Exception:
            context["targets"] = None
    else:
        context["sensorium"] = None
        context["targets"] = None

    # SITREP
    try:
        from app.routers.sitrep import _build_sitrep
        context["sitrep"] = _build_sitrep(request)
    except Exception:
        context["sitrep"] = None

    return context


def _try_ollama_briefing(context: dict) -> str | None:
    """Try to generate a briefing using local Ollama LLM.

    Returns the generated text, or None if Ollama is unavailable.
    """
    # Use llama-server (OpenAI-compatible) on port 8081
    llm_url = "http://localhost:8081/v1/chat/completions"

    # Build a compact context summary for the LLM
    summary_parts = []

    pod = context.get("picture_of_day")
    if pod:
        summary_parts.append(f"New targets today: {pod.get('new_targets', 0)}")
        summary_parts.append(f"Total sightings: {pod.get('total_sightings', 0)}")
        summary_parts.append(f"Threat level: {pod.get('threat_level', 'UNKNOWN')}")
        summary_parts.append(f"Correlations: {pod.get('correlations', 0)}")

    sitrep = context.get("sitrep")
    if sitrep:
        summary_parts.append(f"SITREP threat level: {sitrep.get('threat_level', 'UNKNOWN')}")
        tgt = sitrep.get("targets", {})
        summary_parts.append(f"Active targets: {tgt.get('total', 0)}")

    targets = context.get("targets")
    if targets:
        summary_parts.append(f"Tracked targets: {targets['total']}")
        for alliance, count in targets.get("by_alliance", {}).items():
            summary_parts.append(f"  {alliance}: {count}")

    sensorium = context.get("sensorium")
    if sensorium:
        summary_parts.append(f"Amy mood: {sensorium.get('mood', 'unknown')}")
        summary_parts.append(f"Events observed: {sensorium.get('event_count', 0)}")

    briefing = context.get("briefing")
    if briefing:
        sys_info = briefing.get("system", {})
        summary_parts.append(f"Uptime: {sys_info.get('uptime_hours', 0)} hours")
        summary_parts.append(f"Active operators: {briefing.get('operator_count', 0)}")
        summary_parts.append(f"Active missions: {briefing.get('mission_count', 0)}")

    context_text = "\n".join(summary_parts)

    prompt = f"""You are Amy, the AI Commander of the Tritium distributed sensor system.
Generate a concise daily briefing (3-5 paragraphs) covering the last 24 hours.
Be professional, tactical, and specific. Use military-style brevity.
Reference specific numbers from the data below.

OPERATIONAL DATA:
{context_text}

Write the briefing now. Start with "DAILY BRIEFING" and the current date/time."""

    payload = json.dumps({
        "model": "qwen2.5:7b",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.7,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            llm_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            return choices[0]["message"]["content"].strip() if choices else None
    except (urllib.error.URLError, TimeoutError, Exception):
        return None


def _template_briefing(context: dict) -> str:
    """Generate a structured briefing using a template (no LLM required)."""
    now = datetime.now(timezone.utc)
    lines = []
    lines.append(f"DAILY BRIEFING — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # Threat assessment
    pod = context.get("picture_of_day")
    sitrep = context.get("sitrep")
    threat_level = "UNKNOWN"
    if sitrep:
        threat_level = sitrep.get("threat_level", "UNKNOWN")
    elif pod:
        threat_level = pod.get("threat_level", "UNKNOWN")

    lines.append(f"THREAT ASSESSMENT: {threat_level}")
    lines.append("")

    # Target activity
    targets = context.get("targets")
    if targets:
        lines.append(f"TRACKED TARGETS: {targets['total']} active")
        for alliance, count in targets.get("by_alliance", {}).items():
            lines.append(f"  {alliance.upper()}: {count}")
    else:
        lines.append("TRACKED TARGETS: No tracking data available")
    lines.append("")

    # Daily metrics
    if pod:
        lines.append("24-HOUR METRICS:")
        lines.append(f"  New targets discovered: {pod.get('new_targets', 0)}")
        lines.append(f"  Total sightings: {pod.get('total_sightings', 0)}")
        lines.append(f"  Correlations established: {pod.get('correlations', 0)}")
        lines.append(f"  Threats detected: {pod.get('threats', 0)}")
        lines.append(f"  Zone events: {pod.get('zone_events', 0)}")
        sbs = pod.get("sightings_by_source", {})
        if sbs:
            lines.append("  Sightings by source:")
            for src, count in sorted(sbs.items()):
                lines.append(f"    {src}: {count}")
    lines.append("")

    # System status
    briefing = context.get("briefing")
    if briefing:
        sys_info = briefing.get("system", {})
        lines.append("SYSTEM STATUS:")
        lines.append(f"  Uptime: {sys_info.get('uptime_hours', 0)} hours")
        lines.append(f"  Active operators: {briefing.get('operator_count', 0)}")
        lines.append(f"  Active missions: {briefing.get('mission_count', 0)}")
        lines.append(f"  Active investigations: {briefing.get('investigation_count', 0)}")
    lines.append("")

    # Sensorium
    sensorium = context.get("sensorium")
    if sensorium:
        lines.append("AMY STATUS:")
        lines.append(f"  Mood: {sensorium.get('mood', 'nominal')}")
        lines.append(f"  Events processed: {sensorium.get('event_count', 0)}")
        if sensorium.get("summary"):
            lines.append(f"  Assessment: {sensorium['summary']}")
    lines.append("")

    lines.append("— Amy, AI Commander, Tritium System")

    return "\n".join(lines)


@router.post("/briefing")
async def generate_briefing(request: Request):
    """Generate a natural-language daily briefing.

    Uses local Ollama LLM if available (qwen2.5:7b), otherwise falls back
    to a structured template.  Results are cached for 5 minutes.
    """
    global _cached_briefing, _cached_at

    context = _gather_context(request)

    # Try LLM first, fall back to template
    llm_text = _try_ollama_briefing(context)
    source = "ollama" if llm_text else "template"
    briefing_text = llm_text if llm_text else _template_briefing(context)

    result = {
        "briefing_id": f"AMY-BRIEF-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "text": briefing_text,
        "context_summary": {
            "threat_level": (context.get("sitrep") or {}).get("threat_level", "UNKNOWN"),
            "total_targets": (context.get("targets") or {}).get("total", 0),
            "new_targets_24h": (context.get("picture_of_day") or {}).get("new_targets", 0),
        },
    }

    _cached_briefing = result
    _cached_at = time.time()

    return result


@router.get("/briefing")
async def get_briefing(request: Request):
    """Get the most recently generated daily briefing.

    Returns the cached briefing if generated within the last 5 minutes,
    otherwise generates a fresh one.
    """
    global _cached_briefing, _cached_at

    if _cached_briefing and (time.time() - _cached_at) < _CACHE_TTL_S:
        return _cached_briefing

    # Generate a fresh one
    context = _gather_context(request)
    llm_text = _try_ollama_briefing(context)
    source = "ollama" if llm_text else "template"
    briefing_text = llm_text if llm_text else _template_briefing(context)

    result = {
        "briefing_id": f"AMY-BRIEF-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "text": briefing_text,
        "context_summary": {
            "threat_level": (context.get("sitrep") or {}).get("threat_level", "UNKNOWN"),
            "total_targets": (context.get("targets") or {}).get("total", 0),
            "new_targets_24h": (context.get("picture_of_day") or {}).get("new_targets", 0),
        },
    }

    _cached_briefing = result
    _cached_at = time.time()

    return result


# ---------------------------------------------------------------------------
# Morning briefing auto-trigger
# ---------------------------------------------------------------------------


@router.get("/briefing/config")
async def get_briefing_config():
    """Get the morning briefing auto-trigger configuration."""
    return {
        "enabled": _morning_briefing_enabled,
        "hour": _morning_briefing_hour,
        "last_auto_date": _last_morning_briefing_date,
        "has_cached": _cached_briefing is not None,
        "cached_at": _cached_at if _cached_briefing else None,
    }


@router.post("/briefing/config")
async def set_briefing_config(
    request: Request,
    enabled: Optional[bool] = None,
    hour: Optional[int] = None,
):
    """Configure the morning briefing auto-trigger.

    Body (JSON):
        enabled: Enable or disable auto-trigger
        hour: Hour of day (0-23) for the auto-briefing
    """
    global _morning_briefing_enabled, _morning_briefing_hour

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    if enabled is not None:
        _morning_briefing_enabled = enabled
    elif "enabled" in body:
        _morning_briefing_enabled = bool(body["enabled"])

    if hour is not None:
        _morning_briefing_hour = max(0, min(23, hour))
    elif "hour" in body:
        _morning_briefing_hour = max(0, min(23, int(body["hour"])))

    return {
        "enabled": _morning_briefing_enabled,
        "hour": _morning_briefing_hour,
    }


async def _morning_briefing_loop(app) -> None:
    """Background loop that auto-generates a briefing at the configured hour.

    Checks once per minute whether it's time to generate a morning briefing.
    Only generates one briefing per calendar day.
    """
    global _cached_briefing, _cached_at, _last_morning_briefing_date

    log.info("Morning briefing auto-trigger started (hour=%d)", _morning_briefing_hour)

    while True:
        try:
            await asyncio.sleep(60)  # check every minute

            if not _morning_briefing_enabled:
                continue

            now = datetime.now()
            today = now.strftime("%Y-%m-%d")

            # Already generated today?
            if _last_morning_briefing_date == today:
                continue

            # Is it the right hour?
            if now.hour != _morning_briefing_hour:
                continue

            log.info("Auto-generating morning briefing for %s", today)

            # Build a minimal request-like object to gather context
            class _FakeRequest:
                def __init__(self, app_ref):
                    self.app = app_ref

            fake_req = _FakeRequest(app)
            context = _gather_context(fake_req)

            llm_text = _try_ollama_briefing(context)
            source = "ollama" if llm_text else "template"
            briefing_text = llm_text if llm_text else _template_briefing(context)

            result = {
                "briefing_id": f"AMY-BRIEF-{now.strftime('%Y%m%d-%H%M%S')}",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "auto_generated": True,
                "text": briefing_text,
                "context_summary": {
                    "threat_level": (context.get("sitrep") or {}).get("threat_level", "UNKNOWN"),
                    "total_targets": (context.get("targets") or {}).get("total", 0),
                    "new_targets_24h": (context.get("picture_of_day") or {}).get("new_targets", 0),
                },
            }

            _cached_briefing = result
            _cached_at = time.time()
            _last_morning_briefing_date = today

            log.info(
                "Morning briefing generated: %s (source=%s)",
                result["briefing_id"], source,
            )

        except asyncio.CancelledError:
            log.info("Morning briefing loop cancelled")
            break
        except Exception as exc:
            log.warning("Morning briefing loop error: %s", exc)
            await asyncio.sleep(300)  # back off on error


def start_morning_briefing(app) -> None:
    """Start the morning briefing background task.

    Called from app startup. Pass the FastAPI app instance.
    """
    global _morning_briefing_task

    if _morning_briefing_task is not None:
        return

    _morning_briefing_task = asyncio.create_task(
        _morning_briefing_loop(app)
    )
    log.info("Morning briefing task created")


def stop_morning_briefing() -> None:
    """Stop the morning briefing background task."""
    global _morning_briefing_task

    if _morning_briefing_task is not None:
        _morning_briefing_task.cancel()
        _morning_briefing_task = None
        log.info("Morning briefing task stopped")
