# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
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

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.auth import require_auth

if TYPE_CHECKING:
    from .commander import Commander

# All /api/amy/* endpoints require authentication when auth_enabled=True
router = APIRouter(
    prefix="/api/amy",
    tags=["amy"],
    dependencies=[Depends(require_auth)],
)


def _get_amy(request: Request) -> "Commander | None":
    """Get Amy commander from app state."""
    return getattr(request.app.state, "amy", None)


def _get_sim_engine(request: Request):
    """Get simulation engine from Amy or headless app state."""
    amy = _get_amy(request)
    if amy is not None:
        engine = getattr(amy, "simulation_engine", None)
        if engine is not None:
            return engine
    return getattr(request.app.state, "simulation_engine", None)


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
    """Make Amy say something through the server speakers."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    # Run in thread to avoid blocking
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, amy.say, body.text)
    return {"status": "ok", "text": body.text}


@router.post("/speak/audio")
async def amy_speak_audio(request: Request, body: SpeakRequest):
    """Synthesize Amy's speech and return WAV audio for browser playback.

    Uses Piper TTS to generate raw PCM, wraps in a WAV header, and returns
    the audio as a downloadable response.  The frontend can play this via
    an Audio element, toggled with the V key.
    """
    amy = _get_amy(request)
    speaker = None
    if amy is not None:
        speaker = getattr(amy, "speaker", None)

    # Fallback: try to use Speaker directly
    if speaker is None:
        try:
            from engine.comms.speaker import Speaker
            speaker = Speaker()
        except Exception:
            return JSONResponse(
                {"error": "TTS not available"},
                status_code=503,
            )

    if not speaker.available:
        return JSONResponse(
            {"error": "Piper TTS not installed"},
            status_code=503,
        )

    import struct

    loop = asyncio.get_event_loop()
    raw_pcm = await loop.run_in_executor(None, speaker.synthesize_raw, body.text)
    if raw_pcm is None or len(raw_pcm) == 0:
        return JSONResponse(
            {"error": "TTS synthesis failed"},
            status_code=500,
        )

    # Wrap raw S16 mono PCM in a WAV header
    sample_rate = speaker.sample_rate
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(raw_pcm)

    wav_header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + data_size,
        b'WAVE',
        b'fmt ',
        16,              # PCM format chunk size
        1,               # PCM format
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b'data',
        data_size,
    )

    wav_data = wav_header + raw_pcm

    return Response(
        content=wav_data,
        media_type="audio/wav",
        headers={
            "Content-Disposition": "inline; filename=amy_speech.wav",
            "Cache-Control": "no-cache",
        },
    )


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


@router.get("/nodes/{node_id}/snapshot")
async def amy_node_snapshot(request: Request, node_id: str):
    """Single JPEG snapshot from a camera node."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    node = amy.nodes.get(node_id)
    if node is None or not node.has_camera:
        return JSONResponse({"error": f"No camera node '{node_id}'"}, status_code=404)

    if node == amy.primary_camera:
        frame = amy.grab_mjpeg_frame()
    else:
        frame = node.get_jpeg()

    if frame is None:
        return JSONResponse({"error": "No frame available"}, status_code=503)

    return Response(content=frame, media_type="image/jpeg")


@router.post("/command")
async def amy_command(request: Request, body: CommandRequest):
    """Execute a Lua-style action (look_at, scan, etc.)."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    from engine.actions.lua_motor import parse_motor_output

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

class DispatchTarget(BaseModel):
    x: float
    y: float


class DispatchRequest(BaseModel):
    unit_id: str
    target: DispatchTarget


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
    engine = _get_sim_engine(request)
    if engine is None:
        return {"targets": [], "message": "Simulation engine not active"}
    targets = engine.get_targets()
    return {"targets": [t.to_dict() for t in targets]}


@router.post("/simulation/spawn")
async def sim_spawn(request: Request, body: SpawnRequest):
    """Spawn a new simulation target."""
    engine = _get_sim_engine(request)
    if engine is None:
        return JSONResponse({"error": "Simulation engine not active"}, status_code=503)

    pos = None
    if body.lat is not None and body.lng is not None:
        # Real-world coordinates — convert to local meters
        from engine.tactical.geo import latlng_to_local
        x, y, _ = latlng_to_local(body.lat, body.lng)
        pos = (x, y)
    elif body.position:
        pos = (body.position.get("x", 0.0), body.position.get("y", 0.0))

    if body.alliance == "hostile":
        target = engine.spawn_hostile(name=body.name, position=pos)
    else:
        from tritium_lib.sim_engine.core.entity import SimulationTarget
        import uuid
        _SPEEDS = {
            "rover": 2.0, "drone": 4.0, "turret": 0.0, "person": 1.5,
            "tank": 1.5, "apc": 2.5, "heavy_turret": 0.0,
            "missile_turret": 0.0, "scout_drone": 5.0,
            "camera": 0.0, "ptz_camera": 0.0, "dome_camera": 0.0,
            "motion_sensor": 0.0, "microphone_sensor": 0.0,
            "speaker": 0.0, "floodlight": 0.0,
            "patrol_rover": 2.0, "interceptor_bot": 3.0,
            "recon_drone": 4.0, "heavy_drone": 3.0,
            "sentry_turret": 0.0,
        }
        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=body.name or f"Unit-{len(engine.get_targets()) + 1}",
            alliance=body.alliance,
            asset_type=body.asset_type,
            position=pos or (0.0, 0.0),
            speed=_SPEEDS.get(body.asset_type, 2.0),
            status="stationary" if _SPEEDS.get(body.asset_type, 2.0) == 0.0 else "idle",
        )
        target.apply_combat_profile()
        engine.add_target(target)

    return {"status": "ok", "target": target.to_dict()}


@router.post("/simulation/dispatch")
async def sim_dispatch(request: Request, body: DispatchRequest):
    """Dispatch a friendly unit to a target position."""
    engine = _get_sim_engine(request)
    if engine is None:
        return JSONResponse({"error": "Simulation engine not available"}, status_code=503)

    if not engine._running:
        return JSONResponse({"error": "Simulation not active"}, status_code=409)

    target = engine.get_target(body.unit_id)
    if target is None:
        return JSONResponse({"error": f"Unit '{body.unit_id}' not found"}, status_code=404)

    if target.speed == 0:
        return JSONResponse(
            {"error": f"Unit '{body.unit_id}' is stationary and cannot be dispatched"},
            status_code=422,
        )

    engine.dispatch_unit(body.unit_id, (body.target.x, body.target.y))

    return {
        "status": "dispatched",
        "unit_id": body.unit_id,
        "target": {"x": body.target.x, "y": body.target.y},
    }


@router.delete("/simulation/targets/{target_id}")
async def sim_remove(request: Request, target_id: str):
    """Remove a simulation target."""
    engine = _get_sim_engine(request)
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
    import engine

    layouts_dir = os.path.join(os.path.dirname(engine.__file__), "layouts")
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
    import engine

    layouts_dir = os.path.join(os.path.dirname(engine.__file__), "layouts")
    if not os.path.isdir(layouts_dir):
        return {"layouts": []}
    files = sorted(f[:-5] for f in os.listdir(layouts_dir) if f.endswith(".json"))
    return {"layouts": files}


@router.get("/layouts/{name}")
async def get_layout(request: Request, name: str):
    """Load a specific layout."""
    import os
    import json as _json
    import engine

    layouts_dir = os.path.join(os.path.dirname(engine.__file__), "layouts")
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

    from engine.simulation.loader import load_layout as _load_layout

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

    # Game state from game mode (wave controller, score, etc.)
    game_state = None
    engine = getattr(amy, "simulation_engine", None)
    if engine is not None:
        game_mode = getattr(engine, "game_mode", None)
        if game_mode is not None:
            game_state = game_mode.get_state()

    return {
        "targets": targets,
        "threats": threats,
        "zones": zones,
        "dispatches": dispatches,
        "amy": amy_state,
        "thoughts": recent_thoughts,
        "game_state": game_state,
    }


# ---------------------------------------------------------------------------
# Fleet + Model Routing
# ---------------------------------------------------------------------------

@router.get("/fleet/status")
async def fleet_status(request: Request):
    """Fleet status — discovered hosts, models, latency."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    router_obj = getattr(amy, "model_router", None)
    if router_obj is None:
        return {"fleet_enabled": False, "hosts": [], "profiles": []}

    fleet = getattr(router_obj, "_fleet", None)
    hosts = []
    if fleet is not None:
        for h in fleet.hosts:
            hosts.append({
                "name": h.name,
                "url": h.url,
                "models": h.models,
                "latency_ms": round(h.latency_ms, 1),
            })

    profiles = [p.to_dict() for p in router_obj.profiles]

    return {
        "fleet_enabled": True,
        "hosts": hosts,
        "profiles": profiles,
    }


@router.get("/fleet/models")
async def fleet_models(request: Request):
    """List all available models across the fleet."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    router_obj = getattr(amy, "model_router", None)
    if router_obj is None:
        return {"models": [
            {"name": amy._chat_model, "source": "static"},
            {"name": amy.deep_model, "source": "static"},
        ]}

    fleet = getattr(router_obj, "_fleet", None)
    all_models: dict[str, list[str]] = {}
    if fleet is not None:
        for h in fleet.hosts:
            for m in h.models:
                all_models.setdefault(m, []).append(h.name)

    return {
        "models": [
            {"name": name, "hosts": hosts}
            for name, hosts in sorted(all_models.items())
        ],
    }


@router.get("/fleet/actions")
async def fleet_actions(request: Request):
    """List all registered Lua actions (core + robot)."""
    amy = _get_amy(request)

    # Use the registry if Amy has one, otherwise return core actions
    try:
        from engine.actions.lua_registry import LuaActionRegistry
        reg = LuaActionRegistry.with_core_actions()
        actions = []
        for name in reg.list_actions():
            action = reg.get(name)
            actions.append({
                "name": action.name,
                "min_params": action.min_params,
                "max_params": action.max_params,
                "description": action.description,
                "source": action.source,
            })
        return {"actions": actions, "count": len(actions)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Tactical summary SSE stream
# ---------------------------------------------------------------------------

@router.get("/tactical-stream")
async def amy_tactical_stream(request: Request):
    """SSE stream of Amy's running tactical commentary.

    Returns Server-Sent Events with Amy's continuous narration of the
    tactical situation: what she sees, what changed, what concerns her.
    Events are JSON with fields: type, timestamp, summary, details, concerns.

    Each event is generated every ~5 seconds by analyzing the current
    tactical state: target counts, alliance distribution, recent changes,
    threat levels, and sensor coverage.
    """
    amy = _get_amy(request)
    sim_engine = _get_sim_engine(request)

    async def tactical_stream():
        prev_state = {}
        try:
            while True:
                event = _build_tactical_summary(amy, sim_engine, prev_state)
                prev_state = event.get("_prev", {})
                # Remove internal state from output
                output = {k: v for k, v in event.items() if not k.startswith("_")}
                yield f"data: {json.dumps(output)}\n\n"
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        tactical_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _build_tactical_summary(
    amy: "Commander | None",
    sim_engine,
    prev_state: dict,
) -> dict:
    """Build a tactical summary event from current system state."""
    now = time.time()
    summary_parts = []
    concerns = []
    details = {}

    # --- Target counts ---
    target_counts = {"friendly": 0, "hostile": 0, "neutral": 0, "unknown": 0, "total": 0}
    if sim_engine is not None:
        try:
            targets = list(sim_engine.targets.values()) if hasattr(sim_engine, "targets") else []
            for t in targets:
                alliance = getattr(t, "alliance", "unknown")
                if isinstance(alliance, str):
                    alliance = alliance.lower()
                else:
                    alliance = str(alliance.value).lower() if hasattr(alliance, "value") else "unknown"
                target_counts[alliance] = target_counts.get(alliance, 0) + 1
                target_counts["total"] += 1
        except Exception:
            pass
    details["targets"] = target_counts

    # Narrate target situation
    if target_counts["total"] == 0:
        summary_parts.append("No targets on scope.")
    else:
        parts = []
        if target_counts["hostile"] > 0:
            parts.append(f"{target_counts['hostile']} hostile")
        if target_counts["friendly"] > 0:
            parts.append(f"{target_counts['friendly']} friendly")
        if target_counts["neutral"] > 0:
            parts.append(f"{target_counts['neutral']} neutral")
        if target_counts["unknown"] > 0:
            parts.append(f"{target_counts['unknown']} unknown")
        summary_parts.append(f"Tracking {target_counts['total']} targets: {', '.join(parts)}.")

    # --- Changes from previous state ---
    prev_counts = prev_state.get("target_counts", {})
    if prev_counts:
        hostile_delta = target_counts.get("hostile", 0) - prev_counts.get("hostile", 0)
        if hostile_delta > 0:
            summary_parts.append(f"ALERT: {hostile_delta} new hostile target{'s' if hostile_delta > 1 else ''} detected.")
            concerns.append(f"hostile_increase:{hostile_delta}")
        elif hostile_delta < 0:
            summary_parts.append(f"{abs(hostile_delta)} hostile target{'s' if abs(hostile_delta) > 1 else ''} neutralized or lost.")

        total_delta = target_counts.get("total", 0) - prev_counts.get("total", 0)
        if total_delta > 3:
            concerns.append(f"rapid_target_increase:{total_delta}")

    # --- Game state ---
    if sim_engine is not None:
        try:
            game_mode = getattr(sim_engine, "game_mode", None)
            if game_mode is not None:
                phase = getattr(game_mode, "phase", None)
                wave = getattr(game_mode, "current_wave", 0)
                if phase is not None:
                    phase_str = phase.value if hasattr(phase, "value") else str(phase)
                    details["game"] = {"phase": phase_str, "wave": wave}
                    if phase_str == "active":
                        summary_parts.append(f"Battle active, wave {wave}.")
                    elif phase_str == "idle":
                        summary_parts.append("Standing by. No active engagement.")
        except Exception:
            pass

    # --- Amy state ---
    if amy is not None:
        try:
            mood = amy.sensorium.mood if hasattr(amy, "sensorium") else "unknown"
            state = amy._state.value if hasattr(amy._state, "value") else str(getattr(amy, "_state", "unknown"))
            details["amy"] = {"mood": mood, "state": state}
            if mood == "alert" or mood == "alarmed":
                concerns.append(f"amy_mood:{mood}")
                summary_parts.append(f"Amy is {mood}.")
        except Exception:
            pass

    # --- Threat assessment ---
    if target_counts.get("hostile", 0) > 0 and target_counts.get("friendly", 0) > 0:
        ratio = target_counts["hostile"] / max(1, target_counts["friendly"])
        if ratio > 2:
            concerns.append(f"outnumbered:{ratio:.1f}x")
            summary_parts.append(f"Warning: outnumbered {ratio:.1f}:1.")
        details["force_ratio"] = round(ratio, 2)

    # Build final event
    event_type = "alert" if concerns else "status"
    summary = " ".join(summary_parts) if summary_parts else "All quiet. Nothing to report."

    return {
        "type": event_type,
        "timestamp": now,
        "summary": summary,
        "details": details,
        "concerns": concerns,
        "_prev": {"target_counts": target_counts},
    }


@router.get("/learning-summary")
async def amy_daily_learning_summary(request: Request):
    """Amy reviews her last 24 hours of performance and narrates what she learned.

    Covers:
    - Correlation accuracy: how well she fused BLE + camera + mesh targets
    - Threat assessment outcomes: classifications that proved correct/incorrect
    - Operator feedback: overrides operators made to her classifications
    - Model improvement narrative: what she would adjust going forward
    """
    amy = _get_amy(request)
    now = time.time()
    cutoff = now - 86400  # 24 hours ago

    summary = {
        "generated_at": now,
        "period_hours": 24,
        "correlation_stats": {},
        "threat_assessment": {},
        "operator_feedback": [],
        "narrative": "",
    }

    # --- Correlation accuracy ---
    tracker = None
    if amy is not None:
        tracker = getattr(amy, "target_tracker", None)

    total_targets = 0
    correlated_targets = 0
    multi_source_targets = 0
    source_counts: dict[str, int] = {}

    if tracker is not None:
        try:
            all_targets = tracker.get_all()
            total_targets = len(all_targets)
            for t in all_targets:
                d = t.to_dict() if hasattr(t, "to_dict") else {}
                src = d.get("source", "unknown")
                source_counts[src] = source_counts.get(src, 0) + 1
                # Check if target has correlation data from multiple sources
                corr = d.get("correlated_sources") or d.get("fused_sources") or []
                if len(corr) > 1 or d.get("correlated", False):
                    correlated_targets += 1
                    multi_source_targets += 1
        except Exception:
            pass

    correlation_rate = (correlated_targets / max(1, total_targets)) * 100
    summary["correlation_stats"] = {
        "total_targets": total_targets,
        "correlated_targets": correlated_targets,
        "multi_source_targets": multi_source_targets,
        "correlation_rate_pct": round(correlation_rate, 1),
        "source_distribution": source_counts,
    }

    # --- Threat assessment ---
    alliance_counts: dict[str, int] = {}
    if tracker is not None:
        try:
            for t in tracker.get_all():
                d = t.to_dict() if hasattr(t, "to_dict") else {}
                alliance = d.get("alliance", "unknown")
                alliance_counts[alliance] = alliance_counts.get(alliance, 0) + 1
        except Exception:
            pass

    summary["threat_assessment"] = {
        "alliance_distribution": alliance_counts,
        "hostile_count": alliance_counts.get("hostile", 0),
        "friendly_count": alliance_counts.get("friendly", 0),
        "unknown_count": alliance_counts.get("unknown", 0),
    }

    # --- Operator feedback (classification overrides) ---
    try:
        from app.audit_middleware import get_audit_store
        audit = get_audit_store()
        if audit is not None:
            recent = audit.get_recent(limit=200) if hasattr(audit, "get_recent") else []
            overrides = [
                e for e in recent
                if e.get("action") == "classification_override"
                and (e.get("ts") or 0) >= cutoff
            ]
            for ov in overrides[-20:]:  # Last 20 overrides
                summary["operator_feedback"].append({
                    "actor": ov.get("actor", "operator"),
                    "target": ov.get("resource", ""),
                    "details": ov.get("details", {}),
                    "timestamp": ov.get("ts", 0),
                })
    except Exception:
        pass

    override_count = len(summary["operator_feedback"])

    # --- Generate narrative ---
    narrative_parts = []

    # Correlation narrative
    if total_targets == 0:
        narrative_parts.append(
            "No targets were tracked in the last 24 hours. My correlation models "
            "had nothing to work with. I remain ready to fuse sensor data when targets appear."
        )
    elif correlation_rate > 50:
        narrative_parts.append(
            f"I tracked {total_targets} targets, with {correlation_rate:.0f}% successfully "
            f"correlated across multiple sensors. My fusion algorithms are performing well — "
            f"I can reliably match BLE, camera, and mesh detections to the same physical entity."
        )
    elif correlation_rate > 20:
        narrative_parts.append(
            f"I tracked {total_targets} targets, but only {correlation_rate:.0f}% had "
            f"multi-source correlation. I should improve my temporal and spatial matching "
            f"thresholds to catch more cross-sensor correlations."
        )
    else:
        narrative_parts.append(
            f"I tracked {total_targets} targets, but correlation was low at {correlation_rate:.0f}%. "
            f"Most detections came from single sensors ({', '.join(source_counts.keys())}). "
            f"I need more diverse sensor coverage or tighter co-location windows."
        )

    # Source diversity
    if len(source_counts) > 2:
        narrative_parts.append(
            f"Data came from {len(source_counts)} distinct sources: "
            f"{', '.join(f'{k}({v})' for k, v in source_counts.items())}. "
            f"Good sensor diversity for reliable fusion."
        )

    # Threat assessment narrative
    hostile = alliance_counts.get("hostile", 0)
    if hostile > 0:
        narrative_parts.append(
            f"I classified {hostile} targets as hostile. "
            f"{'This is a high threat density.' if hostile > 5 else 'Manageable threat level.'}"
        )
    unknowns = alliance_counts.get("unknown", 0)
    if unknowns > 3:
        narrative_parts.append(
            f"There are {unknowns} unclassified targets — I should prioritize "
            f"resolving these ambiguities with additional sensor passes."
        )

    # Operator feedback narrative
    if override_count > 0:
        narrative_parts.append(
            f"Operators overrode my classifications {override_count} time(s) in the "
            f"last 24 hours. Each override is a learning signal — I will weight "
            f"similar patterns toward the operator's judgment in future assessments."
        )
    else:
        narrative_parts.append(
            "No operator overrides in the last 24 hours — my classifications "
            "were either accurate or unchallenged."
        )

    # Self-improvement
    narrative_parts.append(
        "Next cycle priorities: improve temporal correlation windows, "
        "reduce unknown classifications, and increase multi-source fusion coverage."
    )

    summary["narrative"] = " ".join(narrative_parts)

    return summary
