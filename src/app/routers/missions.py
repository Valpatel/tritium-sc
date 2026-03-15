# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Mission management API — CRUD for coordinated multi-asset operations.

Endpoints:
    GET    /api/missions              — list missions (filter by status/type)
    POST   /api/missions              — create a mission
    GET    /api/missions/{id}         — get mission details
    PUT    /api/missions/{id}         — update a mission
    DELETE /api/missions/{id}         — delete a mission
    POST   /api/missions/{id}/start   — transition to active
    POST   /api/missions/{id}/pause   — pause an active mission
    POST   /api/missions/{id}/complete — mark completed
    POST   /api/missions/{id}/abort   — abort the mission
    POST   /api/missions/{id}/objectives/{oid}/complete — complete an objective
"""

from __future__ import annotations

import html
import re
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from tritium_lib.models.mission import (
    GeofenceZone,
    Mission,
    MissionObjective,
    MissionStatus,
    MissionType,
)

router = APIRouter(prefix="/api/missions", tags=["missions"])

_MAX_MISSIONS = 1000
_MAX_TEXT_LEN = 5000
_MAX_TITLE_LEN = 200
_MAX_TAG_LEN = 100
_MAX_TAGS = 50
_MAX_ASSETS = 200
_MAX_OBJECTIVES = 100
_MAX_VERTICES = 1000
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _sanitize(value: str, max_len: int) -> str:
    """Strip HTML tags, escape, and enforce length limit."""
    value = _HTML_TAG_RE.sub("", value)
    value = html.escape(value)
    return value[:max_len]


# In-memory store — keyed by mission_id
_missions: dict[str, Mission] = {}


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------

class ObjectiveRequest(BaseModel):
    description: str = Field(default="", max_length=_MAX_TEXT_LEN)
    priority: int = Field(default=1, ge=1, le=10)

    @field_validator("description")
    @classmethod
    def sanitize_desc(cls, v: str) -> str:
        return _sanitize(v, _MAX_TEXT_LEN)


class GeofenceZoneRequest(BaseModel):
    name: str = Field(default="", max_length=_MAX_TITLE_LEN)
    vertices: list[list[float]] = Field(default_factory=list)
    center_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    center_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_m: Optional[float] = Field(default=None, ge=0, le=1_000_000)

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        return _sanitize(v, _MAX_TITLE_LEN)

    @field_validator("vertices")
    @classmethod
    def validate_vertices(cls, v):
        if len(v) > _MAX_VERTICES:
            raise ValueError(f"Too many vertices (max {_MAX_VERTICES})")
        return v


class CreateMissionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=_MAX_TITLE_LEN)
    type: str = "custom"
    description: str = Field(default="", max_length=_MAX_TEXT_LEN)
    assigned_assets: list[str] = Field(default_factory=list)
    objectives: list[ObjectiveRequest] = Field(default_factory=list)
    geofence_zone: Optional[GeofenceZoneRequest] = None
    priority: int = Field(default=3, ge=1, le=10)
    tags: list[str] = Field(default_factory=list)
    created_by: str = Field(default="", max_length=_MAX_TITLE_LEN)

    @field_validator("title", "description", "created_by")
    @classmethod
    def sanitize_strings(cls, v: str) -> str:
        return _sanitize(v, _MAX_TEXT_LEN)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        if len(v) > _MAX_TAGS:
            raise ValueError(f"Too many tags (max {_MAX_TAGS})")
        return [_sanitize(t, _MAX_TAG_LEN) for t in v]

    @field_validator("assigned_assets")
    @classmethod
    def validate_assets(cls, v: list[str]) -> list[str]:
        if len(v) > _MAX_ASSETS:
            raise ValueError(f"Too many assets (max {_MAX_ASSETS})")
        return [_sanitize(a, _MAX_TITLE_LEN) for a in v]

    @field_validator("objectives")
    @classmethod
    def validate_objectives(cls, v):
        if len(v) > _MAX_OBJECTIVES:
            raise ValueError(f"Too many objectives (max {_MAX_OBJECTIVES})")
        return v


class UpdateMissionRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=_MAX_TITLE_LEN)
    description: Optional[str] = Field(default=None, max_length=_MAX_TEXT_LEN)
    assigned_assets: Optional[list[str]] = None
    objectives: Optional[list[ObjectiveRequest]] = None
    geofence_zone: Optional[GeofenceZoneRequest] = None
    priority: Optional[int] = Field(default=None, ge=1, le=10)
    tags: Optional[list[str]] = None

    @field_validator("title", "description")
    @classmethod
    def sanitize_strings(cls, v):
        if v is not None:
            return _sanitize(v, _MAX_TEXT_LEN)
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v):
        if v is not None:
            if len(v) > _MAX_TAGS:
                raise ValueError(f"Too many tags (max {_MAX_TAGS})")
            return [_sanitize(t, _MAX_TAG_LEN) for t in v]
        return v

    @field_validator("assigned_assets")
    @classmethod
    def validate_assets(cls, v):
        if v is not None:
            if len(v) > _MAX_ASSETS:
                raise ValueError(f"Too many assets (max {_MAX_ASSETS})")
            return [_sanitize(a, _MAX_TITLE_LEN) for a in v]
        return v

    @field_validator("objectives")
    @classmethod
    def validate_objectives(cls, v):
        if v is not None and len(v) > _MAX_OBJECTIVES:
            raise ValueError(f"Too many objectives (max {_MAX_OBJECTIVES})")
        return v


class AbortRequest(BaseModel):
    reason: str = Field(default="", max_length=_MAX_TEXT_LEN)

    @field_validator("reason")
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        return _sanitize(v, _MAX_TEXT_LEN)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _validate_type(type_str: str) -> MissionType:
    try:
        return MissionType(type_str)
    except ValueError:
        valid = [t.value for t in MissionType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mission type '{type_str}'. Valid: {valid}",
        )


def _build_geofence(gz: GeofenceZoneRequest) -> GeofenceZone:
    return GeofenceZone(
        zone_id=uuid.uuid4().hex[:12],
        name=gz.name,
        vertices=[tuple(v) for v in gz.vertices],
        center_lat=gz.center_lat,
        center_lng=gz.center_lng,
        radius_m=gz.radius_m,
    )


def _get_mission(mission_id: str) -> Mission:
    m = _missions.get(mission_id)
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    return m


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("")
async def list_missions(
    status: Optional[str] = Query(None),
    mission_type: Optional[str] = Query(None, alias="type"),
    limit: int = Query(100, le=500),
):
    """List missions, newest first."""
    missions = sorted(_missions.values(), key=lambda m: m.created, reverse=True)

    if status:
        try:
            s = MissionStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status '{status}'")
        missions = [m for m in missions if m.status == s]

    if mission_type:
        t = _validate_type(mission_type)
        missions = [m for m in missions if m.type == t]

    return [m.to_dict() for m in missions[:limit]]


@router.post("", status_code=201)
async def create_mission(request: CreateMissionRequest):
    """Create a new mission."""
    if len(_missions) >= _MAX_MISSIONS:
        raise HTTPException(status_code=429, detail=f"Mission limit reached ({_MAX_MISSIONS})")
    mt = _validate_type(request.type)

    objectives = [
        MissionObjective(description=o.description, priority=o.priority)
        for o in request.objectives
    ]

    gz = _build_geofence(request.geofence_zone) if request.geofence_zone else None

    mission = Mission(
        title=request.title,
        type=mt,
        description=request.description,
        assigned_assets=request.assigned_assets,
        objectives=objectives,
        geofence_zone=gz,
        priority=request.priority,
        tags=request.tags,
        created_by=request.created_by,
    )

    _missions[mission.mission_id] = mission
    return mission.to_dict()


@router.get("/{mission_id}")
async def get_mission(mission_id: str):
    """Get mission details."""
    return _get_mission(mission_id).to_dict()


@router.put("/{mission_id}")
async def update_mission(mission_id: str, request: UpdateMissionRequest):
    """Update mission fields (only modifiable in non-terminal states)."""
    m = _get_mission(mission_id)
    if m.is_terminal:
        raise HTTPException(status_code=409, detail="Cannot modify a terminal mission")

    if request.title is not None:
        m.title = request.title
    if request.description is not None:
        m.description = request.description
    if request.assigned_assets is not None:
        m.assigned_assets = request.assigned_assets
    if request.objectives is not None:
        m.objectives = [
            MissionObjective(description=o.description, priority=o.priority)
            for o in request.objectives
        ]
    if request.geofence_zone is not None:
        m.geofence_zone = _build_geofence(request.geofence_zone)
    if request.priority is not None:
        m.priority = request.priority
    if request.tags is not None:
        m.tags = request.tags

    return m.to_dict()


@router.delete("/{mission_id}")
async def delete_mission(mission_id: str):
    """Delete a mission."""
    if mission_id not in _missions:
        raise HTTPException(status_code=404, detail="Mission not found")
    del _missions[mission_id]
    return {"status": "deleted", "mission_id": mission_id}


@router.post("/{mission_id}/start")
async def start_mission(mission_id: str):
    """Transition mission to active status."""
    m = _get_mission(mission_id)
    if m.status not in (MissionStatus.DRAFT, MissionStatus.PLANNED, MissionStatus.PAUSED):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot start mission in status '{m.status.value}'",
        )
    m.start()
    return m.to_dict()


@router.post("/{mission_id}/pause")
async def pause_mission(mission_id: str):
    """Pause an active mission."""
    m = _get_mission(mission_id)
    if m.status != MissionStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Can only pause active missions")
    m.pause()
    return m.to_dict()


@router.post("/{mission_id}/complete")
async def complete_mission(mission_id: str):
    """Mark mission as completed."""
    m = _get_mission(mission_id)
    if m.status not in (MissionStatus.ACTIVE, MissionStatus.PAUSED):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot complete mission in status '{m.status.value}'",
        )
    m.complete()
    return m.to_dict()


@router.post("/{mission_id}/abort")
async def abort_mission(mission_id: str, request: AbortRequest):
    """Abort a mission."""
    m = _get_mission(mission_id)
    if m.is_terminal:
        raise HTTPException(status_code=409, detail="Mission is already in a terminal state")
    m.abort(request.reason)
    return m.to_dict()


@router.post("/{mission_id}/objectives/{objective_id}/complete")
async def complete_objective(mission_id: str, objective_id: str):
    """Mark a specific objective as completed."""
    m = _get_mission(mission_id)
    if not m.complete_objective(objective_id):
        raise HTTPException(status_code=404, detail="Objective not found")
    return m.to_dict()


@router.get("/{mission_id}/targets")
async def get_mission_targets(mission_id: str):
    """Get targets bound to this mission (inside geofence zone).

    Returns a list of target IDs detected within the mission's
    geofence zone. Targets are auto-bound by the MissionTargetBinder
    when they are inside an active mission's area of operations.
    """
    _get_mission(mission_id)  # Validate mission exists
    try:
        from engine.tactical.mission_target_binder import _binder
        if _binder is not None:
            targets = _binder.get_mission_targets(mission_id)
            return {"mission_id": mission_id, "targets": targets, "count": len(targets)}
    except (ImportError, AttributeError):
        pass
    return {"mission_id": mission_id, "targets": [], "count": 0}


@router.post("/{mission_id}/targets/{target_id}")
async def bind_target_to_mission(mission_id: str, target_id: str):
    """Manually bind a target to a mission."""
    _get_mission(mission_id)  # Validate mission exists
    try:
        from engine.tactical.mission_target_binder import _binder
        if _binder is not None:
            was_new = _binder.bind_target_manually(mission_id, target_id)
            return {"bound": True, "was_new": was_new, "target_id": target_id}
    except (ImportError, AttributeError):
        pass
    raise HTTPException(status_code=503, detail="MissionTargetBinder not available")


@router.delete("/{mission_id}/targets/{target_id}")
async def unbind_target_from_mission(mission_id: str, target_id: str):
    """Remove a target binding from a mission."""
    _get_mission(mission_id)  # Validate mission exists
    try:
        from engine.tactical.mission_target_binder import _binder
        if _binder is not None:
            removed = _binder.unbind_target(mission_id, target_id)
            return {"unbound": removed, "target_id": target_id}
    except (ImportError, AttributeError):
        pass
    raise HTTPException(status_code=503, detail="MissionTargetBinder not available")
