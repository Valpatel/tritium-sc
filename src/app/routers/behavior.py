# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Behavioral pattern recognition and anomaly detection API.

Tracks target movement patterns, detects anomalies, scores correlations
between targets from different sensors for fusion.

Endpoints:
    POST /api/behavior/pattern       — report a detected pattern
    GET  /api/behavior/patterns      — list active patterns
    POST /api/behavior/anomaly       — report an anomaly
    GET  /api/behavior/anomalies     — list recent anomalies
    POST /api/behavior/correlate     — score correlation between two targets
    GET  /api/behavior/stats         — behavior analysis statistics
"""

import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/behavior", tags=["behavior"])


# --- In-memory stores ---

_patterns: dict[str, list[dict]] = defaultdict(list)  # target_id -> patterns
_patterns_lock = Lock()

_anomalies: list[dict] = []
_anomalies_lock = Lock()
_max_anomalies = 1000

_correlations: dict[str, dict] = {}  # "a|b" -> correlation result
_correlations_lock = Lock()


# --- Request models ---


class PatternReport(BaseModel):
    target_id: str
    behavior_type: str = "unknown"
    confidence: float = 0.0
    center_lat: float = 0.0
    center_lng: float = 0.0
    radius_m: float = 0.0
    duration_s: float = 0.0
    samples: int = 0


class AnomalyReport(BaseModel):
    target_id: str
    anomaly_type: str = "unknown"
    severity: str = "info"
    description: str = ""
    location_lat: float = 0.0
    location_lng: float = 0.0
    baseline_value: str = ""
    observed_value: str = ""


class CorrelationRequest(BaseModel):
    target_a: str
    target_b: str
    temporal_overlap: float = 0.0  # 0.0-1.0
    spatial_proximity_m: float = 100.0
    co_movement_score: float = 0.0  # 0.0-1.0
    source_a: str = ""
    source_b: str = ""


# --- Helpers ---

def _compute_score(temporal: float, spatial_m: float, co_movement: float) -> float:
    """Weighted correlation score."""
    spatial_score = max(0, 1.0 - spatial_m / 50.0)
    score = 0.4 * temporal + 0.35 * spatial_score + 0.25 * co_movement
    return min(1.0, max(0.0, score))


def _correlation_key(a: str, b: str) -> str:
    """Consistent key regardless of order."""
    return "|".join(sorted([a, b]))


# --- Endpoints ---


@router.post("/pattern")
async def report_pattern(report: PatternReport):
    """Report a detected behavioral pattern."""
    pattern = {
        "target_id": report.target_id,
        "behavior_type": report.behavior_type,
        "confidence": report.confidence,
        "center_lat": report.center_lat,
        "center_lng": report.center_lng,
        "radius_m": report.radius_m,
        "duration_s": report.duration_s,
        "samples": report.samples,
        "timestamp": time.time(),
        "active": True,
    }
    with _patterns_lock:
        _patterns[report.target_id].append(pattern)
        # Keep only last 20 patterns per target
        if len(_patterns[report.target_id]) > 20:
            _patterns[report.target_id] = _patterns[report.target_id][-20:]

    return {"status": "recorded", "target_id": report.target_id}


@router.get("/patterns")
async def get_patterns(
    target_id: str | None = None,
    behavior_type: str | None = None,
    limit: int = 50,
):
    """List patterns, optionally filtered."""
    with _patterns_lock:
        if target_id:
            results = list(_patterns.get(target_id, []))
        else:
            results = []
            for patterns in _patterns.values():
                results.extend(patterns)

    if behavior_type:
        results = [p for p in results if p["behavior_type"] == behavior_type]

    results.sort(key=lambda p: p.get("timestamp", 0), reverse=True)
    return results[:limit]


@router.post("/anomaly")
async def report_anomaly(report: AnomalyReport):
    """Report a behavioral anomaly."""
    anomaly = {
        "target_id": report.target_id,
        "anomaly_type": report.anomaly_type,
        "severity": report.severity,
        "description": report.description,
        "location_lat": report.location_lat,
        "location_lng": report.location_lng,
        "baseline_value": report.baseline_value,
        "observed_value": report.observed_value,
        "timestamp": time.time(),
    }
    with _anomalies_lock:
        _anomalies.append(anomaly)
        if len(_anomalies) > _max_anomalies:
            _anomalies[:] = _anomalies[-_max_anomalies:]

    return {"status": "recorded", "severity": report.severity}


@router.get("/anomalies")
async def get_anomalies(
    target_id: str | None = None,
    severity: str | None = None,
    limit: int = 50,
):
    """List recent anomalies."""
    with _anomalies_lock:
        results = list(_anomalies)

    if target_id:
        results = [a for a in results if a["target_id"] == target_id]
    if severity:
        results = [a for a in results if a["severity"] == severity]

    results.sort(key=lambda a: a.get("timestamp", 0), reverse=True)
    return results[:limit]


@router.post("/correlate")
async def correlate_targets(request: CorrelationRequest):
    """Score correlation between two targets for potential fusion."""
    score = _compute_score(
        request.temporal_overlap,
        request.spatial_proximity_m,
        request.co_movement_score,
    )

    reasons = []
    if request.temporal_overlap > 0.7:
        reasons.append("strong temporal overlap")
    if request.spatial_proximity_m < 5:
        reasons.append("very close proximity")
    elif request.spatial_proximity_m < 20:
        reasons.append("close proximity")
    if request.co_movement_score > 0.7:
        reasons.append("co-movement detected")
    if request.source_a != request.source_b and request.source_a and request.source_b:
        reasons.append(f"cross-sensor ({request.source_a}+{request.source_b})")

    result = {
        "target_a": request.target_a,
        "target_b": request.target_b,
        "score": round(score, 3),
        "should_fuse": score > 0.7,
        "reasons": reasons,
        "temporal_overlap": request.temporal_overlap,
        "spatial_proximity_m": request.spatial_proximity_m,
        "co_movement_score": request.co_movement_score,
    }

    key = _correlation_key(request.target_a, request.target_b)
    with _correlations_lock:
        _correlations[key] = result

    return result


@router.get("/stats")
async def get_stats():
    """Get behavior analysis statistics."""
    with _patterns_lock:
        total_patterns = sum(len(p) for p in _patterns.values())
        targets_with_patterns = len(_patterns)
        type_counts: dict[str, int] = defaultdict(int)
        for patterns in _patterns.values():
            for p in patterns:
                type_counts[p["behavior_type"]] += 1

    with _anomalies_lock:
        total_anomalies = len(_anomalies)
        severity_counts: dict[str, int] = defaultdict(int)
        for a in _anomalies:
            severity_counts[a["severity"]] += 1

    with _correlations_lock:
        total_correlations = len(_correlations)
        high_score = sum(1 for c in _correlations.values() if c.get("score", 0) > 0.7)

    return {
        "total_patterns": total_patterns,
        "targets_with_patterns": targets_with_patterns,
        "pattern_types": dict(type_counts),
        "total_anomalies": total_anomalies,
        "anomaly_severities": dict(severity_counts),
        "total_correlations": total_correlations,
        "high_score_correlations": high_score,
    }
