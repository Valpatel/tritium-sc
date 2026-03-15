# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Target Dossier API — CRUD, search, merge, tags, notes for persistent entity intelligence.

Routes through DossierManager when available (bridges TargetTracker and
DossierStore).  Falls back to a direct DossierStore singleton when the
manager has not been started.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Body
from loguru import logger

from app.auth import require_auth

router = APIRouter(prefix="/api/dossiers", tags=["dossiers"])

# Lazy-init singleton store (fallback when DossierManager is not wired up)
_store = None
_DB_PATH = Path("data/dossiers.db")


def _get_store():
    """Lazy-initialise the DossierStore singleton."""
    global _store
    if _store is None:
        try:
            from tritium_lib.store.dossiers import DossierStore
            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _store = DossierStore(_DB_PATH)
            logger.info(f"DossierStore initialised: {_DB_PATH}")
        except Exception as e:
            logger.warning(f"DossierStore init failed: {e}")
            return None
    return _store


def _get_manager(request: Request):
    """Get DossierManager from app state, or None."""
    return getattr(request.app.state, "dossier_manager", None)


# -- Endpoints -------------------------------------------------------------

@router.get("")
async def list_dossiers(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    entity_type: Optional[str] = Query(None),
    threat_level: Optional[str] = Query(None),
    alliance: Optional[str] = Query(None),
    sort: Optional[str] = Query(
        "last_seen",
        description="Sort field: last_seen, first_seen, confidence, threat_level, name, signals",
    ),
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    """List dossiers with optional filters, pagination, and sorting."""
    mgr = _get_manager(request)
    store = _get_store()

    if mgr is not None:
        dossiers = mgr.list_dossiers(
            limit=limit, offset=offset, sort_by=sort, order=order,
        )
    elif store is not None:
        dossiers = store.get_recent(limit=limit + offset)
        dossiers = dossiers[offset:offset + limit]
    else:
        return {"dossiers": [], "total": 0}

    # Apply filters
    if entity_type:
        dossiers = [d for d in dossiers if d.get("entity_type") == entity_type]
    if threat_level:
        dossiers = [d for d in dossiers if d.get("threat_level") == threat_level]
    if alliance:
        dossiers = [d for d in dossiers if d.get("alliance") == alliance]

    # Get signal counts (lightweight — no full signal load)
    if store is not None:
        for d in dossiers:
            did = d["dossier_id"]
            try:
                row = store._conn.execute(
                    "SELECT COUNT(*) as cnt FROM dossier_signals WHERE dossier_id = ?",
                    (did,),
                ).fetchone()
                d["signal_count"] = row["cnt"] if row else 0
            except Exception:
                d["signal_count"] = 0

    # Sort by signal count if requested (can't do in SQL easily)
    if sort == "signals":
        dossiers.sort(key=lambda d: d.get("signal_count", 0), reverse=(order == "desc"))

    return {"dossiers": dossiers, "total": len(dossiers)}


@router.get("/search")
async def search_dossiers(
    request: Request,
    q: str = Query("", min_length=0, description="Search query"),
):
    """Full-text search across dossier names, types, identifiers, tags."""
    if not q.strip():
        return {"results": [], "total": 0, "query": q}

    mgr = _get_manager(request)
    if mgr is not None:
        results = mgr.search(q)
    else:
        store = _get_store()
        if store is None:
            return {"results": [], "total": 0, "query": q}
        results = store.search(q)

    # Add signal counts
    store = _get_store()
    if store is not None:
        for d in results:
            try:
                row = store._conn.execute(
                    "SELECT COUNT(*) as cnt FROM dossier_signals WHERE dossier_id = ?",
                    (d["dossier_id"],),
                ).fetchone()
                d["signal_count"] = row["cnt"] if row else 0
            except Exception:
                d["signal_count"] = 0

    return {"results": results, "total": len(results), "query": q}


@router.get("/{dossier_id}")
async def get_dossier(request: Request, dossier_id: str):
    """Get full dossier detail including signals, enrichments, positions."""
    mgr = _get_manager(request)
    store = _get_store()

    if mgr is not None:
        dossier = mgr.get_dossier(dossier_id)
    elif store is not None:
        dossier = store.get_dossier(dossier_id)
    else:
        raise HTTPException(status_code=503, detail="Dossier store unavailable")

    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier not found")

    # Add position history from signals
    if store is not None:
        try:
            rows = store._conn.execute(
                """SELECT position_x, position_y, timestamp, source
                   FROM dossier_signals
                   WHERE dossier_id = ? AND position_x IS NOT NULL AND position_y IS NOT NULL
                   ORDER BY timestamp DESC
                   LIMIT 20""",
                (dossier_id,),
            ).fetchall()
            dossier["position_history"] = [
                {"x": r["position_x"], "y": r["position_y"],
                 "timestamp": r["timestamp"], "source": r["source"]}
                for r in rows
            ]
        except Exception:
            dossier["position_history"] = []

    return dossier


@router.post("/{dossier_id}/merge/{other_id}")
async def merge_dossiers_path(request: Request, dossier_id: str, other_id: str, _user: dict = Depends(require_auth)):
    """Merge another dossier into this one (path-based)."""
    mgr = _get_manager(request)
    if mgr is not None:
        ok = mgr.merge(dossier_id, other_id)
    else:
        store = _get_store()
        if store is None:
            raise HTTPException(status_code=503, detail="Dossier store unavailable")
        ok = store.merge_dossiers(dossier_id, other_id)

    if not ok:
        raise HTTPException(status_code=404, detail="One or both dossiers not found")
    return {"ok": True, "primary_id": dossier_id, "merged_from": other_id}


@router.post("/merge")
async def merge_dossiers_body(
    request: Request,
    primary_id: str = Body(..., embed=True),
    secondary_id: str = Body(..., embed=True),
    _user: dict = Depends(require_auth),
):
    """Merge secondary dossier into primary (body-based, legacy)."""
    mgr = _get_manager(request)
    if mgr is not None:
        ok = mgr.merge(primary_id, secondary_id)
    else:
        store = _get_store()
        if store is None:
            raise HTTPException(status_code=503, detail="Dossier store unavailable")
        ok = store.merge_dossiers(primary_id, secondary_id)

    if not ok:
        raise HTTPException(status_code=404, detail="Merge failed — one or both dossiers not found")
    return {"ok": True, "primary_id": primary_id, "merged_from": secondary_id}


@router.get("/{dossier_id}/signal-history")
async def get_signal_history(
    request: Request,
    dossier_id: str,
    signal_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    since: Optional[float] = Query(None),
):
    """Get signal history timeline for a dossier (RSSI over time, etc.)."""
    mgr = _get_manager(request)
    if mgr is not None:
        timeline = mgr.get_signal_history(
            dossier_id, signal_type=signal_type, source=source,
            limit=limit, since=since,
        )
        return {"dossier_id": dossier_id, "timeline": timeline, "count": len(timeline)}

    store = _get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Dossier store unavailable")

    dossier = store.get_dossier(dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier not found")

    signals = dossier.get("signals", [])
    if signal_type:
        signals = [s for s in signals if s.get("signal_type") == signal_type]
    if source:
        signals = [s for s in signals if s.get("source") == source]
    if since:
        signals = [s for s in signals if s.get("timestamp", 0) >= since]
    signals.sort(key=lambda s: s.get("timestamp", 0))

    timeline = []
    for sig in signals[-limit:]:
        data = sig.get("data", {})
        point = {
            "timestamp": sig.get("timestamp", 0),
            "source": sig.get("source", ""),
            "signal_type": sig.get("signal_type", ""),
            "confidence": sig.get("confidence", 0),
        }
        rssi = data.get("rssi") if isinstance(data, dict) else None
        if rssi is not None:
            point["rssi"] = rssi
        if sig.get("position_x") is not None:
            point["position_x"] = sig["position_x"]
            point["position_y"] = sig.get("position_y")
        timeline.append(point)

    return {"dossier_id": dossier_id, "timeline": timeline, "count": len(timeline)}


@router.get("/{dossier_id}/location-summary")
async def get_location_summary(request: Request, dossier_id: str):
    """Get location history summary — zones visited, time per zone, distance."""
    mgr = _get_manager(request)
    if mgr is not None:
        summary = mgr.get_location_summary(dossier_id)
        return {"dossier_id": dossier_id, **summary}

    store = _get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Dossier store unavailable")

    dossier = store.get_dossier(dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier not found")

    return {"dossier_id": dossier_id, "zones_visited": [], "position_count": 0, "positions": [], "total_distance": 0.0}


@router.get("/{dossier_id}/behavioral-profile")
async def get_behavioral_profile(request: Request, dossier_id: str):
    """Get behavioral profile — movement pattern, speed, activity hours, RSSI trends."""
    mgr = _get_manager(request)
    if mgr is not None:
        profile = mgr.get_behavioral_profile(dossier_id)
        return {"dossier_id": dossier_id, **profile}

    store = _get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Dossier store unavailable")

    dossier = store.get_dossier(dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier not found")

    return {
        "dossier_id": dossier_id,
        "movement_pattern": "unknown",
        "average_speed": 0.0,
        "max_speed": 0.0,
        "activity_hours": [],
        "signal_count": 0,
        "source_breakdown": {},
        "rssi_stats": {},
        "first_seen": dossier.get("first_seen", 0),
        "last_seen": dossier.get("last_seen", 0),
        "active_duration_s": 0,
    }


@router.post("/{dossier_id}/tag")
async def add_tag(
    request: Request,
    dossier_id: str,
    tag: str = Body(..., embed=True),
    _user: dict = Depends(require_auth),
):
    """Add a tag to a dossier."""
    mgr = _get_manager(request)
    if mgr is not None:
        ok = mgr.add_tag(dossier_id, tag)
        if not ok:
            raise HTTPException(status_code=404, detail="Dossier not found")
        return {"ok": True, "dossier_id": dossier_id, "tag": tag}

    store = _get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Dossier store unavailable")

    dossier = store.get_dossier(dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier not found")

    tags = dossier.get("tags", [])
    if tag not in tags:
        tags.append(tag)
        store._update_json_field(dossier_id, "tags", tags)

    return {"ok": True, "tags": tags}


@router.post("/{dossier_id}/tags")
async def add_tag_legacy(
    request: Request,
    dossier_id: str,
    tag: str = Body(..., embed=True),
    _user: dict = Depends(require_auth),
):
    """Add a tag to a dossier (legacy /tags endpoint)."""
    return await add_tag(request, dossier_id, tag)


@router.delete("/{dossier_id}/tags/{tag}")
async def remove_tag(request: Request, dossier_id: str, tag: str, _user: dict = Depends(require_auth)):
    """Remove a tag from a dossier."""
    store = _get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Dossier store unavailable")

    dossier = store.get_dossier(dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier not found")

    tags = dossier.get("tags", [])
    if tag in tags:
        tags.remove(tag)
        store._update_json_field(dossier_id, "tags", tags)

    return {"ok": True, "tags": tags}


@router.post("/{dossier_id}/note")
async def add_note(
    request: Request,
    dossier_id: str,
    note: str = Body(..., embed=True),
    _user: dict = Depends(require_auth),
):
    """Add a note to a dossier."""
    mgr = _get_manager(request)
    if mgr is not None:
        ok = mgr.add_note(dossier_id, note)
        if not ok:
            raise HTTPException(status_code=404, detail="Dossier not found")
        return {"ok": True, "dossier_id": dossier_id, "note": note}

    store = _get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Dossier store unavailable")

    dossier = store.get_dossier(dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier not found")

    notes = dossier.get("notes", [])
    notes.append(note)
    store._update_json_field(dossier_id, "notes", notes)

    return {"ok": True, "notes": notes}


@router.post("/{dossier_id}/notes")
async def add_note_legacy(
    request: Request,
    dossier_id: str,
    note: str = Body(..., embed=True),
    _user: dict = Depends(require_auth),
):
    """Add a note to a dossier (legacy /notes endpoint)."""
    return await add_note(request, dossier_id, note)
