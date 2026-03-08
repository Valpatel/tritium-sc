# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Fleet API router — proxies tritium-edge fleet server REST endpoints.

Provides /api/fleet/nodes, /api/fleet/presence, and /api/fleet/node/{id}
so the frontend can query edge sensor node data without direct fleet server
access.  Falls back to cached data from FleetBridge when the fleet server
is unreachable.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


def _get_fleet_url(request: Request) -> str:
    """Resolve fleet server base URL from bridge or settings."""
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        return bridge.rest_url
    # Fallback to settings
    try:
        from app.config import settings
        return settings.fleet_server_url.rstrip("/")
    except Exception:
        return "http://localhost:8080"


def _proxy_get(url: str, timeout: float = 5.0) -> dict | list | None:
    """GET a JSON endpoint from the fleet server."""
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
        logger.debug(f"Fleet proxy GET {url} failed: {e}")
        return None


@router.get("/nodes")
async def fleet_nodes(request: Request):
    """GET /api/fleet/nodes — list all tritium-edge sensor nodes.

    Proxies to the fleet server /api/devices endpoint.  Falls back to
    cached device data from FleetBridge if the fleet server is unreachable.
    """
    base = _get_fleet_url(request)
    data = _proxy_get(f"{base}/api/devices")

    if data is not None:
        devices = data if isinstance(data, list) else data.get("devices", [])
        return {"nodes": devices, "count": len(devices), "source": "live"}

    # Fallback: return cached data from bridge
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        devices = list(bridge.devices.values())
        return {"nodes": devices, "count": len(devices), "source": "cached"}

    return {"nodes": [], "count": 0, "source": "unavailable"}


@router.get("/presence")
async def fleet_presence(request: Request):
    """GET /api/fleet/presence — BLE presence data from edge nodes.

    Proxies to the fleet server /api/presence/ble endpoint.
    """
    base = _get_fleet_url(request)
    data = _proxy_get(f"{base}/api/presence/ble")

    if data is not None:
        devices = data if isinstance(data, list) else data.get("devices", [])
        return {"devices": devices, "count": len(devices), "source": "live"}

    # Fallback: cached BLE data from bridge
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        devices = bridge.ble_presence
        return {"devices": devices, "count": len(devices), "source": "cached"}

    return {"devices": [], "count": 0, "source": "unavailable"}


@router.get("/config")
async def fleet_config(request: Request):
    """GET /api/fleet/config — fleet configuration sync status.

    Proxies to the fleet server /api/fleet/config endpoint.  Falls back to
    cached config_sync data from FleetBridge when the fleet server is
    unreachable.
    """
    base = _get_fleet_url(request)
    data = _proxy_get(f"{base}/api/fleet/config")

    if data is not None:
        return {**data, "source": "live"}

    # Fallback: cached config sync from bridge
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        cached = bridge.config_sync
        if cached:
            return {**cached, "source": "cached"}

    return {
        "config_version": "unknown",
        "nodes_synced": 0,
        "nodes_total": 0,
        "nodes_pending": [],
        "source": "unavailable",
    }


@router.get("/dashboard")
async def fleet_dashboard(request: Request):
    """GET /api/fleet/dashboard — combined health + config + alerts summary.

    Proxies to the fleet server /api/fleet/dashboard endpoint.  Falls back
    to cached dashboard data from FleetBridge when unreachable.
    """
    base = _get_fleet_url(request)
    data = _proxy_get(f"{base}/api/fleet/dashboard")

    if data is not None:
        return {**data, "source": "live"}

    # Fallback: cached dashboard from bridge
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        cached = bridge.dashboard
        if cached:
            return {**cached, "source": "cached"}

    return {
        "health": {"score": 0, "total_nodes": 0, "online_count": 0, "ble_total": 0},
        "config": {"synced_count": 0, "drifted_count": 0, "critical_drift_count": 0, "sync_ratio": 1.0},
        "alerts": {"recent_count": 0, "critical": 0, "warning": 0, "recent": []},
        "server_uptime_s": 0,
        "source": "unavailable",
    }


@router.get("/health-report")
async def fleet_health_report(request: Request):
    """GET /api/fleet/health-report — per-node health classification and anomalies.

    Proxies to the fleet server /api/fleet/health-report endpoint.  Falls back
    to cached health report from FleetBridge when unreachable.
    """
    base = _get_fleet_url(request)
    data = _proxy_get(f"{base}/api/fleet/health-report")

    if data is not None:
        return {**data, "source": "live"}

    # Fallback: cached health report from bridge
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        cached = bridge.health_report
        if cached:
            return {**cached, "source": "cached"}

    return {
        "total_nodes": 0,
        "healthy": 0,
        "warning": 0,
        "critical": 0,
        "anomaly_count": 0,
        "anomalies": [],
        "nodes": [],
        "source": "unavailable",
    }


@router.get("/node/{device_id}")
async def fleet_node_detail(request: Request, device_id: str):
    """GET /api/fleet/node/{device_id} — detail for a specific edge node.

    Proxies to the fleet server /api/devices/{id}/sensors endpoint and
    merges with base device data.
    """
    base = _get_fleet_url(request)

    # Fetch device list and find the matching device
    devices_data = _proxy_get(f"{base}/api/devices")
    device = None
    if devices_data is not None:
        devices = devices_data if isinstance(devices_data, list) else devices_data.get("devices", [])
        for d in devices:
            did = d.get("device_id") or d.get("id", "")
            if did == device_id:
                device = d
                break

    # Fetch sensor data
    sensors_data = _proxy_get(f"{base}/api/devices/{device_id}/sensors")

    if device is None:
        # Try cached data from bridge
        bridge = getattr(request.app.state, "fleet_bridge", None)
        if bridge is not None:
            device = bridge.devices.get(device_id)

    if device is None:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    result = {**device}
    if sensors_data is not None:
        result["sensors_detail"] = sensors_data

    return result
