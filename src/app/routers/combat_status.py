# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Combat / simulation status API.

Endpoints:
    GET /api/combat/status — combat system status and statistics
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/combat", tags=["combat"])


def _get_engine(request: Request):
    """Get SimulationEngine from app state (Amy or headless)."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        sim = getattr(amy, "simulation_engine", None)
        if sim is not None:
            return sim
    return getattr(request.app.state, "simulation_engine", None)


@router.get("/status")
async def combat_status(request: Request):
    """Combat system status.

    Returns whether combat is active, the current game state, wave info,
    score, and counts of friendly/hostile combatants.
    """
    engine = _get_engine(request)
    if engine is None:
        return {
            "status": "stopped",
            "available": False,
            "game_state": "none",
            "combat_active": False,
            "friendlies": 0,
            "hostiles": 0,
            "score": 0,
        }

    try:
        game_state = engine.game_mode.get_state()
        combat_active = game_state.get("state") == "active"

        targets = engine.get_targets()
        friendlies = 0
        hostiles = 0
        for t in targets:
            if getattr(t, "status", "") == "eliminated":
                continue
            alliance = getattr(t, "alliance", "")
            if alliance == "friendly" and getattr(t, "is_combatant", False):
                friendlies += 1
            elif alliance == "hostile":
                hostiles += 1

        # Active projectiles
        projectile_count = 0
        combat_sys = getattr(engine, "combat", None)
        if combat_sys is not None:
            active = combat_sys.get_active_projectiles()
            if isinstance(active, list):
                projectile_count = len(active)
            elif isinstance(active, dict):
                projectile_count = len(active.get("projectiles", []))

        return {
            "status": "running" if combat_active else "idle",
            "available": True,
            "game_state": game_state.get("state", "unknown"),
            "combat_active": combat_active,
            "wave": game_state.get("wave", 0),
            "total_waves": game_state.get("total_waves", 0),
            "score": game_state.get("score", 0),
            "friendlies": friendlies,
            "hostiles": hostiles,
            "active_projectiles": projectile_count,
            "total_eliminations": game_state.get("total_eliminations", 0),
        }
    except Exception as e:
        logger.warning("Combat status error: %s", e)
        return {
            "status": "error",
            "available": False,
            "error": str(e),
        }
