# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Target group management — CRUD API for operator-defined target collections.

Operators create named groups of targets ("Building A devices", "Patrol route
suspects") and add/remove targets. Groups persist in SQLite and can be filtered
on the tactical map.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/target-groups", tags=["target-groups"])

# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

_DB_PATH: str | None = None
_db_initialized = False


def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        import os
        data_dir = os.environ.get("TRITIUM_DATA_DIR", "data")
        os.makedirs(data_dir, exist_ok=True)
        _DB_PATH = os.path.join(data_dir, "target_groups.db")
    return _DB_PATH


def _ensure_db():
    global _db_initialized
    if _db_initialized:
        return
    import sqlite3
    conn = sqlite3.connect(_get_db_path())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS target_groups (
            group_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            target_ids TEXT DEFAULT '[]',
            created_by TEXT DEFAULT 'operator',
            color TEXT DEFAULT '#00f0ff',
            icon TEXT DEFAULT 'group',
            created_at REAL,
            updated_at REAL
        )
    """)
    conn.commit()
    conn.close()
    _db_initialized = True


def _row_to_dict(row) -> dict:
    return {
        "group_id": row[0],
        "name": row[1],
        "description": row[2],
        "target_ids": json.loads(row[3]) if row[3] else [],
        "created_by": row[4],
        "color": row[5],
        "icon": row[6],
        "created_at": row[7],
        "updated_at": row[8],
    }


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    color: str = Field(default="#00f0ff", max_length=20)
    icon: str = Field(default="group", max_length=50)
    created_by: str = Field(default="operator", max_length=100)
    target_ids: list[str] = Field(default_factory=list)


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    color: Optional[str] = Field(default=None, max_length=20)
    icon: Optional[str] = Field(default=None, max_length=50)


class TargetModify(BaseModel):
    target_ids: list[str] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_groups():
    """List all target groups."""
    import sqlite3
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    rows = conn.execute(
        "SELECT * FROM target_groups ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    groups = [_row_to_dict(r) for r in rows]
    return {"groups": groups, "count": len(groups)}


@router.post("")
async def create_group(body: GroupCreate):
    """Create a new target group."""
    import sqlite3
    _ensure_db()
    now = time.time()
    group_id = f"grp_{uuid.uuid4().hex[:8]}"
    conn = sqlite3.connect(_get_db_path())
    conn.execute(
        """INSERT INTO target_groups
           (group_id, name, description, target_ids, created_by, color, icon, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (group_id, body.name, body.description,
         json.dumps(body.target_ids), body.created_by,
         body.color, body.icon, now, now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM target_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    conn.close()
    return _row_to_dict(row)


@router.get("/{group_id}")
async def get_group(group_id: str):
    """Get a single target group."""
    import sqlite3
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    row = conn.execute(
        "SELECT * FROM target_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Target group not found")
    return _row_to_dict(row)


@router.put("/{group_id}")
async def update_group(group_id: str, body: GroupUpdate):
    """Update a target group's metadata."""
    import sqlite3
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    row = conn.execute(
        "SELECT * FROM target_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Target group not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        conn.close()
        return _row_to_dict(row)

    _ALLOWED_COLUMNS = {"name", "description", "color", "icon"}
    sets = []
    vals = []
    for k, v in updates.items():
        if k not in _ALLOWED_COLUMNS:
            continue
        sets.append(f"{k} = ?")
        vals.append(v)
    sets.append("updated_at = ?")
    vals.append(time.time())
    vals.append(group_id)

    conn.execute(
        f"UPDATE target_groups SET {', '.join(sets)} WHERE group_id = ?",
        vals,
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM target_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    conn.close()
    return _row_to_dict(row)


@router.delete("/{group_id}")
async def delete_group(group_id: str):
    """Delete a target group."""
    import sqlite3
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    row = conn.execute(
        "SELECT group_id FROM target_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Target group not found")
    conn.execute("DELETE FROM target_groups WHERE group_id = ?", (group_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": group_id}


@router.post("/{group_id}/targets")
async def add_targets(group_id: str, body: TargetModify):
    """Add targets to a group."""
    import sqlite3
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    row = conn.execute(
        "SELECT target_ids FROM target_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Target group not found")

    current = json.loads(row[0]) if row[0] else []
    added = []
    for tid in body.target_ids:
        if tid not in current:
            current.append(tid)
            added.append(tid)

    conn.execute(
        "UPDATE target_groups SET target_ids = ?, updated_at = ? WHERE group_id = ?",
        (json.dumps(current), time.time(), group_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "added": added, "total_targets": len(current)}


@router.delete("/{group_id}/targets")
async def remove_targets(group_id: str, body: TargetModify):
    """Remove targets from a group."""
    import sqlite3
    _ensure_db()
    conn = sqlite3.connect(_get_db_path())
    row = conn.execute(
        "SELECT target_ids FROM target_groups WHERE group_id = ?", (group_id,)
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Target group not found")

    current = json.loads(row[0]) if row[0] else []
    removed = []
    for tid in body.target_ids:
        if tid in current:
            current.remove(tid)
            removed.append(tid)

    conn.execute(
        "UPDATE target_groups SET target_ids = ?, updated_at = ? WHERE group_id = ?",
        (json.dumps(current), time.time(), group_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "removed": removed, "total_targets": len(current)}
