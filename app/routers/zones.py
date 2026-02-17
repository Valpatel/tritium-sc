"""Zone management API endpoints."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from loguru import logger

from app.config import settings
from app.zones.manager import ZoneManager
from app.zones.models import ZoneType, ZoneEventType

router = APIRouter(prefix="/api/zones", tags=["zones"])

# Initialize zone manager
_zone_manager: Optional[ZoneManager] = None


def get_zone_manager() -> ZoneManager:
    """Get or create zone manager singleton."""
    global _zone_manager
    if _zone_manager is None:
        # Use recordings path if available, fall back to local data dir
        if settings.recordings_path.exists():
            storage_path = settings.recordings_path / ".cache" / "zones"
        else:
            storage_path = Path(__file__).parent.parent.parent / "data" / "zones"
        _zone_manager = ZoneManager(storage_path)
    return _zone_manager


# ==================
# Request/Response Models
# ==================

class CreateZoneRequest(BaseModel):
    """Request to create a zone."""
    camera_id: int
    name: str
    polygon: list[list[int]]  # [[x1,y1], [x2,y2], ...]
    zone_type: str  # entry_exit, activity, tripwire, object_monitor
    monitored_object: Optional[str] = None
    alert_on_enter: bool = True
    alert_on_exit: bool = False
    alert_on_linger: bool = False
    linger_threshold_seconds: int = 60
    cooldown_seconds: int = 30


class UpdateZoneRequest(BaseModel):
    """Request to update a zone."""
    name: Optional[str] = None
    polygon: Optional[list[list[int]]] = None
    enabled: Optional[bool] = None
    monitored_object: Optional[str] = None
    alert_on_enter: Optional[bool] = None
    alert_on_exit: Optional[bool] = None
    alert_on_linger: Optional[bool] = None
    linger_threshold_seconds: Optional[int] = None
    cooldown_seconds: Optional[int] = None


class ZoneResponse(BaseModel):
    """Zone response model."""
    zone_id: str
    camera_id: int
    name: str
    polygon: list[list[int]]
    zone_type: str
    enabled: bool
    created_at: str
    monitored_object: Optional[str]
    total_events: int
    last_event_at: Optional[str]


class ZoneEventResponse(BaseModel):
    """Zone event response model."""
    event_id: str
    zone_id: str
    zone_name: str
    event_type: str
    timestamp: str
    camera_id: int
    target_type: Optional[str]
    target_thumbnail_id: Optional[str]
    video_path: Optional[str]
    frame_number: Optional[int]


# ==================
# Zone CRUD Endpoints
# ==================

@router.post("/", response_model=ZoneResponse)
async def create_zone(request: CreateZoneRequest):
    """Create a new monitoring zone."""
    manager = get_zone_manager()

    try:
        zone_type = ZoneType(request.zone_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid zone_type. Must be one of: {[t.value for t in ZoneType]}"
        )

    # Convert polygon format
    polygon = [tuple(p) for p in request.polygon]

    if len(polygon) < 3:
        raise HTTPException(status_code=400, detail="Polygon must have at least 3 points")

    zone = manager.create_zone(
        camera_id=request.camera_id,
        name=request.name,
        polygon=polygon,
        zone_type=zone_type,
        monitored_object=request.monitored_object,
        alert_on_enter=request.alert_on_enter,
        alert_on_exit=request.alert_on_exit,
        alert_on_linger=request.alert_on_linger,
        linger_threshold_seconds=request.linger_threshold_seconds,
        cooldown_seconds=request.cooldown_seconds,
    )

    return _zone_to_response(zone)


@router.get("/", response_model=list[ZoneResponse])
async def list_zones(camera_id: Optional[int] = Query(None)):
    """List all zones, optionally filtered by camera."""
    manager = get_zone_manager()

    if camera_id is not None:
        zones = manager.get_zones_for_camera(camera_id)
    else:
        zones = manager.get_all_zones()

    return [_zone_to_response(z) for z in zones]


@router.get("/{zone_id}", response_model=ZoneResponse)
async def get_zone(zone_id: str):
    """Get a specific zone."""
    manager = get_zone_manager()
    zone = manager.get_zone(zone_id)

    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    return _zone_to_response(zone)


@router.put("/{zone_id}", response_model=ZoneResponse)
async def update_zone(zone_id: str, request: UpdateZoneRequest):
    """Update a zone."""
    manager = get_zone_manager()

    updates = request.dict(exclude_unset=True)

    # Convert polygon if provided
    if "polygon" in updates and updates["polygon"]:
        updates["polygon"] = [tuple(p) for p in updates["polygon"]]

    zone = manager.update_zone(zone_id, **updates)

    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    return _zone_to_response(zone)


@router.delete("/{zone_id}")
async def delete_zone(zone_id: str):
    """Delete a zone."""
    manager = get_zone_manager()
    success = manager.delete_zone(zone_id)

    if not success:
        raise HTTPException(status_code=404, detail="Zone not found")

    return {"status": "deleted", "zone_id": zone_id}


# ==================
# Zone Events
# ==================

@router.get("/{zone_id}/events", response_model=list[ZoneEventResponse])
async def get_zone_events(
    zone_id: str,
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
):
    """Get events for a zone."""
    manager = get_zone_manager()

    zone = manager.get_zone(zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    events = manager.get_events_for_zone(
        zone_id,
        limit=limit,
        offset=offset,
        date_from=date_from,
        date_to=date_to,
    )

    return [_event_to_response(e) for e in events]


@router.get("/{zone_id}/summary")
async def get_zone_summary(zone_id: str):
    """Get activity summary for a zone.

    Returns event counts, hourly distribution, recent events, etc.
    Perfect for answering "how many times was the dumpster opened today?"
    """
    manager = get_zone_manager()
    summary = manager.get_zone_summary(zone_id)

    if not summary:
        raise HTTPException(status_code=404, detail="Zone not found")

    return summary


@router.get("/events/by-target")
async def get_events_by_target(
    target_type: Optional[str] = Query(None, description="person, vehicle, etc."),
    zone_id: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
):
    """Get zone events filtered by target type.

    Useful for "show me all people who entered any zone" queries.
    """
    manager = get_zone_manager()
    events = manager.get_events_by_target(
        target_type=target_type,
        zone_id=zone_id,
        limit=limit,
    )

    return [_event_to_response(e) for e in events]


# ==================
# Camera Frame Check
# ==================

@router.post("/check-frame/{camera_id}")
async def check_frame_zones(
    camera_id: int,
    detections: list[dict],
    timestamp: str,
    video_path: str,
    frame_number: int,
):
    """Check if detections in a frame trigger any zone events.

    Called during video analysis to detect zone activity.
    """
    manager = get_zone_manager()

    ts = datetime.fromisoformat(timestamp)

    events = manager.check_detections(
        camera_id=camera_id,
        detections=detections,
        timestamp=ts,
        video_path=video_path,
        frame_number=frame_number,
    )

    return {
        "triggered_events": len(events),
        "events": [_event_to_response(e) for e in events],
    }


# ==================
# Helpers
# ==================

def _zone_to_response(zone) -> ZoneResponse:
    return ZoneResponse(
        zone_id=zone.zone_id,
        camera_id=zone.camera_id,
        name=zone.name,
        polygon=[list(p) for p in zone.polygon],
        zone_type=zone.zone_type.value,
        enabled=zone.enabled,
        created_at=zone.created_at.isoformat(),
        monitored_object=zone.monitored_object,
        total_events=zone.total_events,
        last_event_at=zone.last_event_at.isoformat() if zone.last_event_at else None,
    )


def _event_to_response(event) -> ZoneEventResponse:
    return ZoneEventResponse(
        event_id=event.event_id,
        zone_id=event.zone_id,
        zone_name=event.zone_name,
        event_type=event.event_type.value,
        timestamp=event.timestamp.isoformat(),
        camera_id=event.camera_id,
        target_type=event.target_type,
        target_thumbnail_id=event.target_thumbnail_id,
        video_path=event.video_path,
        frame_number=event.frame_number,
    )
