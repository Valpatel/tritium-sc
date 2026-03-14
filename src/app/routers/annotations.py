# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Map annotation system — persist text labels, arrows, circles, and freehand
drawings on the tactical map for briefings and operational planning.

Annotations are stored in-memory (reset on server restart). Each annotation
has a type, position, style, and optional metadata.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import html
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix="/api/annotations", tags=["annotations"])

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
_MAX_TEXT_LEN = 2000
_MAX_LABEL_LEN = 200
_MAX_LAYER_LEN = 100
_MAX_COLOR_LEN = 20
_MAX_POINTS = 5000
_MAX_ANNOTATIONS = 10000
_VALID_TYPES = {"text", "arrow", "circle", "freehand", "rectangle", "polygon"}

# Strip HTML/script tags — defence-in-depth against XSS
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _sanitize(value: str, max_len: int) -> str:
    """Strip HTML tags and enforce length limit."""
    value = _HTML_TAG_RE.sub("", value)
    value = html.escape(value)
    return value[:max_len]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AnnotationCreate(BaseModel):
    """Create a new map annotation."""
    type: str = Field(..., description="text | arrow | circle | freehand | rectangle | polygon")
    lat: float = Field(..., ge=-90, le=90, description="Latitude of annotation anchor")
    lng: float = Field(..., ge=-180, le=180, description="Longitude of annotation anchor")
    # Text content (for text annotations)
    text: str = Field(default="", max_length=_MAX_TEXT_LEN)
    # Geometry (type-specific)
    end_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    end_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_m: Optional[float] = Field(default=None, ge=0, le=100_000)
    points: Optional[list[list[float]]] = None  # freehand/polygon: [[lat,lng], ...]
    width: Optional[float] = Field(default=None, ge=0, le=100_000)
    height: Optional[float] = Field(default=None, ge=0, le=100_000)
    # Style
    color: str = Field(default="#00f0ff", max_length=_MAX_COLOR_LEN)
    stroke_width: float = Field(default=2.0, ge=0.1, le=50)
    font_size: float = Field(default=14.0, ge=1, le=200)
    opacity: float = Field(default=0.8, ge=0, le=1)
    fill: bool = False
    fill_opacity: float = Field(default=0.2, ge=0, le=1)
    # Metadata
    label: str = Field(default="", max_length=_MAX_LABEL_LEN)
    layer: str = Field(default="default", max_length=_MAX_LAYER_LEN)
    locked: bool = False

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in _VALID_TYPES:
            raise ValueError(f"type must be one of {_VALID_TYPES}")
        return v

    @field_validator("points")
    @classmethod
    def validate_points(cls, v):
        if v is not None and len(v) > _MAX_POINTS:
            raise ValueError(f"points list exceeds maximum of {_MAX_POINTS}")
        return v

    @field_validator("text", "label", "layer", "color")
    @classmethod
    def sanitize_strings(cls, v: str) -> str:
        return _sanitize(v, _MAX_TEXT_LEN)


class AnnotationUpdate(BaseModel):
    """Partial update for an annotation."""
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    text: Optional[str] = Field(default=None, max_length=_MAX_TEXT_LEN)
    end_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    end_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_m: Optional[float] = Field(default=None, ge=0, le=100_000)
    points: Optional[list[list[float]]] = None
    width: Optional[float] = Field(default=None, ge=0, le=100_000)
    height: Optional[float] = Field(default=None, ge=0, le=100_000)
    color: Optional[str] = Field(default=None, max_length=_MAX_COLOR_LEN)
    stroke_width: Optional[float] = Field(default=None, ge=0.1, le=50)
    font_size: Optional[float] = Field(default=None, ge=1, le=200)
    opacity: Optional[float] = Field(default=None, ge=0, le=1)
    fill: Optional[bool] = None
    fill_opacity: Optional[float] = Field(default=None, ge=0, le=1)
    label: Optional[str] = Field(default=None, max_length=_MAX_LABEL_LEN)
    layer: Optional[str] = Field(default=None, max_length=_MAX_LAYER_LEN)
    locked: Optional[bool] = None

    @field_validator("text", "label", "layer", "color")
    @classmethod
    def sanitize_strings(cls, v):
        if v is not None:
            return _sanitize(v, _MAX_TEXT_LEN)
        return v

    @field_validator("points")
    @classmethod
    def validate_points(cls, v):
        if v is not None and len(v) > _MAX_POINTS:
            raise ValueError(f"points list exceeds maximum of {_MAX_POINTS}")
        return v


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_annotations: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_annotations(layer: Optional[str] = None):
    """List all map annotations, optionally filtered by layer."""
    items = list(_annotations.values())
    if layer:
        items = [a for a in items if a.get("layer") == layer]
    return {
        "annotations": sorted(items, key=lambda a: a.get("created_at", 0)),
        "count": len(items),
    }


@router.post("")
async def create_annotation(body: AnnotationCreate):
    """Create a new map annotation."""
    if len(_annotations) >= _MAX_ANNOTATIONS:
        raise HTTPException(
            status_code=429,
            detail=f"Annotation limit reached ({_MAX_ANNOTATIONS})",
        )
    now = time.time()
    ann_id = f"ann_{uuid.uuid4().hex[:8]}"
    annotation = {
        "id": ann_id,
        "type": body.type,
        "lat": body.lat,
        "lng": body.lng,
        "text": body.text,
        "end_lat": body.end_lat,
        "end_lng": body.end_lng,
        "radius_m": body.radius_m,
        "points": body.points,
        "width": body.width,
        "height": body.height,
        "color": body.color,
        "stroke_width": body.stroke_width,
        "font_size": body.font_size,
        "opacity": body.opacity,
        "fill": body.fill,
        "fill_opacity": body.fill_opacity,
        "label": body.label,
        "layer": body.layer,
        "locked": body.locked,
        "created_at": now,
        "updated_at": now,
    }
    _annotations[ann_id] = annotation
    return annotation


@router.get("/{annotation_id}")
async def get_annotation(annotation_id: str):
    """Get a single annotation by ID."""
    ann = _annotations.get(annotation_id)
    if ann is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return ann


@router.put("/{annotation_id}")
async def update_annotation(annotation_id: str, body: AnnotationUpdate):
    """Update an existing annotation."""
    ann = _annotations.get(annotation_id)
    if ann is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    if ann.get("locked"):
        raise HTTPException(status_code=403, detail="Annotation is locked")

    updates = body.model_dump(exclude_none=True)
    if updates:
        ann.update(updates)
        ann["updated_at"] = time.time()

    return ann


@router.delete("/{annotation_id}")
async def delete_annotation(annotation_id: str):
    """Delete an annotation."""
    if annotation_id not in _annotations:
        raise HTTPException(status_code=404, detail="Annotation not found")
    del _annotations[annotation_id]
    return {"ok": True, "deleted": annotation_id}


@router.delete("")
async def clear_annotations(layer: Optional[str] = None):
    """Clear all annotations, optionally filtered by layer."""
    if layer:
        to_delete = [k for k, v in _annotations.items() if v.get("layer") == layer]
    else:
        to_delete = list(_annotations.keys())
    for k in to_delete:
        del _annotations[k]
    return {"ok": True, "deleted_count": len(to_delete)}


@router.get("/layers/list")
async def list_layers():
    """List all annotation layers."""
    layers = set()
    for ann in _annotations.values():
        layers.add(ann.get("layer", "default"))
    return {"layers": sorted(layers)}
