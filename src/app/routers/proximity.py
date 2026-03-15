# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Proximity alert API routes.

Provides REST endpoints for proximity monitoring:
- List active breaches and recent alerts
- CRUD for proximity rules
- Monitor statistics
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/proximity", tags=["proximity"])


class CreateRuleRequest(BaseModel):
    name: str = "Proximity Alert"
    alliance_pair: str = "hostile_friendly"
    threshold_m: float = 10.0
    cooldown_s: float = 60.0
    enabled: bool = True
    notify_on_approach: bool = False
    approach_factor: float = 1.5


class UpdateRuleRequest(BaseModel):
    name: Optional[str] = None
    alliance_pair: Optional[str] = None
    threshold_m: Optional[float] = None
    cooldown_s: Optional[float] = None
    enabled: Optional[bool] = None
    notify_on_approach: Optional[bool] = None
    approach_factor: Optional[float] = None


def _get_monitor(request: Request):
    """Get ProximityMonitor from app state."""
    monitor = getattr(request.app.state, "proximity_monitor", None)
    if monitor is None:
        raise HTTPException(status_code=503, detail="Proximity monitor not initialized")
    return monitor


@router.get("/alerts")
async def list_alerts(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
):
    """List recent proximity alerts."""
    monitor = _get_monitor(request)
    alerts = monitor.get_recent_alerts(limit=limit)
    return {
        "alerts": alerts,
        "count": len(alerts),
    }


@router.get("/breaches")
async def list_active_breaches(request: Request):
    """List currently active proximity breaches (targets still within threshold)."""
    monitor = _get_monitor(request)
    breaches = monitor.get_active_breaches()
    return {
        "breaches": breaches,
        "count": len(breaches),
    }


@router.get("/stats")
async def proximity_stats(request: Request):
    """Get proximity monitor statistics."""
    monitor = _get_monitor(request)
    return monitor.get_stats()


@router.get("/rules")
async def list_rules(request: Request):
    """List all proximity rules."""
    monitor = _get_monitor(request)
    rules = monitor.list_rules()
    return {
        "rules": [r.to_dict() for r in rules],
        "count": len(rules),
    }


@router.post("/rules")
async def create_rule(request: Request, req: CreateRuleRequest):
    """Create a new proximity rule."""
    monitor = _get_monitor(request)

    try:
        from tritium_lib.models.proximity import ProximityRule
    except ImportError:
        from engine.tactical.proximity_monitor import ProximityRule

    rule = ProximityRule(
        name=req.name,
        alliance_pair=req.alliance_pair,
        threshold_m=req.threshold_m,
        cooldown_s=req.cooldown_s,
        enabled=req.enabled,
        notify_on_approach=req.notify_on_approach,
        approach_factor=req.approach_factor,
    )
    monitor.add_rule(rule)
    return {"created": True, "rule": rule.to_dict()}


@router.put("/rules/{rule_id}")
async def update_rule(request: Request, rule_id: str, req: UpdateRuleRequest):
    """Update an existing proximity rule."""
    monitor = _get_monitor(request)
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    ok = monitor.update_rule(rule_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return {"updated": True, "rule_id": rule_id}


@router.delete("/rules/{rule_id}")
async def delete_rule(request: Request, rule_id: str):
    """Delete a proximity rule."""
    monitor = _get_monitor(request)
    ok = monitor.remove_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return {"deleted": True, "rule_id": rule_id}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(request: Request, alert_id: str):
    """Acknowledge a proximity alert."""
    monitor = _get_monitor(request)
    ok = monitor.acknowledge_alert(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return {"acknowledged": True, "alert_id": alert_id}
