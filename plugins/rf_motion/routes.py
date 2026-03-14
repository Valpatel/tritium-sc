# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for RF motion detection plugin.

Provides REST endpoints for querying motion events, zone status,
baselines, and detector configuration.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


# -- Request/response models ---------------------------------------------------

class SetNodePositionRequest(BaseModel):
    node_id: str
    x: float
    y: float


class RecordPairRSSIRequest(BaseModel):
    node_a: str
    node_b: str
    rssi: float


class RecordDeviceRSSIRequest(BaseModel):
    observer_id: str
    device_mac: str
    rssi: float


class CreateZoneRequest(BaseModel):
    zone_id: str
    name: str
    pair_ids: list[str]
    vacancy_timeout: float = 30.0


class UpdateConfigRequest(BaseModel):
    static_threshold: Optional[float] = None
    motion_threshold: Optional[float] = None
    window_seconds: Optional[float] = None
    poll_interval: Optional[float] = None


# -- Router factory ------------------------------------------------------------

def create_router(
    detector: Any,
    zone_manager: Any,
) -> APIRouter:
    """Build RF motion detection API router.

    Parameters
    ----------
    detector:
        RSSIMotionDetector instance.
    zone_manager:
        ZoneManager instance.
    """
    router = APIRouter(prefix="/api/rf-motion", tags=["rf-motion"])

    # -- Motion events ---------------------------------------------------------

    @router.get("/events")
    async def get_events():
        """Return current motion events from latest detection cycle."""
        events = detector.get_recent_events()
        return {
            "events": [e.to_dict() for e in events],
            "count": len(events),
        }

    @router.post("/detect")
    async def trigger_detect():
        """Manually trigger a detection cycle and return events."""
        events = detector.detect()
        # Also update zones
        zone_manager.check_all(events)
        return {
            "events": [e.to_dict() for e in events],
            "count": len(events),
        }

    # -- Baselines -------------------------------------------------------------

    @router.get("/baselines")
    async def get_baselines():
        """Return baseline RSSI stats for all radio pairs."""
        baselines = detector.get_baselines()
        return {
            "baselines": [b.to_dict() for b in baselines],
            "count": len(baselines),
        }

    @router.get("/baselines/{pair_id:path}")
    async def get_baseline(pair_id: str):
        """Return baseline for a specific radio pair."""
        baseline = detector.get_baseline(pair_id)
        if baseline is None:
            raise HTTPException(status_code=404, detail="Pair baseline not found")
        return baseline.to_dict()

    # -- Zones -----------------------------------------------------------------

    @router.get("/zones")
    async def list_zones():
        """List all RF motion zones."""
        zones = zone_manager.list_zones()
        return {
            "zones": [z.to_dict() for z in zones],
            "count": len(zones),
        }

    @router.post("/zones")
    async def create_zone(body: CreateZoneRequest):
        """Create a new RF motion zone."""
        zone = zone_manager.add_zone(
            zone_id=body.zone_id,
            name=body.name,
            pair_ids=body.pair_ids,
            vacancy_timeout=body.vacancy_timeout,
        )
        return zone.to_dict()

    @router.get("/zones/{zone_id}")
    async def get_zone(zone_id: str):
        """Get a specific zone."""
        zone = zone_manager.get_zone(zone_id)
        if zone is None:
            raise HTTPException(status_code=404, detail="Zone not found")
        return zone.to_dict()

    @router.delete("/zones/{zone_id}")
    async def delete_zone(zone_id: str):
        """Delete a zone."""
        removed = zone_manager.remove_zone(zone_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Zone not found")
        return {"removed": True, "zone_id": zone_id}

    @router.get("/zones/occupied")
    async def get_occupied_zones():
        """Return only occupied zones."""
        zones = zone_manager.get_occupied_zones()
        return {
            "zones": [z.to_dict() for z in zones],
            "count": len(zones),
        }

    # -- Node positions --------------------------------------------------------

    @router.get("/nodes")
    async def get_nodes():
        """Return all node positions."""
        positions = detector.get_node_positions()
        return {
            "nodes": {nid: {"x": p[0], "y": p[1]} for nid, p in positions.items()},
            "count": len(positions),
        }

    @router.put("/nodes/position")
    async def set_node_position(body: SetNodePositionRequest):
        """Set a node's position."""
        detector.set_node_position(body.node_id, (body.x, body.y))
        return {"node_id": body.node_id, "set": True}

    # -- Data ingestion (for testing / manual feeds) ---------------------------

    @router.post("/rssi/pair")
    async def record_pair(body: RecordPairRSSIRequest):
        """Record a pair RSSI reading."""
        detector.record_pair_rssi(body.node_a, body.node_b, body.rssi)
        return {"recorded": True}

    @router.post("/rssi/device")
    async def record_device(body: RecordDeviceRSSIRequest):
        """Record a device RSSI reading from a single observer."""
        detector.record_device_rssi(body.observer_id, body.device_mac, body.rssi)
        return {"recorded": True}

    # -- Config ----------------------------------------------------------------

    @router.get("/config")
    async def get_config():
        """Return current detector configuration."""
        return {
            "static_threshold": detector._static_threshold,
            "motion_threshold": detector._motion_threshold,
            "window_seconds": detector._window_seconds,
        }

    @router.put("/config")
    async def update_config(body: UpdateConfigRequest):
        """Update detector configuration."""
        if body.static_threshold is not None:
            detector._static_threshold = body.static_threshold
        if body.motion_threshold is not None:
            detector._motion_threshold = body.motion_threshold
        if body.window_seconds is not None:
            detector._window_seconds = body.window_seconds
        return {"updated": True}

    # -- Active motion summary -------------------------------------------------

    @router.get("/active")
    async def get_active():
        """Return pairs with active motion and occupied zones."""
        active_pairs = detector.get_active_motion()
        occupied_zones = zone_manager.get_occupied_zones()
        return {
            "active_pairs": [b.to_dict() for b in active_pairs],
            "occupied_zones": [z.to_dict() for z in occupied_zones],
            "motion_detected": len(active_pairs) > 0 or len(occupied_zones) > 0,
        }

    return router
