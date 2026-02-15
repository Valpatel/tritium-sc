"""FastAPI router for Amy — /api/amy/* endpoints.

Provides REST + SSE endpoints for Amy's state, thoughts, sensorium,
commands, and MJPEG video from sensor nodes.
"""

from __future__ import annotations

import asyncio
import json
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
        amy.sensorium.push("audio", f'User said: "{body.text[:60]}"', importance=0.8)
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
