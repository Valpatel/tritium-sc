# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Movement analytics router — velocity, direction, dwell time for targets.

Provides per-target movement analytics derived from TargetHistory position
ring buffers.  Includes velocity estimation, direction histograms, dwell
time calculation per zone, and fleet-wide aggregates.

Endpoints:
    GET /api/analytics/movement/{target_id}   — per-target movement analytics
    GET /api/analytics/movement               — fleet-wide movement metrics
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# Direction bin labels and angle ranges (compass, 0=north clockwise)
_DIRECTION_BINS = [
    ("N", 337.5, 22.5),
    ("NE", 22.5, 67.5),
    ("E", 67.5, 112.5),
    ("SE", 112.5, 157.5),
    ("S", 157.5, 202.5),
    ("SW", 202.5, 247.5),
    ("W", 247.5, 292.5),
    ("NW", 292.5, 337.5),
]

# Minimum speed (m/s) to consider a target moving
_STATIONARY_THRESHOLD = 0.3


def _heading_to_bin(heading_deg: float) -> str:
    """Map a compass heading (0-360) to an 8-point direction label."""
    h = heading_deg % 360
    for label, lo, hi in _DIRECTION_BINS:
        if label == "N":
            if h >= lo or h < hi:
                return label
        else:
            if lo <= h < hi:
                return label
    return "N"


def _compute_movement_analytics(
    target_id: str,
    history,
    zones: list | None = None,
    window_s: float = 3600.0,
) -> dict:
    """Compute movement analytics from position history.

    Args:
        target_id: Target ID to analyze.
        history: TargetHistory instance.
        zones: Optional list of zone dicts with id, name, center_x, center_y, radius.
        window_s: Analysis window in seconds (default 1 hour).

    Returns:
        Dict suitable for JSON response.
    """
    trail = history.get_trail(target_id, max_points=1000)
    if not trail:
        return {
            "target_id": target_id,
            "error": "no_history",
            "message": "No position history available for this target",
        }

    now = trail[-1][2]  # most recent timestamp
    cutoff = now - window_s

    # Filter to analysis window
    windowed = [(x, y, t) for x, y, t in trail if t >= cutoff]
    if len(windowed) < 2:
        windowed = trail[-2:] if len(trail) >= 2 else trail

    # Compute segment-level metrics
    speeds = []
    headings = []
    total_distance = 0.0
    max_speed = 0.0

    for i in range(1, len(windowed)):
        x0, y0, t0 = windowed[i - 1]
        x1, y1, t1 = windowed[i]
        dt = t1 - t0
        if dt <= 0:
            continue
        dist = math.hypot(x1 - x0, y1 - y0)
        spd = dist / dt
        total_distance += dist
        speeds.append(spd)
        if spd > max_speed:
            max_speed = spd

        # Heading (compass: 0=north/+Y, clockwise)
        if dist > 0.01:
            heading = math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360
            headings.append(heading)

    avg_speed = sum(speeds) / len(speeds) if speeds else 0.0
    current_speed = speeds[-1] if speeds else 0.0
    current_heading = headings[-1] if headings else 0.0
    is_stationary = current_speed < _STATIONARY_THRESHOLD

    # Direction histogram
    direction_hist = {d: 0.0 for d, _, _ in _DIRECTION_BINS}
    if headings:
        for h in headings:
            b = _heading_to_bin(h)
            direction_hist[b] += 1.0
        total_h = sum(direction_hist.values())
        if total_h > 0:
            direction_hist = {k: v / total_h for k, v in direction_hist.items()}

    # Activity periods (contiguous segments above threshold)
    activity_periods = []
    if len(windowed) >= 2:
        in_activity = False
        period_start = 0.0
        period_dist = 0.0
        period_speeds: list[float] = []
        for i in range(1, len(windowed)):
            x0, y0, t0 = windowed[i - 1]
            x1, y1, t1 = windowed[i]
            dt = t1 - t0
            if dt <= 0:
                continue
            dist = math.hypot(x1 - x0, y1 - y0)
            spd = dist / dt
            if spd >= _STATIONARY_THRESHOLD:
                if not in_activity:
                    in_activity = True
                    period_start = t0
                    period_dist = 0.0
                    period_speeds = []
                period_dist += dist
                period_speeds.append(spd)
            else:
                if in_activity:
                    in_activity = False
                    activity_periods.append({
                        "start_epoch": period_start,
                        "end_epoch": windowed[i - 1][2],
                        "avg_speed_mps": round(sum(period_speeds) / len(period_speeds), 3) if period_speeds else 0.0,
                        "distance_m": round(period_dist, 2),
                        "duration_s": round(windowed[i - 1][2] - period_start, 1),
                    })
        if in_activity:
            activity_periods.append({
                "start_epoch": period_start,
                "end_epoch": windowed[-1][2],
                "avg_speed_mps": round(sum(period_speeds) / len(period_speeds), 3) if period_speeds else 0.0,
                "distance_m": round(period_dist, 2),
                "duration_s": round(windowed[-1][2] - period_start, 1),
            })

    # Dwell times per zone
    dwell_times = []
    if zones:
        for zone in zones:
            zone_id = zone.get("id", "")
            zone_name = zone.get("name", zone_id)
            cx = zone.get("center_x", zone.get("x", 0.0))
            cy = zone.get("center_y", zone.get("y", 0.0))
            radius = zone.get("radius", 50.0)

            total_dwell = 0.0
            entry_count = 0
            in_zone = False
            last_entry = 0.0
            last_exit = 0.0

            for x, y, t in windowed:
                dist = math.hypot(x - cx, y - cy)
                if dist <= radius:
                    if not in_zone:
                        in_zone = True
                        entry_count += 1
                        last_entry = t
                else:
                    if in_zone:
                        in_zone = False
                        last_exit = t
                        total_dwell += t - last_entry

            # If still in zone at end
            if in_zone and windowed:
                total_dwell += windowed[-1][2] - last_entry
                last_exit = windowed[-1][2]

            if entry_count > 0:
                dwell_times.append({
                    "zone_id": zone_id,
                    "zone_name": zone_name,
                    "total_seconds": round(total_dwell, 1),
                    "entry_count": entry_count,
                    "last_entry_epoch": last_entry,
                    "last_exit_epoch": last_exit,
                })

    return {
        "target_id": target_id,
        "avg_speed_mps": round(avg_speed, 3),
        "max_speed_mps": round(max_speed, 3),
        "total_distance_m": round(total_distance, 2),
        "current_speed_mps": round(current_speed, 3),
        "current_heading_deg": round(current_heading, 1),
        "is_stationary": is_stationary,
        "direction_histogram": {k: round(v, 4) for k, v in direction_hist.items()},
        "activity_periods": activity_periods,
        "dwell_times": dwell_times,
        "trail_points": len(windowed),
        "analysis_window_s": window_s,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _get_target_tracker(request: Request):
    """Get the target tracker from Amy or app state."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        return getattr(amy, "target_tracker", None)
    return getattr(request.app.state, "target_tracker", None)


def _get_zones(request: Request) -> list:
    """Get zone definitions for dwell time calculation."""
    try:
        from app.routers.geofence import _get_zone_store
        store = _get_zone_store()
        if store is None:
            return []
        zones_raw = store.list_all() if hasattr(store, "list_all") else []
        return zones_raw
    except Exception:
        return []


@router.get("/movement/{target_id}")
async def get_movement_analytics(request: Request, target_id: str, window: float = 3600.0):
    """Get movement analytics for a specific target.

    Computes velocity estimation, direction prediction, dwell time per zone,
    and activity periods from the target's position history.

    Args:
        target_id: The unique target identifier.
        window: Analysis window in seconds (default 3600 = 1 hour).
    """
    tracker = _get_target_tracker(request)
    if tracker is None:
        return JSONResponse(
            {"error": "Target tracker not available"},
            status_code=503,
        )

    # Get the history from the tracker
    history = getattr(tracker, "history", None)
    if history is None:
        return JSONResponse(
            {"error": "Target history not available"},
            status_code=503,
        )

    # Check if target exists
    target = tracker.get_target(target_id)
    if target is None:
        return JSONResponse(
            {"error": f"Target '{target_id}' not found"},
            status_code=404,
        )

    zones = _get_zones(request)
    analytics = _compute_movement_analytics(target_id, history, zones=zones, window_s=window)

    # Enrich with target info
    analytics["target_name"] = target.name
    analytics["target_type"] = target.asset_type
    analytics["alliance"] = target.alliance

    return analytics


@router.get("/movement")
async def get_fleet_movement(request: Request, window: float = 3600.0):
    """Get fleet-wide movement metrics across all tracked targets.

    Returns aggregate speed, distance, direction, and per-target summaries
    for all currently tracked targets.
    """
    tracker = _get_target_tracker(request)
    if tracker is None:
        return JSONResponse(
            {"error": "Target tracker not available"},
            status_code=503,
        )

    history = getattr(tracker, "history", None)
    if history is None:
        return JSONResponse(
            {"error": "Target history not available"},
            status_code=503,
        )

    targets = tracker.get_all()
    zones = _get_zones(request)

    per_target = []
    speeds = []
    max_speed = 0.0
    total_distance = 0.0
    moving_count = 0
    dir_totals: dict[str, float] = {}

    for t in targets:
        analytics = _compute_movement_analytics(t.target_id, history, zones=zones, window_s=window)
        if "error" in analytics:
            continue

        per_target.append({
            "target_id": t.target_id,
            "name": t.name,
            "type": t.asset_type,
            "speed": analytics["current_speed_mps"],
            "heading": analytics["current_heading_deg"],
            "distance": analytics["total_distance_m"],
            "stationary": analytics["is_stationary"],
        })

        total_distance += analytics["total_distance_m"]
        if analytics["max_speed_mps"] > max_speed:
            max_speed = analytics["max_speed_mps"]
        if not analytics["is_stationary"]:
            moving_count += 1
            speeds.append(analytics["current_speed_mps"])
        for d, v in analytics["direction_histogram"].items():
            dir_totals[d] = dir_totals.get(d, 0.0) + v

    avg_speed = sum(speeds) / len(speeds) if speeds else 0.0
    dominant = max(dir_totals, key=dir_totals.get, default="") if dir_totals else ""

    return {
        "total_targets": len(targets),
        "moving_targets": moving_count,
        "stationary_targets": len(targets) - moving_count,
        "avg_fleet_speed_mps": round(avg_speed, 3),
        "max_fleet_speed_mps": round(max_speed, 3),
        "total_fleet_distance_m": round(total_distance, 2),
        "dominant_direction": dominant,
        "per_target": per_target,
        "analysis_window_s": window,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
