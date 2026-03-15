# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Fleet map API — dedicated edge device map view.

Shows ONLY edge devices on the map with coverage indicators, health status,
and group assignments. A simplified view without all the target clutter.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.auth import optional_auth

router = APIRouter(prefix="/api/fleet/map", tags=["fleet-map"])


def _get_fleet_plugin(request: Request):
    """Get fleet dashboard plugin from app state."""
    return getattr(request.app.state, "fleet_dashboard_plugin", None)


def _get_edge_tracker(request: Request):
    """Get edge tracker plugin from app state."""
    return getattr(request.app.state, "edge_tracker_plugin", None)


@router.get("/devices")
async def get_fleet_map_devices(request: Request, user: dict | None = Depends(optional_auth)):
    """Return all edge devices with map-relevant data.

    Each device includes:
    - Position (lat/lng if known)
    - Health status (online/offline/stale)
    - Battery level
    - Group assignment
    - Coverage radius estimate
    - Sensor capabilities
    - Sighting counts (BLE + WiFi)
    """
    fleet = _get_fleet_plugin(request)
    if fleet is None:
        return {"devices": [], "count": 0, "message": "Fleet plugin not loaded"}

    devices = fleet.get_devices()
    edge_tracker = _get_edge_tracker(request)

    map_devices = []
    for dev in devices:
        device_id = dev.get("device_id", "")

        # Get node position from edge tracker if available
        position = dev.get("position") or {}
        lat = position.get("lat") or dev.get("lat")
        lng = position.get("lon") or dev.get("lng") or dev.get("lon")

        # If edge tracker has position info, use it
        if edge_tracker is not None and hasattr(edge_tracker, "store") and edge_tracker.store is not None:
            node_positions = edge_tracker.store.get_node_positions()
            node_pos = node_positions.get(device_id, {})
            if node_pos:
                lat = node_pos.get("lat", lat)
                lng = node_pos.get("lon", lng)

        # Health status
        last_heartbeat = dev.get("last_heartbeat", 0)
        now = time.time()
        if isinstance(last_heartbeat, (int, float)) and last_heartbeat > 0:
            age = now - last_heartbeat
            if age < 90:
                health = "online"
            elif age < 300:
                health = "stale"
            else:
                health = "offline"
        else:
            health = "unknown"

        # Coverage estimate based on device type
        # BLE range ~30m, WiFi ~50m in typical indoor environments
        coverage_radius_m = 50.0
        capabilities = dev.get("capabilities", {})
        if isinstance(capabilities, dict):
            has_ble = capabilities.get("ble_scanner", False)
            has_wifi = capabilities.get("wifi_scanner", False)
            if has_ble and has_wifi:
                coverage_radius_m = 50.0
            elif has_wifi:
                coverage_radius_m = 50.0
            elif has_ble:
                coverage_radius_m = 30.0

        map_device = {
            "device_id": device_id,
            "name": dev.get("name", device_id),
            "lat": lat,
            "lng": lng,
            "health": health,
            "battery": dev.get("battery", None),
            "group": dev.get("group", "default"),
            "coverage_radius_m": coverage_radius_m,
            "capabilities": capabilities,
            "firmware_version": dev.get("firmware_version", ""),
            "uptime_seconds": dev.get("uptime_seconds", 0),
            "ble_device_count": dev.get("ble_count", 0),
            "wifi_network_count": dev.get("wifi_count", 0),
            "last_heartbeat": last_heartbeat,
        }
        map_devices.append(map_device)

    # Group summary
    groups: dict[str, int] = {}
    for d in map_devices:
        g = d.get("group", "default")
        groups[g] = groups.get(g, 0) + 1

    online_count = sum(1 for d in map_devices if d["health"] == "online")
    offline_count = sum(1 for d in map_devices if d["health"] == "offline")
    positioned = sum(1 for d in map_devices if d["lat"] is not None and d["lng"] is not None)

    return {
        "devices": map_devices,
        "count": len(map_devices),
        "online": online_count,
        "offline": offline_count,
        "positioned": positioned,
        "groups": groups,
    }


@router.get("/coverage")
async def get_fleet_coverage(request: Request, user: dict | None = Depends(optional_auth)):
    """Return coverage overlay data for all positioned devices.

    Each entry is a circle: center (lat/lng), radius, and color based
    on health status.
    """
    fleet = _get_fleet_plugin(request)
    if fleet is None:
        return {"coverage": [], "count": 0}

    devices = fleet.get_devices()
    coverage = []

    for dev in devices:
        position = dev.get("position") or {}
        lat = position.get("lat") or dev.get("lat")
        lng = position.get("lon") or dev.get("lng") or dev.get("lon")

        if lat is None or lng is None:
            continue

        last_heartbeat = dev.get("last_heartbeat", 0)
        now = time.time()
        if isinstance(last_heartbeat, (int, float)) and last_heartbeat > 0:
            age = now - last_heartbeat
            if age < 90:
                color = "#05ffa180"  # green, semi-transparent
            elif age < 300:
                color = "#fcee0a60"  # yellow
            else:
                color = "#ff2a6d40"  # magenta/red
        else:
            color = "#ffffff20"  # white, very transparent

        coverage.append({
            "device_id": dev.get("device_id", ""),
            "lat": lat,
            "lng": lng,
            "radius_m": 50.0,
            "color": color,
        })

    return {"coverage": coverage, "count": len(coverage)}
