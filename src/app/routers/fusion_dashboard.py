# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Fusion dashboard API — cross-sensor correlation pipeline health metrics.

Endpoints:
    GET /api/fusion/status       — full fusion pipeline health
    GET /api/fusion/strategies   — per-strategy performance
    GET /api/fusion/pairs        — fusion counts by source pair
    GET /api/fusion/weights      — recommended strategy weights from feedback
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fusion", tags=["fusion"])


def _get_fusion_engine(request: Request):
    """Get FusionEngine from app state, or None."""
    return getattr(request.app.state, "fusion_engine", None)


def _get_fusion_metrics(request: Request):
    """Get FusionMetrics from app state, or None."""
    return getattr(request.app.state, "fusion_metrics", None)


def _get_correlator(request: Request):
    """Get the TargetCorrelator from app state, or None."""
    return getattr(request.app.state, "correlator", None)


@router.get("/status")
async def fusion_status(request: Request):
    """Full fusion pipeline health status.

    Returns total fusions, confirmation rate, hourly rate,
    source pair breakdown, and strategy performance.
    """
    metrics = _get_fusion_metrics(request)
    correlator = _get_correlator(request)

    result = {
        "metrics_available": metrics is not None,
        "correlator_available": correlator is not None,
    }

    if metrics is not None:
        result.update(metrics.get_status())

    # Add correlator state
    if correlator is not None:
        try:
            records = correlator.get_correlations()
            result["active_correlations"] = len(records)
            result["correlator_weights"] = dict(correlator.weights)
            result["correlator_threshold"] = correlator.confidence_threshold
            result["correlator_strategies"] = [
                s.name for s in correlator.strategies
            ]
        except Exception:
            result["active_correlations"] = 0

    return result


@router.get("/strategies")
async def fusion_strategies(request: Request):
    """Per-strategy performance metrics."""
    metrics = _get_fusion_metrics(request)
    if metrics is None:
        return {"strategies": []}
    return {"strategies": metrics.get_strategy_performance()}


@router.get("/pairs")
async def fusion_pairs(request: Request):
    """Fusion counts by source pair (e.g., ble+camera)."""
    metrics = _get_fusion_metrics(request)
    if metrics is None:
        return {"pairs": {}, "hourly_rate": 0.0}
    return {
        "pairs": metrics.get_source_pair_stats(),
        "hourly_rate": round(metrics.get_hourly_rate(), 2),
    }


@router.get("/weights")
async def fusion_weight_recommendations(request: Request):
    """Recommended strategy weights from operator feedback.

    Returns suggested weights that can be applied to the correlator
    to improve fusion accuracy over time.
    """
    metrics = _get_fusion_metrics(request)
    correlator = _get_correlator(request)

    result: dict = {"recommendations": {}, "current_weights": {}}

    if metrics is not None:
        result["recommendations"] = metrics.get_strategy_weights_recommendation()

    if correlator is not None:
        result["current_weights"] = dict(correlator.weights)

    return result


@router.get("/engine")
async def fusion_engine_status(request: Request):
    """FusionEngine overview — snapshot of the full fusion pipeline state.

    Returns target counts, dossier counts, correlation counts,
    zone counts, and per-source target breakdowns.  This endpoint
    exercises the new tritium-lib FusionEngine that wraps the
    existing TargetTracker with correlation, heatmap, and dossier
    capabilities.
    """
    engine = _get_fusion_engine(request)
    if engine is None:
        return {
            "engine_available": False,
            "error": "FusionEngine not initialized",
        }

    try:
        snapshot = engine.get_snapshot()
        result = snapshot.to_dict()
        result["engine_available"] = True

        # Add source breakdown
        by_source: dict[str, int] = {}
        for ft in snapshot.targets:
            src = ft.target.source or "unknown"
            by_source[src] = by_source.get(src, 0) + 1
        result["targets_by_source"] = by_source

        # Multi-source targets (confirmed by 2+ sensors)
        multi = engine.get_multi_source_targets(min_sources=2)
        result["multi_source_count"] = len(multi)

        return result
    except Exception as e:
        logger.warning("FusionEngine snapshot error: %s", e)
        return {
            "engine_available": True,
            "error": str(e),
        }
