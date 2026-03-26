# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Acoustic classification API endpoints.

Provides event classification results, sensor management, and
acoustic event history for the tactical map.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from engine.audio.acoustic_classifier import (
    AcousticClassifier,
    AcousticEventType,
    AudioFeatures,
)

router = APIRouter(prefix="/api/acoustic", tags=["acoustic"])

# Singleton classifier instance
_classifier = AcousticClassifier()


class ClassifyRequest(BaseModel):
    """Request to classify audio features."""

    rms_energy: float = 0.0
    peak_amplitude: float = 0.0
    zero_crossing_rate: float = 0.0
    spectral_centroid: float = 0.0
    spectral_bandwidth: float = 0.0
    duration_ms: int = 0
    device_id: str = ""


class AcousticEventResponse(BaseModel):
    """Response with classified acoustic event."""

    event_type: str
    confidence: float
    timestamp: float
    duration_ms: int
    peak_frequency_hz: float
    peak_amplitude_db: float
    device_id: str


@router.get("/status")
async def acoustic_status():
    """Acoustic classifier status.

    Returns whether the acoustic classifier is running, which event types
    it recognises, and summary event counts.
    """
    try:
        event_counts = _classifier.get_event_counts()
        total = len(_classifier.get_recent_events(10000))
        return {
            "status": "running",
            "available": True,
            "event_types": [e.value for e in AcousticEventType],
            "total_events": total,
            "event_counts": event_counts,
            "ml_available": False,
        }
    except Exception as e:
        return {
            "status": "error",
            "available": False,
            "error": str(e),
        }


@router.post("/classify", response_model=AcousticEventResponse)
async def classify_audio(request: ClassifyRequest):
    """Classify audio features into an acoustic event type."""
    features = AudioFeatures(
        rms_energy=request.rms_energy,
        peak_amplitude=request.peak_amplitude,
        zero_crossing_rate=request.zero_crossing_rate,
        spectral_centroid=request.spectral_centroid,
        spectral_bandwidth=request.spectral_bandwidth,
        duration_ms=request.duration_ms,
    )
    event = _classifier.classify(features)
    event.device_id = request.device_id

    return AcousticEventResponse(
        event_type=event.event_type.value,
        confidence=event.confidence,
        timestamp=event.timestamp,
        duration_ms=event.duration_ms,
        peak_frequency_hz=event.peak_frequency_hz,
        peak_amplitude_db=event.peak_amplitude_db,
        device_id=event.device_id,
    )


@router.get("/events")
async def get_events(count: int = 50):
    """Get recent acoustic events."""
    events = _classifier.get_recent_events(count)
    return [
        {
            "event_type": e.event_type.value,
            "confidence": e.confidence,
            "timestamp": e.timestamp,
            "duration_ms": e.duration_ms,
            "peak_frequency_hz": e.peak_frequency_hz,
            "device_id": e.device_id,
        }
        for e in events
    ]


@router.get("/stats")
async def get_stats():
    """Get acoustic event statistics.

    Returns stats compatible with the acoustic panel's expected format:
    events_classified, active_targets, high_severity_count, localizations,
    ml_available, plus the raw event_counts and event_types.
    """
    event_counts = _classifier.get_event_counts()
    total = len(_classifier.get_recent_events(10000))
    high_types = {"gunshot", "explosion", "glass_break"}
    high_count = sum(event_counts.get(t, 0) for t in high_types)
    return {
        "event_counts": event_counts,
        "event_types": [e.value for e in AcousticEventType],
        "total_events": total,
        # Fields expected by acoustic-intelligence.js panel
        "events_classified": total,
        "active_targets": 0,
        "high_severity_count": high_count,
        "localizations": 0,
        "ml_available": False,
    }


@router.get("/timeline")
async def get_timeline(count: int = 50):
    """Get acoustic events formatted as a timeline for the panel.

    Wraps /events data with colour hints and location stubs so the
    acoustic-intelligence.js panel can render without changes.
    """
    events = _classifier.get_recent_events(count)
    high_types = {"gunshot", "explosion", "glass_break"}
    medium_types = {"siren", "alarm", "vehicle"}

    timeline = []
    for e in events:
        evt_type = e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)
        if evt_type in high_types:
            color = "#ff2a6d"
        elif evt_type in medium_types:
            color = "#fcee0a"
        else:
            color = "#00f0ff"
        timeline.append({
            "event_type": evt_type,
            "confidence": e.confidence,
            "timestamp": e.timestamp,
            "duration_ms": e.duration_ms,
            "peak_frequency_hz": e.peak_frequency_hz,
            "device_id": e.device_id,
            "color": color,
            "model_version": "",
            "location": None,
        })
    return {"events": timeline}


@router.get("/localizations")
async def get_localizations(count: int = 30):
    """Get acoustic source localizations.

    Multi-sensor triangulated localizations require 2+ acoustic sensors
    reporting the same event.  Returns an empty list when no localization
    data is available (single-sensor deployments).
    """
    # Localizations require multi-sensor correlation which is not yet
    # implemented in the single-classifier pipeline.  Return the empty
    # structure the panel expects so the UI renders gracefully.
    return {"localizations": []}


@router.get("/counts")
async def get_counts():
    """Get per-event-type counts for the acoustic panel bar chart."""
    return {"counts": _classifier.get_event_counts()}
