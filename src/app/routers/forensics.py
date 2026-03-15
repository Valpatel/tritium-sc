# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Forensic reconstruction and incident report API.

Endpoints:
    POST /api/forensics/reconstruct    — reconstruct events in time/area window
    GET  /api/forensics/{recon_id}     — get a cached reconstruction
    GET  /api/forensics                — list all reconstructions
    POST /api/forensics/report         — generate incident report from reconstruction
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/forensics", tags=["forensics"])


class ReconstructRequest(BaseModel):
    """Request body for forensic reconstruction."""
    start: float = Field(..., description="Start timestamp (unix)")
    end: float = Field(..., description="End timestamp (unix)")
    bounds: Optional[dict] = Field(
        None,
        description="Geographic bounds: {north, south, east, west}",
    )
    max_events: int = Field(10000, description="Maximum events to include", ge=1, le=100000)


class ReportRequest(BaseModel):
    """Request body for incident report generation."""
    reconstruction_id: str = Field(..., description="ID of the reconstruction to report on")
    title: str = Field("", description="Report title (auto-generated if empty)")
    created_by: str = Field("operator", description="Author of the report")


def _get_reconstructor(request: Request):
    """Get ForensicReconstructor from app state."""
    return getattr(request.app.state, "forensic_reconstructor", None)


@router.post("/reconstruct")
async def reconstruct(request: Request, body: ReconstructRequest):
    """Reconstruct what happened in a time/area window.

    Given a time range and optional geographic bounds, queries all stored
    events and target data to produce a complete reconstruction: which
    targets were where, what events occurred, what sensors detected what.
    """
    reconstructor = _get_reconstructor(request)
    if reconstructor is None:
        # Lazy init
        from engine.tactical.forensic_reconstructor import ForensicReconstructor

        event_store = getattr(request.app.state, "tactical_event_store", None)
        target_tracker = getattr(request.app.state, "target_tracker", None)
        playback = getattr(request.app.state, "temporal_playback", None)

        # Also check Amy for these objects
        amy = getattr(request.app.state, "amy", None)
        if amy:
            if target_tracker is None:
                target_tracker = getattr(amy, "target_tracker", None)
            if playback is None:
                playback = getattr(amy, "temporal_playback", None)

        reconstructor = ForensicReconstructor(
            event_store=event_store,
            target_tracker=target_tracker,
            playback=playback,
        )
        request.app.state.forensic_reconstructor = reconstructor

    if body.end <= body.start:
        return {"error": "end must be after start", "status": "failed"}

    result = reconstructor.reconstruct(
        start=body.start,
        end=body.end,
        bounds=body.bounds,
        max_events=body.max_events,
    )
    return result


@router.get("/{recon_id}")
async def get_reconstruction(request: Request, recon_id: str):
    """Retrieve a cached forensic reconstruction by ID."""
    reconstructor = _get_reconstructor(request)
    if reconstructor is None:
        return {"error": "No reconstructions available"}

    result = reconstructor.get_reconstruction(recon_id)
    if result is None:
        return {"error": f"Reconstruction {recon_id} not found"}
    return result


@router.get("")
async def list_reconstructions(request: Request):
    """List all cached forensic reconstructions."""
    reconstructor = _get_reconstructor(request)
    if reconstructor is None:
        return {"reconstructions": [], "count": 0}

    items = reconstructor.list_reconstructions()
    return {"reconstructions": items, "count": len(items)}


@router.post("/report")
async def generate_report(request: Request, body: ReportRequest):
    """Generate a structured incident report from a forensic reconstruction.

    The report includes timeline, entity list, sensor coverage map,
    findings, recommendations, and classification.
    """
    reconstructor = _get_reconstructor(request)
    if reconstructor is None:
        return {"error": "No reconstructor available"}

    recon = reconstructor.get_reconstruction(body.reconstruction_id)
    if recon is None:
        return {"error": f"Reconstruction {body.reconstruction_id} not found"}

    report = reconstructor.generate_incident_report(
        reconstruction=recon,
        title=body.title,
        created_by=body.created_by,
    )
    return report
