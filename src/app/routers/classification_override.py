# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Target classification override API.

Operators can manually reclassify a target's alliance (friendly->hostile)
or device type. Overrides persist in the dossier and are logged in the audit trail.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Body
from pydantic import BaseModel
from loguru import logger

router = APIRouter(prefix="/api/targets", tags=["target-classification"])


class ClassificationOverride(BaseModel):
    """Operator-supplied classification override."""
    target_id: str
    alliance: Optional[str] = None       # friendly, hostile, neutral, unknown
    device_type: Optional[str] = None    # person, vehicle, phone, etc.
    reason: str = ""                     # operator's reason for override
    operator: str = ""                   # operator who made the change


VALID_ALLIANCES = {"friendly", "hostile", "neutral", "unknown"}
VALID_DEVICE_TYPES = {
    "person", "vehicle", "phone", "watch", "computer", "animal",
    "mesh_radio", "ble_device", "drone", "sensor", "unknown",
}


@router.post("/{target_id}/classify")
async def override_classification(
    target_id: str,
    request: Request,
    override: ClassificationOverride = Body(...),
):
    """Override a target's classification (alliance and/or device type).

    The override is applied to:
    1. The live TargetTracker (immediate effect on the tactical map)
    2. The DossierStore (persisted for future sessions)
    3. The audit log (compliance trail)
    """
    # Validate
    if override.alliance and override.alliance not in VALID_ALLIANCES:
        raise HTTPException(400, f"Invalid alliance: {override.alliance}. Must be one of {VALID_ALLIANCES}")
    if override.device_type and override.device_type not in VALID_DEVICE_TYPES:
        raise HTTPException(400, f"Invalid device_type: {override.device_type}. Must be one of {VALID_DEVICE_TYPES}")
    if not override.alliance and not override.device_type:
        raise HTTPException(400, "Must provide at least one of: alliance, device_type")

    changes = {}
    old_values = {}

    # Apply to live TargetTracker
    tracker = _get_tracker(request)
    target = None
    if tracker is not None:
        target = tracker.get(target_id)
        if target is None:
            raise HTTPException(404, f"Target not found: {target_id}")

        if override.alliance:
            old_values["alliance"] = getattr(target, "alliance", "unknown")
            target.alliance = override.alliance
            changes["alliance"] = override.alliance

        if override.device_type:
            old_values["device_type"] = getattr(target, "device_type", "unknown")
            if hasattr(target, "device_type"):
                target.device_type = override.device_type
            elif hasattr(target, "classification"):
                target.classification = override.device_type
            changes["device_type"] = override.device_type
    else:
        # No tracker but we can still update the dossier
        logger.warning(f"No target tracker available, updating dossier only for {target_id}")

    # Persist override in dossier
    dossier_mgr = getattr(request.app.state, "dossier_manager", None)
    if dossier_mgr is not None:
        try:
            note = f"Classification override by {override.operator or 'operator'}: "
            if override.alliance:
                note += f"alliance {old_values.get('alliance', '?')} -> {override.alliance}"
            if override.device_type:
                if override.alliance:
                    note += ", "
                note += f"type {old_values.get('device_type', '?')} -> {override.device_type}"
            if override.reason:
                note += f" (reason: {override.reason})"

            dossier_mgr.add_note(target_id, note)

            # Update dossier fields
            if override.alliance:
                dossier_mgr.update_field(target_id, "alliance", override.alliance)
            if override.device_type:
                dossier_mgr.update_field(target_id, "entity_type", override.device_type)
        except Exception as e:
            logger.warning(f"Failed to update dossier for {target_id}: {e}")

    # Audit log entry
    try:
        from app.audit_middleware import get_audit_store
        audit = get_audit_store()
        if audit is not None:
            audit.log(
                actor=override.operator or "operator",
                action="classification_override",
                resource=f"target:{target_id}",
                severity="warning",
                details={
                    "target_id": target_id,
                    "changes": changes,
                    "old_values": old_values,
                    "reason": override.reason,
                    "timestamp": time.time(),
                },
            )
    except Exception as e:
        logger.warning(f"Failed to write audit entry: {e}")

    # Broadcast change via WebSocket
    try:
        from app.routers.ws import manager as ws_manager
        import asyncio
        msg = {
            "type": "target_classification_changed",
            "data": {
                "target_id": target_id,
                "changes": changes,
                "old_values": old_values,
                "operator": override.operator,
                "reason": override.reason,
            },
        }
        await ws_manager.broadcast(msg)
    except Exception:
        pass

    return {
        "status": "ok",
        "target_id": target_id,
        "changes": changes,
        "old_values": old_values,
    }


@router.get("/{target_id}/classification")
async def get_classification(target_id: str, request: Request):
    """Get current classification for a target."""
    tracker = _get_tracker(request)
    if tracker is None:
        raise HTTPException(503, "Target tracker not available")

    target = tracker.get(target_id)
    if target is None:
        raise HTTPException(404, f"Target not found: {target_id}")

    return {
        "target_id": target_id,
        "alliance": getattr(target, "alliance", "unknown"),
        "device_type": getattr(target, "device_type", None) or getattr(target, "classification", "unknown"),
        "source": getattr(target, "source", "unknown"),
    }


def _get_tracker(request: Request):
    """Get target tracker from Amy or simulation engine."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        return getattr(amy, "target_tracker", None)
    return None
