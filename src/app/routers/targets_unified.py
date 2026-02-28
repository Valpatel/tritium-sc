"""Unified target tracking endpoint — real + virtual targets."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["targets"])


def _get_tracker(request: Request):
    """Get target tracker from Amy, or fall back to simulation engine targets."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        tracker = getattr(amy, "target_tracker", None)
        if tracker is not None:
            return tracker
    return None


def _get_sim_engine(request: Request):
    """Get simulation engine (headless fallback when Amy is disabled)."""
    return getattr(request.app.state, "simulation_engine", None)


@router.get("/targets")
async def get_targets(request: Request):
    """Return all tracked targets (simulation + YOLO detections)."""
    tracker = _get_tracker(request)
    if tracker is not None:
        targets = tracker.get_all()
        return {
            "targets": [t.to_dict() for t in targets],
            "summary": tracker.summary(),
        }

    # Headless mode: read targets directly from simulation engine
    engine = _get_sim_engine(request)
    if engine is not None:
        targets = engine.get_targets()
        return {
            "targets": [t.to_dict() for t in targets],
            "summary": f"{len(targets)} simulation targets",
        }

    return {"targets": [], "summary": "No tracking available"}


@router.get("/targets/hostiles")
async def get_hostiles(request: Request):
    """Return only hostile targets."""
    tracker = _get_tracker(request)
    if tracker is not None:
        return {"targets": [t.to_dict() for t in tracker.get_hostiles()]}

    engine = _get_sim_engine(request)
    if engine is not None:
        targets = [t for t in engine.get_targets() if t.alliance == "hostile"]
        return {"targets": [t.to_dict() for t in targets]}

    return {"targets": []}


@router.get("/targets/friendlies")
async def get_friendlies(request: Request):
    """Return only friendly targets."""
    tracker = _get_tracker(request)
    if tracker is not None:
        return {"targets": [t.to_dict() for t in tracker.get_friendlies()]}

    engine = _get_sim_engine(request)
    if engine is not None:
        targets = [t for t in engine.get_targets() if t.alliance == "friendly"]
        return {"targets": [t.to_dict() for t in targets]}

    return {"targets": []}


@router.post("/sighting")
async def report_sighting(request: Request):
    """Accept a sighting report from camera or robot."""
    engine = _get_sim_engine(request)
    if engine is None:
        return {"error": "No simulation engine"}
    body = await request.json()
    from engine.simulation.vision import SightingReport
    report = SightingReport(
        observer_id=body.get("observer_id", "unknown"),
        target_id=body.get("target_id", ""),
        observer_type=body.get("observer_type", "camera"),
        confidence=body.get("confidence", 1.0),
        position=tuple(body["position"]) if "position" in body else None,
        timestamp=body.get("timestamp", 0.0),
    )
    engine.vision_system.add_sighting(report)
    return {"status": "accepted"}
