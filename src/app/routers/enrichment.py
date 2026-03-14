# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Target enrichment API — query and trigger intelligence enrichment."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/targets", tags=["enrichment"])


def _get_pipeline(request: Request):
    """Get enrichment pipeline from app state."""
    return getattr(request.app.state, "enrichment_pipeline", None)


def _get_tracker(request: Request):
    """Get target tracker from Amy or app state."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        tracker = getattr(amy, "target_tracker", None)
        if tracker is not None:
            return tracker
    return None


def _build_identifiers(target) -> dict:
    """Build identifiers dict from a TrackedTarget for enrichment."""
    identifiers: dict = {}
    tid = target.target_id

    # Extract MAC from BLE target IDs (ble_aabbccddeeff -> AA:BB:CC:DD:EE:FF)
    if tid.startswith("ble_"):
        raw = tid[4:]
        if len(raw) == 12:
            mac = ":".join(raw[i:i+2] for i in range(0, 12, 2)).upper()
            identifiers["mac"] = mac

    if target.name:
        identifiers["name"] = target.name
    if target.asset_type:
        identifiers["asset_type"] = target.asset_type

    return identifiers


@router.get("/{target_id}/enrichments")
async def get_enrichments(request: Request, target_id: str):
    """Get all enrichment data for a target.

    Returns cached results if available, otherwise runs enrichment on demand.
    """
    pipeline = _get_pipeline(request)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Enrichment pipeline not available")

    # Check cache first
    cached = pipeline.get_cached(target_id)
    if cached is not None:
        return {
            "target_id": target_id,
            "enrichments": [r.to_dict() for r in cached],
            "cached": True,
        }

    # Not cached — try to enrich if we can find the target
    tracker = _get_tracker(request)
    if tracker is not None:
        target = tracker.get_target(target_id)
        if target is not None:
            identifiers = _build_identifiers(target)
            results = await pipeline.enrich(target_id, identifiers)
            return {
                "target_id": target_id,
                "enrichments": [r.to_dict() for r in results],
                "cached": False,
            }

    # No cached data and target not found in tracker
    return {
        "target_id": target_id,
        "enrichments": [],
        "cached": False,
    }


@router.post("/{target_id}/enrich")
async def force_enrich(request: Request, target_id: str):
    """Force re-enrichment of a target, bypassing cache."""
    pipeline = _get_pipeline(request)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Enrichment pipeline not available")

    tracker = _get_tracker(request)
    identifiers: dict = {}

    if tracker is not None:
        target = tracker.get_target(target_id)
        if target is not None:
            identifiers = _build_identifiers(target)

    # Also accept identifiers from request body
    try:
        body = await request.json()
        if isinstance(body, dict):
            identifiers.update(body)
    except Exception:
        pass  # No body or invalid JSON is fine

    if not identifiers:
        raise HTTPException(
            status_code=404,
            detail="Target not found and no identifiers provided",
        )

    results = await pipeline.force_enrich(target_id, identifiers)
    return {
        "target_id": target_id,
        "enrichments": [r.to_dict() for r in results],
        "cached": False,
    }
