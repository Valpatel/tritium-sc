# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Target correlation API.

Exposes active correlation records from the TargetCorrelator so the
frontend can draw correlation lines between fused targets on the map.

Endpoints:
    GET /api/correlations          — list active correlation records
    GET /api/correlations/summary  — correlation stats summary
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/correlations", tags=["correlations"])


def _get_correlator(request: Request):
    """Get the TargetCorrelator from app state, or None."""
    try:
        return getattr(request.app.state, "correlator", None)
    except (AttributeError, KeyError):
        return None


@router.get("/status")
async def correlation_status(request: Request):
    """Target correlation engine status.

    Returns whether the correlator is active, how many active correlations
    exist, average confidence, and which strategies are contributing.
    """
    correlator = _get_correlator(request)
    if correlator is None:
        return {
            "status": "stopped",
            "available": False,
            "total_correlations": 0,
            "high_confidence": 0,
            "avg_confidence": 0.0,
            "strategy_counts": {},
        }

    try:
        records = correlator.get_correlations()
        high = sum(1 for r in records if r.confidence >= 0.7)
        avg = (
            round(sum(r.confidence for r in records) / len(records), 3)
            if records else 0.0
        )

        strategy_counts: dict[str, int] = {}
        for r in records:
            for s in r.strategy_scores:
                if s.score > 0:
                    strategy_counts[s.strategy_name] = (
                        strategy_counts.get(s.strategy_name, 0) + 1
                    )

        return {
            "status": "running",
            "available": True,
            "total_correlations": len(records),
            "high_confidence": high,
            "avg_confidence": avg,
            "strategy_counts": strategy_counts,
        }
    except Exception as e:
        logger.warning("Correlation status error: %s", e)
        return {
            "status": "error",
            "available": False,
            "error": str(e),
        }


@router.get("")
async def list_correlations(request: Request):
    """List all active target correlation records.

    Returns correlation pairs with primary/secondary target IDs,
    confidence scores, and strategy breakdown. Used by the frontend
    to render correlation lines on the tactical map.
    """
    correlator = _get_correlator(request)
    if correlator is None:
        return {"correlations": [], "count": 0}

    records = correlator.get_correlations()
    return {
        "correlations": [
            {
                "primary_id": r.primary_id,
                "secondary_id": r.secondary_id,
                "confidence": round(r.confidence, 3),
                "reason": r.reason,
                "timestamp": r.timestamp,
                "dossier_uuid": r.dossier_uuid,
                "strategies": [
                    {
                        "name": s.strategy_name,
                        "score": round(s.score, 3),
                        "detail": s.detail,
                    }
                    for s in r.strategy_scores
                ],
            }
            for r in records
        ],
        "count": len(records),
    }


@router.get("/summary")
async def correlation_summary(request: Request):
    """Summary statistics of active correlations."""
    correlator = _get_correlator(request)
    if correlator is None:
        return {
            "total": 0,
            "high_confidence": 0,
            "avg_confidence": 0.0,
            "strategy_counts": {},
        }

    records = correlator.get_correlations()
    if not records:
        return {
            "total": 0,
            "high_confidence": 0,
            "avg_confidence": 0.0,
            "strategy_counts": {},
        }

    high = sum(1 for r in records if r.confidence >= 0.7)
    avg = sum(r.confidence for r in records) / len(records)

    # Count which strategies contributed most
    strategy_counts: dict[str, int] = {}
    for r in records:
        for s in r.strategy_scores:
            if s.score > 0:
                strategy_counts[s.strategy_name] = strategy_counts.get(s.strategy_name, 0) + 1

    return {
        "total": len(records),
        "high_confidence": high,
        "avg_confidence": round(avg, 3),
        "strategy_counts": strategy_counts,
    }
