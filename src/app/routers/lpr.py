# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""License Plate Recognition (LPR) API endpoints.

Provides plate detection management, watchlist CRUD, detection history,
and plate search. Integrates with YOLO detector plugin for vehicle
detection and target tracker for unified target mapping.

Endpoints:
    POST /api/lpr/detect       — submit a plate detection
    GET  /api/lpr/detections   — recent plate detections
    GET  /api/lpr/search       — search plates by text
    GET  /api/lpr/stats        — LPR pipeline statistics
    POST /api/lpr/watchlist    — add plate to watchlist
    GET  /api/lpr/watchlist    — list watchlist entries
    DELETE /api/lpr/watchlist/{plate} — remove from watchlist
"""

import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_auth

router = APIRouter(prefix="/api/lpr", tags=["lpr"])


# --- In-memory stores (replace with DB in production) ---

_detections: list[dict] = []
_detections_lock = Lock()
_max_detections = 5000

_watchlist: dict[str, dict] = {}  # normalized_plate -> entry dict
_watchlist_lock = Lock()


# --- Request/Response models ---


class PlateDetectionRequest(BaseModel):
    """Submit a plate detection from the LPR pipeline."""

    plate_text: str
    confidence: float = 0.0
    camera_id: str = ""
    vehicle_type: str = ""
    vehicle_color: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    timestamp: float = Field(default_factory=time.time)


class WatchlistAddRequest(BaseModel):
    """Add a plate to the watchlist."""

    plate_text: str
    alert_type: str = "bolo"  # stolen, wanted, bolo, amber_alert, custom
    description: str = ""
    notify: bool = True
    expires_hours: float | None = None  # None = never expires


class PlateDetectionResponse(BaseModel):
    """Response for a plate detection."""

    plate_text: str
    confidence: float
    camera_id: str
    vehicle_type: str
    vehicle_color: str
    target_id: str
    watchlist_hit: bool
    alert_type: str
    timestamp: float


# --- Helpers ---


def _normalize_plate(text: str) -> str:
    """Normalize a plate string for matching."""
    return text.replace(" ", "").replace("-", "").replace(".", "").upper()


def _check_watchlist(plate_text: str) -> dict | None:
    """Check if a plate is on the watchlist."""
    normalized = _normalize_plate(plate_text)
    with _watchlist_lock:
        entry = _watchlist.get(normalized)
        if entry and entry.get("expires_at"):
            if time.time() > entry["expires_at"]:
                del _watchlist[normalized]
                return None
        return entry


# --- Endpoints ---


@router.get("/")
async def get_lpr_root():
    """Root LPR endpoint returning basic stats for the panel.

    The LPR panel calls ``GET /api/lpr/`` to populate its stats bar.
    Returns a ``stats`` dict with total_detections, unique_plates,
    watchlist_hits, and watchlist_size.
    """
    with _detections_lock:
        total = len(_detections)
        plates = set(d["plate_normalized"] for d in _detections)
        watchlist_hits = sum(1 for d in _detections if d["watchlist_hit"])
    with _watchlist_lock:
        wl_size = len(_watchlist)
    return {
        "status": "ok",
        "stats": {
            "total_detections": total,
            "unique_plates": len(plates),
            "watchlist_hits": watchlist_hits,
            "watchlist_size": wl_size,
        },
    }


@router.post("/detect", response_model=PlateDetectionResponse)
async def detect_plate(request: PlateDetectionRequest, _user: dict = Depends(require_auth)):
    """Submit a plate detection from the LPR pipeline.

    Checks against watchlist and stores the detection.
    Requires authentication.
    """
    normalized = _normalize_plate(request.plate_text)
    target_id = f"lpr_{normalized}"

    # Check watchlist
    watchlist_entry = _check_watchlist(request.plate_text)
    watchlist_hit = watchlist_entry is not None
    alert_type = watchlist_entry.get("alert_type", "none") if watchlist_entry else "none"

    # Store detection
    detection = {
        "plate_text": request.plate_text,
        "plate_normalized": normalized,
        "confidence": request.confidence,
        "camera_id": request.camera_id,
        "vehicle_type": request.vehicle_type,
        "vehicle_color": request.vehicle_color,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "target_id": target_id,
        "watchlist_hit": watchlist_hit,
        "alert_type": alert_type,
        "timestamp": request.timestamp,
    }

    with _detections_lock:
        _detections.append(detection)
        if len(_detections) > _max_detections:
            _detections[:] = _detections[-_max_detections:]

    return PlateDetectionResponse(
        plate_text=request.plate_text,
        confidence=request.confidence,
        camera_id=request.camera_id,
        vehicle_type=request.vehicle_type,
        vehicle_color=request.vehicle_color,
        target_id=target_id,
        watchlist_hit=watchlist_hit,
        alert_type=alert_type,
        timestamp=request.timestamp,
    )


@router.get("/detections")
async def get_detections(
    count: int = 50,
    camera_id: str | None = None,
    plate: str | None = None,
):
    """Get recent plate detections with optional filters."""
    with _detections_lock:
        results = list(_detections)

    if camera_id:
        results = [d for d in results if d["camera_id"] == camera_id]
    if plate:
        normalized = _normalize_plate(plate)
        results = [d for d in results if normalized in d["plate_normalized"]]

    return results[-count:]


@router.get("/search")
async def search_plates(q: str, limit: int = 20):
    """Search plate detections by partial plate text."""
    normalized = _normalize_plate(q)
    with _detections_lock:
        results = [
            d for d in _detections
            if normalized in d["plate_normalized"]
        ]
    # Deduplicate by plate
    seen = set()
    unique = []
    for d in reversed(results):
        if d["plate_normalized"] not in seen:
            seen.add(d["plate_normalized"])
            unique.append(d)
            if len(unique) >= limit:
                break
    return unique


@router.get("/stats")
async def get_stats():
    """Get LPR pipeline statistics."""
    with _detections_lock:
        total = len(_detections)
        plates = set(d["plate_normalized"] for d in _detections)
        watchlist_hits = sum(1 for d in _detections if d["watchlist_hit"])
        confidences = [d["confidence"] for d in _detections if d["confidence"] > 0]
        per_camera: dict[str, int] = defaultdict(int)
        for d in _detections:
            if d["camera_id"]:
                per_camera[d["camera_id"]] += 1

    # Top plates by frequency
    plate_counts: dict[str, int] = defaultdict(int)
    with _detections_lock:
        for d in _detections:
            plate_counts[d["plate_normalized"]] += 1
    top_plates = sorted(
        [{"plate": p, "count": c} for p, c in plate_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    return {
        "total_detections": total,
        "unique_plates": len(plates),
        "watchlist_hits": watchlist_hits,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else 0.0,
        "detections_per_camera": dict(per_camera),
        "top_plates": top_plates,
        "last_detection_time": _detections[-1]["timestamp"] if _detections else 0.0,
        "watchlist_size": len(_watchlist),
    }


@router.post("/watchlist")
async def add_to_watchlist(request: WatchlistAddRequest, _user: dict = Depends(require_auth)):
    """Add a plate to the watchlist. Requires authentication."""
    normalized = _normalize_plate(request.plate_text)
    entry = {
        "plate_text": request.plate_text,
        "plate_normalized": normalized,
        "alert_type": request.alert_type,
        "description": request.description,
        "notify": request.notify,
        "added_at": time.time(),
        "expires_at": (
            time.time() + request.expires_hours * 3600
            if request.expires_hours
            else None
        ),
    }
    with _watchlist_lock:
        _watchlist[normalized] = entry
    return {"status": "added", "plate": normalized}


@router.get("/watchlist")
async def get_watchlist(_user: dict = Depends(require_auth)):
    """Get all watchlist entries. Requires authentication."""
    with _watchlist_lock:
        entries = list(_watchlist.values())
    # Filter expired
    now = time.time()
    active = [
        e for e in entries
        if not e.get("expires_at") or e["expires_at"] > now
    ]
    return active


@router.delete("/watchlist/{plate}")
async def remove_from_watchlist(plate: str, _user: dict = Depends(require_auth)):
    """Remove a plate from the watchlist. Requires authentication."""
    normalized = _normalize_plate(plate)
    with _watchlist_lock:
        if normalized in _watchlist:
            del _watchlist[normalized]
            return {"status": "removed", "plate": normalized}
    raise HTTPException(status_code=404, detail=f"Plate {plate} not on watchlist")
