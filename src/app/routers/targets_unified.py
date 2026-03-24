# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unified target tracking endpoint — real + virtual targets."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["targets"])


class TagRequest(BaseModel):
    """Alliance tag update for a target."""
    alliance: str  # friendly, hostile, unknown, vip


def _get_tracker(request: Request):
    """Get target tracker from Amy, or fall back to simulation engine targets."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        tracker = getattr(amy, "target_tracker", None)
        if tracker is not None:
            return tracker
    return None


def _get_sim_engine(request: Request):
    """Get simulation engine (headless fallback when Amy is disabled)."""
    return getattr(request.app.state, "simulation_engine", None)


@router.get("/targets")
async def get_targets(
    request: Request,
    source: Optional[str] = Query(None, description="Filter by source: real, sim, graphling"),
):
    """Return all tracked targets (simulation + YOLO detections).

    Optional query parameter ``source`` filters by target source classification:
    - ``real`` — physical hardware / YOLO-detected targets
    - ``sim`` — locally simulated targets
    - ``graphling`` — remote Graphlings agents
    """
    tracker = _get_tracker(request)
    if tracker is not None:
        targets = tracker.get_all()
        dicts = [t.to_dict() for t in targets]
        if source:
            # TrackedTarget.source uses "yolo"/"simulation"/"manual"; map to
            # SimulationTarget convention for filtering consistency.
            _source_map = {"real": "yolo", "sim": "simulation"}
            tracker_source = _source_map.get(source, source)
            dicts = [d for d in dicts if d.get("source") == tracker_source]
        return {
            "targets": dicts,
            "summary": tracker.summary(),
        }

    # Headless mode: read targets directly from simulation engine
    engine = _get_sim_engine(request)
    if engine is not None:
        targets = engine.get_targets()
        if source:
            # Apply same source mapping as tracker path for consistency.
            _source_map = {"real": "yolo", "sim": "simulation"}
            # SimulationTarget.source uses short names ("sim", "real", "graphling"),
            # while TrackedTarget uses long names ("simulation", "yolo").
            # Accept both conventions.
            mapped = _source_map.get(source, source)
            targets = [
                t for t in targets if t.source == source or t.source == mapped
            ]
        return {
            "targets": [t.to_dict() for t in targets],
            "summary": f"{len(targets)} simulation targets",
        }

    return {"targets": [], "summary": "No tracking available"}


@router.get("/targets/hostiles")
async def get_hostiles(request: Request):
    """Return only hostile targets."""
    tracker = _get_tracker(request)
    if tracker is not None:
        return {"targets": [t.to_dict() for t in tracker.get_hostiles()]}

    engine = _get_sim_engine(request)
    if engine is not None:
        targets = [t for t in engine.get_targets() if t.alliance == "hostile"]
        return {"targets": [t.to_dict() for t in targets]}

    return {"targets": []}


@router.get("/targets/friendlies")
async def get_friendlies(request: Request):
    """Return only friendly targets."""
    tracker = _get_tracker(request)
    if tracker is not None:
        return {"targets": [t.to_dict() for t in tracker.get_friendlies()]}

    engine = _get_sim_engine(request)
    if engine is not None:
        targets = [t for t in engine.get_targets() if t.alliance == "friendly"]
        return {"targets": [t.to_dict() for t in targets]}

    return {"targets": []}


VALID_ALLIANCES = {"friendly", "hostile", "unknown", "vip", "neutral"}


@router.post("/targets/{target_id}/tag")
async def tag_target(request: Request, target_id: str, body: TagRequest):
    """Tag a target with an alliance (friendly, hostile, unknown, vip).

    Updates the live TargetTracker immediately. UX Loop 6: Investigate a Target.
    """
    if body.alliance not in VALID_ALLIANCES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid alliance '{body.alliance}'. Must be one of: {sorted(VALID_ALLIANCES)}",
        )

    tracker = _get_tracker(request)
    if tracker is None:
        raise HTTPException(status_code=503, detail="Target tracker not available")

    target = tracker.get_target(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Target not found: {target_id}")

    old_alliance = target.alliance
    target.alliance = body.alliance

    # Persist in dossier if available
    dossier_mgr = getattr(request.app.state, "dossier_manager", None)
    if dossier_mgr is not None:
        try:
            dossier_mgr.add_note(
                target_id,
                f"Alliance tagged: {old_alliance} -> {body.alliance}",
            )
            dossier_mgr.update_field(target_id, "alliance", body.alliance)
        except Exception:
            pass

    # Broadcast via WebSocket
    try:
        from app.routers.ws import manager as ws_manager
        await ws_manager.broadcast({
            "type": "target_tagged",
            "data": {
                "target_id": target_id,
                "alliance": body.alliance,
                "old_alliance": old_alliance,
            },
        })
    except Exception:
        pass

    return {
        "status": "ok",
        "target_id": target_id,
        "alliance": body.alliance,
        "old_alliance": old_alliance,
    }


@router.get("/targets/{target_id}/trail")
async def get_target_trail(
    request: Request,
    target_id: str,
    max_points: int = Query(100, ge=1, le=1000, description="Max trail points"),
):
    """Return position history trail for a specific target."""
    tracker = _get_tracker(request)
    if tracker is None:
        return {"error": "No tracker available", "trail": []}

    target = tracker.get_target(target_id)
    if target is None:
        return {"error": "Target not found", "trail": []}

    trail = tracker.history.get_trail_dicts(target_id, max_points=max_points)
    return {
        "target_id": target_id,
        "trail": trail,
        "speed": tracker.history.get_speed(target_id),
        "heading": tracker.history.get_heading(target_id),
        "point_count": len(trail),
    }


@router.get("/targets/{target_id}/trail/gpx")
async def export_target_trail_gpx_direct(
    request: Request,
    target_id: str,
    start_time: Optional[str] = Query(None, description="Start time filter (ISO8601)"),
    end_time: Optional[str] = Query(None, description="End time filter (ISO8601)"),
    simplify: bool = Query(False, description="Simplify trail points using RDP algorithm"),
    max_points: int = Query(10000, ge=1, le=100000, description="Max trail points"),
):
    """Export target trail as GPX 1.1 XML.

    Direct GPX endpoint for ATAK, Google Earth, and any GPX-compatible
    GIS application. Returns ``application/gpx+xml`` content type.

    Query parameters:
    - ``start_time`` / ``end_time`` — ISO8601 time window filter
    - ``simplify`` — reduce point count using Ramer-Douglas-Peucker
    - ``max_points`` — maximum number of trail points to return
    """
    from fastapi.responses import Response
    from tritium_lib.models.gpx import GPXDocument
    from tritium_lib.models.trail_export import TrailExport, TrailPoint, TrailFormat

    tracker = _get_tracker(request)
    if tracker is None:
        return {"error": "No tracker available"}

    target = tracker.get_target(target_id)
    if target is None:
        return {"error": "Target not found"}

    trail = tracker.history.get_trail_dicts(target_id, max_points=max_points)
    trail = _filter_trail_by_time(trail, start_time, end_time)
    target_dict = target.to_dict()
    safe_id = target_id.replace("/", "_").replace("\\", "_")

    # Build TrailExport model for optional simplification
    if simplify and len(trail) > 2:
        export_model = TrailExport(
            target_id=target_id,
            format=TrailFormat.GPX,
            points=[TrailPoint.from_dict(_normalize_trail_pt(pt)) for pt in trail],
        )
        export_model = export_model.simplify()
        # Rebuild trail from simplified points
        trail = [p.to_dict() for p in export_model.points]

    doc = GPXDocument(
        creator="Tritium Command Center",
        name=f"Target {target_id} trail",
        desc=f"Movement trail for target {target_id}",
    )
    trk = doc.add_track(name=target_id, desc=target_dict.get("name", ""))

    for pt in trail:
        lat, lng = _extract_lat_lng(pt)
        ele = pt.get("ele", pt.get("altitude", pt.get("alt")))
        t_dt = _parse_trail_time(pt)
        trk.add_point(lat, lng, ele=ele, time=t_dt)

    if trail:
        first = trail[0]
        last = trail[-1]
        for label, pt_data in [("First seen", first), ("Last seen", last)]:
            lat, lng = _extract_lat_lng(pt_data)
            doc.add_waypoint(lat, lng, name=f"{target_id} - {label}", sym="Flag")

    return Response(
        content=doc.to_xml(),
        media_type="application/gpx+xml",
        headers={
            "Content-Disposition": f"attachment; filename={safe_id}_trail.gpx",
        },
    )


@router.get("/targets/{target_id}/trail/kml")
async def export_target_trail_kml(
    request: Request,
    target_id: str,
    start_time: Optional[str] = Query(None, description="Start time filter (ISO8601)"),
    end_time: Optional[str] = Query(None, description="End time filter (ISO8601)"),
    simplify: bool = Query(False, description="Simplify trail points using RDP algorithm"),
    max_points: int = Query(10000, ge=1, le=100000, description="Max trail points"),
):
    """Export target trail as KML 2.2 XML.

    For Google Earth, ATAK, and any KML-compatible GIS application.
    Returns ``application/vnd.google-earth.kml+xml`` content type.

    Query parameters:
    - ``start_time`` / ``end_time`` — ISO8601 time window filter
    - ``simplify`` — reduce point count using Ramer-Douglas-Peucker
    - ``max_points`` — maximum number of trail points to return
    """
    from fastapi.responses import Response
    from tritium_lib.models.kml import KMLDocument
    from tritium_lib.models.trail_export import TrailExport, TrailPoint, TrailFormat

    tracker = _get_tracker(request)
    if tracker is None:
        return {"error": "No tracker available"}

    target = tracker.get_target(target_id)
    if target is None:
        return {"error": "Target not found"}

    trail = tracker.history.get_trail_dicts(target_id, max_points=max_points)
    trail = _filter_trail_by_time(trail, start_time, end_time)
    target_dict = target.to_dict()
    safe_id = target_id.replace("/", "_").replace("\\", "_")

    # Build TrailExport model for optional simplification
    if simplify and len(trail) > 2:
        export_model = TrailExport(
            target_id=target_id,
            format=TrailFormat.KML,
            points=[TrailPoint.from_dict(_normalize_trail_pt(pt)) for pt in trail],
        )
        export_model = export_model.simplify()
        trail = [p.to_dict() for p in export_model.points]

    doc = KMLDocument(
        name=f"Target {target_id} trail",
        desc=f"Movement trail for target {target_id}",
    )
    trk = doc.add_track(name=target_id, desc=target_dict.get("name", ""))

    for pt in trail:
        lat, lng = _extract_lat_lng(pt)
        alt = pt.get("alt", pt.get("ele", pt.get("altitude")))
        t_dt = _parse_trail_time(pt)
        trk.add_point(lat, lng, alt=alt, time=t_dt)

    # Add start/end placemarks
    if trail:
        first = trail[0]
        last = trail[-1]
        for label, pt_data in [("First seen", first), ("Last seen", last)]:
            lat, lng = _extract_lat_lng(pt_data)
            doc.add_placemark(lat, lng, name=f"{target_id} - {label}")

    return Response(
        content=doc.to_xml(),
        media_type="application/vnd.google-earth.kml+xml",
        headers={
            "Content-Disposition": f"attachment; filename={safe_id}_trail.kml",
        },
    )


def _extract_lat_lng(pt: dict) -> tuple[float, float]:
    """Extract lat/lng from a trail point dict, falling back to x/y."""
    lat = pt.get("lat", 0.0) or 0.0
    lng = pt.get("lng", pt.get("lon", 0.0)) or 0.0
    if lat == 0.0 and lng == 0.0:
        lng = pt.get("x", 0.0)
        lat = pt.get("y", 0.0)
    return lat, lng


def _parse_trail_time(pt: dict):
    """Parse a trail point's time field into a datetime, or None."""
    t_str = pt.get("time", pt.get("timestamp"))
    if t_str is None:
        return None
    try:
        from datetime import datetime as dt_cls
        if isinstance(t_str, (int, float)):
            from datetime import timezone as tz
            return dt_cls.fromtimestamp(t_str, tz=tz.utc)
        return dt_cls.fromisoformat(str(t_str))
    except Exception:
        return None


def _normalize_trail_pt(pt: dict) -> dict:
    """Normalize a trail point dict for TrailPoint.from_dict()."""
    lat, lng = _extract_lat_lng(pt)
    return {
        "lat": lat,
        "lng": lng,
        "alt": pt.get("alt", pt.get("ele", pt.get("altitude"))),
        "timestamp": pt.get("time", pt.get("timestamp")),
        "speed": pt.get("speed"),
        "heading": pt.get("heading"),
        "confidence": pt.get("confidence"),
    }


def _filter_trail_by_time(trail: list[dict], start_time: str | None, end_time: str | None) -> list[dict]:
    """Filter trail points by ISO8601 time window."""
    if not start_time and not end_time:
        return trail

    from datetime import datetime as dt_cls

    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = dt_cls.fromisoformat(start_time)
        except ValueError:
            pass
    if end_time:
        try:
            end_dt = dt_cls.fromisoformat(end_time)
        except ValueError:
            pass

    if start_dt is None and end_dt is None:
        return trail

    filtered = []
    for pt in trail:
        t_dt = _parse_trail_time(pt)
        if t_dt is None:
            filtered.append(pt)  # keep points without timestamps
            continue
        # Make comparison timezone-aware if needed
        if start_dt and t_dt.tzinfo and not start_dt.tzinfo:
            from datetime import timezone as tz
            start_dt = start_dt.replace(tzinfo=tz.utc)
        if end_dt and t_dt.tzinfo and not end_dt.tzinfo:
            from datetime import timezone as tz
            end_dt = end_dt.replace(tzinfo=tz.utc)
        if start_dt and t_dt < start_dt:
            continue
        if end_dt and t_dt > end_dt:
            continue
        filtered.append(pt)
    return filtered


@router.get("/targets/{target_id}/trail/export")
async def export_target_trail_gpx(
    request: Request,
    target_id: str,
    format: str = Query("gpx", description="Export format: gpx, kml, csv, json, geojson"),
    max_points: int = Query(10000, ge=1, le=100000, description="Max trail points"),
    start_time: Optional[str] = Query(None, description="Start time filter (ISO8601)"),
    end_time: Optional[str] = Query(None, description="End time filter (ISO8601)"),
    simplify: bool = Query(False, description="Simplify trail points using RDP algorithm"),
):
    """Export a target's movement trail for external mapping tools.

    Default format is GPX for direct import into ATAK, Google Earth,
    or any GPX-compatible GIS application.

    Supported formats:
    - ``gpx`` — GPX 1.1 XML (default, for ATAK/Google Earth)
    - ``kml`` — KML 2.2 XML (for Google Earth)
    - ``geojson`` — GeoJSON Feature with LineString geometry (web-friendly)
    - ``csv`` / ``json`` — delegates to history/export
    """
    fmt = format.lower().strip()

    # Delegate to dedicated endpoints for GPX and KML
    if fmt == "gpx":
        return await export_target_trail_gpx_direct(
            request, target_id, start_time=start_time, end_time=end_time,
            simplify=simplify, max_points=max_points,
        )
    if fmt == "kml":
        return await export_target_trail_kml(
            request, target_id, start_time=start_time, end_time=end_time,
            simplify=simplify, max_points=max_points,
        )

    # GeoJSON: direct implementation for trail-specific export
    if fmt == "geojson":
        import json
        from fastapi.responses import Response

        tracker = _get_tracker(request)
        if tracker is None:
            return {"error": "No tracker available"}

        target = tracker.get_target(target_id)
        if target is None:
            return {"error": "Target not found"}

        trail = tracker.history.get_trail_dicts(target_id, max_points=max_points)
        target_dict = target.to_dict()
        safe_id = target_id.replace("/", "_").replace("\\", "_")

        coordinates: list[list[float]] = []
        timestamps: list = []
        speeds: list = []
        headings: list = []

        for pt in trail:
            lat = pt.get("lat", 0.0) or 0.0
            lng = pt.get("lng", 0.0) or 0.0
            if lat == 0.0 and lng == 0.0:
                lng = pt.get("x", 0.0)
                lat = pt.get("y", 0.0)
            ele = pt.get("ele", pt.get("altitude"))
            coord = [lng, lat]
            if ele is not None:
                coord.append(float(ele))
            coordinates.append(coord)
            timestamps.append(pt.get("time", pt.get("timestamp", "")))
            speeds.append(pt.get("speed", None))
            headings.append(pt.get("heading", None))

        # Build GeoJSON Feature with LineString
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coordinates,
                    } if len(coordinates) >= 2 else {
                        "type": "Point",
                        "coordinates": coordinates[0] if coordinates else [0, 0],
                    },
                    "properties": {
                        "target_id": target_id,
                        "name": target_dict.get("name", ""),
                        "alliance": target_dict.get("alliance", ""),
                        "source": target_dict.get("source", ""),
                        "classification": target_dict.get("classification",
                                                          target_dict.get("asset_type", "")),
                        "point_count": len(trail),
                        "timestamps": timestamps,
                        "speeds": [s for s in speeds if s is not None],
                        "headings": [h for h in headings if h is not None],
                    },
                },
            ],
        }

        # Add start/end waypoints as Point features
        if trail:
            for label, idx in [("start", 0), ("end", -1)]:
                pt = trail[idx]
                lat = pt.get("lat", 0.0) or pt.get("y", 0.0) or 0.0
                lng = pt.get("lng", 0.0) or pt.get("x", 0.0) or 0.0
                geojson["features"].append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lng, lat]},
                    "properties": {
                        "marker": label,
                        "target_id": target_id,
                        "timestamp": pt.get("time", pt.get("timestamp", "")),
                    },
                })

        return Response(
            content=json.dumps(geojson, default=str),
            media_type="application/geo+json",
            headers={
                "Content-Disposition": f"attachment; filename={safe_id}_trail.geojson",
            },
        )

    # Delegate non-GPX/non-GeoJSON formats to existing history/export
    if fmt != "gpx":
        return await export_target_history(
            request, target_id, format=format, max_points=max_points,
        )

    from fastapi.responses import Response
    from tritium_lib.models.gpx import GPXDocument

    tracker = _get_tracker(request)
    if tracker is None:
        return {"error": "No tracker available"}

    target = tracker.get_target(target_id)
    if target is None:
        return {"error": "Target not found"}

    trail = tracker.history.get_trail_dicts(target_id, max_points=max_points)
    target_dict = target.to_dict()
    safe_id = target_id.replace("/", "_").replace("\\", "_")

    doc = GPXDocument(
        creator="Tritium Command Center",
        name=f"Target {target_id} trail",
        desc=f"Movement trail for target {target_id}",
    )
    trk = doc.add_track(name=target_id, desc=target_dict.get("name", ""))

    for pt in trail:
        lat = pt.get("lat", 0.0) or 0.0
        lng = pt.get("lng", 0.0) or 0.0
        if lat == 0.0 and lng == 0.0:
            lng = pt.get("x", 0.0)
            lat = pt.get("y", 0.0)
        ele = pt.get("ele", pt.get("altitude"))
        t_str = pt.get("time", pt.get("timestamp"))
        t_dt = None
        if t_str:
            try:
                from datetime import datetime as dt_cls
                if isinstance(t_str, (int, float)):
                    from datetime import timezone as tz
                    t_dt = dt_cls.fromtimestamp(t_str, tz=tz.utc)
                else:
                    t_dt = dt_cls.fromisoformat(str(t_str))
            except Exception:
                pass
        trk.add_point(lat, lng, ele=ele, time=t_dt)

    if trail:
        first = trail[0]
        last = trail[-1]
        for label, pt_data in [("First seen", first), ("Last seen", last)]:
            lat = pt_data.get("lat", 0.0) or pt_data.get("y", 0.0) or 0.0
            lng = pt_data.get("lng", 0.0) or pt_data.get("x", 0.0) or 0.0
            doc.add_waypoint(lat, lng, name=f"{target_id} - {label}", sym="Flag")

    return Response(
        content=doc.to_xml(),
        media_type="application/gpx+xml",
        headers={
            "Content-Disposition": f"attachment; filename={safe_id}_trail.gpx",
        },
    )


@router.get("/targets/predictions")
async def get_target_predictions(
    request: Request,
    horizons: str = Query("1,5,15", description="Comma-separated prediction horizons in minutes"),
):
    """Return predicted future positions for all moving targets.

    For each target with sufficient movement history, returns predicted
    positions at the specified horizons (default 1, 5, 15 minutes) with
    confidence cones.  Stationary targets are excluded.
    """
    tracker = _get_tracker(request)
    if tracker is None:
        return {"predictions": {}, "target_count": 0}

    horizon_list = [int(h.strip()) for h in horizons.split(",") if h.strip().isdigit()]
    if not horizon_list:
        horizon_list = [1, 5, 15]

    from engine.tactical.target_prediction import predict_all_targets

    target_ids = [t.target_id for t in tracker.get_all()]
    predictions = predict_all_targets(target_ids, tracker.history, horizons=horizon_list)

    # Serialize with geo coordinates
    from engine.tactical.geo import local_to_latlng

    result = {}
    for tid, preds in predictions.items():
        result[tid] = []
        for p in preds:
            d = p.to_dict()
            geo = local_to_latlng(p.x, p.y)
            d["lat"] = geo["lat"]
            d["lng"] = geo["lng"]
            result[tid].append(d)

    return {
        "predictions": result,
        "target_count": len(result),
        "horizons": horizon_list,
    }


@router.get("/targets/{target_id}/predictions")
async def get_single_target_predictions(
    request: Request,
    target_id: str,
    horizons: str = Query("1,5,15", description="Comma-separated prediction horizons in minutes"),
):
    """Return predicted future positions for a specific target."""
    tracker = _get_tracker(request)
    if tracker is None:
        return {"error": "No tracker available", "predictions": []}

    target = tracker.get_target(target_id)
    if target is None:
        return {"error": "Target not found", "predictions": []}

    horizon_list = [int(h.strip()) for h in horizons.split(",") if h.strip().isdigit()]
    if not horizon_list:
        horizon_list = [1, 5, 15]

    from engine.tactical.target_prediction import predict_target
    from engine.tactical.geo import local_to_latlng

    preds = predict_target(target_id, tracker.history, horizons=horizon_list)
    result = []
    for p in preds:
        d = p.to_dict()
        geo = local_to_latlng(p.x, p.y)
        d["lat"] = geo["lat"]
        d["lng"] = geo["lng"]
        result.append(d)

    return {
        "target_id": target_id,
        "predictions": result,
        "moving": len(result) > 0,
    }


@router.get("/targets/clusters")
async def get_target_clusters(
    request: Request,
    zoom: float = Query(16.0, ge=1, le=22, description="Map zoom level"),
    cell_size: Optional[float] = Query(
        None, ge=0.00001, le=1.0,
        description="Override grid cell size in degrees (auto if omitted)",
    ),
):
    """Return targets grouped into spatial clusters for map readability.

    At high zoom levels, returns all targets as singles with no clusters.
    At lower zoom levels, nearby targets are merged into cluster objects
    showing count, center position, and dominant alliance/type.
    """
    tracker = _get_tracker(request)
    all_targets: list[dict] = []

    if tracker is not None:
        all_targets = [t.to_dict() for t in tracker.get_all()]
    else:
        engine = _get_sim_engine(request)
        if engine is not None:
            all_targets = [t.to_dict() for t in engine.get_targets()]

    # Determine cell size from zoom if not overridden
    if cell_size is None:
        if zoom >= 18:
            cell_size = 0.0
        elif zoom >= 17:
            cell_size = 0.0002
        elif zoom >= 16:
            cell_size = 0.0005
        elif zoom >= 15:
            cell_size = 0.001
        elif zoom >= 14:
            cell_size = 0.002
        elif zoom >= 13:
            cell_size = 0.005
        else:
            cell_size = 0.01

    if cell_size == 0.0 or not all_targets:
        return {
            "singles": all_targets,
            "clusters": [],
            "total_targets": len(all_targets),
            "zoom": zoom,
        }

    # Grid-based spatial clustering
    import math

    grid: dict[str, list[dict]] = {}
    no_position: list[dict] = []

    for t in all_targets:
        lat = t.get("lat", 0.0) or 0.0
        lng = t.get("lng", 0.0) or 0.0
        if lat == 0.0 and lng == 0.0:
            no_position.append(t)
            continue
        cx = math.floor(lng / cell_size)
        cy = math.floor(lat / cell_size)
        key = f"{cx}:{cy}"
        grid.setdefault(key, []).append(t)

    singles = list(no_position)
    clusters = []

    for key, members in grid.items():
        if len(members) < 2:
            singles.extend(members)
            continue

        sum_lat = sum(m.get("lat", 0.0) or 0.0 for m in members)
        sum_lng = sum(m.get("lng", 0.0) or 0.0 for m in members)
        count = len(members)

        # Compute dominant alliance and type
        alliance_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for m in members:
            a = m.get("alliance", "unknown") or "unknown"
            alliance_counts[a] = alliance_counts.get(a, 0) + 1
            at = m.get("asset_type", "unknown") or "unknown"
            type_counts[at] = type_counts.get(at, 0) + 1

        clusters.append({
            "cluster_id": f"cluster_{len(clusters)}",
            "lat": sum_lat / count,
            "lng": sum_lng / count,
            "count": count,
            "dominant_alliance": max(alliance_counts, key=alliance_counts.get),
            "dominant_type": max(type_counts, key=type_counts.get),
            "target_ids": [m.get("target_id", "") for m in members],
        })

    return {
        "singles": singles,
        "clusters": clusters,
        "total_targets": len(all_targets),
        "zoom": zoom,
    }


@router.get("/targets/export")
async def export_targets(
    request: Request,
    format: str = Query("json", description="Export format: json, csv, geojson, or cot"),
):
    """Export all current targets in standard formats for external analysis.

    Supported formats:
    - ``json`` — Array of target dicts
    - ``csv`` — Comma-separated values with header row
    - ``geojson`` — GeoJSON FeatureCollection with Point geometries
    - ``cot`` — Cursor on Target XML for ATAK/WinTAK interoperability
    """
    from fastapi.responses import Response

    tracker = _get_tracker(request)
    all_targets: list[dict] = []

    if tracker is not None:
        all_targets = [t.to_dict() for t in tracker.get_all()]
    else:
        engine = _get_sim_engine(request)
        if engine is not None:
            all_targets = [t.to_dict() for t in engine.get_targets()]

    fmt = format.lower().strip()

    if fmt == "csv":
        import csv
        import io

        if not all_targets:
            return Response(
                content="target_id,name,type,alliance,lat,lng,source,confidence\n",
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=targets.csv"},
            )

        # Collect all keys
        all_keys = set()
        for t in all_targets:
            all_keys.update(t.keys())
        # Priority columns first, then alphabetical remainder
        priority = ["target_id", "name", "type", "asset_type", "alliance", "lat", "lng",
                     "source", "confidence", "rssi", "heading", "speed", "health"]
        ordered_keys = [k for k in priority if k in all_keys]
        ordered_keys += sorted(k for k in all_keys if k not in priority)

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=ordered_keys, extrasaction="ignore")
        writer.writeheader()
        for t in all_targets:
            # Flatten nested position
            row = dict(t)
            if "position" in row and isinstance(row["position"], dict):
                pos = row.pop("position")
                row.setdefault("pos_x", pos.get("x"))
                row.setdefault("pos_y", pos.get("y"))
            writer.writerow(row)

        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=targets.csv"},
        )

    elif fmt == "geojson":
        import json

        features = []
        for t in all_targets:
            lat = t.get("lat", 0.0) or 0.0
            lng = t.get("lng", 0.0) or 0.0
            # Fall back to position x/y if no lat/lng
            if lat == 0.0 and lng == 0.0:
                pos = t.get("position", {})
                if isinstance(pos, dict):
                    lng = pos.get("x", 0.0)
                    lat = pos.get("y", 0.0)

            props = {k: v for k, v in t.items()
                     if k not in ("lat", "lng", "position") and not isinstance(v, (dict, list))}

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lng, lat],
                },
                "properties": props,
            })

        geojson = {
            "type": "FeatureCollection",
            "features": features,
        }

        return Response(
            content=json.dumps(geojson, default=str),
            media_type="application/geo+json",
            headers={"Content-Disposition": "attachment; filename=targets.geojson"},
        )

    elif fmt == "cot":
        # Cursor on Target XML for ATAK/WinTAK
        try:
            from tritium_lib.models.tak_export import targets_to_cot_file
            cot_xml = targets_to_cot_file(all_targets)
        except ImportError:
            # Fall back to engine's cot module for individual events
            from engine.comms.cot import target_to_cot_xml
            parts = ['<?xml version="1.0" encoding="UTF-8"?>']
            parts.append(f'<cot-events version="1.0" count="{len(all_targets)}">')
            for t in all_targets:
                parts.append(target_to_cot_xml(t))
            parts.append('</cot-events>')
            cot_xml = "\n".join(parts)

        return Response(
            content=cot_xml,
            media_type="application/xml",
            headers={"Content-Disposition": "attachment; filename=targets.cot.xml"},
        )

    else:
        # Default: JSON array
        import json
        return Response(
            content=json.dumps(all_targets, default=str),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=targets.json"},
        )


@router.get("/targets/{target_id}/history/export")
async def export_target_history(
    request: Request,
    target_id: str,
    format: str = Query("csv", description="Export format: csv, json, or geojson"),
    max_points: int = Query(10000, ge=1, le=100000, description="Max history points"),
):
    """Export full position history of a specific target for external analysis.

    Supported formats:
    - ``csv`` — Comma-separated with header (timestamp, lat, lng, x, y, heading, speed)
    - ``json`` — Array of position records
    - ``geojson`` — GeoJSON LineString geometry with point timestamps
    """
    from fastapi.responses import Response

    tracker = _get_tracker(request)
    if tracker is None:
        return {"error": "No tracker available"}

    target = tracker.get_target(target_id)
    if target is None:
        return {"error": "Target not found"}

    trail = tracker.history.get_trail_dicts(target_id, max_points=max_points)

    # Also include current target metadata
    target_dict = target.to_dict()

    fmt = format.lower().strip()
    safe_id = target_id.replace("/", "_").replace("\\", "_")

    if fmt == "csv":
        import csv
        import io

        buf = io.StringIO()
        fieldnames = ["timestamp", "lat", "lng", "x", "y", "heading", "speed", "confidence"]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for pt in trail:
            writer.writerow({
                "timestamp": pt.get("time", pt.get("timestamp", "")),
                "lat": pt.get("lat", ""),
                "lng": pt.get("lng", ""),
                "x": pt.get("x", ""),
                "y": pt.get("y", ""),
                "heading": pt.get("heading", ""),
                "speed": pt.get("speed", ""),
                "confidence": pt.get("confidence", ""),
            })

        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={safe_id}_history.csv",
            },
        )

    elif fmt == "gpx":
        from tritium_lib.models.gpx import GPXDocument

        doc = GPXDocument(
            creator="Tritium Command Center",
            name=f"Target {target_id} trail",
            desc=f"Movement trail for target {target_id}",
        )
        trk = doc.add_track(name=target_id, desc=target_dict.get("name", ""))

        for pt in trail:
            lat = pt.get("lat", 0.0) or 0.0
            lng = pt.get("lng", 0.0) or 0.0
            if lat == 0.0 and lng == 0.0:
                # Fall back to local x/y as pseudo-coords
                lng = pt.get("x", 0.0)
                lat = pt.get("y", 0.0)
            ele = pt.get("ele", pt.get("altitude"))
            t_str = pt.get("time", pt.get("timestamp"))
            t_dt = None
            if t_str:
                try:
                    from datetime import datetime as dt_cls
                    if isinstance(t_str, (int, float)):
                        from datetime import timezone as tz
                        t_dt = dt_cls.fromtimestamp(t_str, tz=tz.utc)
                    else:
                        t_dt = dt_cls.fromisoformat(str(t_str))
                except Exception:
                    pass
            trk.add_point(lat, lng, ele=ele, time=t_dt)

        # Add first/last seen as waypoints
        if trail:
            first = trail[0]
            last = trail[-1]
            for label, pt_data in [("First seen", first), ("Last seen", last)]:
                lat = pt_data.get("lat", 0.0) or pt_data.get("y", 0.0) or 0.0
                lng = pt_data.get("lng", 0.0) or pt_data.get("x", 0.0) or 0.0
                doc.add_waypoint(lat, lng, name=f"{target_id} - {label}", sym="Flag")

        return Response(
            content=doc.to_xml(),
            media_type="application/gpx+xml",
            headers={
                "Content-Disposition": f"attachment; filename={safe_id}_trail.gpx",
            },
        )

    elif fmt == "geojson":
        import json

        coordinates = []
        timestamps = []
        for pt in trail:
            lat = pt.get("lat", 0.0) or 0.0
            lng = pt.get("lng", 0.0) or 0.0
            if lat == 0.0 and lng == 0.0:
                lng = pt.get("x", 0.0)
                lat = pt.get("y", 0.0)
            coordinates.append([lng, lat])
            timestamps.append(pt.get("time", pt.get("timestamp", "")))

        geojson = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates,
            },
            "properties": {
                "target_id": target_id,
                "name": target_dict.get("name", ""),
                "alliance": target_dict.get("alliance", ""),
                "type": target_dict.get("asset_type", target_dict.get("type", "")),
                "point_count": len(trail),
                "timestamps": timestamps,
            },
        }

        return Response(
            content=json.dumps(geojson, default=str),
            media_type="application/geo+json",
            headers={
                "Content-Disposition": f"attachment; filename={safe_id}_history.geojson",
            },
        )

    else:
        import json

        export = {
            "target_id": target_id,
            "target": target_dict,
            "point_count": len(trail),
            "trail": trail,
        }

        return Response(
            content=json.dumps(export, default=str),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={safe_id}_history.json",
            },
        )


@router.post("/sighting")
async def report_sighting(request: Request):
    """Accept a sighting report from camera or robot."""
    # Try Amy's engine first, then headless fallback.
    engine = None
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        engine = getattr(amy, "simulation_engine", None)
    if engine is None:
        engine = _get_sim_engine(request)
    if engine is None:
        return {"error": "No simulation engine"}
    body = await request.json()
    from tritium_lib.sim_engine.world.vision import SightingReport
    report = SightingReport(
        observer_id=body.get("observer_id", "unknown"),
        target_id=body.get("target_id", ""),
        observer_type=body.get("observer_type", "camera"),
        confidence=body.get("confidence", 1.0),
        position=tuple(body["position"]) if "position" in body else None,
        timestamp=body.get("timestamp", 0.0),
    )
    engine.vision_system.add_sighting(report)
    return {"status": "accepted"}


def _get_convoy_detector(request: Request):
    """Get convoy detector from Amy's event bus subsystems."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        cd = getattr(amy, "convoy_detector", None)
        if cd is not None:
            return cd
    return getattr(request.app.state, "convoy_detector", None)


@router.get("/convoys")
async def get_convoys(request: Request):
    """Return active convoys with member positions for map visualization.

    Each convoy includes a ConvoyVisualization-shaped response with
    bounding polygon, heading, speed, formation type, and confidence
    for rendering convoy overlays on the tactical map.
    """
    detector = _get_convoy_detector(request)
    if detector is None:
        return {"convoys": [], "summary": {"active_convoys": 0}}

    convoys = detector.get_active_convoys()
    tracker = _get_tracker(request)

    # Enrich each convoy with geo positions and produce ConvoyVisualization
    enriched = []
    for c in convoys:
        member_positions = []
        if tracker is not None:
            for tid in c.get("member_target_ids", []):
                t = tracker.get_target(tid)
                if t is not None:
                    td = t.to_dict()
                    member_positions.append({
                        "target_id": tid,
                        "lat": td.get("lat", 0.0),
                        "lng": td.get("lng", 0.0),
                    })

        # Build ConvoyVisualization via the detector's conversion method
        viz = detector.to_visualization(c, member_positions)
        viz_dict = viz.to_dict()

        # Also include raw convoy data and member positions for backwards compat
        viz_dict["member_positions"] = member_positions
        viz_dict["suspicious_score"] = c.get("suspicious_score", 0.0)
        viz_dict["status"] = c.get("status", "active")
        viz_dict["duration_s"] = c.get("duration_s", 0.0)

        enriched.append(viz_dict)

    return {
        "convoys": enriched,
        "summary": detector.get_summary(),
    }
