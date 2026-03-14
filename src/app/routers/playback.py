# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Temporal playback API — replay historical target positions on map.

Endpoints:
    GET  /api/playback          — query snapshots in time range
    GET  /api/playback/range    — get available time range
    GET  /api/playback/state    — get state at specific timestamp
    POST /api/playback/start    — start playback
    POST /api/playback/stop     — stop playback
    POST /api/playback/seek     — seek to timestamp
    GET  /api/playback/status   — playback status
    GET  /api/playback/trajectory/{target_id} — target movement path
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/playback", tags=["playback"])


def _get_playback(request: Request):
    """Get TemporalPlayback from app state."""
    playback = getattr(request.app.state, "temporal_playback", None)
    if playback is None:
        # Try from Amy
        amy = getattr(request.app.state, "amy", None)
        if amy:
            playback = getattr(amy, "temporal_playback", None)
    return playback


@router.get("")
async def get_playback_snapshots(
    request: Request,
    start: Optional[float] = Query(None, description="Start timestamp (unix)"),
    end: Optional[float] = Query(None, description="End timestamp (unix)"),
    speed: Optional[float] = Query(None, description="Playback speed multiplier"),
    max_count: int = Query(100, description="Max snapshots to return"),
):
    """Query snapshots within a time range for map replay.

    If start/end not provided, returns the most recent snapshots.
    """
    playback = _get_playback(request)
    if playback is None:
        return {
            "snapshots": [],
            "count": 0,
            "error": "Temporal playback not initialized",
        }

    now = time.time()
    s = start if start is not None else now - 3600  # default: last hour
    e = end if end is not None else now

    snapshots = playback.get_snapshots_between(s, e, max_count=max_count)
    return {
        "snapshots": snapshots,
        "count": len(snapshots),
        "start": s,
        "end": e,
        "speed": speed or 1.0,
    }


@router.get("/range")
async def get_time_range(request: Request):
    """Get the available time range for playback."""
    playback = _get_playback(request)
    if playback is None:
        return {"start": 0.0, "end": 0.0, "duration_s": 0.0, "snapshot_count": 0}
    return playback.get_time_range()


@router.get("/state")
async def get_state_at(
    request: Request,
    timestamp: float = Query(..., description="Unix timestamp to query"),
):
    """Get the tactical state at a specific point in time."""
    playback = _get_playback(request)
    if playback is None:
        return {
            "timestamp": timestamp,
            "targets": [],
            "events": [],
            "alerts": [],
            "target_count": 0,
            "exact_match": False,
            "snapshot_count": 0,
        }
    return playback.get_state_at(timestamp)


@router.post("/start")
async def start_playback(
    request: Request,
    start_time: Optional[float] = Query(None, description="Start timestamp"),
    speed: float = Query(1.0, description="Playback speed (1.0 = realtime)"),
):
    """Start temporal playback from a given time."""
    playback = _get_playback(request)
    if playback is None:
        return {"error": "Temporal playback not initialized"}
    return playback.start_playback(start_time=start_time, speed=speed)


@router.post("/stop")
async def stop_playback(request: Request):
    """Stop temporal playback."""
    playback = _get_playback(request)
    if playback is None:
        return {"error": "Temporal playback not initialized"}
    return playback.stop_playback()


@router.post("/seek")
async def seek_playback(
    request: Request,
    timestamp: float = Query(..., description="Timestamp to seek to"),
):
    """Seek to a specific point in time during playback."""
    playback = _get_playback(request)
    if playback is None:
        return {"error": "Temporal playback not initialized"}
    return playback.seek(timestamp)


@router.get("/status")
async def get_playback_status(request: Request):
    """Get current playback state."""
    playback = _get_playback(request)
    if playback is None:
        return {
            "active": False,
            "time": 0.0,
            "speed": 1.0,
            "range": {"start": 0.0, "end": 0.0, "duration_s": 0.0, "snapshot_count": 0},
        }
    return playback.get_playback_status()


@router.get("/trajectory/{target_id}")
async def get_trajectory(
    request: Request,
    target_id: str,
    start: Optional[float] = Query(None, description="Start timestamp"),
    end: Optional[float] = Query(None, description="End timestamp"),
):
    """Get the movement trajectory of a specific target across time."""
    playback = _get_playback(request)
    if playback is None:
        return {"target_id": target_id, "trajectory": [], "count": 0}

    trajectory = playback.get_target_trajectory(
        target_id, start=start, end=end
    )
    return {
        "target_id": target_id,
        "trajectory": trajectory,
        "count": len(trajectory),
    }


@router.get("/replay")
async def replay_targets(
    request: Request,
    start: float = Query(..., description="Start timestamp (unix)"),
    end: float = Query(..., description="End timestamp (unix)"),
    speed: float = Query(1.0, description="Playback speed multiplier (1.0 = realtime)"),
    max_count: int = Query(500, description="Max snapshots to replay"),
):
    """Replay historical target positions as a Server-Sent Events stream.

    The stream emits one SSE event per snapshot, with timing adjusted by the
    speed multiplier.  At speed=2.0, events are delivered at 2x real time.
    The frontend subscribes and animates targets through their historical
    positions on the tactical map.

    Each SSE event data is a JSON object:
        {
            "timestamp": <float>,
            "targets": [...],
            "events": [...],
            "progress": <float 0.0-1.0>
        }

    The stream ends with a "done" event.
    """
    playback = _get_playback(request)

    speed = max(0.1, min(100.0, speed))

    async def event_stream():
        if playback is None:
            yield f"data: {json.dumps({'error': 'Temporal playback not initialized'})}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        snapshots = playback.get_snapshots_between(start, end, max_count=max_count)
        if not snapshots:
            yield f"data: {json.dumps({'error': 'No snapshots in range', 'start': start, 'end': end})}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        total = len(snapshots)
        prev_ts = None

        for i, snap in enumerate(snapshots):
            # Check if client disconnected
            if await request.is_disconnected():
                break

            snap_ts = snap.get("timestamp", 0)

            # Compute delay between snapshots based on speed
            if prev_ts is not None and speed > 0:
                real_delta = snap_ts - prev_ts
                if real_delta > 0:
                    wait = real_delta / speed
                    # Cap individual wait to 2 seconds to prevent stalls
                    wait = min(wait, 2.0)
                    if wait > 0.01:
                        await asyncio.sleep(wait)

            prev_ts = snap_ts

            payload = {
                "timestamp": snap_ts,
                "targets": snap.get("targets", []),
                "events": snap.get("events", []),
                "progress": round((i + 1) / total, 4),
                "index": i,
                "total": total,
            }
            yield f"data: {json.dumps(payload)}\n\n"

        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
