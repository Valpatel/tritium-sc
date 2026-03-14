# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unified target tracking endpoint — real + virtual targets."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api", tags=["targets"])


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
    format: str = Query("json", description="Export format: json, csv, or geojson"),
):
    """Export all current targets in standard formats for external analysis.

    Supported formats:
    - ``json`` — Array of target dicts
    - ``csv`` — Comma-separated values with header row
    - ``geojson`` — GeoJSON FeatureCollection with Point geometries
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
    from engine.simulation.vision import SightingReport
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
