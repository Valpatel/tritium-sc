"""Game control API — begin war, get state, reset, place units."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/game", tags=["game"])


class PlaceUnit(BaseModel):
    name: str
    asset_type: str  # turret, drone, rover
    position: dict   # {"x": float, "y": float}


def _get_engine(request: Request):
    """Retrieve the SimulationEngine from app state.

    Checks Amy's engine first, falls back to headless simulation engine
    (used when AMY_ENABLED=false but SIMULATION_ENABLED=true).
    """
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        sim = getattr(amy, "simulation_engine", None)
        if sim is not None:
            return sim

    # Headless mode: simulation engine stored directly on app.state
    sim = getattr(request.app.state, "simulation_engine", None)
    if sim is not None:
        return sim

    raise HTTPException(503, "Simulation engine not available")


@router.get("/state")
async def get_game_state(request: Request):
    """Get current game state."""
    engine = _get_engine(request)
    return engine.get_game_state()


@router.post("/begin")
async def begin_war(request: Request):
    """Start the war! Transitions from setup -> countdown -> active."""
    engine = _get_engine(request)
    state = engine.game_mode.state
    if state != "setup":
        raise HTTPException(400, f"Cannot begin war in state: {state}")
    engine.begin_war()
    return {"status": "countdown_started", "wave": 1, "countdown": 5}


@router.post("/reset")
async def reset_game(request: Request):
    """Reset to setup state. Clear all hostiles, reset score."""
    engine = _get_engine(request)
    engine.reset_game()
    return {"status": "reset", "state": "setup"}


@router.post("/place")
async def place_unit(unit: PlaceUnit, request: Request):
    """Place a friendly unit during setup phase."""
    engine = _get_engine(request)
    if engine.game_mode.state != "setup":
        raise HTTPException(400, "Can only place units during setup")

    from amy.simulation.target import SimulationTarget

    target = SimulationTarget(
        target_id=f"{unit.asset_type}-{uuid.uuid4().hex[:6]}",
        name=unit.name,
        alliance="friendly",
        asset_type=unit.asset_type,
        position=(unit.position["x"], unit.position["y"]),
        speed=0.0 if unit.asset_type == "turret" else 2.0,
        waypoints=[],
        status="idle" if unit.asset_type != "turret" else "stationary",
    )
    target.apply_combat_profile()
    engine.add_target(target)
    return {"target_id": target.target_id, "status": "placed"}


@router.get("/projectiles")
async def get_projectiles(request: Request):
    """Get active projectiles for late-joining clients."""
    engine = _get_engine(request)
    return engine.combat.get_active_projectiles()
