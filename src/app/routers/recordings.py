# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Video recording management API.

Manages recording of camera feeds to disk, playback, and clip extraction.
Supports both RTSP camera streams and MQTT JPEG frame streams.
"""

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from loguru import logger

from app.config import settings
from app.path_safety import sanitize_path_param

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


class RecordingInfo(BaseModel):
    """Information about a recording."""

    id: str
    camera_id: str
    start_time: str
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    file_path: str = ""
    file_size_bytes: int = 0
    fps: float = 0.0
    status: str = "idle"  # idle, recording, completed, error


class RecordingRequest(BaseModel):
    """Request to start recording a camera feed."""

    camera_id: str
    duration_seconds: int = Field(default=300, ge=10, le=3600, description="Recording duration (10s-1h)")
    fps: float = Field(default=5.0, ge=1.0, le=30.0, description="Frames per second")
    format: str = Field(default="mjpeg", description="Recording format: mjpeg or mp4")


class ClipRequest(BaseModel):
    """Request to extract a clip from a recording."""

    recording_id: str
    start_offset_seconds: float = 0.0
    duration_seconds: float = 30.0


# In-memory recording state (replace with database persistence in production)
_recordings: dict[str, RecordingInfo] = {}
_active_tasks: dict[str, asyncio.Task] = {}


def _get_recordings_dir() -> Path:
    """Get the recordings directory."""
    path = Path(settings.recordings_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _generate_recording_id(camera_id: str) -> str:
    """Generate a unique recording ID."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"rec_{camera_id}_{timestamp}"


@router.get("/")
async def list_recordings(camera_id: Optional[str] = None, limit: int = 50):
    """List all recordings, optionally filtered by camera."""
    recordings = list(_recordings.values())
    if camera_id:
        recordings = [r for r in recordings if r.camera_id == camera_id]

    # Also scan disk for existing recordings
    rec_dir = _get_recordings_dir()
    disk_recordings = []
    if rec_dir.exists():
        for f in sorted(rec_dir.iterdir(), reverse=True)[:limit]:
            if f.is_file() and f.suffix in (".mjpeg", ".mp4", ".avi"):
                disk_recordings.append({
                    "file": f.name,
                    "size_bytes": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                })

    return {
        "active_recordings": [r.model_dump() for r in recordings],
        "disk_recordings": disk_recordings[:limit],
        "recordings_dir": str(rec_dir),
    }


@router.post("/start", response_model=RecordingInfo)
async def start_recording(request: RecordingRequest):
    """Start recording a camera feed."""
    rec_id = _generate_recording_id(request.camera_id)

    rec_dir = _get_recordings_dir()
    file_path = rec_dir / f"{rec_id}.{request.format}"

    info = RecordingInfo(
        id=rec_id,
        camera_id=request.camera_id,
        start_time=datetime.now(timezone.utc).isoformat(),
        file_path=str(file_path),
        fps=request.fps,
        status="recording",
    )
    _recordings[rec_id] = info

    # Start recording task
    task = asyncio.create_task(_record_frames(info, request.duration_seconds))
    _active_tasks[rec_id] = task

    logger.info(f"Recording started: {rec_id} camera={request.camera_id} duration={request.duration_seconds}s")
    return info


@router.post("/stop/{recording_id}")
async def stop_recording(recording_id: str):
    """Stop an active recording."""
    sanitize_path_param(recording_id, "recording_id")
    if recording_id not in _recordings:
        raise HTTPException(status_code=404, detail="Recording not found")

    info = _recordings[recording_id]
    if info.status != "recording":
        raise HTTPException(status_code=400, detail=f"Recording is not active (status: {info.status})")

    # Cancel the task
    task = _active_tasks.get(recording_id)
    if task and not task.done():
        task.cancel()

    info.status = "completed"
    info.end_time = datetime.now(timezone.utc).isoformat()

    # Calculate duration
    start = datetime.fromisoformat(info.start_time)
    end = datetime.fromisoformat(info.end_time)
    info.duration_seconds = (end - start).total_seconds()

    # Check file size
    if Path(info.file_path).exists():
        info.file_size_bytes = Path(info.file_path).stat().st_size

    logger.info(f"Recording stopped: {recording_id} duration={info.duration_seconds:.1f}s")
    return info.model_dump()


@router.get("/{recording_id}")
async def get_recording(recording_id: str):
    """Get information about a specific recording."""
    if recording_id not in _recordings:
        raise HTTPException(status_code=404, detail="Recording not found")
    return _recordings[recording_id].model_dump()


@router.delete("/{recording_id}")
async def delete_recording(recording_id: str):
    """Delete a recording and its file."""
    if recording_id not in _recordings:
        raise HTTPException(status_code=404, detail="Recording not found")

    info = _recordings[recording_id]

    # Stop if active
    task = _active_tasks.get(recording_id)
    if task and not task.done():
        task.cancel()

    # Delete file
    file_path = Path(info.file_path)
    if file_path.exists():
        file_path.unlink()
        logger.info(f"Recording file deleted: {file_path}")

    del _recordings[recording_id]
    _active_tasks.pop(recording_id, None)

    return {"status": "deleted", "recording_id": recording_id}


@router.get("/status/summary")
async def recording_status():
    """Get summary of recording system status."""
    active = [r for r in _recordings.values() if r.status == "recording"]
    completed = [r for r in _recordings.values() if r.status == "completed"]
    rec_dir = _get_recordings_dir()

    total_size = sum(
        f.stat().st_size for f in rec_dir.iterdir()
        if f.is_file()
    ) if rec_dir.exists() else 0

    return {
        "active_recordings": len(active),
        "completed_recordings": len(completed),
        "total_recordings": len(_recordings),
        "disk_usage_bytes": total_size,
        "recordings_dir": str(rec_dir),
    }


async def _record_frames(info: RecordingInfo, duration_seconds: int) -> None:
    """Background task to record frames from a camera source.

    This is a stub implementation — in production, it would:
    1. Subscribe to the camera's MQTT JPEG frame topic
    2. Write frames to an MJPEG or MP4 file
    3. Track timing and frame count
    """
    try:
        start_time = time.monotonic()
        frame_interval = 1.0 / info.fps

        while (time.monotonic() - start_time) < duration_seconds:
            if info.status != "recording":
                break
            # In production: read frame from MQTT, write to file
            await asyncio.sleep(frame_interval)

        info.status = "completed"
        info.end_time = datetime.now(timezone.utc).isoformat()
        info.duration_seconds = time.monotonic() - start_time

    except asyncio.CancelledError:
        info.status = "completed"
        info.end_time = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        info.status = "error"
        logger.error(f"Recording error: {info.id}: {e}")
