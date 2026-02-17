"""FastAPI router for Amy — /api/amy/* endpoints.

Provides REST + SSE endpoints for Amy's state, thoughts, sensorium,
commands, and MJPEG video from sensor nodes.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from .commander import Commander

router = APIRouter(prefix="/api/amy", tags=["amy"])


def _get_amy(request: Request) -> "Commander | None":
    """Get Amy commander from app state."""
    return getattr(request.app.state, "amy", None)


# --- Models ---

class SpeakRequest(BaseModel):
    text: str


class CommandRequest(BaseModel):
    action: str
    params: list | None = None


class ChatRequest(BaseModel):
    text: str


class ModeRequest(BaseModel):
    mode: str  # "sim" or "live"


# --- Endpoints ---

@router.get("/status")
async def amy_status(request: Request):
    """Amy's current state, mood, node info."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    nodes_info = {}
    for nid, node in amy.nodes.items():
        nodes_info[nid] = {
            "name": node.name,
            "camera": node.has_camera,
            "ptz": node.has_ptz,
            "mic": node.has_mic,
            "speaker": node.has_speaker,
        }

    pose = None
    ptz_node = amy.primary_ptz
    if ptz_node is not None:
        pos = ptz_node.get_position()
        pose_est = amy.pose_estimator.update(pos)
        pose = {
            "pan": pose_est.pan_normalized,
            "tilt": pose_est.tilt_normalized,
            "pan_deg": round(pose_est.pan_degrees, 1) if pose_est.pan_degrees is not None else None,
            "tilt_deg": round(pose_est.tilt_degrees, 1) if pose_est.tilt_degrees is not None else None,
            "calibrated": pose_est.calibrated,
        }

    return {
        "state": amy._state.value,
        "mood": amy.sensorium.mood,
        "running": amy._running,
        "auto_chat": amy._auto_chat,
        "wake_word": amy.wake_word,
        "nodes": nodes_info,
        "thinking_suppressed": amy.thinking.suppressed if amy.thinking else False,
        "deep_model": amy.deep_model,
        "chat_model": amy._chat_model,
        "pose": pose,
        "mode": amy.mode,
    }


@router.get("/mode")
async def amy_mode_get(request: Request):
    """Get Amy's current tactical mode (sim or live)."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    engine = getattr(amy, "simulation_engine", None)
    spawners_paused = engine.spawners_paused if engine is not None else True

    return {
        "mode": amy.mode,
        "spawners_paused": spawners_paused,
    }


@router.post("/mode")
async def amy_mode_set(request: Request, body: ModeRequest):
    """Switch Amy's tactical mode between sim and live."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    try:
        new_mode = amy.set_mode(body.mode)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    engine = getattr(amy, "simulation_engine", None)
    spawners_paused = engine.spawners_paused if engine is not None else True

    return {
        "mode": new_mode,
        "spawners_paused": spawners_paused,
    }


@router.get("/thoughts")
async def amy_thoughts(request: Request):
    """SSE stream of Amy's thoughts and events."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    sub = amy.event_bus.subscribe()

    async def event_stream():
        try:
            while True:
                try:
                    # Non-blocking check with asyncio
                    msg = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: sub.get(timeout=30)
                    )
                    yield f"data: {json.dumps(msg)}\n\n"
                except Exception:
                    # Keepalive
                    yield ": keepalive\n\n"
        finally:
            amy.event_bus.unsubscribe(sub)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/speak")
async def amy_speak(request: Request, body: SpeakRequest):
    """Make Amy say something."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    # Run in thread to avoid blocking
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, amy.say, body.text)
    return {"status": "ok", "text": body.text}


@router.post("/chat")
async def amy_chat(request: Request, body: ChatRequest):
    """Send a text message to Amy (as if spoken)."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)
    if amy.chat_agent is None:
        return JSONResponse({"error": "Chat agent not initialized"}, status_code=503)

    def do_respond():
        amy.event_bus.publish("transcript", {"speaker": "user", "text": body.text})
        amy.transcript.append("user", body.text, "speech")
        amy._respond(transcript=body.text)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, do_respond)
    return {"status": "ok"}


@router.get("/nodes")
async def amy_nodes(request: Request):
    """List connected sensor nodes."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    nodes = {}
    for nid, node in amy.nodes.items():
        nodes[nid] = {
            "name": node.name,
            "camera": node.has_camera,
            "ptz": node.has_ptz,
            "mic": node.has_mic,
            "speaker": node.has_speaker,
        }
    return {"nodes": nodes}


@router.get("/nodes/{node_id}/video")
async def amy_node_video(request: Request, node_id: str):
    """MJPEG stream from a specific camera node."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    node = amy.nodes.get(node_id)
    if node is None or not node.has_camera:
        return JSONResponse({"error": f"No camera node '{node_id}'"}, status_code=404)

    def mjpeg_stream():
        last_id = -1
        while True:
            cur_id = node.frame_id
            if cur_id != last_id:
                # Use commander's MJPEG frame (includes YOLO overlay)
                if node == amy.primary_camera:
                    frame = amy.grab_mjpeg_frame()
                else:
                    frame = node.get_jpeg()
                if frame is not None:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                        + frame + b"\r\n"
                    )
                    last_id = cur_id
            time.sleep(0.033)

    return StreamingResponse(
        mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/command")
async def amy_command(request: Request, body: CommandRequest):
    """Execute a Lua-style action (look_at, scan, etc.)."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    from .lua_motor import parse_motor_output

    lua_str = body.action
    if body.params:
        params_str = ", ".join(
            f'"{p}"' if isinstance(p, str) else str(p)
            for p in body.params
        )
        lua_str = f"{body.action}({params_str})"
    elif "(" not in lua_str:
        lua_str = f"{body.action}()"

    result = parse_motor_output(lua_str)
    if result.valid and amy.thinking:
        # Dispatch through the thinking thread's dispatcher
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, amy.thinking._dispatch, result)
        return {"status": "ok", "action": body.action}
    elif result.valid:
        return {"status": "ok", "action": body.action, "note": "No thinking thread"}
    else:
        return JSONResponse({"error": result.error}, status_code=400)


@router.get("/memory")
async def amy_memory(request: Request):
    """Get Amy's memory data for dashboard."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)
    return amy.memory.get_dashboard_data()


@router.get("/sensorium")
async def amy_sensorium(request: Request):
    """Get the full sensorium narrative."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)
    return {
        "narrative": amy.sensorium.narrative(),
        "summary": amy.sensorium.summary(),
        "mood": amy.sensorium.mood,
        "event_count": amy.sensorium.event_count,
        "people_present": amy.sensorium.people_present,
    }


@router.post("/auto-chat")
async def amy_auto_chat(request: Request):
    """Toggle auto-conversation mode."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)
    new_state = amy.toggle_auto_chat()
    return {"auto_chat": new_state}


# --- Simulation endpoints ---

class SpawnRequest(BaseModel):
    name: str | None = None
    alliance: str = "hostile"
    asset_type: str = "rover"
    position: dict | None = None  # {"x": float, "y": float} local meters
    lat: float | None = None      # Real-world latitude (alternative to position)
    lng: float | None = None      # Real-world longitude (alternative to position)


@router.get("/simulation/targets")
async def sim_targets(request: Request):
    """List all simulation targets."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)
    engine = getattr(amy, "simulation_engine", None)
    if engine is None:
        return {"targets": [], "message": "Simulation engine not active"}
    targets = engine.get_targets()
    return {"targets": [t.to_dict() for t in targets]}


@router.post("/simulation/spawn")
async def sim_spawn(request: Request, body: SpawnRequest):
    """Spawn a new simulation target."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)
    engine = getattr(amy, "simulation_engine", None)
    if engine is None:
        return JSONResponse({"error": "Simulation engine not active"}, status_code=503)

    pos = None
    if body.lat is not None and body.lng is not None:
        # Real-world coordinates — convert to local meters
        from amy.geo import latlng_to_local
        x, y, _ = latlng_to_local(body.lat, body.lng)
        pos = (x, y)
    elif body.position:
        pos = (body.position.get("x", 0.0), body.position.get("y", 0.0))

    if body.alliance == "hostile":
        target = engine.spawn_hostile(name=body.name, position=pos)
    else:
        from .simulation.target import SimulationTarget
        import uuid
        _SPEEDS = {"rover": 2.0, "drone": 4.0, "turret": 0.0, "person": 1.5}
        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=body.name or f"Unit-{len(engine.get_targets()) + 1}",
            alliance=body.alliance,
            asset_type=body.asset_type,
            position=pos or (0.0, 0.0),
            speed=_SPEEDS.get(body.asset_type, 2.0),
        )
        engine.add_target(target)

    return {"status": "ok", "target": target.to_dict()}


@router.delete("/simulation/targets/{target_id}")
async def sim_remove(request: Request, target_id: str):
    """Remove a simulation target."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)
    engine = getattr(amy, "simulation_engine", None)
    if engine is None:
        return JSONResponse({"error": "Simulation engine not active"}, status_code=503)

    removed = engine.remove_target(target_id)
    if removed:
        return {"status": "ok"}
    return JSONResponse({"error": "Target not found"}, status_code=404)


@router.get("/photos")
async def amy_photos(request: Request):
    """List saved photos (newest first)."""
    import os
    photos_dir = os.path.join(os.path.dirname(__file__), "..", "amy", "photos")
    photos_dir = os.path.normpath(photos_dir)
    if not os.path.isdir(photos_dir):
        return {"photos": []}
    files = sorted(
        (f for f in os.listdir(photos_dir) if f.endswith(".jpg")),
        reverse=True,
    )
    photos = []
    for f in files[:100]:
        # Parse timestamp and reason from filename: YYYY-MM-DD_HHMMSS_slug.jpg
        parts = f.rsplit(".", 1)[0].split("_", 2)
        ts = parts[0] if parts else ""
        time_part = parts[1] if len(parts) > 1 else ""
        reason = parts[2].replace("_", " ") if len(parts) > 2 else ""
        photos.append({
            "filename": f,
            "date": ts,
            "time": time_part,
            "reason": reason,
        })
    return {"photos": photos}


@router.get("/photos/{filename}")
async def amy_photo(filename: str):
    """Serve a saved photo."""
    import os
    photos_dir = os.path.join(os.path.dirname(__file__), "..", "amy", "photos")
    photos_dir = os.path.normpath(photos_dir)
    filepath = os.path.join(photos_dir, filename)
    # Prevent path traversal
    if not os.path.normpath(filepath).startswith(photos_dir):
        return JSONResponse({"error": "Invalid filename"}, status_code=400)
    if not os.path.isfile(filepath):
        return JSONResponse({"error": "Photo not found"}, status_code=404)
    return Response(
        content=open(filepath, "rb").read(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# --- Layout management ---

class LayoutSaveRequest(BaseModel):
    name: str
    data: dict  # Full TritiumLevelFormat JSON


@router.post("/layouts")
async def save_layout(request: Request, body: LayoutSaveRequest):
    """Save a layout JSON to the layouts directory."""
    import os
    import json as _json

    layouts_dir = os.path.join(os.path.dirname(__file__), "layouts")
    os.makedirs(layouts_dir, exist_ok=True)
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', body.name)
    filepath = os.path.join(layouts_dir, f"{safe_name}.json")
    if not os.path.normpath(filepath).startswith(os.path.normpath(layouts_dir)):
        return JSONResponse({"error": "Invalid name"}, status_code=400)
    with open(filepath, "w") as f:
        _json.dump(body.data, f, indent=2)
    return {"status": "ok", "name": safe_name}


@router.get("/layouts")
async def list_layouts(request: Request):
    """List saved layouts."""
    import os

    layouts_dir = os.path.join(os.path.dirname(__file__), "layouts")
    if not os.path.isdir(layouts_dir):
        return {"layouts": []}
    files = sorted(f[:-5] for f in os.listdir(layouts_dir) if f.endswith(".json"))
    return {"layouts": files}


@router.get("/layouts/{name}")
async def get_layout(request: Request, name: str):
    """Load a specific layout."""
    import os
    import json as _json

    layouts_dir = os.path.join(os.path.dirname(__file__), "layouts")
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    filepath = os.path.join(layouts_dir, f"{safe_name}.json")
    if not os.path.normpath(filepath).startswith(os.path.normpath(layouts_dir)):
        return JSONResponse({"error": "Invalid name"}, status_code=400)
    if not os.path.isfile(filepath):
        return JSONResponse({"error": "Layout not found"}, status_code=404)
    with open(filepath) as f:
        data = _json.load(f)
    return {"name": safe_name, "data": data}


class LoadLayoutRequest(BaseModel):
    data: dict  # TritiumLevelFormat JSON (inline)
    name: str | None = None  # Optional: load from saved layout by name


@router.post("/simulation/load-layout")
async def load_layout_into_sim(request: Request, body: LoadLayoutRequest):
    """Load a layout into the running simulation engine."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)
    engine = getattr(amy, "simulation_engine", None)
    if engine is None:
        return JSONResponse({"error": "Simulation engine not active"}, status_code=503)

    import os
    import json as _json
    import tempfile

    layout_data = body.data
    if body.name and not layout_data:
        layouts_dir = os.path.join(os.path.dirname(__file__), "layouts")
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', body.name)
        filepath = os.path.join(layouts_dir, f"{safe_name}.json")
        if not os.path.isfile(filepath):
            return JSONResponse({"error": "Layout not found"}, status_code=404)
        with open(filepath) as f:
            layout_data = _json.load(f)

    if not layout_data:
        return JSONResponse({"error": "No layout data provided"}, status_code=400)

    from amy.simulation.loader import load_layout as _load_layout

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
        _json.dump(layout_data, tmp)
        tmp_path = tmp.name

    try:
        count = _load_layout(tmp_path, engine)
    finally:
        os.unlink(tmp_path)

    # Apply amy config if present
    amy_config = layout_data.get("amy", {})
    if amy_config and hasattr(amy, 'amy_config'):
        amy.amy_config.update(amy_config)

    return {"status": "ok", "targets_created": count}


# --- Escalation endpoints ---

@router.get("/escalation/status")
async def escalation_status(request: Request):
    """Current threat classifications."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)
    classifier = getattr(amy, "threat_classifier", None)
    if classifier is None:
        return {"threats": [], "message": "Threat classifier not active"}
    records = classifier.get_records()
    threats = []
    for tid, rec in records.items():
        target = amy.target_tracker.get_target(tid)
        threats.append({
            "target_id": tid,
            "threat_level": rec.threat_level,
            "in_zone": rec.in_zone,
            "name": target.name if target else tid[:8],
            "position": {"x": target.position[0], "y": target.position[1]} if target else None,
        })
    return {"threats": threats}


@router.get("/war/state")
async def war_state(request: Request):
    """Combined state for War Room initialization."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    # Targets
    targets = [t.to_dict() for t in amy.target_tracker.get_all()]

    # Escalation
    classifier = getattr(amy, "threat_classifier", None)
    threats = []
    if classifier:
        for tid, rec in classifier.get_records().items():
            threats.append({
                "target_id": tid,
                "threat_level": rec.threat_level,
                "in_zone": rec.in_zone,
            })

    # Zones from classifier
    zones = classifier.zones if classifier else []

    # Dispatcher
    dispatcher = getattr(amy, "auto_dispatcher", None)
    dispatches = dispatcher.active_dispatches if dispatcher else {}

    # Amy state
    amy_state = {
        "state": amy._state.value,
        "mood": amy.sensorium.mood,
        "mode": amy.mode,
    }

    # Thoughts
    recent_thoughts = amy.sensorium.recent_thoughts[-5:] if amy.sensorium else []

    return {
        "targets": targets,
        "threats": threats,
        "zones": zones,
        "dispatches": dispatches,
        "amy": amy_state,
        "thoughts": recent_thoughts,
    }
