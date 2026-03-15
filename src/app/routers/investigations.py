# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Investigation API — create, expand, annotate, and close entity investigations.

Implements the ontology research workflow:
  Seed -> Expand -> Filter -> Analyze -> Annotate -> Share
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from loguru import logger

router = APIRouter(prefix="/api/investigations", tags=["investigations"])

# Lazy-init singleton engine
_engine = None
_DB_PATH = Path("data/investigations.db")


def _get_engine():
    """Lazy-initialise the InvestigationEngine singleton."""
    global _engine
    if _engine is None:
        try:
            from engine.tactical.investigation import InvestigationEngine

            # Try to get dossier store for graph expansion
            dossier_store = None
            try:
                from tritium_lib.store.dossiers import DossierStore

                store_path = Path("data/dossiers.db")
                if store_path.exists():
                    dossier_store = DossierStore(store_path)
            except Exception:
                pass

            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _engine = InvestigationEngine(
                db_path=_DB_PATH,
                dossier_store=dossier_store,
            )
            logger.info(f"InvestigationEngine initialised: {_DB_PATH}")
        except Exception as e:
            logger.warning(f"InvestigationEngine init failed: {e}")
            return None
    return _engine


# -- Endpoints -------------------------------------------------------------


@router.post("")
async def create_investigation(
    title: str = Body(...),
    seed_entity_ids: list[str] = Body(default=[]),
    description: str = Body(default=""),
):
    """Create a new investigation seeded with entity IDs."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    if not title or not title.strip():
        raise HTTPException(status_code=400, detail="Title is required")

    inv = engine.create(
        title=title.strip(),
        seed_entity_ids=seed_entity_ids,
        description=description,
    )
    return inv.to_dict()


@router.get("")
async def list_investigations(
    status: Optional[str] = Query(None, description="Filter by status: open, closed, archived"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all investigations, optionally filtered by status."""
    engine = _get_engine()
    if engine is None:
        return {"investigations": [], "total": 0}

    investigations = engine.list_investigations(
        status=status, limit=limit, offset=offset,
    )
    result = [inv.to_dict() for inv in investigations]
    return {"investigations": result, "total": len(result)}


@router.get("/{inv_id}")
async def get_investigation(inv_id: str):
    """Get a full investigation with all entities and annotations."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    inv = engine.get(inv_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    result = inv.to_dict()

    # Enrich with dossier summaries if store is available
    if engine._dossier_store is not None:
        entities = []
        for eid in inv.all_entity_ids():
            dossier = engine._dossier_store.get_dossier(eid)
            if dossier:
                entities.append({
                    "dossier_id": eid,
                    "name": dossier.get("name", "Unknown"),
                    "entity_type": dossier.get("entity_type", "unknown"),
                    "threat_level": dossier.get("threat_level", "none"),
                    "confidence": dossier.get("confidence", 0.0),
                    "last_seen": dossier.get("last_seen", 0),
                    "is_seed": eid in inv.seed_entities,
                })
            else:
                entities.append({
                    "dossier_id": eid,
                    "name": "Unknown (deleted?)",
                    "entity_type": "unknown",
                    "threat_level": "none",
                    "confidence": 0.0,
                    "last_seen": 0,
                    "is_seed": eid in inv.seed_entities,
                })
        result["entities"] = entities

    return result


@router.post("/{inv_id}/expand")
async def expand_investigation(
    inv_id: str,
    entity_id: str = Body(...),
    max_hops: int = Body(default=1),
):
    """Expand the investigation graph from an entity via relationship traversal."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    inv = engine.get(inv_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    if inv.status != "open":
        raise HTTPException(status_code=400, detail="Cannot expand a closed investigation")

    newly_discovered = engine.expand(inv_id, entity_id, max_hops=max_hops)
    return {
        "inv_id": inv_id,
        "expanded_from": entity_id,
        "newly_discovered": newly_discovered,
        "count": len(newly_discovered),
    }


@router.post("/{inv_id}/annotate")
async def annotate_investigation(
    inv_id: str,
    entity_id: str = Body(...),
    note: str = Body(...),
    analyst: str = Body(default="system"),
):
    """Add an annotation to an entity within the investigation."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    if not note or not note.strip():
        raise HTTPException(status_code=400, detail="Note is required")

    ann = engine.annotate(inv_id, entity_id, note.strip(), analyst=analyst)
    if ann is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    return ann.to_dict()


@router.post("/{inv_id}/close")
async def close_investigation(inv_id: str):
    """Close an investigation."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    ok = engine.close(inv_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Investigation not found")

    return {"ok": True, "inv_id": inv_id, "status": "closed"}


@router.post("/{inv_id}/archive")
async def archive_investigation(inv_id: str):
    """Archive an investigation."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    ok = engine.archive(inv_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Investigation not found")

    return {"ok": True, "inv_id": inv_id, "status": "archived"}


@router.post("/{inv_id}/filter/time")
async def filter_by_time(
    inv_id: str,
    start: float = Body(...),
    end: float = Body(...),
):
    """Filter investigation entities by time range."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    if start >= end:
        raise HTTPException(status_code=400, detail="start must be before end")

    filtered = engine.filter_by_time(inv_id, start, end)
    return {"inv_id": inv_id, "filtered_entities": filtered, "count": len(filtered)}


@router.get("/{inv_id}/graph")
async def get_investigation_graph(inv_id: str):
    """Return the investigation entities and relationships as a graph for link chart rendering.

    Returns nodes (entities) and edges (relationships) suitable for
    force-directed graph visualization.
    """
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    inv = engine.get(inv_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    nodes = []
    edges = []
    seen_ids = set()

    # Build nodes from all entity IDs
    for eid in inv.all_entity_ids():
        if eid in seen_ids:
            continue
        seen_ids.add(eid)

        node_data = {
            "id": eid,
            "label": eid,
            "entity_type": "unknown",
            "is_seed": eid in inv.seed_entities,
        }

        # Enrich with dossier data if available
        if engine._dossier_store is not None:
            dossier = engine._dossier_store.get_dossier(eid)
            if dossier:
                node_data["label"] = dossier.get("name", eid)
                node_data["entity_type"] = dossier.get("entity_type", "unknown")
                node_data["threat_level"] = dossier.get("threat_level", "none")
                node_data["confidence"] = dossier.get("confidence", 0.0)

                # Extract relationships to build edges
                relationships = dossier.get("relationships", [])
                for rel in relationships:
                    target_id = rel.get("target_id") or rel.get("entity_id")
                    if target_id and target_id in seen_ids or target_id in inv.all_entity_ids():
                        edges.append({
                            "source_id": eid,
                            "target_id": target_id,
                            "type": rel.get("type", rel.get("relationship", "")),
                            "confidence": rel.get("confidence", 0.5),
                        })

        nodes.append(node_data)

    # Connect seed entities to discovered entities if no edges found
    if not edges and len(inv.seed_entities) > 0:
        discovered = [eid for eid in inv.all_entity_ids() if eid not in inv.seed_entities]
        for seed_id in inv.seed_entities:
            for disc_id in discovered:
                edges.append({
                    "source_id": seed_id,
                    "target_id": disc_id,
                    "type": "discovered_from",
                    "confidence": 0.3,
                })

    return {
        "inv_id": inv_id,
        "title": inv.title,
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


@router.get("/{inv_id}/map-entities")
async def get_investigation_map_entities(inv_id: str, request: Request):
    """Return investigation entities with map positions for tactical map overlay.

    For each entity in the investigation, attempts to find its current
    position from the TargetTracker.  Returns entities with lat/lng so
    the frontend can render them with a distinct investigation border.
    """
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    inv = engine.get(inv_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    # Try to get target tracker for position data
    tracker = None
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        tracker = getattr(amy, "target_tracker", None)

    map_entities = []
    for eid in inv.all_entity_ids():
        entity = {
            "entity_id": eid,
            "is_seed": eid in inv.seed_entities,
            "inv_id": inv_id,
            "inv_title": inv.title,
            "inv_status": inv.status,
        }

        # Try to find position from tracker
        if tracker is not None:
            target = tracker.get(eid)
            if target is not None:
                pos = getattr(target, "position", None)
                if pos is not None:
                    entity["lat"] = getattr(pos, "lat", None) or pos.get("lat") if isinstance(pos, dict) else getattr(pos, "lat", None)
                    entity["lng"] = getattr(pos, "lng", None) or pos.get("lng") if isinstance(pos, dict) else getattr(pos, "lng", None)
                entity["name"] = getattr(target, "name", eid)
                entity["classification"] = getattr(target, "classification", "unknown")
                entity["alliance"] = getattr(target, "alliance", "unknown")
                entity["source"] = getattr(target, "source", "unknown")

        # Enrich with dossier data
        if engine._dossier_store is not None:
            dossier = engine._dossier_store.get_dossier(eid)
            if dossier:
                entity.setdefault("name", dossier.get("name", eid))
                entity["entity_type"] = dossier.get("entity_type", "unknown")
                entity["threat_level"] = dossier.get("threat_level", "none")
                # Dossier may have last known position
                if "lat" not in entity:
                    last_pos = dossier.get("last_position")
                    if last_pos and isinstance(last_pos, dict):
                        entity["lat"] = last_pos.get("lat")
                        entity["lng"] = last_pos.get("lng")

        # Only include entities that have a position
        if entity.get("lat") is not None and entity.get("lng") is not None:
            map_entities.append(entity)

    return {
        "inv_id": inv_id,
        "title": inv.title,
        "status": inv.status,
        "entities": map_entities,
        "total_entities": len(inv.all_entity_ids()),
        "positioned_entities": len(map_entities),
    }


@router.get("/active/map-overlay")
async def get_active_investigation_overlay(request: Request):
    """Return map overlay data for all open investigations.

    Combines entities from all open investigations into a single overlay
    suitable for rendering on the tactical map.
    """
    engine = _get_engine()
    if engine is None:
        return {"investigations": [], "entities": []}

    investigations = engine.list_investigations(status="open", limit=100, offset=0)
    if not investigations:
        return {"investigations": [], "entities": []}

    tracker = None
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        tracker = getattr(amy, "target_tracker", None)

    all_entities = []
    inv_summaries = []

    for inv in investigations:
        inv_summaries.append({
            "inv_id": inv.inv_id,
            "title": inv.title,
            "entity_count": len(inv.all_entity_ids()),
        })

        for eid in inv.all_entity_ids():
            entity = {
                "entity_id": eid,
                "is_seed": eid in inv.seed_entities,
                "inv_id": inv.inv_id,
                "inv_title": inv.title,
            }

            if tracker is not None:
                target = tracker.get(eid)
                if target is not None:
                    pos = getattr(target, "position", None)
                    if pos is not None:
                        entity["lat"] = getattr(pos, "lat", None) or (pos.get("lat") if isinstance(pos, dict) else None)
                        entity["lng"] = getattr(pos, "lng", None) or (pos.get("lng") if isinstance(pos, dict) else None)
                    entity["name"] = getattr(target, "name", eid)
                    entity["alliance"] = getattr(target, "alliance", "unknown")

            if entity.get("lat") is not None and entity.get("lng") is not None:
                all_entities.append(entity)

    return {
        "investigations": inv_summaries,
        "entities": all_entities,
    }


@router.post("/{inv_id}/report")
async def generate_report(inv_id: str):
    """Generate a structured IntelligenceReport from an investigation.

    Auto-populates entities, findings based on correlation data,
    and recommendations based on threat levels.  Uses the
    tritium-lib IntelligenceReport model.
    """
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    inv = engine.get(inv_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    try:
        from tritium_lib.models.report import (
            IntelligenceReport,
            ReportFinding,
            ReportRecommendation,
            ReportStatus,
        )
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="tritium-lib report models not available",
        )

    from datetime import datetime, timezone
    import uuid

    now = datetime.now(timezone.utc)

    # Build entity list
    all_entity_ids = sorted(inv.all_entity_ids())

    # Build findings from dossier data
    findings = []
    high_threat_count = 0
    entity_summaries = []

    if engine._dossier_store is not None:
        for eid in all_entity_ids:
            dossier = engine._dossier_store.get_dossier(eid)
            if not dossier:
                continue

            entity_type = dossier.get("entity_type", "unknown")
            threat_level = dossier.get("threat_level", "none")
            confidence = dossier.get("confidence", 0.0)
            name = dossier.get("name", eid[:12])

            entity_summaries.append(f"{name} ({entity_type}, threat={threat_level})")

            if threat_level in ("high", "critical"):
                high_threat_count += 1
                findings.append(ReportFinding(
                    finding_id=str(uuid.uuid4())[:8],
                    title=f"High-threat entity: {name}",
                    description=(
                        f"Entity {eid} classified as {entity_type} with "
                        f"threat level '{threat_level}' and confidence {confidence:.0%}."
                    ),
                    confidence=confidence,
                    evidence_refs=[eid],
                    tags=[threat_level, entity_type],
                ))

            # Check for correlation signals
            signals = dossier.get("signals", [])
            correlation_signals = [
                s for s in signals if s.get("signal_type") == "correlation"
            ]
            if correlation_signals:
                correlated_with = [
                    s.get("data", {}).get("correlated_with", "")
                    for s in correlation_signals
                    if s.get("data", {}).get("correlated_with")
                ]
                if correlated_with:
                    findings.append(ReportFinding(
                        finding_id=str(uuid.uuid4())[:8],
                        title=f"Correlation: {name} linked to {len(correlated_with)} entities",
                        description=(
                            f"Entity {name} has been correlated with: "
                            f"{', '.join(correlated_with[:5])}. "
                            f"Correlation may indicate co-location or shared activity."
                        ),
                        confidence=0.6,
                        evidence_refs=[eid] + correlated_with[:5],
                        tags=["correlation"],
                    ))

    # Add summary finding
    if entity_summaries:
        findings.insert(0, ReportFinding(
            finding_id=str(uuid.uuid4())[:8],
            title=f"Investigation scope: {len(all_entity_ids)} entities",
            description=(
                f"This investigation covers {len(all_entity_ids)} entities. "
                f"Seeds: {len(inv.seed_entities)}, "
                f"Discovered: {len(inv.discovered_entities)}. "
                f"Entities: {'; '.join(entity_summaries[:10])}"
                + ("..." if len(entity_summaries) > 10 else "")
            ),
            confidence=1.0,
            evidence_refs=all_entity_ids[:10],
            tags=["summary"],
        ))

    # Build recommendations based on threat levels
    recommendations = []
    if high_threat_count > 0:
        recommendations.append(ReportRecommendation(
            recommendation_id=str(uuid.uuid4())[:8],
            action=f"Escalate monitoring for {high_threat_count} high-threat entities",
            priority=1,
            rationale=(
                f"{high_threat_count} entities in this investigation have "
                f"high or critical threat levels requiring active monitoring."
            ),
        ))

    if len(inv.discovered_entities) > 0:
        recommendations.append(ReportRecommendation(
            recommendation_id=str(uuid.uuid4())[:8],
            action=f"Review {len(inv.discovered_entities)} discovered entities",
            priority=2,
            rationale=(
                f"Graph expansion discovered {len(inv.discovered_entities)} "
                f"related entities that may require analyst review."
            ),
        ))

    if len(inv.annotations) == 0:
        recommendations.append(ReportRecommendation(
            recommendation_id=str(uuid.uuid4())[:8],
            action="Add analyst annotations to investigation entities",
            priority=3,
            rationale="No analyst annotations have been added yet.",
        ))

    # Build the report
    report = IntelligenceReport(
        report_id=str(uuid.uuid4()),
        title=f"Report: {inv.title}",
        summary=(
            f"Intelligence report generated from investigation '{inv.title}' "
            f"covering {len(all_entity_ids)} entities with "
            f"{len(findings)} findings and {len(recommendations)} recommendations."
        ),
        entities=all_entity_ids,
        findings=findings,
        recommendations=recommendations,
        created_by="system",
        status=ReportStatus.DRAFT,
        created_at=now,
        updated_at=now,
        tags=["auto-generated", f"inv:{inv_id[:8]}"],
        source_investigation=inv_id,
    )

    return report.model_dump(mode="json")


@router.post("/{inv_id}/filter/type")
async def filter_by_type(
    inv_id: str,
    entity_types: list[str] = Body(..., embed=True),
):
    """Filter investigation entities by entity type."""
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    if not entity_types:
        raise HTTPException(status_code=400, detail="At least one entity type is required")

    filtered = engine.filter_by_type(inv_id, entity_types)
    return {"inv_id": inv_id, "filtered_entities": filtered, "count": len(filtered)}


@router.get("/{inv_id}/timeline")
async def get_investigation_timeline(
    inv_id: str,
    limit: int = Query(200, ge=1, le=1000),
):
    """Return a chronological timeline of all events for investigation entities.

    Collects signals from all entity dossiers in the investigation and
    returns them sorted by timestamp with entity metadata for rendering
    an investigation-scoped timeline panel.
    """
    engine = _get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Investigation engine unavailable")

    inv = engine.get(inv_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")

    # Entity type icons for frontend rendering
    ENTITY_ICONS = {
        "person": "P",
        "vehicle": "V",
        "device": "D",
        "animal": "A",
        "unknown": "?",
    }

    # Event type colors for frontend rendering
    EVENT_COLORS = {
        "mac_sighting": "#00f0ff",
        "visual_detection": "#05ffa1",
        "correlation": "#b48eff",
        "probe_request": "#fcee0a",
        "enrichment": "#fcee0a",
        "classification": "#ff2a6d",
        "geofence": "#ff2a6d",
        "tracker_sync": "#888888",
    }

    timeline_events = []

    if engine._dossier_store is not None:
        for eid in inv.all_entity_ids():
            dossier = engine._dossier_store.get_dossier(eid)
            if not dossier:
                continue

            entity_name = dossier.get("name", eid[:12])
            entity_type = dossier.get("entity_type", "unknown")
            entity_icon = ENTITY_ICONS.get(entity_type, "?")

            for signal in dossier.get("signals", []):
                signal_type = signal.get("signal_type", "unknown")
                event = {
                    "timestamp": signal.get("timestamp", 0),
                    "entity_id": eid,
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "entity_icon": entity_icon,
                    "is_seed": eid in inv.seed_entities,
                    "signal_id": signal.get("signal_id", ""),
                    "signal_type": signal_type,
                    "source": signal.get("source", "unknown"),
                    "confidence": signal.get("confidence", 0.0),
                    "color": EVENT_COLORS.get(signal_type, "#888888"),
                    "data": signal.get("data", {}),
                }

                # Add position if available
                pos = signal.get("position")
                if pos and isinstance(pos, (list, tuple)) and len(pos) >= 2:
                    event["position"] = {"x": pos[0], "y": pos[1]}

                timeline_events.append(event)

            # Include annotations as timeline events
            for ann in inv.annotations:
                if ann.entity_id == eid or ann.entity_id == "":
                    timeline_events.append({
                        "timestamp": ann.timestamp,
                        "entity_id": ann.entity_id or "investigation",
                        "entity_name": entity_name if ann.entity_id == eid else "Investigation",
                        "entity_type": entity_type if ann.entity_id == eid else "system",
                        "entity_icon": entity_icon if ann.entity_id == eid else "N",
                        "is_seed": False,
                        "signal_id": ann.annotation_id,
                        "signal_type": "annotation",
                        "source": ann.analyst,
                        "confidence": 1.0,
                        "color": "#ffffff",
                        "data": {"note": ann.note, "analyst": ann.analyst},
                    })

    # Sort by timestamp ascending (chronological)
    timeline_events.sort(key=lambda e: e.get("timestamp", 0))

    # Apply limit (most recent events)
    if len(timeline_events) > limit:
        timeline_events = timeline_events[-limit:]

    return {
        "inv_id": inv_id,
        "title": inv.title,
        "status": inv.status,
        "events": timeline_events,
        "total_events": len(timeline_events),
        "entity_count": len(inv.all_entity_ids()),
    }
