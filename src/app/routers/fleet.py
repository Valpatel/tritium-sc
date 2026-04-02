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

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_auth
from tritium_lib.models.correlation import (
    CorrelationEvent,
    classify_correlation_severity,
    summarize_correlations,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fleet", tags=["fleet"], dependencies=[Depends(require_auth)])


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


@router.get("/status")
async def fleet_status(request: Request):
    """Fleet management status.

    Returns whether the fleet server is reachable, how many edge nodes
    are known, and the data source (live vs cached vs unavailable).
    """
    base = _get_fleet_url(request)

    # Quick probe: try to reach the fleet server
    data = _proxy_get(f"{base}/api/devices", timeout=3.0)

    if data is not None:
        devices = data if isinstance(data, list) else data.get("devices", [])
        online = sum(1 for d in devices if d.get("status") == "online")
        return {
            "status": "running",
            "available": True,
            "fleet_url": base,
            "total_nodes": len(devices),
            "online_nodes": online,
            "source": "live",
        }

    # Fallback: check bridge cache
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None and bridge.devices:
        return {
            "status": "degraded",
            "available": True,
            "fleet_url": base,
            "total_nodes": len(bridge.devices),
            "online_nodes": 0,
            "source": "cached",
        }

    return {
        "status": "stopped",
        "available": False,
        "fleet_url": base,
        "total_nodes": 0,
        "online_nodes": 0,
        "source": "unavailable",
    }


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


@router.get("/correlations")
async def fleet_correlations(request: Request):
    """GET /api/fleet/correlations — cross-node event correlations.

    Proxies to the fleet server /api/fleet/correlations endpoint.
    Returns synchronized reboots, cascading failures, and other
    correlated events across the fleet with confidence scores.
    Each correlation is enriched with a severity badge and
    devices_involved list via tritium-lib models.
    """
    base = _get_fleet_url(request)
    data = _proxy_get(f"{base}/api/fleet/correlations")

    if data is not None:
        result = {**data, "source": "live"} if isinstance(data, dict) else {"correlations": data, "source": "live"}
        result["correlations"] = _enrich_correlations(result.get("correlations", []))
        result["summary"] = _correlation_summary(result.get("correlations", []))
        return result

    # Fallback: cached correlations from bridge
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        cached = getattr(bridge, "correlations", {})
        if cached:
            result = {**cached, "source": "cached"}
            result["correlations"] = _enrich_correlations(result.get("correlations", []))
            result["summary"] = _correlation_summary(result.get("correlations", []))
            return result

    return {
        "correlations": [],
        "count": 0,
        "summary": {"total": 0, "high_confidence": 0, "by_type": {}, "affected_devices": 0},
        "source": "unavailable",
    }


def _enrich_correlations(raw: list) -> list[dict]:
    """Add severity badges and devices_involved to correlation dicts."""
    enriched = []
    for c in raw:
        if not isinstance(c, dict):
            enriched.append(c)
            continue
        # Skip if already enriched (from bridge cache)
        if "severity" in c:
            enriched.append(c)
            continue
        try:
            event = CorrelationEvent(**c)
            enriched.append({
                **c,
                "severity": classify_correlation_severity(event),
                "devices_involved": event.devices_involved,
            })
        except Exception:
            enriched.append(c)
    return enriched


def _correlation_summary(enriched: list) -> dict:
    """Produce a compact summary from enriched correlation dicts."""
    typed: list[CorrelationEvent] = []
    for c in enriched:
        if not isinstance(c, dict):
            continue
        try:
            typed.append(CorrelationEvent(**{
                k: v for k, v in c.items() if k != "severity"
            }))
        except Exception:
            pass
    return summarize_correlations(typed)


@router.get("/topology")
async def fleet_topology(request: Request):
    """GET /api/fleet/topology — fleet network topology and connectivity.

    Proxies to the fleet server /api/fleet/topology endpoint.
    Returns node connectivity graph, link quality, and network structure.
    """
    base = _get_fleet_url(request)
    data = _proxy_get(f"{base}/api/fleet/topology")

    if data is not None:
        return {**data, "source": "live"} if isinstance(data, dict) else {"nodes": data, "source": "live"}

    # Fallback: cached topology from bridge
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        cached = getattr(bridge, "topology", {})
        if cached:
            return {**cached, "source": "cached"}

    return {
        "nodes": [],
        "edges": [],
        "source": "unavailable",
    }


@router.get("/heap-trends")
async def fleet_heap_trends(request: Request):
    """GET /api/fleet/heap-trends — per-node heap memory trend analysis.

    Proxies to the fleet server /api/fleet/heap-trends endpoint.
    Returns heap usage trends, suspected memory leaks, and trend
    direction for each tracked node.
    """
    base = _get_fleet_url(request)
    data = _proxy_get(f"{base}/api/fleet/heap-trends")

    if data is not None:
        return {**data, "source": "live"} if isinstance(data, dict) else {"trends": data, "source": "live"}

    # Fallback: cached heap trends from bridge
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        cached = getattr(bridge, "heap_trends", {})
        if cached:
            return {**cached, "source": "cached"}

    return {
        "trends": [],
        "leak_suspects": [],
        "source": "unavailable",
    }


@router.get("/mesh-peers")
async def fleet_mesh_peers(request: Request):
    """GET /api/fleet/mesh-peers — mesh peer data from all edge nodes.

    Proxies to the fleet server /api/fleet/mesh-peers endpoint.
    Returns per-node mesh peer lists with MAC addresses, RSSI, and hop counts.
    Falls back to extracting mesh_peers from cached device data.
    """
    base = _get_fleet_url(request)
    data = _proxy_get(f"{base}/api/fleet/mesh-peers")

    if data is not None:
        return {**data, "source": "live"} if isinstance(data, dict) else {"nodes": data, "source": "live"}

    # Fallback: extract mesh_peers from cached device data
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        mesh_nodes = []
        for dev_id, dev in bridge.devices.items():
            peers = dev.get("mesh_peers", [])
            if not peers:
                sensors = dev.get("sensors", {})
                mesh = sensors.get("mesh", {})
                peers = mesh.get("peers", [])
            if peers:
                mesh_nodes.append({
                    "device_id": dev_id,
                    "mesh_peers": peers,
                })
        return {"nodes": mesh_nodes, "count": len(mesh_nodes), "source": "cached"}

    return {"nodes": [], "count": 0, "source": "unavailable"}


@router.get("/node/{device_id}/mesh-peers")
async def fleet_node_mesh_peers(request: Request, device_id: str):
    """GET /api/fleet/node/{device_id}/mesh-peers — mesh peers for a specific node.

    Proxies to the fleet server /api/devices/{id}/mesh-peers endpoint.
    Returns the mesh peer list with MAC, RSSI, and hop count for each peer.
    """
    base = _get_fleet_url(request)
    data = _proxy_get(f"{base}/api/devices/{device_id}/mesh-peers")

    if data is not None:
        return {**data, "device_id": device_id, "source": "live"}

    # Fallback: extract from cached device data
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        dev = bridge.devices.get(device_id)
        if dev:
            peers = dev.get("mesh_peers", [])
            if not peers:
                sensors = dev.get("sensors", {})
                mesh = sensors.get("mesh", {})
                peers = mesh.get("peers", [])
            return {"device_id": device_id, "mesh_peers": peers, "source": "cached"}

    return {"device_id": device_id, "mesh_peers": [], "source": "unavailable"}


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


@router.get("/node/{device_id}/diag")
async def fleet_node_diag(request: Request, device_id: str):
    """GET /api/fleet/node/{device_id}/diag — diagnostics for a specific edge node.

    Proxies to the fleet server /api/devices/{id}/diag endpoint for full
    health snapshot, I2C slave data, recent events, and active anomalies.
    Falls back to cached diagnostics from FleetBridge when unreachable.
    """
    base = _get_fleet_url(request)
    data = _proxy_get(f"{base}/api/devices/{device_id}/diag")

    if data is not None:
        return {**data, "device_id": device_id, "source": "live"}

    # Fallback: cached diagnostics from bridge
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is not None:
        cached = getattr(bridge, "node_diag", {}).get(device_id)
        if cached:
            return {**cached, "device_id": device_id, "source": "cached"}

    return {
        "device_id": device_id,
        "health": {},
        "i2c_slaves": [],
        "events": [],
        "anomalies": [],
        "source": "unavailable",
    }
