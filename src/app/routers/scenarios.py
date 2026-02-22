"""Scenario testing API — /api/scenarios/* endpoints.

Run synthetic scenarios through Amy's pipeline, score results,
stream live video + events, and enable human rating for evaluation.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from amy.scenarios.frame_gen import _CACHE_DIR
from amy.scenarios.library import ScenarioLibrary
from amy.scenarios.runner import ScenarioRunner

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])

# In-memory store for active runs
_active_runs: dict[str, dict] = {}
_active_lock = threading.Lock()
_library = ScenarioLibrary()


# --- Request/Response models ---

class RunRequest(BaseModel):
    name: str
    chat_model: str | None = None
    deep_model: str | None = None
    system_prompt_override: str | None = None
    use_listener: bool = False


class RateRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)


# --- Endpoints ---

@router.get("")
async def list_scenarios():
    """List all scenarios with latest scores."""
    return _library.list_scenarios()


@router.get("/stats")
async def scenario_stats():
    """Aggregate improvement data across all scenarios."""
    return _library.get_stats()


@router.get("/cache")
async def cache_status():
    """Check status of pre-generated image cache."""
    bg_dir = _CACHE_DIR / "backgrounds"
    people_dir = _CACHE_DIR / "people"
    backgrounds = sorted(f.name for f in bg_dir.glob("*.jpg")) if bg_dir.exists() else []
    people = sorted(f.name for f in people_dir.glob("*.png")) if people_dir.exists() else []
    return {
        "has_cache": bool(backgrounds) and bool(people),
        "backgrounds": len(backgrounds),
        "people": len(people),
        "background_files": backgrounds,
        "people_files": people,
    }


@router.get("/export")
async def export_results(scenario: str | None = None):
    """Export all results as flat JSON for prompt optimization analysis."""
    return _library.export_results(scenario)


@router.get("/compare")
async def compare_runs(scenario: str):
    """Compare behavioral profiles of the two most recent runs."""
    results = _library.list_results(scenario)
    if len(results) < 2:
        return JSONResponse({"error": "Need at least 2 runs to compare"}, status_code=400)

    current = results[0]
    previous = results[1]

    if current.score.behavioral is None or previous.score.behavioral is None:
        return JSONResponse({"error": "One or both runs missing behavioral profile"}, status_code=400)

    cur = current.score.behavioral
    prev = previous.score.behavioral

    metrics = ["verbosity", "lexical_diversity", "think_speak_balance",
               "responsiveness", "initiative", "emotional_coherence", "safety"]

    comparison = {}
    regressions = []
    for m in metrics:
        cur_val = getattr(cur, m)
        prev_val = getattr(prev, m)
        delta = round(cur_val - prev_val, 3)
        comparison[m] = {"current": cur_val, "previous": prev_val, "delta": delta}
        if delta < -0.1:
            regressions.append(m)

    return {
        "scenario": scenario,
        "current_run": current.run_id,
        "previous_run": previous.run_id,
        "composite": {"current": cur.composite_score, "previous": prev.composite_score,
                      "delta": round(cur.composite_score - prev.composite_score, 3)},
        "metrics": comparison,
        "regressions": regressions,
    }


@router.post("/backfill")
async def backfill_behavioral():
    """Re-compute behavioral profiles for all existing results."""
    from amy.scenarios.scorer import Scorer

    updated = 0
    scorer = Scorer()

    for path in _library._results_dir.glob("*.json"):
        try:
            with open(path) as f:
                data = json.load(f)
            from amy.scenarios.schema import ScenarioResult, RecordedAction
            result = ScenarioResult(**data)

            duration = result.config.get("time_scale", 1.0) * result.duration_actual
            if duration <= 0:
                # Try to estimate from actions
                if result.actions:
                    duration = max(a.timestamp for a in result.actions)

            if duration > 0:
                profile = scorer.profile(result.actions, duration)
                data["score"]["behavioral"] = profile.model_dump()
                with open(path, "w") as f:
                    json.dump(data, f, indent=2)
                updated += 1
        except Exception:
            continue

    return {"updated": updated}


@router.delete("/runs/cleanup")
async def cleanup_runs():
    """Remove completed and failed runs from active memory."""
    cleaned = 0
    with _active_lock:
        to_remove = [
            rid for rid, run in _active_runs.items()
            if run["status"] in ("completed", "failed")
        ]
        for rid in to_remove:
            del _active_runs[rid]
            cleaned += 1
    return {"cleaned": cleaned}


@router.get("/active")
async def active_run():
    """Return the currently running scenario (if any)."""
    with _active_lock:
        for run_id, run in _active_runs.items():
            if run["status"] == "running":
                return {"run_id": run_id, "scenario_name": run["scenario_name"]}
    return {"run_id": None}


@router.get("/{name}")
async def get_scenario(name: str):
    """Get scenario details and run history."""
    try:
        scenario = _library.load_scenario(name)
    except FileNotFoundError:
        return JSONResponse({"error": f"Scenario '{name}' not found"}, status_code=404)

    results = _library.list_results(name)
    return {
        "scenario": scenario.model_dump(),
        "results": [r.model_dump() for r in results[:10]],
    }


@router.post("/run")
async def start_run(body: RunRequest):
    """Start a scenario run (async, returns run_id)."""
    try:
        scenario = _library.load_scenario(body.name)
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"Scenario '{body.name}' not found"}, status_code=404,
        )

    runner = ScenarioRunner(
        scenario,
        chat_model=body.chat_model or "gemma3:4b",
        deep_model=body.deep_model or "llava:7b",
        system_prompt_override=body.system_prompt_override,
        use_listener=body.use_listener,
    )

    # Generate a run_id before starting
    import uuid
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    # Track active run
    with _active_lock:
        _active_runs[run_id] = {
            "status": "running",
            "scenario_name": body.name,
            "started": time.time(),
            "runner": runner,
            "result": None,
        }

    # Run in background thread
    def _run():
        try:
            result = runner.run()
            result.run_id = run_id
            _library.save_result(result)
            with _active_lock:
                if run_id in _active_runs:
                    _active_runs[run_id]["status"] = "completed"
                    _active_runs[run_id]["result"] = result
        except Exception as e:
            with _active_lock:
                if run_id in _active_runs:
                    _active_runs[run_id]["status"] = "failed"
                    _active_runs[run_id]["error"] = str(e)

    t = threading.Thread(target=_run, daemon=True, name=f"scenario-{run_id}")
    t.start()

    return {"run_id": run_id, "status": "running", "scenario": body.name}


@router.get("/run/{run_id}")
async def get_run(run_id: str):
    """Get run status and results."""
    # Check active runs first
    with _active_lock:
        active = _active_runs.get(run_id)

    if active:
        if active["result"] is not None:
            return active["result"].model_dump()
        return {
            "run_id": run_id,
            "status": active["status"],
            "scenario_name": active["scenario_name"],
            "elapsed": time.time() - active["started"],
        }

    # Check saved results
    for path in (_library._results_dir).glob("*.json"):
        try:
            with open(path) as f:
                data = json.load(f)
            if data.get("run_id") == run_id:
                return data
        except Exception:
            continue

    return JSONResponse({"error": "Run not found"}, status_code=404)


@router.get("/run/{run_id}/video")
async def run_video(run_id: str):
    """MJPEG stream of the synthetic camera during a live run."""
    with _active_lock:
        active = _active_runs.get(run_id)

    if not active:
        return JSONResponse({"error": "Run not found"}, status_code=404)

    runner: ScenarioRunner = active["runner"]

    def mjpeg_stream():
        while True:
            with _active_lock:
                run_data = _active_runs.get(run_id)
            if not run_data or run_data["status"] != "running":
                break

            frame = runner.get_jpeg()
            if frame is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                    + frame + b"\r\n"
                )
            time.sleep(0.1)  # ~10fps

    return StreamingResponse(
        mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/run/{run_id}/stream")
async def run_stream(run_id: str):
    """SSE stream of live events during a run.

    Sends action events as they happen (speech, thoughts, detections)
    so the frontend can show a live timeline and trigger browser TTS.
    """
    with _active_lock:
        active = _active_runs.get(run_id)

    if not active:
        return JSONResponse({"error": "Run not found or finished"}, status_code=404)

    runner: ScenarioRunner = active["runner"]

    async def event_stream():
        last_index = 0
        while True:
            with _active_lock:
                run_data = _active_runs.get(run_id)
            if not run_data or run_data["status"] != "running":
                # Send final result if available
                if run_data and run_data.get("result"):
                    result = run_data["result"]
                    yield f"data: {json.dumps({'type': 'finished', 'score': result.score.model_dump()})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'finished', 'status': run_data['status'] if run_data else 'unknown'})}\n\n"
                break

            # Get new actions from the live recorder
            new_actions = runner.get_live_actions(since_index=last_index)
            for action in new_actions:
                yield f"data: {json.dumps({'type': 'action', 'data': action})}\n\n"
            last_index += len(new_actions)

            yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/run/{run_id}/rate")
async def rate_run(run_id: str, body: RateRequest):
    """Submit a human rating (1-5) for a run."""
    if _library.rate_result(run_id, body.rating):
        return {"status": "ok", "run_id": run_id, "rating": body.rating}
    return JSONResponse({"error": "Run not found"}, status_code=404)
