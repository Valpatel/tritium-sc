# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Behavioral Intelligence plugin.

Exposes pattern, relationship, anomaly, and alert queries plus alert CRUD.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .plugin import BehavioralIntelligencePlugin

try:
    from tritium_lib.models.pattern import PatternAlert
except ImportError:
    PatternAlert = None  # type: ignore[assignment,misc]


# -- Request/Response models -----------------------------------------------


class AlertCreateRequest(BaseModel):
    pattern_id: str
    target_id: str = ""
    name: str = ""
    description: str = ""
    severity: str = "medium"
    deviation_threshold: float = 0.5
    cooldown_seconds: float = 3600.0
    enabled: bool = True


class AlertUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    severity: str | None = None
    deviation_threshold: float | None = None
    cooldown_seconds: float | None = None
    enabled: bool | None = None


# -- Router factory --------------------------------------------------------


def create_router(plugin: BehavioralIntelligencePlugin) -> APIRouter:
    """Build and return the behavioral intelligence APIRouter."""

    router = APIRouter(prefix="/api/patterns", tags=["behavioral-intelligence"])

    # -- Patterns ----------------------------------------------------------

    @router.get("/")
    async def list_patterns(target_id: str | None = None):
        """List all detected behavioral patterns."""
        patterns = plugin.detector.get_patterns(target_id)
        return {
            "patterns": [p.model_dump() for p in patterns],
            "count": len(patterns),
        }

    @router.get("/target/{target_id}")
    async def get_target_patterns(target_id: str):
        """Get all patterns for a specific target."""
        patterns = plugin.detector.get_patterns(target_id)
        relationships = plugin.detector.get_relationships(target_id)
        anomalies = plugin.detector.get_anomalies(target_id)
        return {
            "target_id": target_id,
            "patterns": [p.model_dump() for p in patterns],
            "relationships": [r.model_dump() for r in relationships],
            "anomalies": [a.model_dump() for a in anomalies],
        }

    # -- Relationships -----------------------------------------------------

    @router.get("/relationships")
    async def list_relationships(target_id: str | None = None, min_confidence: float = 0.0):
        """List all co-presence relationships."""
        rels = plugin.detector.get_relationships(target_id)
        if min_confidence > 0:
            rels = [r for r in rels if r.confidence >= min_confidence]
        return {
            "relationships": [r.model_dump() for r in rels],
            "count": len(rels),
        }

    # -- Anomalies ---------------------------------------------------------

    @router.get("/anomalies")
    async def list_anomalies(target_id: str | None = None, limit: int = 50):
        """List recent pattern anomalies."""
        anomalies = plugin.detector.get_anomalies(target_id, limit)
        return {
            "anomalies": [a.model_dump() for a in anomalies],
            "count": len(anomalies),
        }

    @router.post("/anomalies/{anomaly_id}/acknowledge")
    async def acknowledge_anomaly(anomaly_id: str):
        """Mark an anomaly as acknowledged."""
        for a in plugin.detector._anomalies:
            if a.anomaly_id == anomaly_id:
                a.acknowledged = True
                return {"acknowledged": True, "anomaly_id": anomaly_id}
        raise HTTPException(status_code=404, detail="Anomaly not found")

    # -- Alerts ------------------------------------------------------------

    @router.get("/alerts")
    async def list_alerts():
        """List all pattern alert rules."""
        alerts = plugin.detector.list_alerts()
        return {
            "alerts": [a.model_dump() for a in alerts],
            "count": len(alerts),
        }

    @router.post("/alerts", status_code=201)
    async def create_alert(req: AlertCreateRequest):
        """Create a new pattern alert rule."""
        if PatternAlert is None:
            raise HTTPException(status_code=500, detail="Pattern models not available")

        alert = PatternAlert(
            alert_id=f"palert_{uuid.uuid4().hex[:12]}",
            pattern_id=req.pattern_id,
            target_id=req.target_id,
            name=req.name or f"Alert for {req.pattern_id}",
            description=req.description,
            severity=req.severity,
            deviation_threshold=req.deviation_threshold,
            cooldown_seconds=req.cooldown_seconds,
            enabled=req.enabled,
        )
        plugin.detector.add_alert(alert)
        plugin._save_alerts()
        return {"alert": alert.model_dump()}

    @router.put("/alerts/{alert_id}")
    async def update_alert(alert_id: str, req: AlertUpdateRequest):
        """Update an existing alert rule."""
        alerts = {a.alert_id: a for a in plugin.detector.list_alerts()}
        alert = alerts.get(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail="Alert not found")

        if req.name is not None:
            alert.name = req.name
        if req.description is not None:
            alert.description = req.description
        if req.severity is not None:
            alert.severity = req.severity
        if req.deviation_threshold is not None:
            alert.deviation_threshold = req.deviation_threshold
        if req.cooldown_seconds is not None:
            alert.cooldown_seconds = req.cooldown_seconds
        if req.enabled is not None:
            alert.enabled = req.enabled

        plugin._save_alerts()
        return {"alert": alert.model_dump()}

    @router.delete("/alerts/{alert_id}")
    async def delete_alert(alert_id: str):
        """Delete an alert rule."""
        removed = plugin.detector.remove_alert(alert_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Alert not found")
        plugin._save_alerts()
        return {"deleted": True, "alert_id": alert_id}

    # -- Stats -------------------------------------------------------------

    @router.get("/stats")
    async def get_stats():
        """Get behavioral intelligence statistics."""
        return plugin.get_stats()

    # -- Heatmap data for frontend -----------------------------------------

    @router.get("/target/{target_id}/heatmap")
    async def get_target_heatmap(target_id: str):
        """Get hourly activity heatmap data for a target.

        Returns a 7x24 matrix (day x hour) with sighting counts.
        """
        sightings = plugin.detector._sightings.get(target_id, [])
        # Build 7x24 heatmap (day of week x hour)
        heatmap = [[0] * 24 for _ in range(7)]
        from datetime import datetime, timezone
        for s in sightings:
            dt = datetime.fromtimestamp(s.timestamp, tz=timezone.utc)
            heatmap[dt.weekday()][dt.hour] += 1

        return {
            "target_id": target_id,
            "heatmap": heatmap,
            "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "total_sightings": len(sightings),
        }

    return router
