# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Correlation status alias — serves /api/correlation/status (singular).

The primary correlation router is at /api/correlations (plural).
This alias ensures /api/correlation/status resolves without 404.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/correlation", tags=["correlations"])


def _get_correlator(request: Request):
    """Get the TargetCorrelator from app state, or None."""
    try:
        return getattr(request.app.state, "correlator", None)
    except (AttributeError, KeyError):
        return None


@router.get("/status")
async def correlation_status(request: Request):
    """Target correlation engine status (alias for /api/correlations/status).

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
