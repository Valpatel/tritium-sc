# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Sensor health API endpoint.

Aggregates health data for all sensors (fleet devices, cameras, mesh radios)
into a unified health grid with sighting rate sparklines, health status,
and last-seen timestamps.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/sensors", tags=["sensor-health"])


def _device_health(device: dict) -> str:
    """Compute health status from device state."""
    status = device.get("status", "offline")
    if status == "offline":
        return "red"
    last_seen = device.get("last_seen")
    if last_seen:
        age = time.time() - last_seen
        if age > 120:
            return "red"
        if age > 60:
            return "yellow"
    battery = device.get("battery_pct")
    if battery is not None and battery < 15:
        return "yellow"
    return "green"


def _camera_health(cam: dict) -> str:
    """Compute health status for a camera."""
    if not cam.get("enabled", True):
        return "red"
    return "green"


@router.get("/health")
async def sensor_health(request: Request) -> dict[str, Any]:
    """Return unified sensor health grid.

    Combines fleet devices, cameras, and mesh radios into a single
    health overview with sparkline data and alert indicators.
    """
    sensors: list[dict[str, Any]] = []
    degraded_count = 0

    # Fleet devices (edge nodes)
    fleet_plugin = None
    plugin_mgr = getattr(request.app.state, "plugin_manager", None)
    if plugin_mgr:
        fleet_plugin = getattr(plugin_mgr, "fleet_dashboard", None)
        if fleet_plugin is None:
            # Try plugins dict
            plugins = getattr(plugin_mgr, "plugins", {})
            if isinstance(plugins, dict):
                fleet_plugin = plugins.get("fleet_dashboard")

    if fleet_plugin and hasattr(fleet_plugin, "get_devices"):
        devices = fleet_plugin.get_devices()
        histories = {}
        if hasattr(fleet_plugin, "get_all_target_histories"):
            histories = fleet_plugin.get_all_target_histories()

        for dev in devices:
            did = dev.get("device_id", "unknown")
            health = _device_health(dev)
            if health != "green":
                degraded_count += 1

            sparkline = []
            hist = histories.get(did, [])
            for entry in hist[-30:]:
                sparkline.append(entry.get("count", 0) if isinstance(entry, dict) else entry)

            sensors.append({
                "id": did,
                "name": dev.get("name", did),
                "type": "edge_node",
                "health": health,
                "status": dev.get("status", "offline"),
                "battery_pct": dev.get("battery_pct"),
                "sighting_rate": dev.get("sighting_rate", 0),
                "sparkline": sparkline,
                "last_seen": dev.get("last_seen"),
                "firmware": dev.get("firmware_version"),
                "group": dev.get("group", "default"),
            })

    # Cameras
    cameras = getattr(request.app.state, "cameras", [])
    if not cameras:
        try:
            from app.database import get_db
            # Try fetching from database
        except Exception:
            pass

    # Registered cameras from API state
    cam_registry = getattr(request.app.state, "camera_registry", {})
    if isinstance(cam_registry, dict):
        for cid, cam in cam_registry.items():
            health = _camera_health(cam)
            if health != "green":
                degraded_count += 1
            sensors.append({
                "id": f"cam_{cid}",
                "name": cam.get("name", f"Camera {cid}"),
                "type": "camera",
                "health": health,
                "status": "online" if cam.get("enabled") else "offline",
                "battery_pct": None,
                "sighting_rate": 0,
                "sparkline": [],
                "last_seen": cam.get("last_frame_ts"),
                "firmware": None,
                "group": "cameras",
            })

    # Mesh radios
    mesh_state = getattr(request.app.state, "mesh_state", None)
    if mesh_state and hasattr(mesh_state, "nodes"):
        nodes = mesh_state.nodes if isinstance(mesh_state.nodes, dict) else {}
        for nid, node in nodes.items():
            last_seen = node.get("last_seen")
            if last_seen and (time.time() - last_seen) > 300:
                health = "red"
            elif last_seen and (time.time() - last_seen) > 120:
                health = "yellow"
            else:
                health = "green" if last_seen else "yellow"
            if health != "green":
                degraded_count += 1
            sensors.append({
                "id": f"mesh_{nid}",
                "name": node.get("long_name", node.get("short_name", nid)),
                "type": "mesh_radio",
                "health": health,
                "status": "online" if health == "green" else "stale" if health == "yellow" else "offline",
                "battery_pct": node.get("battery_level"),
                "sighting_rate": 0,
                "sparkline": [],
                "last_seen": last_seen,
                "firmware": node.get("firmware_version"),
                "group": "mesh",
            })

    # If no sensors found at all, provide synthetic placeholder so panel isn't empty
    if not sensors:
        sensors.append({
            "id": "no_sensors",
            "name": "No Sensors Detected",
            "type": "none",
            "health": "red",
            "status": "offline",
            "battery_pct": None,
            "sighting_rate": 0,
            "sparkline": [],
            "last_seen": None,
            "firmware": None,
            "group": "system",
        })
        degraded_count = 1

    return {
        "sensors": sensors,
        "total": len(sensors),
        "healthy": sum(1 for s in sensors if s["health"] == "green"),
        "degraded": degraded_count,
        "timestamp": time.time(),
    }
