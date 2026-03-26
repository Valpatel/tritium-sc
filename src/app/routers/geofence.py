# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Geofence API — polygon zone CRUD and event retrieval.

Endpoints:
    GET    /api/geofence/zones       — list all geofence zones
    POST   /api/geofence/zones       — create a zone
    DELETE /api/geofence/zones/{id}  — delete a zone
    GET    /api/geofence/events      — list geofence events (enter/exit)
"""

from __future__ import annotations

import html
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.auth import require_auth

from tritium_lib.tracking.geofence import GeoZone, GeofenceEngine

_MAX_NAME_LEN = 200
_MAX_VERTICES = 1000
_MAX_ZONES = 500
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _sanitize(value: str, max_len: int) -> str:
    """Strip HTML tags, escape, and enforce length limit."""
    value = _HTML_TAG_RE.sub("", value)
    value = html.escape(value)
    return value[:max_len]

router = APIRouter(prefix="/api/geofence", tags=["geofence"])

# Module-level singleton; initialized on first access or externally via set_engine()
_engine: GeofenceEngine | None = None


def get_engine() -> GeofenceEngine:
    """Get or create the singleton GeofenceEngine."""
    global _engine
    if _engine is None:
        _engine = GeofenceEngine()
    return _engine


def set_engine(engine: GeofenceEngine) -> None:
    """Set the GeofenceEngine instance (for wiring EventBus at boot)."""
    global _engine
    _engine = engine


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------

class CreateGeoZoneRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=_MAX_NAME_LEN)
    polygon: list[list[float]] = Field(...)  # [[x1,y1], [x2,y2], ...]
    zone_type: str = "monitored"  # "restricted", "monitored", "safe"
    alert_on_enter: bool = True
    alert_on_exit: bool = True

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        return _sanitize(v, _MAX_NAME_LEN)

    @field_validator("polygon")
    @classmethod
    def validate_polygon(cls, v):
        if len(v) > _MAX_VERTICES:
            raise ValueError(f"Too many vertices (max {_MAX_VERTICES})")
        return v


class GeoZoneResponse(BaseModel):
    zone_id: str
    name: str
    polygon: list[list[float]]
    zone_type: str
    alert_on_enter: bool
    alert_on_exit: bool
    enabled: bool
    created_at: float


class GeoEventResponse(BaseModel):
    event_id: str
    event_type: str
    target_id: str
    zone_id: str
    zone_name: str
    zone_type: str
    position: list[float]
    timestamp: float


# ------------------------------------------------------------------
# Zone CRUD
# ------------------------------------------------------------------

@router.get("/zones", response_model=list[GeoZoneResponse])
async def list_zones():
    """List all geofence zones."""
    engine = get_engine()
    return [_zone_response(z) for z in engine.list_zones()]


@router.post("/zones", response_model=GeoZoneResponse, status_code=201)
async def create_zone(request: CreateGeoZoneRequest, _user: dict = Depends(require_auth)):
    """Create a new geofence zone."""
    if len(request.polygon) < 3:
        raise HTTPException(status_code=400, detail="Polygon must have at least 3 vertices")

    engine = get_engine()
    if len(engine.list_zones()) >= _MAX_ZONES:
        raise HTTPException(status_code=429, detail=f"Zone limit reached ({_MAX_ZONES})")

    valid_types = ("restricted", "monitored", "safe")
    if request.zone_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"zone_type must be one of: {valid_types}",
        )

    import uuid
    zone = GeoZone(
        zone_id=uuid.uuid4().hex[:12],
        name=request.name,
        polygon=[tuple(p) for p in request.polygon],
        zone_type=request.zone_type,
        alert_on_enter=request.alert_on_enter,
        alert_on_exit=request.alert_on_exit,
    )

    engine.add_zone(zone)
    return _zone_response(zone)


class UpdateGeoZoneRequest(BaseModel):
    """Request to update a geofence zone."""
    name: Optional[str] = Field(None, min_length=1, max_length=_MAX_NAME_LEN)
    zone_type: Optional[str] = None
    alert_on_enter: Optional[bool] = None
    alert_on_exit: Optional[bool] = None
    enabled: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _sanitize(v, _MAX_NAME_LEN)


@router.put("/zones/{zone_id}", response_model=GeoZoneResponse)
async def update_zone(zone_id: str, request: UpdateGeoZoneRequest, _user: dict = Depends(require_auth)):
    """Update a geofence zone's properties."""
    engine = get_engine()
    zone = engine.get_zone(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")

    valid_types = ("restricted", "monitored", "safe")
    updates = request.model_dump(exclude_unset=True)

    if "zone_type" in updates and updates["zone_type"] not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"zone_type must be one of: {valid_types}",
        )

    for key, value in updates.items():
        if hasattr(zone, key):
            setattr(zone, key, value)

    # Re-add to engine (dict replacement ensures consistency)
    engine.add_zone(zone)
    return _zone_response(zone)


@router.get("/zones/{zone_id}/occupants")
async def get_zone_occupants(zone_id: str):
    """Return target IDs currently inside a zone."""
    engine = get_engine()
    zone = engine.get_zone(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    occupants = engine.get_zone_occupants(zone_id)
    return {
        "zone_id": zone_id,
        "zone_name": zone.name,
        "zone_type": zone.zone_type,
        "occupant_count": len(occupants),
        "occupants": occupants,
    }


@router.get("/occupancy")
async def get_all_occupancy():
    """Return occupancy counts for all zones (zone_id -> count)."""
    engine = get_engine()
    result = {}
    for zone in engine.list_zones():
        occupants = engine.get_zone_occupants(zone.zone_id)
        result[zone.zone_id] = len(occupants)
    return result


@router.delete("/zones/{zone_id}")
async def delete_zone(zone_id: str, _user: dict = Depends(require_auth)):
    """Delete a geofence zone."""
    engine = get_engine()
    if not engine.remove_zone(zone_id):
        raise HTTPException(status_code=404, detail="Zone not found")
    return {"status": "deleted", "zone_id": zone_id}


# ------------------------------------------------------------------
# Events
# ------------------------------------------------------------------

@router.get("/events", response_model=list[GeoEventResponse])
async def list_events(
    limit: int = Query(100, le=1000),
    zone_id: Optional[str] = Query(None),
    target_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None, description="enter, exit, or inside"),
):
    """List recent geofence events (enter/exit transitions)."""
    engine = get_engine()
    events = engine.get_events(
        limit=limit,
        zone_id=zone_id,
        target_id=target_id,
        event_type=event_type,
    )
    return [_event_response(e) for e in events]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _zone_response(zone: GeoZone) -> GeoZoneResponse:
    return GeoZoneResponse(
        zone_id=zone.zone_id,
        name=zone.name,
        polygon=[list(p) for p in zone.polygon],
        zone_type=zone.zone_type,
        alert_on_enter=zone.alert_on_enter,
        alert_on_exit=zone.alert_on_exit,
        enabled=zone.enabled,
        created_at=zone.created_at,
    )


def _event_response(e) -> GeoEventResponse:
    return GeoEventResponse(
        event_id=e.event_id,
        event_type=e.event_type,
        target_id=e.target_id,
        zone_id=e.zone_id,
        zone_name=e.zone_name,
        zone_type=e.zone_type,
        position=list(e.position),
        timestamp=e.timestamp,
    )
