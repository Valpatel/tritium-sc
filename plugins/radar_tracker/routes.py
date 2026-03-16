# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the radar tracker plugin.

Provides REST endpoints for radar status, track queries,
configuration, and PPI scope data.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from .models import RadarConfigRequest


def create_router(tracker: Any) -> APIRouter:
    """Build the radar tracker APIRouter.

    Parameters
    ----------
    tracker:
        RadarTracker instance providing track and radar management.
    """
    router = APIRouter(prefix="/api/radar", tags=["radar-tracker"])

    # -- Status ------------------------------------------------------------

    @router.get("/status")
    async def get_status():
        """Return radar system status.

        Shows configured radars, active track count, and running state.
        """
        radars = tracker.list_radars()
        tracks = tracker.get_tracks()
        stats = tracker.get_stats()
        return {
            "radars": radars,
            "total_tracks": len(tracks),
            "running": True,
            "stats": stats,
        }

    # -- Tracks ------------------------------------------------------------

    @router.get("/tracks")
    async def get_tracks(
        radar_id: Optional[str] = Query(default=None, description="Filter by radar ID"),
        limit: int = Query(default=200, ge=1, le=2000),
    ):
        """Return current radar tracks.

        Each track includes range, azimuth, velocity, RCS,
        computed lat/lng, and classification.
        """
        tracks = tracker.get_tracks(radar_id=radar_id)
        return {"tracks": tracks[:limit], "count": len(tracks)}

    # -- Configuration -----------------------------------------------------

    @router.post("/configure")
    async def configure_radar(body: RadarConfigRequest):
        """Configure a radar unit's position, orientation, and range limits.

        This must be called before tracks from this radar can be
        plotted on the map (range/azimuth needs a reference position).
        """
        unit = tracker.configure_radar(
            radar_id=body.radar_id,
            lat=body.lat,
            lng=body.lng,
            altitude_m=body.altitude_m,
            orientation_deg=body.orientation_deg,
            max_range_m=body.max_range_m,
            min_range_m=body.min_range_m,
            name=body.name,
            enabled=body.enabled,
        )
        return {"status": "ok", "radar": unit.to_dict()}

    @router.get("/radars")
    async def list_radars():
        """List all configured radar units."""
        radars = tracker.list_radars()
        return {"radars": radars, "count": len(radars)}

    @router.delete("/radars/{radar_id}")
    async def remove_radar(radar_id: str):
        """Remove a radar unit and all its tracks."""
        removed = tracker.remove_radar(radar_id)
        if not removed:
            raise HTTPException(status_code=404, detail=f"Radar '{radar_id}' not found")
        return {"removed": True, "radar_id": radar_id}

    # -- PPI scope ---------------------------------------------------------

    @router.get("/ppi/{radar_id}")
    async def get_ppi(radar_id: str):
        """Return PPI scope data for a specific radar.

        Provides track positions in range/azimuth coordinates
        relative to the radar, suitable for rendering a PPI display.
        """
        data = tracker.get_ppi_data(radar_id)
        if data is None:
            raise HTTPException(
                status_code=404,
                detail=f"Radar '{radar_id}' not found or not configured",
            )
        return data

    # -- Ingest (manual/testing) -------------------------------------------

    @router.post("/ingest/{radar_id}")
    async def ingest_tracks(radar_id: str, tracks: list[dict]):
        """Manually ingest radar tracks (for testing or non-MQTT sources).

        Body should be a JSON array of track objects with at minimum:
            track_id, range_m, azimuth_deg
        """
        count = tracker.ingest_tracks(radar_id, tracks)
        return {"status": "ok", "processed": count}

    # -- Stats -------------------------------------------------------------

    @router.get("/stats")
    async def get_stats():
        """Return radar tracker statistics."""
        return tracker.get_stats()

    return router
