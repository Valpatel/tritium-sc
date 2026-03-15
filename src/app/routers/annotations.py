# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Map annotation system — persist text labels, arrows, circles, and freehand
drawings on the tactical map for briefings and operational planning.

Annotations are persisted in SQLite so they survive server restarts.
Supports import/export as GeoJSON.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Optional

import html
import re

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
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
# SQLite persistence
# ---------------------------------------------------------------------------

_DB_PATH: str | None = None
_db_initialized = False

_COLUMNS = [
    "id", "type", "lat", "lng", "text", "end_lat", "end_lng",
    "radius_m", "points", "width", "height", "color", "stroke_width",
    "font_size", "opacity", "fill", "fill_opacity", "label", "layer",
    "locked", "created_at", "updated_at",
]


def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        data_dir = os.environ.get("TRITIUM_DATA_DIR", "data")
        os.makedirs(data_dir, exist_ok=True)
        _DB_PATH = os.path.join(data_dir, "annotations.db")
    return _DB_PATH


def _ensure_db():
    global _db_initialized
    if _db_initialized:
        return
    conn = sqlite3.connect(_get_db_path())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS annotations (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            text TEXT DEFAULT '',
            end_lat REAL,
            end_lng REAL,
            radius_m REAL,
            points TEXT,
            width REAL,
            height REAL,
            color TEXT DEFAULT '#00f0ff',
            stroke_width REAL DEFAULT 2.0,
            font_size REAL DEFAULT 14.0,
            opacity REAL DEFAULT 0.8,
            fill INTEGER DEFAULT 0,
            fill_opacity REAL DEFAULT 0.2,
            label TEXT DEFAULT '',
            layer TEXT DEFAULT 'default',
            locked INTEGER DEFAULT 0,
            created_at REAL,
            updated_at REAL
        )
    """)
    conn.commit()
    conn.close()
    _db_initialized = True


def _row_to_dict(row) -> dict:
    """Convert a sqlite row tuple to annotation dict."""
    return {
        "id": row[0],
        "type": row[1],
        "lat": row[2],
        "lng": row[3],
        "text": row[4],
        "end_lat": row[5],
        "end_lng": row[6],
        "radius_m": row[7],
        "points": json.loads(row[8]) if row[8] else None,
        "width": row[9],
        "height": row[10],
        "color": row[11],
        "stroke_width": row[12],
        "font_size": row[13],
        "opacity": row[14],
        "fill": bool(row[15]),
        "fill_opacity": row[16],
        "label": row[17],
        "layer": row[18],
        "locked": bool(row[19]),
        "created_at": row[20],
        "updated_at": row[21],
    }


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
# GeoJSON conversion
# ---------------------------------------------------------------------------

def _annotation_to_geojson_feature(ann: dict) -> dict:
    """Convert an annotation dict to a GeoJSON Feature."""
    ann_type = ann.get("type", "text")
    props = {
        "id": ann.get("id"),
        "annotation_type": ann_type,
        "text": ann.get("text", ""),
        "color": ann.get("color", "#00f0ff"),
        "stroke_width": ann.get("stroke_width", 2.0),
        "font_size": ann.get("font_size", 14.0),
        "opacity": ann.get("opacity", 0.8),
        "fill": ann.get("fill", False),
        "fill_opacity": ann.get("fill_opacity", 0.2),
        "label": ann.get("label", ""),
        "layer": ann.get("layer", "default"),
        "locked": ann.get("locked", False),
        "created_at": ann.get("created_at"),
        "updated_at": ann.get("updated_at"),
    }

    if ann_type == "text":
        geometry = {
            "type": "Point",
            "coordinates": [ann["lng"], ann["lat"]],
        }
    elif ann_type == "circle":
        geometry = {
            "type": "Point",
            "coordinates": [ann["lng"], ann["lat"]],
        }
        props["radius_m"] = ann.get("radius_m")
    elif ann_type == "arrow":
        geometry = {
            "type": "LineString",
            "coordinates": [
                [ann["lng"], ann["lat"]],
                [ann.get("end_lng", ann["lng"]), ann.get("end_lat", ann["lat"])],
            ],
        }
    elif ann_type in ("freehand", "polygon"):
        pts = ann.get("points") or []
        coords = [[p[1], p[0]] for p in pts] if pts else [[ann["lng"], ann["lat"]]]
        if ann_type == "polygon" and len(coords) > 2:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            geometry = {"type": "Polygon", "coordinates": [coords]}
        else:
            geometry = {"type": "LineString", "coordinates": coords}
    elif ann_type == "rectangle":
        geometry = {
            "type": "Point",
            "coordinates": [ann["lng"], ann["lat"]],
        }
        props["width"] = ann.get("width")
        props["height"] = ann.get("height")
    else:
        geometry = {
            "type": "Point",
            "coordinates": [ann["lng"], ann["lat"]],
        }

    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": props,
    }


def _geojson_feature_to_annotation(feature: dict) -> dict:
    """Convert a GeoJSON Feature back to an annotation dict."""
    props = feature.get("properties", {})
    geom = feature.get("geometry", {})
    coords = geom.get("coordinates", [0, 0])
    geom_type = geom.get("type", "Point")
    ann_type = props.get("annotation_type", "text")

    now = time.time()
    ann = {
        "id": props.get("id", f"ann_{uuid.uuid4().hex[:8]}"),
        "type": ann_type,
        "text": props.get("text", ""),
        "color": props.get("color", "#00f0ff"),
        "stroke_width": props.get("stroke_width", 2.0),
        "font_size": props.get("font_size", 14.0),
        "opacity": props.get("opacity", 0.8),
        "fill": props.get("fill", False),
        "fill_opacity": props.get("fill_opacity", 0.2),
        "label": props.get("label", ""),
        "layer": props.get("layer", "default"),
        "locked": props.get("locked", False),
        "created_at": props.get("created_at", now),
        "updated_at": now,
        "end_lat": None,
        "end_lng": None,
        "radius_m": props.get("radius_m"),
        "points": None,
        "width": props.get("width"),
        "height": props.get("height"),
    }

    if geom_type == "Point":
        ann["lat"] = coords[1] if len(coords) >= 2 else 0
        ann["lng"] = coords[0] if len(coords) >= 1 else 0
    elif geom_type == "LineString":
        if ann_type == "arrow" and len(coords) >= 2:
            ann["lat"] = coords[0][1]
            ann["lng"] = coords[0][0]
            ann["end_lat"] = coords[1][1]
            ann["end_lng"] = coords[1][0]
        else:
            # Freehand
            ann["lat"] = coords[0][1] if coords else 0
            ann["lng"] = coords[0][0] if coords else 0
            ann["points"] = [[c[1], c[0]] for c in coords]
    elif geom_type == "Polygon":
        ring = coords[0] if coords else []
        ann["lat"] = ring[0][1] if ring else 0
        ann["lng"] = ring[0][0] if ring else 0
        ann["points"] = [[c[1], c[0]] for c in ring]

    return ann


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_annotations(layer: Optional[str] = None):
    """List all map annotations, optionally filtered by layer."""
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    if layer:
        rows = conn.execute(
            "SELECT * FROM annotations WHERE layer = ? ORDER BY created_at",
            (layer,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM annotations ORDER BY created_at"
        ).fetchall()
    conn.close()
    items = [_row_to_dict(r) for r in rows]
    return {
        "annotations": items,
        "count": len(items),
    }


@router.post("")
async def create_annotation(body: AnnotationCreate):
    """Create a new map annotation (persisted to SQLite)."""
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    count = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
    if count >= _MAX_ANNOTATIONS:
        conn.close()
        raise HTTPException(
            status_code=429,
            detail=f"Annotation limit reached ({_MAX_ANNOTATIONS})",
        )
    now = time.time()
    ann_id = f"ann_{uuid.uuid4().hex[:8]}"
    conn.execute(
        """INSERT INTO annotations
           (id, type, lat, lng, text, end_lat, end_lng, radius_m, points,
            width, height, color, stroke_width, font_size, opacity, fill,
            fill_opacity, label, layer, locked, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ann_id, body.type, body.lat, body.lng, body.text,
         body.end_lat, body.end_lng, body.radius_m,
         json.dumps(body.points) if body.points else None,
         body.width, body.height, body.color, body.stroke_width,
         body.font_size, body.opacity, int(body.fill), body.fill_opacity,
         body.label, body.layer, int(body.locked), now, now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM annotations WHERE id = ?", (ann_id,)
    ).fetchone()
    conn.close()
    return _row_to_dict(row)


@router.get("/export/geojson")
async def export_geojson(layer: Optional[str] = None):
    """Export annotations as GeoJSON FeatureCollection."""
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    if layer:
        rows = conn.execute(
            "SELECT * FROM annotations WHERE layer = ? ORDER BY created_at",
            (layer,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM annotations ORDER BY created_at"
        ).fetchall()
    conn.close()

    features = [_annotation_to_geojson_feature(_row_to_dict(r)) for r in rows]
    return {
        "type": "FeatureCollection",
        "features": features,
    }


@router.post("/import/geojson")
async def import_geojson(file: UploadFile = File(...)):
    """Import annotations from a GeoJSON file. Returns count imported."""
    _ensure_db()
    content = await file.read()
    try:
        geojson = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    features = geojson.get("features", [])
    if not features:
        raise HTTPException(status_code=400, detail="No features in GeoJSON")

    conn = sqlite3.connect(_get_db_path())
    imported = 0
    for feat in features:
        if feat.get("type") != "Feature":
            continue
        ann = _geojson_feature_to_annotation(feat)
        # Generate fresh ID to avoid conflicts
        ann["id"] = f"ann_{uuid.uuid4().hex[:8]}"
        ann["updated_at"] = time.time()
        try:
            conn.execute(
                """INSERT INTO annotations
                   (id, type, lat, lng, text, end_lat, end_lng, radius_m, points,
                    width, height, color, stroke_width, font_size, opacity, fill,
                    fill_opacity, label, layer, locked, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ann["id"], ann["type"], ann["lat"], ann["lng"], ann["text"],
                 ann.get("end_lat"), ann.get("end_lng"), ann.get("radius_m"),
                 json.dumps(ann["points"]) if ann.get("points") else None,
                 ann.get("width"), ann.get("height"), ann["color"],
                 ann["stroke_width"], ann["font_size"], ann["opacity"],
                 int(ann.get("fill", False)), ann["fill_opacity"],
                 ann["label"], ann["layer"], int(ann.get("locked", False)),
                 ann.get("created_at", time.time()), ann["updated_at"]),
            )
            imported += 1
        except Exception:
            continue
    conn.commit()
    conn.close()
    return {"ok": True, "imported": imported, "total_features": len(features)}


@router.get("/{annotation_id}")
async def get_annotation(annotation_id: str):
    """Get a single annotation by ID."""
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    row = conn.execute(
        "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return _row_to_dict(row)


@router.put("/{annotation_id}")
async def update_annotation(annotation_id: str, body: AnnotationUpdate):
    """Update an existing annotation."""
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    row = conn.execute(
        "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Annotation not found")

    ann = _row_to_dict(row)
    if ann.get("locked"):
        conn.close()
        raise HTTPException(status_code=403, detail="Annotation is locked")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        conn.close()
        return ann

    sets = []
    vals = []
    for k, v in updates.items():
        if k == "points":
            sets.append("points = ?")
            vals.append(json.dumps(v) if v else None)
        elif k == "fill" or k == "locked":
            sets.append(f"{k} = ?")
            vals.append(int(v))
        else:
            sets.append(f"{k} = ?")
            vals.append(v)
    sets.append("updated_at = ?")
    vals.append(time.time())
    vals.append(annotation_id)

    conn.execute(
        f"UPDATE annotations SET {', '.join(sets)} WHERE id = ?",
        vals,
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
    ).fetchone()
    conn.close()
    return _row_to_dict(row)


@router.delete("/{annotation_id}")
async def delete_annotation(annotation_id: str):
    """Delete an annotation."""
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    row = conn.execute(
        "SELECT id FROM annotations WHERE id = ?", (annotation_id,)
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Annotation not found")
    conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": annotation_id}


@router.delete("")
async def clear_annotations(layer: Optional[str] = None):
    """Clear all annotations, optionally filtered by layer."""
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    if layer:
        result = conn.execute(
            "DELETE FROM annotations WHERE layer = ?", (layer,)
        )
    else:
        result = conn.execute("DELETE FROM annotations")
    count = result.rowcount
    conn.commit()
    conn.close()
    return {"ok": True, "deleted_count": count}


@router.get("/layers/list")
async def list_layers():
    """List all annotation layers."""
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    rows = conn.execute(
        "SELECT DISTINCT layer FROM annotations ORDER BY layer"
    ).fetchall()
    conn.close()
    return {"layers": [r[0] for r in rows]}
