"""Search endpoints for people/vehicle lookup and similarity search.

CRITICAL FOR SAFETY: This module enables identifying recurring individuals
who may pose a threat (e.g., stalkers). Key features:
- Visual similarity search to find the same person across appearances
- Recurring person detection (flags people who appear 3+ times)
- Suspicious pattern detection (same time each day = higher alert)
- Human-in-the-loop labeling (known vs unknown classification)
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, stdev
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from loguru import logger

from app.config import settings

router = APIRouter(prefix="/api/search", tags=["search"])

# Storage paths
THUMBNAILS_DIR = settings.recordings_path / ".cache" / "thumbnails"
VECTORS_PATH = settings.recordings_path / ".cache" / "vectors.json"
LABELS_PATH = settings.recordings_path / ".cache" / "labels.json"
MERGES_PATH = settings.recordings_path / ".cache" / "merges.json"
FEEDBACK_PATH = settings.recordings_path / ".cache" / "feedback.json"


class MergeRequest(BaseModel):
    """Request to merge multiple detections as same object."""
    primary_id: str  # The ID to keep
    duplicate_ids: list[str]  # IDs to merge into primary


class LabelRequest(BaseModel):
    """Request to label an object."""
    thumbnail_id: str
    label: str  # User-provided name like "my car", "mailman", etc.
    notes: Optional[str] = None


class FeedbackRequest(BaseModel):
    """User feedback for a detection."""
    thumbnail_id: str
    feedback_type: str  # "correct", "wrong_type", "wrong_merge", "not_real"
    correct_type: Optional[str] = None  # If wrong_type
    notes: Optional[str] = None


def load_json(path: Path, default=None):
    """Load JSON file or return default."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return default or {}


def save_json(path: Path, data):
    """Save data to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def get_vector_store():
    """Get the vector store instance."""
    from app.ai.embeddings import VectorStore
    return VectorStore(VECTORS_PATH)


@router.get("/people")
async def list_people(
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    channel: Optional[int] = Query(None, description="Filter by channel"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """List all detected people with thumbnails."""
    store = get_vector_store()
    results = store.get_all(
        target_type="person",
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )

    # Add labels and merge info
    labels = load_json(LABELS_PATH, {})
    merges = load_json(MERGES_PATH, {"merged_into": {}, "groups": {}})

    enriched = []
    seen_groups = set()

    for r in results:
        tid = r.get("thumbnail_id", "")

        # Skip if merged into another
        if tid in merges.get("merged_into", {}):
            primary = merges["merged_into"][tid]
            if primary in seen_groups:
                continue
            seen_groups.add(primary)
            r = next((x for x in results if x.get("thumbnail_id") == primary), r)
            tid = primary

        # Add label if exists
        r["label"] = labels.get(tid, {}).get("label")
        r["notes"] = labels.get(tid, {}).get("notes")

        # Add URL for thumbnail
        r["thumbnail_url"] = f"/api/search/thumbnail/{tid}"

        # Count how many are merged into this
        r["merged_count"] = len(merges.get("groups", {}).get(tid, []))

        if channel and r.get("channel") != channel:
            continue

        enriched.append(r)

    return {
        "total": len(enriched),
        "items": enriched,
        "offset": offset,
        "limit": limit,
    }


@router.get("/vehicles")
async def list_vehicles(
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    channel: Optional[int] = Query(None, description="Filter by channel"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """List all detected vehicles with thumbnails."""
    store = get_vector_store()

    # Get cars, trucks, etc.
    results = []
    for vtype in ["car", "truck", "bus", "motorcycle", "bicycle"]:
        results.extend(store.get_all(
            target_type=vtype,
            date_from=date_from,
            date_to=date_to,
            limit=limit * 2,  # Get extra since we'll merge
        ))

    # Sort by timestamp
    results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    # Add labels and merge info
    labels = load_json(LABELS_PATH, {})
    merges = load_json(MERGES_PATH, {"merged_into": {}, "groups": {}})

    enriched = []
    seen_groups = set()

    for r in results:
        tid = r.get("thumbnail_id", "")

        # Skip if merged into another
        if tid in merges.get("merged_into", {}):
            primary = merges["merged_into"][tid]
            if primary in seen_groups:
                continue
            seen_groups.add(primary)
            # Use primary's data
            r = next((x for x in results if x.get("thumbnail_id") == primary), r)
            tid = primary

        r["label"] = labels.get(tid, {}).get("label")
        r["notes"] = labels.get(tid, {}).get("notes")
        r["thumbnail_url"] = f"/api/search/thumbnail/{tid}"
        r["merged_count"] = len(merges.get("groups", {}).get(tid, []))

        if channel and r.get("channel") != channel:
            continue

        enriched.append(r)

    return {
        "total": len(enriched),
        "items": enriched[:limit],
        "offset": offset,
        "limit": limit,
    }


@router.get("/thumbnail/{thumbnail_id}")
async def get_thumbnail(thumbnail_id: str):
    """Get a thumbnail image."""
    # Search in all category directories
    for category in ["person", "vehicle", "animal"]:
        path = THUMBNAILS_DIR / category / f"{thumbnail_id}.jpg"
        if path.exists():
            return FileResponse(path, media_type="image/jpeg")

    raise HTTPException(status_code=404, detail="Thumbnail not found")


@router.get("/similar/{thumbnail_id}")
async def find_similar(
    thumbnail_id: str,
    limit: int = Query(10, le=50),
):
    """Find similar objects to a given thumbnail."""
    store = get_vector_store()
    results = store.search_by_thumbnail(thumbnail_id, k=limit)

    return {
        "query_id": thumbnail_id,
        "similar": [
            {
                **meta,
                "similarity": round(score, 3),
                "thumbnail_url": f"/api/search/thumbnail/{meta.get('thumbnail_id', '')}",
            }
            for meta, score in results
        ],
    }


@router.post("/merge")
async def merge_detections(request: MergeRequest):
    """Merge multiple detections as the same object.

    User feedback: 'These are all the same car/person'.
    """
    merges = load_json(MERGES_PATH, {"merged_into": {}, "groups": {}})

    # Add each duplicate to the merged_into map
    for dup_id in request.duplicate_ids:
        merges["merged_into"][dup_id] = request.primary_id

    # Update groups
    if request.primary_id not in merges["groups"]:
        merges["groups"][request.primary_id] = []
    merges["groups"][request.primary_id].extend(request.duplicate_ids)

    save_json(MERGES_PATH, merges)

    # Also log as feedback for future training
    feedback = load_json(FEEDBACK_PATH, {"items": []})
    feedback["items"].append({
        "type": "merge",
        "primary_id": request.primary_id,
        "duplicate_ids": request.duplicate_ids,
        "timestamp": datetime.now().isoformat(),
    })
    save_json(FEEDBACK_PATH, feedback)

    logger.info(f"Merged {len(request.duplicate_ids)} detections into {request.primary_id}")

    return {
        "status": "success",
        "primary_id": request.primary_id,
        "merged_count": len(request.duplicate_ids),
    }


@router.post("/unmerge/{thumbnail_id}")
async def unmerge_detection(thumbnail_id: str):
    """Remove a detection from its merge group."""
    merges = load_json(MERGES_PATH, {"merged_into": {}, "groups": {}})

    if thumbnail_id in merges["merged_into"]:
        primary = merges["merged_into"].pop(thumbnail_id)
        if primary in merges["groups"]:
            merges["groups"][primary] = [
                x for x in merges["groups"][primary] if x != thumbnail_id
            ]
        save_json(MERGES_PATH, merges)
        return {"status": "success", "unmerged": thumbnail_id}

    raise HTTPException(status_code=404, detail="Not in a merge group")


@router.post("/label")
async def label_object(request: LabelRequest):
    """Add a label to a detected object.

    Examples: 'my car', 'mailman', 'neighbor bob', 'delivery truck'.
    """
    labels = load_json(LABELS_PATH, {})

    labels[request.thumbnail_id] = {
        "label": request.label,
        "notes": request.notes,
        "labeled_at": datetime.now().isoformat(),
    }

    save_json(LABELS_PATH, labels)

    # Log for training
    feedback = load_json(FEEDBACK_PATH, {"items": []})
    feedback["items"].append({
        "type": "label",
        "thumbnail_id": request.thumbnail_id,
        "label": request.label,
        "timestamp": datetime.now().isoformat(),
    })
    save_json(FEEDBACK_PATH, feedback)

    logger.info(f"Labeled {request.thumbnail_id} as '{request.label}'")

    return {"status": "success", "thumbnail_id": request.thumbnail_id}


@router.delete("/label/{thumbnail_id}")
async def remove_label(thumbnail_id: str):
    """Remove a label from an object."""
    labels = load_json(LABELS_PATH, {})

    if thumbnail_id in labels:
        del labels[thumbnail_id]
        save_json(LABELS_PATH, labels)
        return {"status": "success"}

    raise HTTPException(status_code=404, detail="Label not found")


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """Submit feedback about a detection.

    For reinforcement learning and improving the system.
    """
    feedback = load_json(FEEDBACK_PATH, {"items": []})

    feedback["items"].append({
        "type": "detection_feedback",
        "thumbnail_id": request.thumbnail_id,
        "feedback_type": request.feedback_type,
        "correct_type": request.correct_type,
        "notes": request.notes,
        "timestamp": datetime.now().isoformat(),
    })

    save_json(FEEDBACK_PATH, feedback)

    logger.info(f"Feedback received for {request.thumbnail_id}: {request.feedback_type}")

    return {"status": "success"}


@router.get("/feedback/stats")
async def get_feedback_stats():
    """Get statistics about user feedback."""
    feedback = load_json(FEEDBACK_PATH, {"items": []})
    merges = load_json(MERGES_PATH, {"merged_into": {}, "groups": {}})
    labels = load_json(LABELS_PATH, {})

    items = feedback.get("items", [])

    return {
        "total_feedback": len(items),
        "total_labels": len(labels),
        "total_merge_groups": len(merges.get("groups", {})),
        "total_merged_items": len(merges.get("merged_into", {})),
        "feedback_by_type": {
            ftype: sum(1 for i in items if i.get("type") == ftype)
            for ftype in set(i.get("type") for i in items)
        },
    }


@router.get("/stats")
async def get_search_stats():
    """Get overall search/detection statistics."""
    store = get_vector_store()
    stats = store.stats()

    merges = load_json(MERGES_PATH, {"merged_into": {}, "groups": {}})
    labels = load_json(LABELS_PATH, {})

    # Calculate unique after merges
    unique_counts = {}
    for obj_type, count in stats.get("by_type", {}).items():
        # Count how many are primary (not merged into others)
        merged = sum(1 for tid, primary in merges.get("merged_into", {}).items()
                    if any(m.get("target_type") == obj_type
                          for m in store.get_all(target_type=obj_type)))
        unique_counts[obj_type] = count - merged

    return {
        "total_detections": stats.get("total", 0),
        "by_type": stats.get("by_type", {}),
        "unique_after_merge": unique_counts,
        "labeled_count": len(labels),
        "merge_groups": len(merges.get("groups", {})),
    }


@router.get("/sightings/{thumbnail_id}")
async def get_target_sightings(
    thumbnail_id: str,
    limit: int = Query(50, le=200),
):
    """Get all sightings/appearances of a target.

    Returns chronological list of when this target (or merged targets) was detected.
    """
    store = get_vector_store()
    merges = load_json(MERGES_PATH, {"merged_into": {}, "groups": {}})
    labels = load_json(LABELS_PATH, {})

    # Get all IDs in this target's merge group
    target_ids = [thumbnail_id]

    # If this is merged into another, use the primary
    if thumbnail_id in merges.get("merged_into", {}):
        primary = merges["merged_into"][thumbnail_id]
        target_ids = [primary] + merges.get("groups", {}).get(primary, [])
    elif thumbnail_id in merges.get("groups", {}):
        # This is a primary with merged items
        target_ids = [thumbnail_id] + merges["groups"][thumbnail_id]

    # Get all sightings for these IDs
    sightings = []
    for tid in target_ids:
        # Get metadata for this thumbnail
        all_items = store.get_all(limit=10000)  # Get all to search
        matching = [item for item in all_items if item.get("thumbnail_id") == tid]
        sightings.extend(matching)

    # Sort by timestamp
    sightings.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    # Get label
    label_info = labels.get(thumbnail_id, {})

    # Aggregate by day and channel
    by_day = {}
    by_channel = {}
    by_hour = [0] * 24

    for s in sightings:
        ts = s.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                day = dt.strftime("%Y-%m-%d")
                hour = dt.hour
                by_day[day] = by_day.get(day, 0) + 1
                by_hour[hour] = by_hour[hour] + 1
            except:
                pass

        ch = s.get("channel")
        if ch:
            by_channel[ch] = by_channel.get(ch, 0) + 1

    # Find first and last sighting
    first_seen = sightings[-1].get("timestamp") if sightings else None
    last_seen = sightings[0].get("timestamp") if sightings else None

    return {
        "thumbnail_id": thumbnail_id,
        "label": label_info.get("label"),
        "total_sightings": len(sightings),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "sightings": sightings[:limit],
        "by_day": dict(sorted(by_day.items(), reverse=True)),
        "by_channel": by_channel,
        "by_hour": by_hour,
        "merged_ids": target_ids,
    }


@router.get("/trends")
async def get_detection_trends(
    days: int = Query(7, le=30, description="Number of days to analyze"),
    channel: Optional[int] = Query(None, description="Filter by channel"),
):
    """Get detection trends and analytics.

    Returns aggregate statistics for target analysis.
    """
    from collections import defaultdict

    store = get_vector_store()
    labels = load_json(LABELS_PATH, {})

    # Get all detections
    all_items = store.get_all(limit=10000)

    # Calculate date range
    today = datetime.now().date()
    start_date = today - timedelta(days=days)

    # Aggregate data
    by_day = defaultdict(lambda: {"person": 0, "vehicle": 0, "total": 0})
    by_hour = defaultdict(int)
    by_channel = defaultdict(int)
    recent_targets = []

    for item in all_items:
        ts = item.get("timestamp", "")
        if not ts:
            continue

        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            item_date = dt.date()

            # Filter by date range
            if item_date < start_date:
                continue

            # Filter by channel if specified
            if channel and item.get("channel") != channel:
                continue

            day_key = item_date.strftime("%Y-%m-%d")
            target_type = item.get("target_type", "unknown")

            by_day[day_key]["total"] += 1
            if target_type == "person":
                by_day[day_key]["person"] += 1
            elif target_type in ("car", "truck", "bus", "motorcycle"):
                by_day[day_key]["vehicle"] += 1

            by_hour[dt.hour] += 1
            by_channel[item.get("channel", 0)] += 1

            # Track recent unique targets
            if item_date == today:
                item["label"] = labels.get(item.get("thumbnail_id"), {}).get("label")
                recent_targets.append(item)

        except:
            continue

    # Sort recent targets by timestamp
    recent_targets.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    # Calculate peak hours
    hour_list = [by_hour.get(h, 0) for h in range(24)]
    peak_hour = hour_list.index(max(hour_list)) if any(hour_list) else None

    # Format response
    return {
        "days_analyzed": days,
        "channel_filter": channel,
        "daily_counts": dict(sorted(by_day.items())),
        "hourly_distribution": hour_list,
        "peak_hour": peak_hour,
        "by_channel": dict(by_channel),
        "total_people": sum(d["person"] for d in by_day.values()),
        "total_vehicles": sum(d["vehicle"] for d in by_day.values()),
        "total_detections": sum(d["total"] for d in by_day.values()),
        "recent_targets": recent_targets[:20],
    }


@router.get("/target/{thumbnail_id}")
async def get_target_detail(thumbnail_id: str):
    """Get detailed information about a specific target."""
    store = get_vector_store()
    labels = load_json(LABELS_PATH, {})
    merges = load_json(MERGES_PATH, {"merged_into": {}, "groups": {}})

    # Get the item
    all_items = store.get_all(limit=10000)
    item = next((i for i in all_items if i.get("thumbnail_id") == thumbnail_id), None)

    if not item:
        raise HTTPException(status_code=404, detail="Target not found")

    # Enrich with label and merge info
    item["label"] = labels.get(thumbnail_id, {}).get("label")
    item["notes"] = labels.get(thumbnail_id, {}).get("notes")
    item["thumbnail_url"] = f"/api/search/thumbnail/{thumbnail_id}"

    # Check merge status
    if thumbnail_id in merges.get("merged_into", {}):
        item["merged_into"] = merges["merged_into"][thumbnail_id]

    if thumbnail_id in merges.get("groups", {}):
        item["merged_items"] = merges["groups"][thumbnail_id]
        item["merged_count"] = len(merges["groups"][thumbnail_id])

    # Get similar targets for reference
    try:
        similar_results = store.search_by_thumbnail(thumbnail_id, k=5)
        item["similar_targets"] = [
            {
                "thumbnail_id": m.get("thumbnail_id"),
                "similarity": round(s, 3),
                "thumbnail_url": f"/api/search/thumbnail/{m.get('thumbnail_id')}",
            }
            for m, s in similar_results if m.get("thumbnail_id") != thumbnail_id
        ]
    except:
        item["similar_targets"] = []

    return item


# =============================================================================
# RECURRING PERSON DETECTION - CRITICAL FOR SAFETY
# =============================================================================

class SuspiciousFlagRequest(BaseModel):
    """Request to flag an individual as suspicious."""
    thumbnail_id: str
    reason: Optional[str] = None
    alert_on_return: bool = True


SUSPICIOUS_PATH = settings.recordings_path / ".cache" / "suspicious.json"


@router.get("/recurring")
async def get_recurring_individuals(
    min_appearances: int = Query(3, description="Minimum appearances to flag"),
    days: int = Query(14, le=90, description="Days to look back"),
    include_labeled: bool = Query(False, description="Include known/labeled people"),
):
    """CRITICAL: Find individuals who appear multiple times.

    A stalker will appear repeatedly. This endpoint identifies:
    - People with 3+ appearances in the time window
    - Unknown individuals (not labeled as neighbor/delivery/etc)
    - Time patterns (same time each day = higher suspicion)

    Returns sorted by suspicion score (most suspicious first).
    """
    store = get_vector_store()
    labels = load_json(LABELS_PATH, {})
    merges = load_json(MERGES_PATH, {"merged_into": {}, "groups": {}})
    suspicious = load_json(SUSPICIOUS_PATH, {"flagged": {}})

    # Get all person detections
    all_items = store.get_all(target_type="person", limit=50000)

    # Calculate date range
    cutoff = datetime.now() - timedelta(days=days)

    # Build identity groups (respecting merges)
    identity_sightings = defaultdict(list)

    for item in all_items:
        ts_str = item.get("timestamp", "")
        if not ts_str:
            continue

        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts < cutoff:
                continue
        except:
            continue

        tid = item.get("thumbnail_id", "")

        # Get primary ID if merged
        primary_id = merges.get("merged_into", {}).get(tid, tid)

        identity_sightings[primary_id].append({
            "timestamp": ts,
            "channel": item.get("channel"),
            "thumbnail_id": tid,
            "confidence": item.get("confidence", 0),
        })

    # Analyze each identity
    recurring = []

    for identity_id, sightings in identity_sightings.items():
        if len(sightings) < min_appearances:
            continue

        # Skip labeled individuals if requested
        label_info = labels.get(identity_id, {})
        if not include_labeled and label_info.get("label"):
            # Unless they're flagged as suspicious
            if identity_id not in suspicious.get("flagged", {}):
                continue

        # Calculate suspicion score
        score, pattern = calculate_suspicion_score(sightings)

        # Count days with appearances
        unique_days = len(set(s["timestamp"].date() for s in sightings))

        # First and last seen
        timestamps = sorted(s["timestamp"] for s in sightings)

        recurring.append({
            "identity_id": identity_id,
            "thumbnail_url": f"/api/search/thumbnail/{identity_id}",
            "total_appearances": len(sightings),
            "unique_days": unique_days,
            "first_seen": timestamps[0].isoformat(),
            "last_seen": timestamps[-1].isoformat(),
            "suspicion_score": score,
            "pattern": pattern,
            "label": label_info.get("label"),
            "is_flagged": identity_id in suspicious.get("flagged", {}),
            "merged_count": len(merges.get("groups", {}).get(identity_id, [])),
            "channels": list(set(s["channel"] for s in sightings if s.get("channel"))),
        })

    # Sort by suspicion score (highest first)
    recurring.sort(key=lambda x: x["suspicion_score"], reverse=True)

    return {
        "days_analyzed": days,
        "min_appearances": min_appearances,
        "total_recurring": len(recurring),
        "flagged_count": len(suspicious.get("flagged", {})),
        "individuals": recurring,
    }


def calculate_suspicion_score(sightings: list) -> tuple[int, dict]:
    """Calculate suspicion score based on appearance patterns.

    Factors:
    - Frequency (more appearances = higher)
    - Time regularity (same time each day = much higher)
    - Duration (appearing over longer period = higher)
    - Unknown status (no label = higher)

    Returns:
        (score 0-100, pattern details)
    """
    score = 0
    pattern = {"factors": []}

    # Factor 1: Frequency (max 30 points)
    count = len(sightings)
    if count >= 10:
        score += 30
        pattern["factors"].append(f"High frequency: {count} appearances")
    elif count >= 5:
        score += 20
        pattern["factors"].append(f"Moderate frequency: {count} appearances")
    else:
        score += 10
        pattern["factors"].append(f"Multiple appearances: {count}")

    # Factor 2: Time regularity (max 40 points) - MOST IMPORTANT
    times = [s["timestamp"].time() for s in sightings]
    if len(times) >= 3:
        # Convert to minutes since midnight for analysis
        minutes = [t.hour * 60 + t.minute for t in times]
        avg_time = mean(minutes)
        time_variance = stdev(minutes) if len(minutes) > 1 else 0

        if time_variance < 30:  # Within 30 minutes
            score += 40
            avg_hour = int(avg_time // 60)
            avg_min = int(avg_time % 60)
            pattern["typical_time"] = f"{avg_hour:02d}:{avg_min:02d}"
            pattern["time_variance_mins"] = round(time_variance, 1)
            pattern["factors"].append(f"REGULAR TIME PATTERN: ~{avg_hour:02d}:{avg_min:02d} (within {time_variance:.0f} min)")
        elif time_variance < 60:
            score += 25
            pattern["factors"].append("Somewhat regular timing")
        elif time_variance < 120:
            score += 10
            pattern["factors"].append("Loosely regular timing")

    # Factor 3: Duration span (max 20 points)
    timestamps = sorted(s["timestamp"] for s in sightings)
    duration = (timestamps[-1] - timestamps[0]).days

    if duration >= 7:
        score += 20
        pattern["factors"].append(f"Appearing over {duration} days")
    elif duration >= 3:
        score += 15
        pattern["factors"].append(f"Appearing over {duration} days")
    elif duration >= 1:
        score += 10

    # Factor 4: Multi-channel (max 10 points)
    channels = set(s["channel"] for s in sightings if s.get("channel"))
    if len(channels) >= 3:
        score += 10
        pattern["factors"].append(f"Seen on {len(channels)} different cameras")
    elif len(channels) >= 2:
        score += 5

    pattern["score_breakdown"] = {
        "frequency": min(30, count * 3),
        "time_regularity": score - min(30, count * 3),
        "duration": min(20, duration * 3),
    }

    return min(100, score), pattern


@router.post("/flag-suspicious")
async def flag_as_suspicious(request: SuspiciousFlagRequest):
    """Flag an individual as suspicious for enhanced monitoring.

    When flagged:
    - Will always appear in recurring list even if labeled
    - Can trigger alerts on future appearances
    - Marked for priority review
    """
    suspicious = load_json(SUSPICIOUS_PATH, {"flagged": {}})

    suspicious["flagged"][request.thumbnail_id] = {
        "reason": request.reason,
        "alert_on_return": request.alert_on_return,
        "flagged_at": datetime.now().isoformat(),
    }

    save_json(SUSPICIOUS_PATH, suspicious)

    # Log for audit trail
    feedback = load_json(FEEDBACK_PATH, {"items": []})
    feedback["items"].append({
        "type": "flag_suspicious",
        "thumbnail_id": request.thumbnail_id,
        "reason": request.reason,
        "timestamp": datetime.now().isoformat(),
    })
    save_json(FEEDBACK_PATH, feedback)

    logger.warning(f"SUSPICIOUS FLAG: {request.thumbnail_id} - {request.reason}")

    return {
        "status": "flagged",
        "thumbnail_id": request.thumbnail_id,
        "alert_on_return": request.alert_on_return,
    }


@router.delete("/flag-suspicious/{thumbnail_id}")
async def unflag_suspicious(thumbnail_id: str):
    """Remove suspicious flag from an individual."""
    suspicious = load_json(SUSPICIOUS_PATH, {"flagged": {}})

    if thumbnail_id in suspicious.get("flagged", {}):
        del suspicious["flagged"][thumbnail_id]
        save_json(SUSPICIOUS_PATH, suspicious)
        return {"status": "unflagged", "thumbnail_id": thumbnail_id}

    raise HTTPException(status_code=404, detail="Not flagged")


@router.get("/flagged")
async def get_flagged_individuals():
    """Get all individuals flagged as suspicious."""
    suspicious = load_json(SUSPICIOUS_PATH, {"flagged": {}})
    labels = load_json(LABELS_PATH, {})

    flagged_list = []
    for tid, info in suspicious.get("flagged", {}).items():
        flagged_list.append({
            "thumbnail_id": tid,
            "thumbnail_url": f"/api/search/thumbnail/{tid}",
            "reason": info.get("reason"),
            "alert_on_return": info.get("alert_on_return", True),
            "flagged_at": info.get("flagged_at"),
            "label": labels.get(tid, {}).get("label"),
        })

    # Sort by flagged date (most recent first)
    flagged_list.sort(key=lambda x: x.get("flagged_at", ""), reverse=True)

    return {
        "total_flagged": len(flagged_list),
        "individuals": flagged_list,
    }


@router.get("/text-search")
async def text_search_targets(
    q: str = Query(..., min_length=2, description="Search query (e.g., 'red jacket', 'tall male')"),
    target_type: Optional[str] = Query(None, description="Filter by type"),
    limit: int = Query(20, le=100),
):
    """Search for targets using natural language description.

    Uses CLIP text embeddings to find visually matching targets.
    Examples: 'person in red jacket', 'white truck', 'man with backpack'
    """
    try:
        from app.ai.embeddings import EmbeddingGenerator
        generator = EmbeddingGenerator()
    except Exception as e:
        logger.warning(f"CLIP not available for text search: {e}")
        raise HTTPException(status_code=503, detail="Text search not available - CLIP not loaded")

    # Generate text embedding
    query_embedding = generator.embed_text(q)

    # Search vector store
    store = get_vector_store()
    results = store.search(
        query_embedding,
        k=limit,
        target_type=target_type,
    )

    labels = load_json(LABELS_PATH, {})

    return {
        "query": q,
        "results": [
            {
                **meta,
                "similarity": round(score, 3),
                "thumbnail_url": f"/api/search/thumbnail/{meta.get('thumbnail_id', '')}",
                "label": labels.get(meta.get("thumbnail_id"), {}).get("label"),
            }
            for meta, score in results
            if score > 0.15  # Filter low similarity
        ],
    }
