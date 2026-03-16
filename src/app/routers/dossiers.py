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


@router.get("/by-target")
async def get_dossier_by_target(
    request: Request,
    target_id: str = Query(..., description="Target ID (e.g. ble_AABBCC112201)"),
    fields: Optional[str] = Query(
        None,
        description="'summary' to return metadata only (no signals/enrichments), default returns full detail",
    ),
):
    """Look up the dossier linked to a tracked target.

    Returns the dossier metadata (or full detail if fields is not 'summary'),
    or 404 if no dossier exists for the target.

    Use ``?fields=summary`` to get a lightweight response with just the
    dossier_id and metadata — avoids loading thousands of signals.
    """
    summary_only = fields == "summary"

    # Fast path: if we only need the dossier_id + metadata, avoid loading signals
    if summary_only:
        did = _resolve_dossier_id_for_target(request, target_id)
        if did is None:
            raise HTTPException(status_code=404, detail=f"No dossier found for target {target_id}")
        store = _get_store()
        if store is not None:
            # Lightweight query: just the dossier row, no signals
            try:
                row = store._conn.execute(
                    "SELECT * FROM dossiers WHERE dossier_id = ?", (did,)
                ).fetchone()
                if row:
                    return store._row_to_dossier(row)
            except Exception:
                pass
        # Fallback to full load + strip
        mgr = _get_manager(request)
        if mgr is not None:
            dossier = mgr.get_dossier(did)
            if dossier:
                return _strip_signals(dossier)
        raise HTTPException(status_code=404, detail=f"No dossier found for target {target_id}")

    mgr = _get_manager(request)
    if mgr is not None:
        dossier = mgr.get_dossier_for_target(target_id)
        if dossier:
            return dossier
    # Fallback: try store identifier lookup for BLE MACs
    store = _get_store()
    if store is not None and target_id.startswith("ble_"):
        raw = target_id[4:]
        if len(raw) == 12:
            mac = ":".join(raw[i:i + 2] for i in range(0, 12, 2)).upper()
            dossier = store.find_by_identifier("mac", mac)
            if dossier:
                return dossier
        # Also try raw value as MAC (with colons)
        dossier = store.find_by_identifier("mac", raw)
        if dossier:
            return dossier
    # Try name match as last resort
    if store is not None:
        results = store.search(target_id)
        if results:
            return results[0]
    raise HTTPException(status_code=404, detail=f"No dossier found for target {target_id}")


def _resolve_dossier_id_for_target(request, target_id: str) -> str | None:
    """Resolve a target_id to a dossier_id without loading the full dossier."""
    mgr = _get_manager(request)
    if mgr is not None:
        with mgr._lock:
            did = mgr._target_dossier_map.get(target_id)
        if did:
            return did

    store = _get_store()
    if store is None:
        return None

    # BLE MAC lookup
    if target_id.startswith("ble_"):
        raw = target_id[4:]
        if len(raw) == 12:
            mac = ":".join(raw[i:i + 2] for i in range(0, 12, 2)).upper()
            try:
                row = store._conn.execute(
                    """SELECT dossier_id FROM dossiers
                       WHERE json_extract(identifiers, '$.mac') = ?""",
                    (mac,),
                ).fetchone()
                if row:
                    return row["dossier_id"]
            except Exception:
                pass
        # Try raw
        try:
            row = store._conn.execute(
                """SELECT dossier_id FROM dossiers
                   WHERE json_extract(identifiers, '$.mac') = ?""",
                (raw,),
            ).fetchone()
            if row:
                return row["dossier_id"]
        except Exception:
            pass

    # Name match as last resort (uses FTS, returns list)
    if store is not None:
        results = store.search(target_id)
        if results:
            return results[0].get("dossier_id")

    return None


def _strip_signals(dossier: dict) -> dict:
    """Return dossier metadata without heavy signal/enrichment payloads."""
    return {
        k: v for k, v in dossier.items()
        if k not in ("signals", "enrichments", "position_history")
    }


@router.get("/{dossier_id}")
async def get_dossier(
    request: Request,
    dossier_id: str,
    signal_limit: int = Query(
        200,
        ge=0,
        le=5000,
        description="Max signals to include in response (0 = none). Keeps response size manageable for large dossiers.",
    ),
):
    """Get full dossier detail including signals, enrichments, positions.

    The ``signal_limit`` parameter caps the number of signals returned
    (most recent first) to prevent multi-megabyte responses for dossiers
    with thousands of accumulated signals.  Signals are loaded with a
    SQL LIMIT clause so large dossiers remain fast.
    """
    store = _get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Dossier store unavailable")

    # Load dossier metadata (without signals) directly from the store
    try:
        row = store._conn.execute(
            "SELECT * FROM dossiers WHERE dossier_id = ?", (dossier_id,)
        ).fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="Dossier store unavailable")

    if row is None:
        raise HTTPException(status_code=404, detail="Dossier not found")

    dossier = store._row_to_dossier(row)

    # Load signals with SQL LIMIT to avoid loading 20K+ rows
    try:
        signal_rows = store._conn.execute(
            """SELECT * FROM dossier_signals
               WHERE dossier_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (dossier_id, signal_limit),
        ).fetchall()
        dossier["signals"] = [store._row_to_signal(s) for s in signal_rows]

        # Get total signal count efficiently
        count_row = store._conn.execute(
            "SELECT COUNT(*) as cnt FROM dossier_signals WHERE dossier_id = ?",
            (dossier_id,),
        ).fetchone()
        total = count_row["cnt"] if count_row else len(signal_rows)
        if total > signal_limit:
            dossier["signal_truncated"] = True
            dossier["signal_total"] = total
    except Exception:
        dossier["signals"] = []

    # Load enrichments (typically few)
    try:
        enrich_rows = store._conn.execute(
            """SELECT * FROM dossier_enrichments
               WHERE dossier_id = ?
               ORDER BY timestamp DESC""",
            (dossier_id,),
        ).fetchall()
        dossier["enrichments"] = [store._row_to_enrichment(e) for e in enrich_rows]
    except Exception:
        dossier["enrichments"] = []

    # Add position history from signals
    try:
        pos_rows = store._conn.execute(
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
            for r in pos_rows
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


@router.get("/{dossier_id}/correlated-targets")
async def get_correlated_targets(request: Request, dossier_id: str):
    """Find targets correlated with this dossier.

    Returns three categories:
    - linked: targets whose correlated_ids reference this dossier's targets
    - nearby_cross_source: targets from different sensor sources at the same location
    - correlator_records: confirmed correlation records from the TargetCorrelator
    """
    import math

    mgr = _get_manager(request)
    store = _get_store()

    # Get dossier details
    if mgr is not None:
        dossier = mgr.get_dossier(dossier_id)
    elif store is not None:
        dossier = store.get_dossier(dossier_id)
    else:
        raise HTTPException(status_code=503, detail="Dossier store unavailable")

    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier not found")

    # Build the set of target IDs belonging to this dossier
    my_target_ids: set[str] = set()

    # From DossierManager's target_dossier_map
    if mgr is not None:
        with mgr._lock:
            for tid, did in mgr._target_dossier_map.items():
                if did == dossier_id:
                    my_target_ids.add(tid)

    # From dossier identifiers (MAC -> ble_XX target ID)
    identifiers = dossier.get("identifiers", {})
    if identifiers.get("mac"):
        mac_clean = identifiers["mac"].replace(":", "").lower()
        my_target_ids.add(f"ble_{mac_clean}")

    # Get the tracker for live target state
    tracker = getattr(request.app.state, "tracker", None)
    all_targets = tracker.get_all() if tracker else []
    target_map = {t.target_id: t for t in all_targets}

    # Determine this dossier's position and sources from its targets
    my_sources: set[str] = set()
    my_positions: list[tuple[float, float]] = []
    for tid in my_target_ids:
        t = target_map.get(tid)
        if t:
            my_sources.add(t.source)
            if t.lat and t.lng:
                my_positions.append((t.lat, t.lng))

    # Also check dossier tags for source info
    for tag in dossier.get("tags", []):
        if tag in ("ble", "yolo", "wifi", "mesh", "acoustic", "manual", "mqtt", "simulation"):
            my_sources.add(tag)

    # Category 1: Linked targets (correlated_ids bidirectional lookup)
    linked = []
    for t in all_targets:
        if t.target_id in my_target_ids:
            # This is our own target — check its correlated_ids
            for cid in t.correlated_ids:
                ct = target_map.get(cid)
                if ct:
                    linked.append({
                        "target_id": cid,
                        "name": ct.name or cid,
                        "source": ct.source,
                        "asset_type": ct.asset_type,
                        "alliance": ct.alliance,
                        "confidence": t.correlation_confidence,
                        "lat": ct.lat,
                        "lng": ct.lng,
                        "reason": "correlated_ids (fused by correlator)",
                    })
            continue
        # Check if OTHER targets reference our IDs
        for cid in t.correlated_ids:
            if cid in my_target_ids:
                linked.append({
                    "target_id": t.target_id,
                    "name": t.name or t.target_id,
                    "source": t.source,
                    "asset_type": t.asset_type,
                    "alliance": t.alliance,
                    "confidence": t.correlation_confidence,
                    "lat": t.lat,
                    "lng": t.lng,
                    "reason": "correlated_ids (reverse link)",
                })
                break

    # Category 2: Nearby cross-source targets (potential correlations)
    nearby_cross_source = []
    if my_positions:
        proximity_threshold = 0.0005  # ~55 meters in lat/lng degrees
        for t in all_targets:
            if t.target_id in my_target_ids:
                continue
            if t.source in my_sources:
                continue  # same source type, less interesting
            if not t.lat or not t.lng:
                continue
            # Check proximity to any of our positions
            for my_lat, my_lng in my_positions:
                dist = math.hypot(t.lat - my_lat, t.lng - my_lng)
                if dist < proximity_threshold:
                    # Find dossier for this nearby target
                    nearby_dossier_id = None
                    if mgr is not None:
                        nearby_dossier = mgr.get_dossier_for_target(t.target_id)
                        if nearby_dossier:
                            nearby_dossier_id = nearby_dossier.get("dossier_id")
                    nearby_cross_source.append({
                        "target_id": t.target_id,
                        "name": t.name or t.target_id,
                        "source": t.source,
                        "asset_type": t.asset_type,
                        "alliance": t.alliance,
                        "distance_m": round(dist * 111320, 1),  # approximate meters
                        "lat": t.lat,
                        "lng": t.lng,
                        "dossier_id": nearby_dossier_id,
                        "reason": f"cross-source proximity ({t.source} near {', '.join(my_sources)})",
                    })
                    break

    # Category 3: Confirmed correlator records
    correlator_records = []
    correlator = getattr(request.app.state, "correlator", None)
    if correlator:
        for rec in correlator.get_correlations():
            if rec.primary_id in my_target_ids or rec.secondary_id in my_target_ids:
                other_id = rec.secondary_id if rec.primary_id in my_target_ids else rec.primary_id
                ct = target_map.get(other_id)
                correlator_records.append({
                    "target_id": other_id,
                    "name": ct.name if ct else other_id,
                    "source": ct.source if ct else "unknown",
                    "asset_type": ct.asset_type if ct else "unknown",
                    "confidence": rec.confidence,
                    "reason": rec.reason,
                    "strategies": [
                        {"name": s.strategy_name, "score": round(s.score, 3), "detail": s.detail}
                        for s in rec.strategy_scores
                    ],
                })

    # Deduplicate across categories
    seen_ids: set[str] = set()
    def _dedup(items):
        result = []
        for item in items:
            if item["target_id"] not in seen_ids:
                seen_ids.add(item["target_id"])
                result.append(item)
        return result

    correlator_records = _dedup(correlator_records)
    linked = _dedup(linked)
    nearby_cross_source = _dedup(nearby_cross_source)

    return {
        "dossier_id": dossier_id,
        "my_target_ids": sorted(my_target_ids),
        "correlator_records": correlator_records,
        "linked": linked,
        "nearby_cross_source": nearby_cross_source[:15],
        "total": len(correlator_records) + len(linked) + len(nearby_cross_source),
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
