# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Nearby targets timeline enhancement — discover co-located targets.

When viewing a target's timeline, this endpoint reveals which other
targets were observed nearby at the same time. Helps discover
relationships (e.g., person A and car B always appear together at 8am).

Endpoints:
    GET /api/targets/{target_id}/nearby — targets co-located in time+space
"""

from __future__ import annotations

import logging
import math
from fastapi import APIRouter, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/targets", tags=["timeline"])


def _get_tracker(request: Request):
    """Get target tracker from Amy or app state."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        return getattr(amy, "target_tracker", None)
    return None


def _distance(pos_a: tuple[float, float], pos_b: tuple[float, float]) -> float:
    """Euclidean distance between two (x, y) positions."""
    dx = pos_a[0] - pos_b[0]
    dy = pos_a[1] - pos_b[1]
    return math.sqrt(dx * dx + dy * dy)


@router.get("/{target_id}/nearby")
async def get_nearby_targets(
    request: Request,
    target_id: str,
    radius: float = Query(50.0, ge=1.0, le=10000.0, description="Search radius in meters"),
    time_window: float = Query(300.0, ge=10.0, le=86400.0, description="Time window in seconds"),
    limit: int = Query(50, ge=1, le=500, description="Max nearby targets to return"),
):
    """Find targets that were near this target at the same time.

    Scans the target tracker for other targets whose positions overlapped
    with this target's position within the given time window and radius.
    Returns a list of co-located targets sorted by proximity, including
    how many times they were observed together.

    Useful for discovering relationships:
    - Person A and Car B always co-appear at 8am
    - Phone X is always near BLE beacon Y
    - Two mesh nodes move together
    """
    tracker = _get_tracker(request)

    # Also check simulation engine
    sim_engine = None
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        sim_engine = getattr(amy, "simulation_engine", None)
    if sim_engine is None:
        sim_engine = getattr(request.app.state, "simulation_engine", None)

    # Resolve the primary target
    primary = None
    if tracker is not None:
        primary = tracker.get_target(target_id)
    if primary is None and sim_engine is not None:
        for t in sim_engine.get_targets():
            if t.target_id == target_id:
                primary = t
                break

    if primary is None:
        return {
            "target_id": target_id,
            "nearby": [],
            "count": 0,
            "error": "Target not found",
        }

    # Get primary position
    primary_pos = getattr(primary, "position", None)
    if primary_pos is None:
        primary_pos = (0.0, 0.0)
    elif not isinstance(primary_pos, tuple):
        try:
            primary_pos = (float(primary_pos[0]), float(primary_pos[1]))
        except (TypeError, IndexError):
            primary_pos = (0.0, 0.0)

    primary_last_seen = getattr(primary, "last_seen", 0.0) or 0.0
    time_min = primary_last_seen - time_window
    time_max = primary_last_seen + time_window

    # Scan all other targets for co-location
    all_targets = []
    if tracker is not None:
        all_targets.extend(tracker.get_all())
    if sim_engine is not None:
        for t in sim_engine.get_targets():
            # Avoid duplicates
            if not any(at.target_id == t.target_id for at in all_targets):
                all_targets.append(t)

    nearby: list[dict] = []

    for t in all_targets:
        if t.target_id == target_id:
            continue

        t_last_seen = getattr(t, "last_seen", 0.0) or 0.0

        # Check time overlap
        if t_last_seen < time_min or t_last_seen > time_max:
            continue

        # Check spatial proximity
        t_pos = getattr(t, "position", None)
        if t_pos is None:
            continue
        if not isinstance(t_pos, tuple):
            try:
                t_pos = (float(t_pos[0]), float(t_pos[1]))
            except (TypeError, IndexError):
                continue

        dist = _distance(primary_pos, t_pos)
        if dist > radius:
            continue

        # Count co-occurrences from trail history
        co_occurrence_count = 1
        if tracker is not None:
            history = getattr(tracker, "history", None)
            if history is not None:
                try:
                    trail = history.get_trail_dicts(t.target_id, max_points=100)
                    for pt in trail:
                        pt_time = pt.get("timestamp", 0.0)
                        if time_min <= pt_time <= time_max:
                            pt_pos = (pt.get("x", 0.0), pt.get("y", 0.0))
                            if _distance(primary_pos, pt_pos) <= radius:
                                co_occurrence_count += 1
                except Exception:
                    pass

        t_dict = t.to_dict() if hasattr(t, "to_dict") else {"target_id": t.target_id}
        nearby.append({
            "target_id": t.target_id,
            "name": t_dict.get("name", ""),
            "asset_type": t_dict.get("asset_type", t_dict.get("type", "unknown")),
            "alliance": t_dict.get("alliance", "unknown"),
            "source": t_dict.get("source", "unknown"),
            "distance": round(dist, 1),
            "co_occurrences": co_occurrence_count,
            "last_seen": t_last_seen,
            "position": {"x": t_pos[0], "y": t_pos[1]},
        })

    # Sort by distance (closest first)
    nearby.sort(key=lambda n: n["distance"])
    nearby = nearby[:limit]

    return {
        "target_id": target_id,
        "primary_position": {"x": primary_pos[0], "y": primary_pos[1]},
        "radius": radius,
        "time_window": time_window,
        "nearby": nearby,
        "count": len(nearby),
    }
