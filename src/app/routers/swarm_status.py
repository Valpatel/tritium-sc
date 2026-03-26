# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Swarm coordination status API.

Endpoints:
    GET /api/swarm/status — swarm coordination status
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/swarm", tags=["swarm"])


def _get_engine(request: Request):
    """Get SimulationEngine from app state (Amy or headless)."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        sim = getattr(amy, "simulation_engine", None)
        if sim is not None:
            return sim
    return getattr(request.app.state, "simulation_engine", None)


@router.get("/status")
async def swarm_status(request: Request):
    """Swarm coordination status.

    Returns whether the swarm behavior system is active and the count of
    swarm drones currently in the simulation.  Swarm behavior is only
    active during drone_swarm game mode.
    """
    engine = _get_engine(request)
    if engine is None:
        return {
            "status": "stopped",
            "available": False,
            "swarm_active": False,
            "drone_count": 0,
            "game_mode_type": None,
        }

    try:
        swarm = getattr(engine, "_swarm_behavior", None)
        game_mode_type = getattr(engine.game_mode, "game_mode_type", None)
        swarm_active = swarm is not None and game_mode_type == "drone_swarm"

        # Count swarm drones
        drone_count = 0
        if swarm_active:
            for t in engine.get_targets():
                if (
                    getattr(t, "alliance", "") == "hostile"
                    and getattr(t, "asset_type", "") == "swarm_drone"
                    and getattr(t, "status", "") != "eliminated"
                ):
                    drone_count += 1

        # Also check plugin manager for swarm_coordination plugin
        pm = getattr(request.app.state, "plugin_manager", None)
        plugin_active = False
        if pm is not None:
            try:
                plugin = pm.get_plugin("swarm_coordination")
                plugin_active = plugin is not None
            except Exception:
                pass

        return {
            "status": "running" if (swarm_active or plugin_active) else "stopped",
            "available": True,
            "swarm_active": swarm_active,
            "drone_count": drone_count,
            "game_mode_type": game_mode_type,
            "plugin_loaded": plugin_active,
        }
    except Exception as e:
        logger.warning("Swarm status error: %s", e)
        return {
            "status": "error",
            "available": False,
            "error": str(e),
        }
