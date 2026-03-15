# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Target activity heatmap API — 24-bin hourly histogram of sightings.

Aggregates all target sightings into a 24-hour histogram showing which
hours of the day are busiest. Reveals daily patterns for operational planning.

Endpoints:
    GET /api/analytics/activity-heatmap — aggregate hourly activity histogram
    GET /api/analytics/activity-heatmap/{target_id} — per-target hourly pattern
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _get_event_store(request: Request):
    """Get the TacticalEventStore from app state, or None."""
    return getattr(request.app.state, "tactical_event_store", None)


@router.get("/activity-heatmap")
async def get_activity_heatmap(
    request: Request,
    hours: Optional[float] = Query(24, description="Look-back window in hours"),
):
    """Get aggregate 24-bin hourly activity histogram.

    Returns a histogram of sighting/event counts by hour of day (0-23),
    plus metadata: peak_hour, quiet_hours, total count, and active_hours.
    """
    store = _get_event_store(request)

    now = time.time()
    start = now - (hours * 3600) if hours else now - 86400

    hourly_bins = [0] * 24

    if store is not None:
        # Use the store's hourly breakdown
        hourly = store.get_hourly_breakdown(start=start, end=now)
        if isinstance(hourly, dict):
            for hour_str, count in hourly.items():
                try:
                    h = int(hour_str)
                    if 0 <= h <= 23:
                        hourly_bins[h] = count
                except (ValueError, TypeError):
                    pass

    total = sum(hourly_bins)
    peak_count = max(hourly_bins)
    peak_hour = hourly_bins.index(peak_count) if peak_count > 0 else 0

    # Quiet hours: below 5% of peak
    threshold = peak_count * 0.05 if peak_count > 0 else 0
    quiet_hours = [h for h in range(24) if hourly_bins[h] <= threshold]
    active_hours = [h for h in range(24) if hourly_bins[h] > 0]

    return JSONResponse(content={
        "hourly_counts": hourly_bins,
        "peak_hour": peak_hour,
        "peak_count": peak_count,
        "quiet_hours": quiet_hours,
        "active_hours": active_hours,
        "total_sightings": total,
        "time_window_hours": hours,
        "generated_at": now,
    })


@router.get("/activity-heatmap/{target_id}")
async def get_target_activity_heatmap(
    request: Request,
    target_id: str,
    hours: Optional[float] = Query(24, description="Look-back window in hours"),
):
    """Get per-target 24-bin hourly activity histogram.

    Returns the hourly breakdown for a specific target, plus regularity_score
    and pattern classification (daytime/nighttime/mixed).
    """
    store = _get_event_store(request)

    now = time.time()
    start = now - (hours * 3600) if hours else now - 86400

    hourly_bins = [0] * 24

    if store is not None:
        # Get events for this specific target
        events = store.query(target_id=target_id, start=start, end=now, limit=10000)
        if events:
            from datetime import datetime, timezone
            for evt in events:
                ts = evt.get("timestamp", evt.get("ts", 0))
                if isinstance(ts, (int, float)) and ts > 0:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    hourly_bins[dt.hour] += 1

    total = sum(hourly_bins)
    peak_count = max(hourly_bins)
    peak_hour = hourly_bins.index(peak_count) if peak_count > 0 else 0

    # Compute regularity score (normalized entropy)
    import math
    if total > 0:
        max_entropy = math.log(24)
        entropy = 0.0
        for c in hourly_bins:
            if c > 0:
                p = c / total
                entropy -= p * math.log(p)
        regularity_score = round(1.0 - (entropy / max_entropy), 4)
    else:
        regularity_score = 0.0

    # Classify pattern
    daytime_count = sum(hourly_bins[6:18])
    nighttime_count = total - daytime_count
    if total == 0:
        pattern_type = "no_data"
    elif daytime_count > 0 and nighttime_count == 0:
        pattern_type = "daytime_only"
    elif nighttime_count > 0 and daytime_count == 0:
        pattern_type = "nighttime_only"
    elif daytime_count > nighttime_count * 3:
        pattern_type = "mostly_daytime"
    elif nighttime_count > daytime_count * 3:
        pattern_type = "mostly_nighttime"
    else:
        pattern_type = "mixed"

    threshold = peak_count * 0.05 if peak_count > 0 else 0
    quiet_hours = [h for h in range(24) if hourly_bins[h] <= threshold]

    return JSONResponse(content={
        "target_id": target_id,
        "hourly_counts": hourly_bins,
        "peak_hour": peak_hour,
        "peak_count": peak_count,
        "quiet_hours": quiet_hours,
        "total_sightings": total,
        "regularity_score": regularity_score,
        "pattern_type": pattern_type,
        "time_window_hours": hours,
        "generated_at": now,
    })
