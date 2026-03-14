# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Fleet Dashboard plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

if TYPE_CHECKING:
    from .plugin import FleetDashboardPlugin


def create_router(plugin: FleetDashboardPlugin) -> APIRouter:
    """Build and return the fleet dashboard APIRouter."""

    router = APIRouter(prefix="/api/fleet", tags=["fleet-dashboard"])

    @router.get("/devices")
    async def list_devices():
        """List all tracked fleet devices with status."""
        devices = plugin.get_devices()
        return {"devices": devices, "count": len(devices)}

    @router.get("/devices/{device_id}")
    async def get_device(device_id: str):
        """Get a single fleet device by ID."""
        device = plugin.get_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        return {"device": device}

    @router.get("/summary")
    async def get_summary():
        """Fleet summary: online/offline/stale counts, avg battery, totals."""
        return plugin.get_summary()

    return router
