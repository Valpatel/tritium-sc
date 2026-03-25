# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tactical Situation Report (SITREP) generator.

Auto-generates a text summary of the current tactical picture:
target counts, active threats, geofence breaches, fleet status, and
Amy's assessment.  The report can be retrieved as JSON or plain text
and is suitable for forwarding via MQTT or TAK to other operators.

Endpoints:
    GET /api/sitrep           — JSON SITREP
    GET /api/sitrep/text      — Plain text SITREP (human-readable)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/api", tags=["sitrep"])


def _get_tracker(request: Request):
    """Get target tracker from Amy or app state."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        return getattr(amy, "target_tracker", None)
    return None


def _get_sim_engine(request: Request):
    """Get simulation engine (headless fallback)."""
    return getattr(request.app.state, "simulation_engine", None)


def _build_target_summary(request: Request) -> dict:
    """Build target counts by alliance and type."""
    tracker = _get_tracker(request)
    targets = []

    if tracker is not None:
        targets = [t.to_dict() for t in tracker.get_all()]
    else:
        engine = _get_sim_engine(request)
        if engine is not None:
            targets = [t.to_dict() for t in engine.get_targets()]

    total = len(targets)

    # Count by alliance
    by_alliance: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    threats = []

    for t in targets:
        alliance = t.get("alliance", "unknown") or "unknown"
        by_alliance[alliance] = by_alliance.get(alliance, 0) + 1

        asset_type = t.get("asset_type", t.get("type", "unknown")) or "unknown"
        by_type[asset_type] = by_type.get(asset_type, 0) + 1

        source = t.get("source", "unknown") or "unknown"
        by_source[source] = by_source.get(source, 0) + 1

        if alliance == "hostile":
            threats.append({
                "target_id": t.get("target_id", ""),
                "name": t.get("name", ""),
                "type": asset_type,
                "lat": t.get("lat"),
                "lng": t.get("lng"),
            })

    return {
        "total": total,
        "by_alliance": by_alliance,
        "by_type": by_type,
        "by_source": by_source,
        "active_threats": threats,
        "threat_count": len(threats),
    }


def _build_fleet_summary(request: Request) -> dict:
    """Build fleet status summary."""
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        cached = getattr(bridge, "cached_nodes", None)
        if cached and isinstance(cached, list):
            online = sum(1 for n in cached if n.get("status") == "online")
            return {
                "total_nodes": len(cached),
                "online": online,
                "offline": len(cached) - online,
            }

    return {"total_nodes": 0, "online": 0, "offline": 0}


def _build_geofence_summary() -> dict:
    """Build geofence breach summary."""
    try:
        from app.routers.geofence import get_engine
        engine = get_engine()
        zones = engine.get_zones()
        events = engine.get_events(limit=20)
        recent_breaches = [
            {
                "zone": e.get("zone_name", ""),
                "target_id": e.get("target_id", ""),
                "event_type": e.get("event_type", ""),
                "time": e.get("timestamp", 0),
            }
            for e in events
        ]
        return {
            "zone_count": len(zones),
            "recent_breaches": recent_breaches,
            "breach_count": len(recent_breaches),
        }
    except Exception:
        return {"zone_count": 0, "recent_breaches": [], "breach_count": 0}


def _get_amy_assessment(request: Request) -> Optional[str]:
    """Get Amy's latest assessment or thought."""
    amy = getattr(request.app.state, "amy", None)
    if amy is None:
        return None

    # Try to get the latest thought
    last_thought = getattr(amy, "last_thought", None)
    if last_thought:
        return str(last_thought)

    # Fall back to mood/state
    state = getattr(amy, "state", "unknown")
    mood = getattr(amy, "mood", "unknown")
    return f"State: {state}, Mood: {mood}"


def _build_sitrep(request: Request) -> dict:
    """Build the full SITREP."""
    now = datetime.now(timezone.utc)

    targets = _build_target_summary(request)
    fleet = _build_fleet_summary(request)
    geofence = _build_geofence_summary()
    amy_assessment = _get_amy_assessment(request)

    # Determine overall threat level
    threat_count = targets["threat_count"]
    if threat_count == 0:
        threat_level = "GREEN"
    elif threat_count <= 3:
        threat_level = "YELLOW"
    elif threat_count <= 10:
        threat_level = "ORANGE"
    else:
        threat_level = "RED"

    return {
        "sitrep_id": f"SITREP-{now.strftime('%Y%m%d-%H%M%S')}",
        "timestamp": now.isoformat(),
        "timestamp_epoch": time.time(),
        "threat_level": threat_level,
        "targets": targets,
        "fleet": fleet,
        "geofence": geofence,
        "amy_assessment": amy_assessment,
        "system": {
            "version": "0.1.0",
            "uptime_s": _get_uptime(),
        },
    }


def _get_uptime() -> float:
    """Get system uptime in seconds."""
    try:
        from app.routers.health import _start_time
        return time.time() - _start_time
    except Exception:
        return 0.0


def _sitrep_to_text(sitrep: dict) -> str:
    """Convert SITREP dict to human-readable plain text."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"  TRITIUM SITUATION REPORT  [{sitrep['sitrep_id']}]")
    lines.append(f"  Generated: {sitrep['timestamp']}")
    lines.append("=" * 60)
    lines.append("")

    # Threat level
    tl = sitrep["threat_level"]
    lines.append(f"THREAT LEVEL: {tl}")
    lines.append("")

    # Target summary
    t = sitrep["targets"]
    lines.append(f"TARGETS: {t['total']} total")
    if t["by_alliance"]:
        parts = [f"  {k}: {v}" for k, v in sorted(t["by_alliance"].items())]
        lines.extend(parts)
    lines.append("")

    if t["by_source"]:
        lines.append("BY SOURCE:")
        for k, v in sorted(t["by_source"].items()):
            lines.append(f"  {k}: {v}")
        lines.append("")

    # Active threats
    if t["active_threats"]:
        lines.append(f"ACTIVE THREATS: {t['threat_count']}")
        for threat in t["active_threats"][:10]:
            name = threat.get("name") or threat.get("target_id", "unknown")
            ttype = threat.get("type", "unknown")
            lat = threat.get("lat")
            lng = threat.get("lng")
            pos = f" at ({lat:.6f}, {lng:.6f})" if lat and lng else ""
            lines.append(f"  - {name} [{ttype}]{pos}")
        lines.append("")

    # Fleet
    f = sitrep["fleet"]
    if f["total_nodes"] > 0:
        lines.append(f"FLEET: {f['online']}/{f['total_nodes']} nodes online")
        lines.append("")

    # Geofence
    g = sitrep["geofence"]
    if g["zone_count"] > 0:
        lines.append(f"GEOFENCE: {g['zone_count']} zones, {g['breach_count']} recent events")
        for b in g["recent_breaches"][:5]:
            lines.append(f"  - {b['event_type']}: {b['target_id']} in {b['zone']}")
        lines.append("")

    # Amy
    if sitrep.get("amy_assessment"):
        lines.append(f"AMY ASSESSMENT: {sitrep['amy_assessment']}")
        lines.append("")

    # LLM narrative summary (if available)
    if sitrep.get("llm_summary"):
        lines.append(f"NARRATIVE SUMMARY: {sitrep['llm_summary']}")
        lines.append("")

    lines.append("=" * 60)
    lines.append("  END SITREP")
    lines.append("=" * 60)

    return "\n".join(lines)


def _llm_enhance_sitrep(sitrep: dict) -> Optional[str]:
    """Optionally enhance SITREP with an LLM-generated natural language summary.

    Uses qwen2.5:3b via OllamaFleet to generate a narrative paragraph
    from the structured SITREP data. Falls back gracefully if no LLM
    is available.

    Returns:
        Natural language summary string, or None if unavailable.
    """
    try:
        from tritium_lib.inference.fleet import OllamaFleet
        fleet = OllamaFleet(auto_discover=False)
        if fleet.count == 0:
            return None

        # Try qwen2.5:3b first, fall back to any available model
        model = "qwen2.5:3b"
        if not fleet.hosts_with_model(model):
            # Try larger qwen
            model = "qwen2.5:7b"
            if not fleet.hosts_with_model(model):
                return None

        # Build a structured prompt
        targets = sitrep.get("targets", {})
        fleet_status = sitrep.get("fleet", {})
        threat_level = sitrep.get("threat_level", "UNKNOWN")

        prompt = (
            "You are a military intelligence analyst. Write a concise 2-3 sentence "
            "situation summary based on this data. Be professional and direct. "
            "Do not use markdown formatting.\n\n"
            f"Threat Level: {threat_level}\n"
            f"Total Targets: {targets.get('total', 0)}\n"
            f"By Alliance: {targets.get('by_alliance', {})}\n"
            f"By Type: {targets.get('by_type', {})}\n"
            f"Active Threats: {targets.get('threat_count', 0)}\n"
            f"Fleet Nodes Online: {fleet_status.get('online', 0)}/{fleet_status.get('total_nodes', 0)}\n"
            f"Geofence Breaches: {sitrep.get('geofence', {}).get('breach_count', 0)}\n"
        )

        response = fleet.generate(model=model, prompt=prompt, timeout=15.0)
        if response and len(response.strip()) > 10:
            return response.strip()
        return None
    except Exception:
        return None


@router.get("/sitrep")
async def get_sitrep(
    request: Request,
    enhance: bool = Query(False, description="Add LLM-generated narrative summary"),
):
    """Generate a tactical situation report (SITREP).

    Returns a JSON summary of:
    - Target counts by alliance, type, and source
    - Active threats with positions
    - Fleet node status
    - Geofence zone breaches
    - Amy's current assessment
    - Overall threat level (GREEN/YELLOW/ORANGE/RED)

    Pass ?enhance=true to include an LLM-generated natural language summary.
    """
    sitrep = _build_sitrep(request)
    if enhance:
        llm_summary = _llm_enhance_sitrep(sitrep)
        if llm_summary:
            sitrep["llm_summary"] = llm_summary
    return sitrep


@router.get("/sitrep/text", response_class=PlainTextResponse)
async def get_sitrep_text(
    request: Request,
    enhance: bool = Query(False, description="Add LLM-generated narrative summary"),
):
    """Generate a human-readable plain text SITREP.

    Suitable for sending via MQTT, TAK, radio, or printing.
    Pass ?enhance=true to include an LLM-generated narrative paragraph.
    """
    sitrep = _build_sitrep(request)
    if enhance:
        llm_summary = _llm_enhance_sitrep(sitrep)
        if llm_summary:
            sitrep["llm_summary"] = llm_summary
    return _sitrep_to_text(sitrep)


@router.get("/threat-level")
async def get_threat_level(request: Request):
    """Return the current system-wide computed threat level.

    The threat level is calculated in real-time from hostile target count,
    geofence breaches, active investigations, threat feed matches, and
    behavioral anomalies. Published to WebSocket as ``system_threat_level``.
    """
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        calc = getattr(amy, "threat_level_calculator", None)
        if calc is not None:
            return calc.get_status()

    return {"level": "green", "score": 0.0}


@router.get("/threat-level/history")
async def get_threat_level_history(
    request: Request,
    hours: float = Query(24.0, ge=0.1, le=24.0, description="Hours of history to return"),
):
    """Return threat level history as time-series data.

    Returns timestamped threat level and score values for the requested
    time window (default 24 hours, max 24 hours). Suitable for rendering
    as a line chart in the analytics dashboard.
    """
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        calc = getattr(amy, "threat_level_calculator", None)
        if calc is not None:
            history = calc.get_history(hours)
            return {
                "hours": hours,
                "count": len(history),
                "current": calc.get_status(),
                "history": history,
            }

    return {"hours": hours, "count": 0, "current": {"level": "green", "score": 0.0}, "history": []}
