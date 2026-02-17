"""Unified target tracking endpoint — real + virtual targets."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["targets"])


@router.get("/targets")
async def get_targets(request: Request):
    """Return all tracked targets (simulation + YOLO detections)."""
    amy = getattr(request.app.state, "amy", None)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    tracker = getattr(amy, "target_tracker", None)
    if tracker is None:
        return {"targets": [], "summary": ""}

    targets = tracker.get_all()
    return {
        "targets": [t.to_dict() for t in targets],
        "summary": tracker.summary(),
    }


@router.get("/targets/hostiles")
async def get_hostiles(request: Request):
    """Return only hostile targets."""
    amy = getattr(request.app.state, "amy", None)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    tracker = getattr(amy, "target_tracker", None)
    if tracker is None:
        return {"targets": []}

    return {"targets": [t.to_dict() for t in tracker.get_hostiles()]}


@router.get("/targets/friendlies")
async def get_friendlies(request: Request):
    """Return only friendly targets."""
    amy = getattr(request.app.state, "amy", None)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    tracker = getattr(amy, "target_tracker", None)
    if tracker is None:
        return {"targets": []}

    return {"targets": [t.to_dict() for t in tracker.get_friendlies()]}
