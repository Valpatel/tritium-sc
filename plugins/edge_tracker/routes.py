# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Edge Tracker BLE and WiFi plugin.

Provides REST endpoints for querying active BLE devices and WiFi networks,
managing tracked targets, sighting history, node positions, and database stats.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Trilateration — may not be available if tritium-lib is still building.
try:
    from tritium_lib.models.trilateration import estimate_position
except ImportError:  # pragma: no cover
    estimate_position = None  # type: ignore[assignment]


# -- Request / response models --------------------------------------------

class AddTargetRequest(BaseModel):
    mac: str
    label: str
    color: str = ""


class AddWifiTargetRequest(BaseModel):
    bssid: str
    label: str
    ssid: str = ""
    color: str = ""


class SetNodePositionRequest(BaseModel):
    x: float
    y: float
    lat: Optional[float] = None
    lon: Optional[float] = None
    label: str = ""


# -- Router factory --------------------------------------------------------

def create_router(store: Any) -> APIRouter:
    """Build and return the edge-tracker APIRouter.

    Parameters
    ----------
    store:
        A ``BleStore`` instance (or ``None`` if tritium-lib is not
        installed — all endpoints will return 503 in that case).
    """
    router = APIRouter(prefix="/api/edge/ble", tags=["edge-tracker"])

    def _require_store() -> Any:
        if store is None:
            raise HTTPException(
                status_code=503,
                detail="BleStore not available — tritium-lib not installed",
            )
        return store

    # -- Active devices ----------------------------------------------------

    @router.get("/active")
    async def get_active_devices():
        """Return active BLE devices enriched with position estimates."""
        s = _require_store()
        devices = s.get_active_devices()

        # Enrich with position estimates if trilateration is available
        if estimate_position is not None:
            node_positions_raw = s.get_node_positions()
            # Build node_id -> (lat, lon) map for trilateration
            node_positions: dict[str, tuple[float, float]] = {}
            for nid, pos in node_positions_raw.items():
                lat = pos.get("lat")
                lon = pos.get("lon")
                if lat is not None and lon is not None:
                    node_positions[nid] = (lat, lon)

            # Also check target tracking status
            targets = {t["mac"]: t for t in s.list_targets()}

            for dev in devices:
                # Position estimate
                if len(dev.get("nodes", [])) >= 2 and node_positions:
                    sightings = [
                        {"node_id": n["node_id"], "ble_rssi": n["rssi"]}
                        for n in dev["nodes"]
                    ]
                    pos_est = estimate_position(sightings, node_positions)
                    if pos_est is not None:
                        dev["position"] = pos_est

                # Tracking status
                target = targets.get(dev["mac"])
                if target:
                    dev["tracked"] = True
                    dev["target_label"] = target.get("label", "")
                    dev["target_color"] = target.get("color", "")
                else:
                    dev["tracked"] = False

        return {"devices": devices, "count": len(devices)}

    # -- Tracked targets ---------------------------------------------------

    @router.get("/targets")
    async def list_targets():
        """List tracked BLE targets."""
        s = _require_store()
        targets = s.list_targets()
        return {"targets": targets, "count": len(targets)}

    @router.post("/targets")
    async def add_target(body: AddTargetRequest):
        """Add a tracked BLE target."""
        s = _require_store()
        target = s.add_target(body.mac, body.label, body.color)
        return {"target": target}

    @router.delete("/targets/{mac:path}")
    async def remove_target(mac: str):
        """Remove a tracked BLE target."""
        s = _require_store()
        removed = s.remove_target(mac)
        if not removed:
            raise HTTPException(status_code=404, detail="Target not found")
        return {"removed": True, "mac": mac}

    # -- History -----------------------------------------------------------

    @router.get("/history/{mac:path}")
    async def get_device_history(mac: str, limit: int = 200):
        """Sighting history for a specific MAC address."""
        s = _require_store()
        history = s.get_device_history(mac, limit=limit)
        return {"mac": mac, "history": history, "count": len(history)}

    # -- Summary -----------------------------------------------------------

    @router.get("/summary")
    async def get_summary():
        """Summary stats from BleStore."""
        s = _require_store()
        return s.get_device_summary()

    # -- Node positions ----------------------------------------------------

    @router.get("/nodes/positions")
    async def get_node_positions():
        """All sensor node positions."""
        s = _require_store()
        positions = s.get_node_positions()
        return {"positions": positions, "count": len(positions)}

    @router.put("/nodes/{node_id}/position")
    async def set_node_position(node_id: str, body: SetNodePositionRequest):
        """Set a sensor node's position."""
        s = _require_store()
        s.set_node_position(
            node_id,
            body.x,
            body.y,
            lat=body.lat,
            lon=body.lon,
            label=body.label,
        )
        return {"node_id": node_id, "set": True}

    @router.delete("/nodes/{node_id}/position")
    async def remove_node_position(node_id: str):
        """Remove a sensor node's position."""
        s = _require_store()
        removed = s.remove_node_position(node_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Node position not found")
        return {"node_id": node_id, "removed": True}

    # -- Database stats ----------------------------------------------------

    @router.get("/stats")
    async def get_stats():
        """Database statistics."""
        s = _require_store()
        return s.get_stats()

    # ==================================================================
    # WiFi endpoints — mounted under /api/edge/wifi
    # ==================================================================

    wifi_router = APIRouter(prefix="/api/edge/wifi", tags=["edge-tracker-wifi"])

    # -- Active WiFi networks ----------------------------------------------

    @wifi_router.get("/active")
    async def get_active_wifi():
        """Return active WiFi networks seen by edge nodes."""
        s = _require_store()
        networks = s.get_active_wifi_networks()

        # Enrich with tracking status
        targets = {t["bssid"]: t for t in s.list_wifi_targets()}
        for net in networks:
            target = targets.get(net["bssid"])
            if target:
                net["tracked"] = True
                net["target_label"] = target.get("label", "")
                net["target_color"] = target.get("color", "")
            else:
                net["tracked"] = False

        return {"networks": networks, "count": len(networks)}

    # -- Tracked WiFi targets ----------------------------------------------

    @wifi_router.get("/targets")
    async def list_wifi_targets():
        """List tracked WiFi targets."""
        s = _require_store()
        targets = s.list_wifi_targets()
        return {"targets": targets, "count": len(targets)}

    @wifi_router.post("/targets")
    async def add_wifi_target(body: AddWifiTargetRequest):
        """Add a tracked WiFi target."""
        s = _require_store()
        target = s.add_wifi_target(body.bssid, body.label, ssid=body.ssid, color=body.color)
        return {"target": target}

    @wifi_router.delete("/targets/{bssid:path}")
    async def remove_wifi_target(bssid: str):
        """Remove a tracked WiFi target."""
        s = _require_store()
        removed = s.remove_wifi_target(bssid)
        if not removed:
            raise HTTPException(status_code=404, detail="WiFi target not found")
        return {"removed": True, "bssid": bssid}

    # -- WiFi History ------------------------------------------------------

    @wifi_router.get("/history/{bssid:path}")
    async def get_wifi_history(bssid: str, limit: int = 200):
        """Sighting history for a specific BSSID."""
        s = _require_store()
        history = s.get_wifi_history(bssid, limit=limit)
        return {"bssid": bssid, "history": history, "count": len(history)}

    # -- WiFi Summary ------------------------------------------------------

    @wifi_router.get("/summary")
    async def get_wifi_summary():
        """Summary stats from WiFi sighting database."""
        s = _require_store()
        return s.get_wifi_summary()

    return router, wifi_router
