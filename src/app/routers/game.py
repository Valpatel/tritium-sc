# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Game control API — begin war, get state, reset, place units, mission generation."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/game", tags=["game"])


class UnitPosition(BaseModel):
    x: float
    y: float


# Asset types that can be placed as friendly defenders.
# Excludes hostile-only, crowd-role, and non-combatant types.
_PLACEABLE_TYPES = frozenset({
    "turret", "drone", "rover", "tank", "apc",
    "heavy_turret", "missile_turret", "scout_drone",
})


class PlaceUnit(BaseModel):
    name: str
    asset_type: str  # turret, drone, rover, tank, apc, etc.
    position: UnitPosition


class ApplyUpgradeRequest(BaseModel):
    unit_id: str
    upgrade_id: str


class UseAbilityRequest(BaseModel):
    unit_id: str
    ability_id: str


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
    # Clear any cached MissionDirector scenario so stale scenarios
    # cannot be re-applied after reset.
    md = getattr(engine, '_mission_director', None)
    if md is not None:
        md.reset()
    return {"status": "reset", "state": "setup"}


@router.post("/place")
async def place_unit(unit: PlaceUnit, request: Request):
    """Place a friendly unit during setup phase."""
    engine = _get_engine(request)
    if engine.game_mode.state != "setup":
        raise HTTPException(400, "Can only place units during setup")

    if unit.asset_type not in _PLACEABLE_TYPES:
        raise HTTPException(
            400,
            f"Invalid asset_type '{unit.asset_type}'. "
            f"Must be one of: {', '.join(sorted(_PLACEABLE_TYPES))}",
        )

    # Validate position is within map bounds.
    bounds = engine._map_bounds
    if abs(unit.position.x) > bounds or abs(unit.position.y) > bounds:
        raise HTTPException(
            400,
            f"Position ({unit.position.x}, {unit.position.y}) is outside "
            f"map bounds (±{bounds}m).",
        )

    from engine.simulation.target import SimulationTarget

    is_turret = "turret" in unit.asset_type
    target = SimulationTarget(
        target_id=f"{unit.asset_type}-{uuid.uuid4().hex[:6]}",
        name=unit.name,
        alliance="friendly",
        asset_type=unit.asset_type,
        position=(unit.position.x, unit.position.y),
        speed=0.0 if is_turret else 2.0,
        waypoints=[],
        status="stationary" if is_turret else "idle",
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
            try:
                result = md.generate_via_llm(
                    game_mode=body.game_mode,
                    model=body.model,
                )
                if result is None:
                    # LLM failed, fall back to scripted
                    md.generate_scripted(game_mode=body.game_mode)
            except Exception:
                # LLM crashed — fall back to scripted so frontend
                # receives a completion event instead of hanging.
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

    # Set game_mode_type from scenario BEFORE begin_war() so subsystems
    # (behaviors, hostile_commander, crowd_density, infrastructure) are
    # configured for the correct mode (civil_unrest, drone_swarm, etc.)
    engine.game_mode.game_mode_type = scenario.get("game_mode", "battle")

    # Load into GameMode: places defenders + sets _scenario_waves
    engine.game_mode.load_scenario(battle_scenario)

    # Begin war (will use scenario wave path, not hardcoded WAVE_CONFIGS)
    engine.begin_war()

    # Extract mission center from MissionArea for frontend camera pan
    mission_center = None
    if md._mission_area is not None:
        area = md._mission_area
        mission_center = {
            "x": area.center_poi.local_x,
            "y": area.center_poi.local_y,
            "lat": area.center_poi.lat,
            "lng": area.center_poi.lng,
            "radius_m": area.radius_m,
        }

    return {
        "status": "scenario_applied",
        "game_mode": scenario.get("game_mode", "battle"),
        "wave_count": len(battle_scenario.waves),
        "defender_count": len(battle_scenario.defenders),
        "source": scenario.get("generated_by", "unknown"),
        "mission_center": mission_center,
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
        # Discover best Ollama host from fleet if available
        ollama_host = settings.ollama_host
        if settings.fleet_enabled:
            try:
                from engine.inference.fleet import OllamaFleet
                fleet = OllamaFleet(auto_discover=settings.fleet_auto_discover)
                if fleet.hosts:
                    ollama_host = fleet.hosts[0].url
            except Exception:
                pass
        engine._mission_director = MissionDirector(
            event_bus=engine._event_bus,
            ollama_host=ollama_host,
            map_center=(settings.map_center_lat, settings.map_center_lng),
        )
    return engine._mission_director


def _get_evaluator(engine):
    """Get or create ModelEvaluator from engine."""
    from engine.simulation.model_evaluator import ModelEvaluator

    if not hasattr(engine, '_model_evaluator'):
        engine._model_evaluator = ModelEvaluator()
    return engine._model_evaluator


# -- Upgrade / Ability endpoints --


@router.get("/upgrades")
async def list_upgrades(request: Request):
    """List all available upgrades with costs, descriptions, and stat modifiers."""
    engine = _get_engine(request)
    upgrades = engine.upgrade_system.list_upgrades()
    return [
        {
            "upgrade_id": u.upgrade_id,
            "name": u.name,
            "description": u.description,
            "stat_modifiers": u.stat_modifiers,
            "cost": u.cost,
            "max_stacks": u.max_stacks,
            "eligible_types": u.eligible_types,
        }
        for u in upgrades
    ]


@router.post("/upgrade")
async def apply_upgrade(body: ApplyUpgradeRequest, request: Request):
    """Apply an upgrade to a friendly unit.

    Returns the current list of upgrades for the unit on success.
    """
    engine = _get_engine(request)
    target = engine.get_target(body.unit_id)
    if target is None:
        raise HTTPException(404, f"Unit not found: {body.unit_id}")

    success = engine.upgrade_system.apply_upgrade(body.unit_id, body.upgrade_id, target)
    if not success:
        raise HTTPException(400, f"Cannot apply upgrade '{body.upgrade_id}' to {body.unit_id}")

    engine.event_bus.publish("upgrade_applied", {
        "unit_id": body.unit_id,
        "upgrade_id": body.upgrade_id,
    })
    return {
        "status": "applied",
        "unit_id": body.unit_id,
        "upgrade_id": body.upgrade_id,
        "upgrades": engine.upgrade_system.get_upgrades(body.unit_id),
    }


@router.get("/abilities")
async def list_abilities(request: Request):
    """List all available abilities with cooldowns and eligible types."""
    engine = _get_engine(request)
    abilities = engine.upgrade_system.list_abilities()
    return [
        {
            "ability_id": a.ability_id,
            "name": a.name,
            "description": a.description,
            "cooldown": a.cooldown,
            "duration": a.duration,
            "effect": a.effect,
            "magnitude": a.magnitude,
            "eligible_types": a.eligible_types,
        }
        for a in abilities
    ]


@router.post("/ability")
async def use_ability(body: UseAbilityRequest, request: Request):
    """Activate an ability on a unit.

    Fails if the ability is on cooldown, not granted, or the unit is eliminated.
    """
    engine = _get_engine(request)
    target = engine.get_target(body.unit_id)
    if target is None:
        raise HTTPException(404, f"Unit not found: {body.unit_id}")

    # Pass targets dict so ability effects (EMP, etc.) can affect other units
    targets_dict = {t.target_id: t for t in engine.get_targets()}
    success = engine.upgrade_system.use_ability(body.unit_id, body.ability_id, targets_dict)
    if not success:
        raise HTTPException(400, f"Cannot use ability '{body.ability_id}' on {body.unit_id}")

    # Look up ability duration for the event
    ability = engine.upgrade_system._resolve_ability(body.ability_id)
    duration = ability.duration if ability else 0
    engine.event_bus.publish("ability_activated", {
        "unit_id": body.unit_id,
        "ability_id": body.ability_id,
        "duration": duration,
    })
    return {
        "status": "activated",
        "unit_id": body.unit_id,
        "ability_id": body.ability_id,
    }


@router.get("/unit/{unit_id}/upgrades")
async def get_unit_upgrades(unit_id: str, request: Request):
    """Get the upgrades and abilities currently applied to a unit."""
    engine = _get_engine(request)
    target = engine.get_target(unit_id)
    if target is None:
        raise HTTPException(404, f"Unit not found: {unit_id}")

    # Build cooldown info for granted abilities
    abilities = engine.upgrade_system.get_abilities(unit_id)
    ability_cooldowns = {}
    for aid in abilities:
        key = (unit_id, aid)
        remaining = engine.upgrade_system._ability_cooldowns.get(key, 0.0)
        ability_cooldowns[aid] = max(0.0, remaining)

    # Active effects
    active_effects = [
        {
            "ability_id": e.ability_id,
            "effect": e.effect,
            "magnitude": e.magnitude,
            "remaining": round(e.remaining, 1),
        }
        for e in engine.upgrade_system.get_active_effects(unit_id)
    ]

    return {
        "unit_id": unit_id,
        "upgrades": engine.upgrade_system.get_upgrades(unit_id),
        "abilities": abilities,
        "ability_cooldowns": ability_cooldowns,
        "active_effects": active_effects,
    }


# -- Replay endpoints --


@router.get("/replay")
async def get_replay(request: Request):
    """Get the full replay data from the last battle."""
    engine = _get_engine(request)
    return engine.replay_recorder.export_json()


@router.get("/replay/heatmap")
async def get_replay_heatmap(request: Request):
    """Get heatmap data from the last battle replay."""
    engine = _get_engine(request)
    return engine.replay_recorder.get_heatmap_data()


@router.get("/replay/timeline")
async def get_replay_timeline(request: Request):
    """Get the chronological event timeline from the last battle."""
    engine = _get_engine(request)
    return engine.replay_recorder.get_timeline()


# -- Spectator transport controls --


class SeekRequest(BaseModel):
    time: float


class SpeedRequest(BaseModel):
    speed: float


class SeekWaveRequest(BaseModel):
    wave: int


@router.post("/replay/play")
async def replay_play(request: Request):
    """Start or resume replay playback."""
    engine = _get_engine(request)
    engine.spectator.play()
    return engine.spectator.get_state()


@router.post("/replay/pause")
async def replay_pause(request: Request):
    """Pause replay playback."""
    engine = _get_engine(request)
    engine.spectator.pause()
    return engine.spectator.get_state()


@router.post("/replay/stop")
async def replay_stop(request: Request):
    """Stop playback and return to live."""
    engine = _get_engine(request)
    engine.spectator.stop()
    return engine.spectator.get_state()


@router.post("/replay/seek")
async def replay_seek(body: SeekRequest, request: Request):
    """Seek to a specific time in the replay."""
    engine = _get_engine(request)
    engine.spectator.seek_time(body.time)
    return engine.spectator.get_state()


@router.post("/replay/speed")
async def replay_speed(body: SpeedRequest, request: Request):
    """Set replay playback speed (0.25, 0.5, 1, 2, 4)."""
    engine = _get_engine(request)
    engine.spectator.set_speed(body.speed)
    return engine.spectator.get_state()


@router.post("/replay/step-forward")
async def replay_step_forward(request: Request):
    """Advance one frame."""
    engine = _get_engine(request)
    engine.spectator.step_forward()
    return engine.spectator.get_state()


@router.post("/replay/step-backward")
async def replay_step_backward(request: Request):
    """Go back one frame."""
    engine = _get_engine(request)
    engine.spectator.step_backward()
    return engine.spectator.get_state()


@router.post("/replay/seek-wave")
async def replay_seek_wave(body: SeekWaveRequest, request: Request):
    """Jump to the start of a specific wave."""
    engine = _get_engine(request)
    engine.spectator.seek_wave(body.wave)
    return engine.spectator.get_state()


@router.get("/replay/state")
async def replay_state(request: Request):
    """Get current spectator playback state."""
    engine = _get_engine(request)
    return engine.spectator.get_state()


@router.get("/replay/frame")
async def replay_frame(request: Request):
    """Get the current frame data at the spectator playhead position.

    The engine tick loop calls spectator.tick(dt) at 10Hz, so the
    playhead advances automatically during playback.  This endpoint
    just reads the current state -- it no longer drives advancement.
    """
    engine = _get_engine(request)
    spectator = engine.spectator
    frame = spectator.get_frame(spectator.current_frame)
    state = spectator.get_state()
    return {"state": state, "frame": frame}


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


@router.get("/hostile-intel")
async def get_hostile_intel(request: Request):
    """Get the hostile commander's tactical assessment and unit objectives."""
    engine = _get_engine(request)
    assessment = dict(engine.hostile_commander._last_assessment)
    # Include per-unit objectives
    objectives = {}
    for uid, obj in engine.hostile_commander._objectives.items():
        objectives[uid] = obj.to_dict()
    if objectives:
        assessment["objectives"] = objectives
    return assessment


@router.get("/stats/mvp")
async def get_mvp(request: Request):
    """Get the MVP of the current/last battle."""
    engine = _get_engine(request)
    mvp = engine.stats_tracker.get_mvp()
    if mvp is None:
        return {"status": "no_data"}
    return {"status": "ready", "mvp": mvp.to_dict()}
