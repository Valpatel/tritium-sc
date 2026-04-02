# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Simulation engine status API.

Endpoints:
    GET /api/sim/status — simulation engine status and statistics
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sim", tags=["simulation"])


def _get_engine(request: Request):
    """Get SimulationEngine from app state (Amy or headless)."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        sim = getattr(amy, "simulation_engine", None)
        if sim is not None:
            return sim

    return getattr(request.app.state, "simulation_engine", None)


@router.get("/status")
async def sim_status(request: Request):
    """Simulation engine status.

    Returns whether the simulation engine is running, its tick rate,
    target counts by alliance, and game mode state.
    """
    engine = _get_engine(request)
    if engine is None:
        return {
            "status": "stopped",
            "available": False,
            "running": False,
            "target_count": 0,
            "game_state": "none",
        }

    try:
        running = getattr(engine, "_running", False)
        targets = engine.get_targets()
        game_state = engine.game_mode.get_state()

        # Count by alliance
        alliance_counts: dict[str, int] = {}
        for t in targets:
            a = getattr(t, "alliance", "unknown")
            alliance_counts[a] = alliance_counts.get(a, 0) + 1

        return {
            "status": "running" if running else "stopped",
            "available": True,
            "running": running,
            "target_count": len(targets),
            "alliance_counts": alliance_counts,
            "game_state": game_state.get("state", "unknown"),
            "wave": game_state.get("wave", 0),
            "score": game_state.get("score", 0),
        }
    except Exception as e:
        logger.warning("Sim status error: %s", e)
        return {
            "status": "error",
            "available": False,
            "error": str(e),
        }
