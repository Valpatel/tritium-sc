# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unified Alerts API — aggregates alerts from all sources into one feed.

Pulls from:
  - Geofence events (enter/exit zones)
  - BLE first-seen / suspicious notifications
  - LPR watchlist matches
  - Threat feed matches (escalation events)
  - Federation shared threats
  - Acoustic high-severity events
  - Sensor health degradation alerts

API:
  GET /api/alerts/unified?limit=100&since=<unix_ts>&source=<filter>&severity=<filter>
  GET /api/alerts/unified/counts — per-source and per-severity counts
"""
from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/alerts/unified", tags=["alerts"])

# Severity ordering for sorting
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

VALID_SOURCES = {
    "geofence", "ble", "lpr", "threat", "federation",
    "acoustic", "sensor_health", "notification", "escalation",
}


def _safe_fetch(func, *args, **kwargs) -> list:
    """Call a function, return empty list on any failure."""
    try:
        result = func(*args, **kwargs)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _gather_geofence_alerts(since: float, limit: int) -> list[dict[str, Any]]:
    """Gather geofence enter/exit events as alerts."""
    alerts: list[dict[str, Any]] = []
    try:
        from app.routers.geofence import get_engine
        engine = get_engine()
        events = engine.get_events(limit=limit)
        for ev in events:
            ts = getattr(ev, "timestamp", 0.0)
            if ts < since:
                continue
            event_type = getattr(ev, "event_type", "enter")
            zone_type = getattr(ev, "zone_type", "monitored")
            # Restricted zone entry is high severity
            if zone_type == "restricted" and event_type == "enter":
                severity = "high"
            elif event_type == "enter":
                severity = "medium"
            else:
                severity = "low"
            alerts.append({
                "id": f"geo_{getattr(ev, 'event_id', '')}",
                "source": "geofence",
                "severity": severity,
                "title": f"Geofence {event_type}",
                "message": f"Target {getattr(ev, 'target_id', '?')[:12]} {event_type} zone {getattr(ev, 'zone_name', '?')}",
                "timestamp": ts,
                "entity_id": getattr(ev, "target_id", None),
                "zone_id": getattr(ev, "zone_id", None),
                "data": {
                    "event_type": event_type,
                    "zone_name": getattr(ev, "zone_name", ""),
                    "zone_type": zone_type,
                    "position": list(getattr(ev, "position", [])),
                },
            })
    except Exception:
        pass
    return alerts


def _gather_notification_alerts(since: float, limit: int) -> list[dict[str, Any]]:
    """Gather cross-plugin notifications as alerts."""
    alerts: list[dict[str, Any]] = []
    try:
        from app.routers.notifications import get_manager
        mgr = get_manager()
        notifs = mgr.get_all(limit=limit, since=since)
        for n in notifs:
            ts = n.timestamp if hasattr(n, "timestamp") else (n.get("timestamp", 0.0) if isinstance(n, dict) else 0.0)
            if ts < since:
                continue
            sev_raw = n.severity if hasattr(n, "severity") else (n.get("severity", "info") if isinstance(n, dict) else "info")
            source_raw = n.source if hasattr(n, "source") else (n.get("source", "notification") if isinstance(n, dict) else "notification")
            # Map notification sources to our alert sources
            alert_source = "notification"
            if "ble" in source_raw.lower():
                alert_source = "ble"
            elif "lpr" in source_raw.lower():
                alert_source = "lpr"
            elif "threat" in source_raw.lower() or "escalat" in source_raw.lower():
                alert_source = "threat"
            elif "federation" in source_raw.lower():
                alert_source = "federation"
            elif "acoustic" in source_raw.lower():
                alert_source = "acoustic"
            elif "sensor" in source_raw.lower() or "health" in source_raw.lower():
                alert_source = "sensor_health"

            title = n.title if hasattr(n, "title") else (n.get("title", "") if isinstance(n, dict) else "")
            message = n.message if hasattr(n, "message") else (n.get("message", "") if isinstance(n, dict) else "")
            nid = n.id if hasattr(n, "id") else (n.get("id", "") if isinstance(n, dict) else "")
            entity_id = n.entity_id if hasattr(n, "entity_id") else (n.get("entity_id", None) if isinstance(n, dict) else None)

            alerts.append({
                "id": f"notif_{nid}",
                "source": alert_source,
                "severity": _map_severity(sev_raw),
                "title": title or f"{alert_source} alert",
                "message": message,
                "timestamp": ts,
                "entity_id": entity_id,
                "data": {"notification_source": source_raw},
            })
    except Exception:
        pass
    return alerts


def _gather_acoustic_alerts(since: float, limit: int) -> list[dict[str, Any]]:
    """Gather high-severity acoustic events as alerts."""
    alerts: list[dict[str, Any]] = []
    try:
        from engine.audio.acoustic_classifier import AcousticClassifier
        classifier = AcousticClassifier()
        timeline = getattr(classifier, "get_timeline", None)
        if timeline is None:
            return alerts
        events = timeline(count=limit)
        if not isinstance(events, list):
            return alerts
        high_severity_types = {"gunshot", "explosion", "scream", "breaking_glass", "alarm"}
        for ev in events:
            ts = ev.get("timestamp", 0.0) if isinstance(ev, dict) else getattr(ev, "timestamp", 0.0)
            if ts < since:
                continue
            event_type = ev.get("event_type", "") if isinstance(ev, dict) else getattr(ev, "event_type", "")
            confidence = ev.get("confidence", 0.0) if isinstance(ev, dict) else getattr(ev, "confidence", 0.0)
            if event_type in high_severity_types or confidence > 0.8:
                severity = "critical" if event_type in {"gunshot", "explosion"} else "high"
                alerts.append({
                    "id": f"acoustic_{ts}",
                    "source": "acoustic",
                    "severity": severity,
                    "title": f"Acoustic: {event_type}",
                    "message": f"Detected {event_type} (confidence {confidence:.0%})",
                    "timestamp": ts,
                    "entity_id": None,
                    "data": {"event_type": event_type, "confidence": confidence},
                })
    except Exception:
        pass
    return alerts


def _gather_sensor_health_alerts(since: float, limit: int) -> list[dict[str, Any]]:
    """Gather sensor health degradation alerts."""
    alerts: list[dict[str, Any]] = []
    try:
        from app.routers.sensor_health import get_health_data
        data = get_health_data()
        sensors = data.get("sensors", []) if isinstance(data, dict) else []
        for s in sensors:
            health = s.get("health", "green") if isinstance(s, dict) else "green"
            if health in ("yellow", "red"):
                name = s.get("name", "unknown") if isinstance(s, dict) else "unknown"
                last_seen = s.get("last_seen", 0.0) if isinstance(s, dict) else 0.0
                severity = "high" if health == "red" else "medium"
                ts = last_seen if last_seen > since else time.time()
                alerts.append({
                    "id": f"sh_{name}_{health}",
                    "source": "sensor_health",
                    "severity": severity,
                    "title": f"Sensor {health.upper()}: {name}",
                    "message": f"Sensor {name} health degraded to {health}",
                    "timestamp": ts,
                    "entity_id": name,
                    "data": {"sensor_name": name, "health": health},
                })
    except Exception:
        pass
    return alerts


def _gather_lpr_watchlist_alerts(since: float, limit: int) -> list[dict[str, Any]]:
    """Gather LPR watchlist match alerts from recent detections."""
    alerts: list[dict[str, Any]] = []
    try:
        from app.routers.lpr import get_manager as get_lpr_manager
        mgr = get_lpr_manager()
        # Get recent detections that matched watchlist
        detections = mgr.get_detections(count=limit)
        if not isinstance(detections, list):
            return alerts
        for det in detections:
            ts = det.get("timestamp", 0.0) if isinstance(det, dict) else getattr(det, "timestamp", 0.0)
            if ts < since:
                continue
            watchlist_match = det.get("watchlist_match", False) if isinstance(det, dict) else getattr(det, "watchlist_match", False)
            if watchlist_match:
                plate = det.get("plate", "?") if isinstance(det, dict) else getattr(det, "plate", "?")
                alerts.append({
                    "id": f"lpr_{plate}_{ts}",
                    "source": "lpr",
                    "severity": "critical",
                    "title": f"LPR Watchlist Match: {plate}",
                    "message": f"Plate {plate} matched watchlist entry",
                    "timestamp": ts,
                    "entity_id": f"lpr_{plate}",
                    "data": {"plate": plate},
                })
    except Exception:
        pass
    return alerts


def _gather_federation_alerts(since: float, limit: int) -> list[dict[str, Any]]:
    """Gather federation shared threat alerts."""
    alerts: list[dict[str, Any]] = []
    try:
        from app.routers.federation import get_manager as get_fed_manager
        mgr = get_fed_manager()
        threats = mgr.get_threats(count=limit) if hasattr(mgr, "get_threats") else []
        if not isinstance(threats, list):
            return alerts
        for t in threats:
            ts = t.get("timestamp", 0.0) if isinstance(t, dict) else getattr(t, "timestamp", 0.0)
            if ts < since:
                continue
            severity = t.get("severity", "high") if isinstance(t, dict) else getattr(t, "severity", "high")
            message = t.get("message", "") if isinstance(t, dict) else getattr(t, "message", "")
            threat_id = t.get("id", "") if isinstance(t, dict) else getattr(t, "id", "")
            alerts.append({
                "id": f"fed_{threat_id}",
                "source": "federation",
                "severity": _map_severity(severity),
                "title": "Federation Threat",
                "message": message or "Shared threat from federated site",
                "timestamp": ts,
                "entity_id": None,
                "data": t if isinstance(t, dict) else {},
            })
    except Exception:
        pass
    return alerts


def _gather_escalation_alerts(since: float, limit: int) -> list[dict[str, Any]]:
    """Gather threat escalation events."""
    alerts: list[dict[str, Any]] = []
    try:
        from engine.tactical.escalation import ThreatClassifier
        # Try to get the singleton or a recently used instance
        classifier = ThreatClassifier()
        history = getattr(classifier, "get_history", None)
        if history is None:
            return alerts
        events = history(limit=limit)
        if not isinstance(events, list):
            return alerts
        for ev in events:
            ts = ev.get("timestamp", 0.0) if isinstance(ev, dict) else getattr(ev, "timestamp", 0.0)
            if ts < since:
                continue
            level = ev.get("level", "unknown") if isinstance(ev, dict) else getattr(ev, "level", "unknown")
            target_id = ev.get("target_id", "") if isinstance(ev, dict) else getattr(ev, "target_id", "")
            severity = "critical" if level in ("hostile", "critical") else "high"
            alerts.append({
                "id": f"esc_{target_id}_{ts}",
                "source": "escalation",
                "severity": severity,
                "title": f"Threat Escalation: {level}",
                "message": f"Target {target_id[:12]} escalated to {level}",
                "timestamp": ts,
                "entity_id": target_id,
                "data": ev if isinstance(ev, dict) else {},
            })
    except Exception:
        pass
    return alerts


def _map_severity(raw: str) -> str:
    """Map various severity strings to our standard set."""
    raw = raw.lower().strip() if raw else "info"
    if raw in ("critical", "hostile"):
        return "critical"
    if raw in ("high", "error", "danger"):
        return "high"
    if raw in ("medium", "warning", "warn"):
        return "medium"
    if raw in ("low", "info", "notice"):
        return "low"
    return "low"


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("")
async def get_unified_alerts(
    limit: int = Query(100, le=500),
    since: float = Query(0.0, description="Unix timestamp — only return alerts after this time"),
    source: Optional[str] = Query(None, description="Filter by source (geofence, ble, lpr, threat, federation, acoustic, sensor_health, escalation)"),
    severity: Optional[str] = Query(None, description="Filter by severity (critical, high, medium, low)"),
):
    """Aggregate alerts from all sources into a single chronological feed."""
    all_alerts: list[dict[str, Any]] = []

    # Gather from each source (with graceful failure)
    gatherers = [
        _gather_geofence_alerts,
        _gather_notification_alerts,
        _gather_acoustic_alerts,
        _gather_sensor_health_alerts,
        _gather_lpr_watchlist_alerts,
        _gather_federation_alerts,
        _gather_escalation_alerts,
    ]

    for gatherer in gatherers:
        try:
            all_alerts.extend(gatherer(since, limit))
        except Exception:
            pass

    # Deduplicate by id
    seen_ids: set[str] = set()
    unique: list[dict[str, Any]] = []
    for a in all_alerts:
        aid = a.get("id", "")
        if aid and aid in seen_ids:
            continue
        if aid:
            seen_ids.add(aid)
        unique.append(a)

    # Filter by source
    if source:
        source_set = {s.strip().lower() for s in source.split(",")}
        unique = [a for a in unique if a.get("source", "") in source_set]

    # Filter by severity
    if severity:
        sev_set = {s.strip().lower() for s in severity.split(",")}
        unique = [a for a in unique if a.get("severity", "") in sev_set]

    # Sort by timestamp descending (newest first)
    unique.sort(key=lambda a: a.get("timestamp", 0.0), reverse=True)

    # Apply limit
    return unique[:limit]


@router.get("/counts")
async def get_alert_counts(
    since: float = Query(0.0, description="Unix timestamp — only count alerts after this time"),
):
    """Get per-source and per-severity alert counts."""
    all_alerts: list[dict[str, Any]] = []

    gatherers = [
        _gather_geofence_alerts,
        _gather_notification_alerts,
        _gather_acoustic_alerts,
        _gather_sensor_health_alerts,
        _gather_lpr_watchlist_alerts,
        _gather_federation_alerts,
        _gather_escalation_alerts,
    ]

    for gatherer in gatherers:
        try:
            all_alerts.extend(gatherer(since, 200))
        except Exception:
            pass

    by_source: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for a in all_alerts:
        src = a.get("source", "unknown")
        sev = a.get("severity", "low")
        by_source[src] = by_source.get(src, 0) + 1
        by_severity[sev] = by_severity.get(sev, 0) + 1

    return {
        "total": len(all_alerts),
        "by_source": by_source,
        "by_severity": by_severity,
    }
