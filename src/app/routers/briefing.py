# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Operational briefing generator — combines SITREP, investigations, fleet,
and threat assessment into a formatted briefing document.

Generates a comprehensive operational briefing suitable for shift handoffs,
status updates, and record-keeping. Available as JSON, plain text, or
printable HTML.

Endpoints:
    GET /api/briefing           — JSON briefing
    GET /api/briefing/text      — plain text briefing
    GET /api/briefing/html      — printable HTML briefing
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from loguru import logger

router = APIRouter(prefix="/api/briefing", tags=["briefing"])


def _get_sitrep(request: Request) -> dict:
    """Get current SITREP data."""
    try:
        from app.routers.sitrep import _build_sitrep
        return _build_sitrep(request)
    except Exception:
        return {"threat_level": "UNKNOWN", "targets": {"total": 0}, "fleet": {}, "geofence": {}}


def _get_active_investigations() -> list[dict]:
    """Get active investigations from the investigations system."""
    try:
        from app.routers.investigations import _get_store
        store = _get_store()
        if store is None:
            return []
        investigations = store.list_active()
        return [
            {
                "id": inv.get("investigation_id", ""),
                "title": inv.get("title", ""),
                "status": inv.get("status", ""),
                "priority": inv.get("priority", ""),
                "created": inv.get("created", ""),
                "assigned_to": inv.get("assigned_to", ""),
            }
            for inv in investigations[:10]
        ]
    except Exception:
        return []


def _get_active_sessions() -> list[dict]:
    """Get active operator sessions."""
    try:
        from app.routers.sessions import get_session_store
        sessions = get_session_store()
        return [
            {
                "username": s.username,
                "display_name": s.display_name,
                "role": s.role.value,
                "connected_at": s.connected_at.isoformat(),
            }
            for s in sessions.values()
        ]
    except Exception:
        return []


def _get_recent_operator_actions() -> list[dict]:
    """Get recent operator actions for the briefing."""
    try:
        from app.audit_middleware import get_audit_store
        store = get_audit_store()
        if store is None:
            return []
        entries = store.query(resource="operator_action", limit=20)
        return [
            {
                "timestamp": e.timestamp,
                "actor": e.actor,
                "action": e.action,
                "detail": e.detail,
            }
            for e in entries
        ]
    except Exception:
        return []


def _get_mission_status(request: Request) -> list[dict]:
    """Get active missions."""
    try:
        from app.routers.missions import _get_store
        store = _get_store()
        if store is None:
            return []
        missions = store.list_all()
        active = [m for m in missions if m.get("status") in ("active", "planned", "briefing")]
        return [
            {
                "id": m.get("mission_id", ""),
                "name": m.get("name", ""),
                "status": m.get("status", ""),
                "type": m.get("mission_type", ""),
            }
            for m in active[:10]
        ]
    except Exception:
        return []


def _build_briefing(request: Request) -> dict:
    """Build the full operational briefing."""
    now = datetime.now(timezone.utc)

    sitrep = _get_sitrep(request)
    investigations = _get_active_investigations()
    sessions = _get_active_sessions()
    recent_actions = _get_recent_operator_actions()
    missions = _get_mission_status(request)

    # System uptime
    try:
        from app.routers.health import _start_time
        uptime_s = time.time() - _start_time
    except Exception:
        uptime_s = 0.0

    uptime_h = uptime_s / 3600

    return {
        "briefing_id": f"BRIEF-{now.strftime('%Y%m%d-%H%M%S')}",
        "generated_at": now.isoformat(),
        "generated_epoch": time.time(),
        "classification": "UNCLASSIFIED",

        # Tactical picture
        "threat_level": sitrep.get("threat_level", "UNKNOWN"),
        "target_summary": sitrep.get("targets", {}),
        "active_threats": sitrep.get("targets", {}).get("active_threats", []),

        # Fleet status
        "fleet": sitrep.get("fleet", {}),

        # Geofence status
        "geofence": sitrep.get("geofence", {}),

        # Intelligence
        "active_investigations": investigations,
        "investigation_count": len(investigations),

        # Missions
        "active_missions": missions,
        "mission_count": len(missions),

        # Operators
        "active_operators": sessions,
        "operator_count": len(sessions),

        # Recent activity
        "recent_actions": recent_actions,

        # Amy assessment
        "amy_assessment": sitrep.get("amy_assessment"),

        # System
        "system": {
            "version": "0.1.0",
            "uptime_hours": round(uptime_h, 1),
            "uptime_seconds": round(uptime_s),
        },
    }


def _briefing_to_text(briefing: dict) -> str:
    """Convert briefing to human-readable plain text."""
    lines = []
    lines.append("=" * 72)
    lines.append(f"  TRITIUM OPERATIONAL BRIEFING  [{briefing['briefing_id']}]")
    lines.append(f"  Classification: {briefing['classification']}")
    lines.append(f"  Generated: {briefing['generated_at']}")
    lines.append("=" * 72)
    lines.append("")

    # 1. Threat Assessment
    lines.append("1. THREAT ASSESSMENT")
    lines.append("-" * 40)
    lines.append(f"   Threat Level: {briefing['threat_level']}")
    ts = briefing.get("target_summary", {})
    lines.append(f"   Total Targets: {ts.get('total', 0)}")
    for alliance, count in sorted(ts.get("by_alliance", {}).items()):
        lines.append(f"     {alliance}: {count}")
    threats = briefing.get("active_threats", [])
    if threats:
        lines.append(f"   Active Threats: {len(threats)}")
        for t in threats[:5]:
            name = t.get("name") or t.get("target_id", "unknown")
            lines.append(f"     - {name} [{t.get('type', '?')}]")
    lines.append("")

    # 2. Fleet Status
    fleet = briefing.get("fleet", {})
    if fleet.get("total_nodes", 0) > 0:
        lines.append("2. FLEET STATUS")
        lines.append("-" * 40)
        lines.append(f"   Nodes: {fleet.get('online', 0)}/{fleet.get('total_nodes', 0)} online")
        lines.append("")

    # 3. Active Missions
    missions = briefing.get("active_missions", [])
    if missions:
        lines.append("3. ACTIVE MISSIONS")
        lines.append("-" * 40)
        for m in missions:
            lines.append(f"   [{m.get('status', '?')}] {m.get('name', 'unnamed')} ({m.get('type', '?')})")
        lines.append("")

    # 4. Intelligence / Investigations
    investigations = briefing.get("active_investigations", [])
    if investigations:
        lines.append("4. ACTIVE INVESTIGATIONS")
        lines.append("-" * 40)
        for inv in investigations:
            lines.append(f"   [{inv.get('priority', '?')}] {inv.get('title', 'untitled')} — {inv.get('status', '?')}")
            if inv.get("assigned_to"):
                lines.append(f"     Assigned: {inv['assigned_to']}")
        lines.append("")

    # 5. Geofence Status
    geo = briefing.get("geofence", {})
    if geo.get("zone_count", 0) > 0:
        lines.append("5. GEOFENCE STATUS")
        lines.append("-" * 40)
        lines.append(f"   Zones: {geo['zone_count']}, Recent events: {geo.get('breach_count', 0)}")
        for b in geo.get("recent_breaches", [])[:3]:
            lines.append(f"     {b.get('event_type', '?')}: {b.get('target_id', '?')} in {b.get('zone', '?')}")
        lines.append("")

    # 6. Active Operators
    operators = briefing.get("active_operators", [])
    lines.append("6. ACTIVE OPERATORS")
    lines.append("-" * 40)
    if operators:
        for op in operators:
            lines.append(f"   {op.get('display_name', op.get('username', '?'))} ({op.get('role', '?')})")
    else:
        lines.append("   No active operator sessions")
    lines.append("")

    # 7. Recent Activity
    actions = briefing.get("recent_actions", [])
    if actions:
        lines.append("7. RECENT ACTIVITY")
        lines.append("-" * 40)
        for a in actions[:10]:
            ts_str = datetime.fromtimestamp(a.get("timestamp", 0), timezone.utc).strftime("%H:%M:%S")
            lines.append(f"   [{ts_str}] {a.get('actor', '?')}: {a.get('action', '?')}")
        lines.append("")

    # 8. Amy Assessment
    if briefing.get("amy_assessment"):
        lines.append("8. AI COMMANDER ASSESSMENT")
        lines.append("-" * 40)
        lines.append(f"   {briefing['amy_assessment']}")
        lines.append("")

    # Footer
    sys = briefing.get("system", {})
    lines.append("=" * 72)
    lines.append(f"  System: TRITIUM-SC v{sys.get('version', '0.1.0')}")
    lines.append(f"  Uptime: {sys.get('uptime_hours', 0)} hours")
    lines.append("  END BRIEFING")
    lines.append("=" * 72)

    return "\n".join(lines)


def _briefing_to_html(briefing: dict) -> str:
    """Convert briefing to printable HTML."""
    text = _briefing_to_text(briefing)

    # Determine threat level color
    tl = briefing.get("threat_level", "UNKNOWN")
    tl_color = {"GREEN": "#05ffa1", "YELLOW": "#fcee0a", "ORANGE": "#ff8c00", "RED": "#ff2a6d"}.get(tl, "#888")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Operational Briefing — {briefing['briefing_id']}</title>
<style>
    @media print {{
        body {{ background: #fff !important; color: #000 !important; }}
        .header {{ border-color: #000 !important; }}
    }}
    body {{
        background: #0a0a0f;
        color: #c8c8d0;
        font-family: 'Courier New', monospace;
        max-width: 800px;
        margin: 40px auto;
        padding: 20px;
        line-height: 1.6;
    }}
    .header {{
        border: 2px solid {tl_color};
        padding: 20px;
        margin-bottom: 30px;
        text-align: center;
    }}
    .header h1 {{
        color: #00f0ff;
        margin: 0;
        font-size: 24px;
    }}
    .header .threat-level {{
        color: {tl_color};
        font-size: 32px;
        font-weight: bold;
        margin: 10px 0;
    }}
    .header .meta {{
        color: #888;
        font-size: 12px;
    }}
    .section {{
        margin-bottom: 25px;
    }}
    .section h2 {{
        color: #00f0ff;
        border-bottom: 1px solid #1a1a2e;
        padding-bottom: 5px;
        font-size: 16px;
    }}
    .section ul {{
        list-style: none;
        padding-left: 10px;
    }}
    .section li {{
        padding: 3px 0;
    }}
    .section li::before {{
        content: "\\25B6 ";
        color: #ff2a6d;
    }}
    .badge {{
        display: inline-block;
        padding: 2px 8px;
        border-radius: 3px;
        font-size: 11px;
        font-weight: bold;
    }}
    .badge-hostile {{ background: #ff2a6d33; color: #ff2a6d; border: 1px solid #ff2a6d; }}
    .badge-friendly {{ background: #05ffa133; color: #05ffa1; border: 1px solid #05ffa1; }}
    .badge-unknown {{ background: #88888833; color: #888888; border: 1px solid #888888; }}
    .footer {{
        border-top: 1px solid #1a1a2e;
        padding-top: 15px;
        color: #555;
        font-size: 12px;
        text-align: center;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 10px 0;
    }}
    th, td {{
        text-align: left;
        padding: 6px 10px;
        border-bottom: 1px solid #1a1a2e;
    }}
    th {{
        color: #00f0ff;
        font-size: 12px;
        text-transform: uppercase;
    }}
</style>
</head>
<body>

<div class="header">
    <h1>TRITIUM OPERATIONAL BRIEFING</h1>
    <div class="threat-level">THREAT LEVEL: {tl}</div>
    <div class="meta">
        {briefing['briefing_id']} | {briefing['generated_at']} |
        {briefing['classification']}
    </div>
</div>
"""

    # Target summary
    ts = briefing.get("target_summary", {})
    html += '<div class="section"><h2>TACTICAL PICTURE</h2>'
    html += f'<p>Total Targets: <strong>{ts.get("total", 0)}</strong></p>'
    if ts.get("by_alliance"):
        html += "<table><tr><th>Alliance</th><th>Count</th></tr>"
        for alliance, count in sorted(ts.get("by_alliance", {}).items()):
            badge = f'badge-{alliance}' if alliance in ("hostile", "friendly") else "badge-unknown"
            html += f'<tr><td><span class="badge {badge}">{alliance}</span></td><td>{count}</td></tr>'
        html += "</table>"

    threats = briefing.get("active_threats", [])
    if threats:
        html += f"<p>Active Threats: <strong>{len(threats)}</strong></p><ul>"
        for t in threats[:10]:
            name = t.get("name") or t.get("target_id", "unknown")
            html += f'<li>{name} [{t.get("type", "?")}]</li>'
        html += "</ul>"
    html += "</div>"

    # Fleet
    fleet = briefing.get("fleet", {})
    if fleet.get("total_nodes", 0) > 0:
        html += '<div class="section"><h2>FLEET STATUS</h2>'
        html += f'<p>{fleet.get("online", 0)} / {fleet.get("total_nodes", 0)} nodes online</p></div>'

    # Missions
    missions = briefing.get("active_missions", [])
    if missions:
        html += '<div class="section"><h2>ACTIVE MISSIONS</h2><table><tr><th>Mission</th><th>Type</th><th>Status</th></tr>'
        for m in missions:
            html += f'<tr><td>{m.get("name", "?")}</td><td>{m.get("type", "?")}</td><td>{m.get("status", "?")}</td></tr>'
        html += "</table></div>"

    # Investigations
    investigations = briefing.get("active_investigations", [])
    if investigations:
        html += '<div class="section"><h2>ACTIVE INVESTIGATIONS</h2><table><tr><th>Title</th><th>Priority</th><th>Status</th><th>Assigned</th></tr>'
        for inv in investigations:
            html += f'<tr><td>{inv.get("title", "?")}</td><td>{inv.get("priority", "?")}</td><td>{inv.get("status", "?")}</td><td>{inv.get("assigned_to", "")}</td></tr>'
        html += "</table></div>"

    # Operators
    operators = briefing.get("active_operators", [])
    html += '<div class="section"><h2>ACTIVE OPERATORS</h2>'
    if operators:
        html += "<table><tr><th>Operator</th><th>Role</th></tr>"
        for op in operators:
            html += f'<tr><td>{op.get("display_name", op.get("username", "?"))}</td><td>{op.get("role", "?")}</td></tr>'
        html += "</table>"
    else:
        html += "<p>No active operator sessions</p>"
    html += "</div>"

    # Amy assessment
    if briefing.get("amy_assessment"):
        html += f'<div class="section"><h2>AI COMMANDER ASSESSMENT</h2><p>{briefing["amy_assessment"]}</p></div>'

    # Footer
    sys = briefing.get("system", {})
    html += f"""
<div class="footer">
    TRITIUM-SC v{sys.get("version", "0.1.0")} |
    Uptime: {sys.get("uptime_hours", 0)} hours |
    Generated by Tritium Command Center
</div>
</body></html>"""

    return html


@router.get("")
async def get_briefing(request: Request):
    """Generate a comprehensive operational briefing (JSON).

    Combines SITREP, active investigations, fleet status, operator
    presence, and threat assessment into a single document.
    """
    return _build_briefing(request)


@router.get("/text", response_class=PlainTextResponse)
async def get_briefing_text(request: Request):
    """Generate a plain text operational briefing.

    Human-readable, suitable for radio/MQTT/TAK forwarding.
    """
    briefing = _build_briefing(request)
    return _briefing_to_text(briefing)


@router.get("/html", response_class=HTMLResponse)
async def get_briefing_html(request: Request):
    """Generate a printable HTML operational briefing.

    Styled with cyberpunk theme, print-friendly CSS for hardcopy output.
    """
    briefing = _build_briefing(request)
    return _briefing_to_html(briefing)
