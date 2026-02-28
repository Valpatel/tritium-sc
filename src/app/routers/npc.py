"""NPC world population API -- spawn, list, bind to real data."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/npc", tags=["npc"])


class BindRequest(BaseModel):
    source: str  # "cot", "mqtt", "yolo"
    track_id: str


class PositionUpdate(BaseModel):
    x: float
    y: float
    heading: float = 0.0
    speed: float = 0.0


class ControlRequest(BaseModel):
    controller_id: str


class ThoughtRequest(BaseModel):
    text: str
    emotion: str = "neutral"
    duration: float = 5.0


class ActionRequest(BaseModel):
    action: str
    thought: str = ""
    waypoints: list[dict] | None = None


def _get_npc_manager(request: Request):
    """Retrieve the NPCManager from the simulation engine."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        sim = getattr(amy, "simulation_engine", None)
        if sim is not None:
            mgr = getattr(sim, "_npc_manager", None)
            if mgr is not None:
                return mgr

    sim = getattr(request.app.state, "simulation_engine", None)
    if sim is not None:
        mgr = getattr(sim, "_npc_manager", None)
        if mgr is not None:
            return mgr

    raise HTTPException(503, "NPC manager not available")


def _get_thought_registry(request: Request):
    """Get ThoughtRegistry from app state or NPC intelligence plugin."""
    # Direct attachment on app state (used in tests and headless mode)
    reg = getattr(request.app.state, "npc_thought_registry", None)
    if reg is not None:
        return reg

    # Via NPC intelligence plugin
    plugin = getattr(request.app.state, "npc_intelligence_plugin", None)
    if plugin is not None:
        reg = getattr(plugin, "thought_registry", None)
        if reg is not None:
            return reg

    raise HTTPException(503, "Thought registry not available")


def _get_npc_plugin(request: Request):
    """Get NPCIntelligencePlugin from app state."""
    plugin = getattr(request.app.state, "npc_intelligence_plugin", None)
    if plugin is not None:
        return plugin
    raise HTTPException(503, "NPC intelligence plugin not available")


@router.get("")
async def list_npcs(request: Request):
    """List all active NPC targets with their missions."""
    mgr = _get_npc_manager(request)
    engine = getattr(request.app.state, "simulation_engine", None)
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        engine = getattr(amy, "simulation_engine", engine)

    result = []
    if engine is not None:
        for target in engine.get_targets():
            if target.target_id in mgr._npc_ids:
                mission = mgr.get_mission(target.target_id)
                vtype = mgr.get_vehicle_type(target.target_id)
                binding = mgr.get_binding(target.target_id)
                result.append({
                    **target.to_dict(),
                    "npc_vehicle_type": vtype,
                    "npc_mission": {
                        "type": mission.mission_type,
                        "completed": mission.completed,
                    } if mission else None,
                    "npc_binding": binding,
                })
    return {"npcs": result, "count": len(result)}


@router.post("/spawn/vehicle")
async def spawn_vehicle(request: Request, vehicle_type: str | None = None):
    """Spawn an NPC vehicle. Optionally specify type (sedan, suv, pickup, etc.)."""
    mgr = _get_npc_manager(request)
    npc = mgr.spawn_vehicle(vehicle_type=vehicle_type)
    if npc is None:
        raise HTTPException(409, "Vehicle population at capacity")
    return {
        "target_id": npc.target_id,
        "name": npc.name,
        "vehicle_type": mgr.get_vehicle_type(npc.target_id),
        "position": {"x": npc.position[0], "y": npc.position[1]},
        "speed": npc.speed,
    }


@router.post("/spawn/pedestrian")
async def spawn_pedestrian(request: Request):
    """Spawn an NPC pedestrian."""
    mgr = _get_npc_manager(request)
    npc = mgr.spawn_pedestrian()
    if npc is None:
        raise HTTPException(409, "Pedestrian population at capacity")
    return {
        "target_id": npc.target_id,
        "name": npc.name,
        "position": {"x": npc.position[0], "y": npc.position[1]},
        "speed": npc.speed,
    }


@router.post("/{target_id}/bind")
async def bind_npc(target_id: str, body: BindRequest, request: Request):
    """Bind an NPC to a real data stream.

    When bound, the NPC's position comes from real tracking instead of simulation.
    """
    mgr = _get_npc_manager(request)
    success = mgr.bind_to_track(target_id, body.source, body.track_id)
    if not success:
        raise HTTPException(404, f"NPC {target_id} not found")
    return {"status": "bound", "target_id": target_id, "source": body.source, "track_id": body.track_id}


@router.delete("/{target_id}/bind")
async def unbind_npc(target_id: str, request: Request):
    """Unbind an NPC from a real data stream."""
    mgr = _get_npc_manager(request)
    if not mgr.is_bound(target_id):
        raise HTTPException(404, f"NPC {target_id} not bound")
    mgr.unbind(target_id)
    return {"status": "unbound", "target_id": target_id}


@router.put("/{target_id}/position")
async def update_npc_position(target_id: str, body: PositionUpdate, request: Request):
    """Update a bound NPC's position from external data."""
    mgr = _get_npc_manager(request)
    if not mgr.is_bound(target_id):
        raise HTTPException(400, f"NPC {target_id} is not bound to a data source")
    mgr.update_bound_position(
        target_id, position=(body.x, body.y), heading=body.heading, speed=body.speed
    )
    return {"status": "updated", "target_id": target_id}


@router.get("/density")
async def get_traffic_density(request: Request):
    """Get current traffic density and NPC population stats."""
    from datetime import datetime

    from engine.simulation.npc import NPC_VEHICLE_TYPES, traffic_density

    mgr = _get_npc_manager(request)
    hour = datetime.now().hour
    density = traffic_density(hour)
    return {
        "hour": hour,
        "density": density,
        "max_vehicles": mgr.max_vehicles,
        "max_pedestrians": mgr.max_pedestrians,
        "active_npcs": mgr.npc_count,
        "vehicle_types": list(NPC_VEHICLE_TYPES.keys()),
    }


# --- Thought bubble / control endpoints ---


@router.get("/controllable")
async def list_controllable(request: Request):
    """List NPCs with their thought/control status."""
    mgr = _get_npc_manager(request)
    engine = getattr(request.app.state, "simulation_engine", None)
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        engine = getattr(amy, "simulation_engine", engine)

    try:
        registry = _get_thought_registry(request)
    except Exception:
        registry = None

    # Also check the intelligence plugin for brain-tracked NPCs
    npc_plugin = getattr(request.app.state, "npc_intelligence_plugin", None)
    brain_ids = set()
    if npc_plugin is not None:
        brain_ids = set(npc_plugin._brains.keys())

    # Merge NPCManager IDs + intelligence plugin brain IDs
    npc_ids = set(mgr._npc_ids) | brain_ids

    result = []
    if engine is not None:
        for target in engine.get_targets():
            if target.target_id in npc_ids:
                thought = registry.get_thought(target.target_id) if registry else None
                controller = registry.get_controller(target.target_id) if registry else None
                result.append({
                    "target_id": target.target_id,
                    "name": target.name,
                    "asset_type": target.asset_type,
                    "alliance": target.alliance,
                    "thought": {
                        "text": thought.text,
                        "emotion": thought.emotion,
                    } if thought else None,
                    "controller": controller,
                })
    return {"npcs": result, "count": len(result)}


@router.post("/{target_id}/control")
async def take_control(target_id: str, body: ControlRequest, request: Request):
    """Take control of an NPC."""
    registry = _get_thought_registry(request)
    success = registry.take_control(target_id, body.controller_id)
    if not success:
        # Could be locked by another controller or unit not found
        existing = registry.get_controller(target_id)
        if existing is not None:
            raise HTTPException(409, f"NPC {target_id} already controlled by {existing}")
        raise HTTPException(404, f"NPC {target_id} not found or has no brain")
    return {"status": "controlled", "target_id": target_id, "controller_id": body.controller_id}


@router.delete("/{target_id}/control")
async def release_control(target_id: str, request: Request):
    """Release control of an NPC."""
    registry = _get_thought_registry(request)
    registry.release_control(target_id)
    return {"status": "released", "target_id": target_id}


@router.post("/{target_id}/thought")
async def set_thought(target_id: str, body: ThoughtRequest, request: Request):
    """Set a thought bubble for an NPC. No control lock needed."""
    registry = _get_thought_registry(request)
    thought = registry.set_thought(
        target_id, body.text, emotion=body.emotion, duration=body.duration,
    )
    return {
        "unit_id": target_id,
        "text": thought.text,
        "emotion": thought.emotion,
        "duration": body.duration,
    }


@router.post("/{target_id}/action")
async def set_action(target_id: str, body: ActionRequest, request: Request):
    """Set action on an NPC. Requires control lock."""
    registry = _get_thought_registry(request)
    controller = registry.get_controller(target_id)
    if controller is None:
        raise HTTPException(403, f"NPC {target_id} is not under control. Take control first.")

    # Apply action via plugin brain
    try:
        plugin = _get_npc_plugin(request)
        brain = plugin.get_brain(target_id)
        if brain is not None:
            brain.apply_action(body.action)
    except Exception:
        pass

    # Set thought if provided
    if body.thought:
        registry.set_thought(target_id, body.thought, duration=5.0)

    return {
        "target_id": target_id,
        "action": body.action,
        "thought": body.thought,
        "waypoints": body.waypoints,
    }


@router.get("/{target_id}")
async def get_npc_detail(target_id: str, request: Request):
    """Get full detail for a single NPC including thoughts, brain state, personality."""
    mgr = _get_npc_manager(request)
    engine = getattr(request.app.state, "simulation_engine", None)
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        engine = getattr(amy, "simulation_engine", engine)

    # Find the target
    target = None
    if engine is not None:
        for t in engine.get_targets():
            if t.target_id == target_id:
                target = t
                break

    if target is None:
        raise HTTPException(404, f"NPC {target_id} not found")

    result = target.to_dict()

    # Thought from registry
    try:
        registry = _get_thought_registry(request)
        thought = registry.get_thought(target_id)
        controller = registry.get_controller(target_id)
    except Exception:
        thought = None
        controller = None

    result["thought"] = (
        {"text": thought.text, "emotion": thought.emotion} if thought else None
    )
    result["controller"] = controller

    # Brain state from plugin
    plugin = getattr(request.app.state, "npc_intelligence_plugin", None)
    brain = plugin.get_brain(target_id) if plugin else None

    if brain is not None:
        result["brain_state"] = brain.get_state()
        result["personality"] = brain.personality.to_dict()
        result["memory_events"] = brain.memory.recent(10)
    else:
        result["brain_state"] = None
        result["personality"] = None
        result["memory_events"] = None

    # NPC mission and vehicle type from NPCManager
    mission = mgr.get_mission(target_id) if target_id in mgr._npc_ids else None
    result["npc_mission"] = (
        {"type": mission.mission_type, "completed": mission.completed}
        if mission else None
    )
    result["npc_vehicle_type"] = (
        mgr.get_vehicle_type(target_id) if target_id in mgr._npc_ids else None
    )

    return result
