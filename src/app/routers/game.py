"""Game control API — begin war, get state, reset, place units, mission generation."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

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

    from engine.simulation.target import SimulationTarget

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


@router.get("/scenarios")
async def list_battle_scenarios():
    """List available battle scenarios."""
    scenarios_dir = Path(__file__).resolve().parents[3] / "scenarios" / "battle"
    if not scenarios_dir.is_dir():
        return []
    results = []
    for f in sorted(scenarios_dir.glob("*.json")):
        try:
            import json
            data = json.loads(f.read_text())
            results.append({
                "name": f.stem,
                "description": data.get("description", ""),
                "map_bounds": data.get("map_bounds"),
                "max_hostiles": data.get("max_hostiles"),
                "wave_count": len(data.get("waves", [])),
                "tags": data.get("tags", []),
            })
        except Exception:
            continue
    return results


@router.post("/battle/{scenario_name}")
async def start_battle_scenario(scenario_name: str, request: Request):
    """Load a battle scenario and begin war atomically.

    Resets game, loads scenario (places defenders, configures waves),
    then starts countdown.
    """
    engine = _get_engine(request)

    # Find scenario file
    scenarios_dir = Path(__file__).resolve().parents[3] / "scenarios" / "battle"
    scenario_file = scenarios_dir / f"{scenario_name}.json"
    if not scenario_file.is_file():
        raise HTTPException(404, f"Scenario not found: {scenario_name}")

    # Reset to clean state
    engine.reset_game()

    # Load scenario
    from engine.simulation.scenario import load_battle_scenario
    scenario = load_battle_scenario(str(scenario_file))

    # Apply: set bounds, place defenders, configure waves
    engine._map_bounds = scenario.map_bounds
    engine.MAX_HOSTILES = scenario.max_hostiles

    # Place defenders
    from engine.simulation.target import SimulationTarget
    for defender in scenario.defenders:
        target = SimulationTarget(
            target_id=f"{defender.asset_type}-{uuid.uuid4().hex[:6]}",
            name=defender.asset_type.replace("_", " ").title(),
            alliance="friendly",
            asset_type=defender.asset_type,
            position=defender.position,
            speed=0.0 if "turret" in defender.asset_type else 2.0,
            waypoints=[],
            status="idle" if "turret" not in defender.asset_type else "stationary",
        )
        target.apply_combat_profile()
        engine.add_target(target)

    # Load scenario into game mode (configures wave spawning)
    engine.game_mode.load_scenario(scenario)

    # Begin war
    engine.begin_war()

    return {
        "status": "scenario_started",
        "scenario": scenario_name,
        "map_bounds": scenario.map_bounds,
        "max_hostiles": scenario.max_hostiles,
        "wave_count": len(scenario.waves),
        "defender_count": len(scenario.defenders),
    }


# -- Mission Director endpoints (LLM-driven scenario generation) ------------

class MissionRequest(BaseModel):
    game_mode: str = "battle"
    model: str | None = None  # Ollama model override
    use_llm: bool = True       # False = scripted only


@router.get("/modes")
async def list_game_modes():
    """List available game modes with descriptions."""
    from engine.simulation.mission_director import GAME_MODES
    return {
        name: {"description": mode["description"], "default_waves": mode["default_waves"]}
        for name, mode in GAME_MODES.items()
    }


@router.get("/models")
async def list_available_models(request: Request):
    """List available Ollama models for scenario generation."""
    engine = _get_engine(request)
    md = _get_mission_director(engine)
    return {"models": md.list_available_models()}


@router.post("/models/evaluate")
async def evaluate_models(request: Request):
    """Evaluate available models for scenario generation quality.

    Runs in background, returns immediately. Results come via /api/game/models/results.
    """
    from engine.simulation.model_evaluator import ModelEvaluator

    engine = _get_engine(request)
    ev = _get_evaluator(engine)

    def _eval():
        ev.evaluate_all(max_size="medium")

    thread = threading.Thread(target=_eval, daemon=True, name="model-eval")
    thread.start()
    return {"status": "evaluating"}


@router.get("/models/results")
async def get_model_evaluation_results(request: Request):
    """Get cached model evaluation results."""
    from engine.simulation.model_evaluator import ModelEvaluator

    engine = _get_engine(request)
    ev = _get_evaluator(engine)
    cache = ev.get_cache()

    if not cache:
        return {"status": "no_results", "recommendation": "gemma3:4b"}

    ranked = ev.rank_models(list(cache.values()))
    return {
        "status": "ready",
        "results": ranked,
        "recommendation": ev.recommend(),
        "fast_recommendation": ev.recommend(prefer="fast"),
        "quality_recommendation": ev.recommend(prefer="quality"),
    }


@router.post("/generate")
async def generate_mission(body: MissionRequest, request: Request):
    """Generate a complete game scenario via LLM (or scripted fallback).

    Progress is streamed via WebSocket 'mission_progress' events.
    Returns immediately with a generation ID; results come via WS.
    """
    engine = _get_engine(request)
    md = _get_mission_director(engine)

    if body.use_llm:
        # Start LLM generation in background thread
        def _gen():
            result = md.generate_via_llm(
                game_mode=body.game_mode,
                model=body.model,
            )
            if result is None:
                # LLM failed, fall back to scripted
                md.generate_scripted(game_mode=body.game_mode)

        thread = threading.Thread(target=_gen, daemon=True, name="mission-gen")
        thread.start()
        return {
            "status": "generating",
            "game_mode": body.game_mode,
            "source": "llm",
            "model": body.model or md.model,
        }
    else:
        scenario = md.generate_scripted(game_mode=body.game_mode)
        return {
            "status": "complete",
            "game_mode": body.game_mode,
            "source": "scripted",
            "scenario": scenario,
        }


@router.post("/mission/apply")
async def apply_mission_scenario(request: Request):
    """Apply the generated scenario — place units, configure waves, begin war.

    Converts MissionDirector scenario into a BattleScenario with concrete
    wave definitions, then loads it via GameMode.load_scenario() so the
    wave spawner uses LLM-generated composition instead of hardcoded defaults.
    """
    engine = _get_engine(request)
    md = _get_mission_director(engine)
    scenario = md.get_current_scenario()

    if scenario is None:
        raise HTTPException(400, "No scenario generated. Call /api/game/generate first.")

    # Reset to clean state
    engine.reset_game()

    # Convert narrative scenario → concrete BattleScenario with wave configs
    battle_scenario = md.scenario_to_battle_scenario(scenario)

    # Load into GameMode: places defenders + sets _scenario_waves
    engine.game_mode.load_scenario(battle_scenario)

    # Begin war (will use scenario wave path, not hardcoded WAVE_CONFIGS)
    engine.begin_war()

    return {
        "status": "scenario_applied",
        "game_mode": scenario.get("game_mode", "battle"),
        "wave_count": len(battle_scenario.waves),
        "defender_count": len(battle_scenario.defenders),
        "source": scenario.get("generated_by", "unknown"),
    }


@router.get("/mission/current")
async def get_current_mission(request: Request):
    """Get the current generated scenario."""
    engine = _get_engine(request)
    md = _get_mission_director(engine)
    scenario = md.get_current_scenario()
    if scenario is None:
        return {"status": "none"}
    return {"status": "ready", "scenario": scenario}


def _get_mission_director(engine):
    """Get or create MissionDirector from engine."""
    from engine.simulation.mission_director import MissionDirector
    from app.config import settings

    if not hasattr(engine, '_mission_director'):
        engine._mission_director = MissionDirector(
            event_bus=engine._event_bus,
            map_center=(settings.map_center_lat, settings.map_center_lng),
        )
    return engine._mission_director


def _get_evaluator(engine):
    """Get or create ModelEvaluator from engine."""
    from engine.simulation.model_evaluator import ModelEvaluator

    if not hasattr(engine, '_model_evaluator'):
        engine._model_evaluator = ModelEvaluator()
    return engine._model_evaluator


# -- Replay endpoints --


@router.get("/replay")
async def get_replay(request: Request):
    """Get the full replay data from the last battle."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(404, "Simulation engine not available")
    return engine.replay_recorder.export_json()


@router.get("/replay/heatmap")
async def get_replay_heatmap(request: Request):
    """Get heatmap data from the last battle replay."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(404, "Simulation engine not available")
    return engine.replay_recorder.get_heatmap_data()


@router.get("/replay/timeline")
async def get_replay_timeline(request: Request):
    """Get the chronological event timeline from the last battle."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(404, "Simulation engine not available")
    return engine.replay_recorder.get_timeline()


# -- After-action stats endpoints --


@router.get("/stats")
async def get_battle_stats(request: Request):
    """Get full after-action stats (per-unit + per-wave + summary)."""
    engine = _get_engine(request)
    return engine.stats_tracker.to_dict()


@router.get("/stats/summary")
async def get_stats_summary(request: Request):
    """Get battle summary (kills, accuracy, MVP, etc.)."""
    engine = _get_engine(request)
    return engine.stats_tracker.get_summary()


@router.get("/stats/mvp")
async def get_mvp(request: Request):
    """Get the MVP of the current/last battle."""
    engine = _get_engine(request)
    mvp = engine.stats_tracker.get_mvp()
    if mvp is None:
        return {"status": "no_data"}
    return {"status": "ready", "mvp": mvp.to_dict()}
