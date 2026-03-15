# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the WiFi Fingerprint plugin.

Provides REST endpoints for viewing probe correlations, WiFi fingerprints,
correlation links between WiFi and BLE devices, and multi-node probe
proximity estimates.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .correlator import ProbeCorrelator
from .probe_proximity import ProbeProximityEstimator

# Auth — optional import (tests may not have app.auth available)
try:
    from app.auth import optional_auth
except ImportError:  # pragma: no cover
    async def optional_auth():  # type: ignore[misc]
        return None


def create_router(
    correlator: ProbeCorrelator,
    proximity_estimator: Optional[ProbeProximityEstimator] = None,
) -> APIRouter:
    """Build and return the wifi-fingerprint APIRouter."""

    router = APIRouter(prefix="/api/wifi-fingerprint", tags=["wifi-fingerprint"])

    @router.get("/status")
    async def get_status():
        """Get correlator status and statistics."""
        status = correlator.get_status()
        if proximity_estimator is not None:
            status["proximity"] = proximity_estimator.get_status()
        return status

    @router.get("/links")
    async def get_links(min_score: float = 0.3):
        """Get all WiFi-BLE correlation links above threshold."""
        links = correlator.get_all_links(min_score=min_score)
        return {"links": links, "count": len(links)}

    @router.get("/fingerprint/{wifi_mac}")
    async def get_fingerprint(wifi_mac: str):
        """Get WiFi fingerprint (probed SSIDs) for a device by MAC."""
        fp = correlator.get_fingerprint(wifi_mac)
        if not fp["probed_ssids"] and fp["probe_count"] == 0:
            raise HTTPException(status_code=404, detail="WiFi MAC not found")
        return fp

    @router.get("/correlations/{ble_mac}")
    async def get_correlations(ble_mac: str):
        """Get WiFi correlations for a BLE device MAC."""
        enrichment = correlator.get_dossier_enrichment(ble_mac)
        if not enrichment:
            return {"wifi_correlations": [], "all_probed_ssids": [], "strongest_score": 0.0}
        return enrichment

    @router.get("/ble-links/{ble_mac}")
    async def get_ble_links(ble_mac: str):
        """Get all WiFi correlation links for a BLE device."""
        links = correlator.get_links_for_ble(ble_mac)
        return {"links": [l.to_dict() for l in links], "count": len(links)}

    @router.get("/proximity")
    async def get_proximity_estimates(
        device_mac: Optional[str] = None,
        limit: int = Query(default=50, ge=1, le=1000),
        _user: dict = Depends(optional_auth),
    ):
        """Get recent probe proximity estimates (multi-node proximity detection)."""
        if proximity_estimator is None:
            return {"estimates": [], "count": 0, "available": False}
        estimates = proximity_estimator.get_estimates(
            device_mac=device_mac, limit=limit,
        )
        return {"estimates": estimates, "count": len(estimates), "available": True}

    @router.get("/proximity/{device_mac}/closest")
    async def get_closest_node(device_mac: str, _user: dict = Depends(optional_auth)):
        """Get the closest edge node for a specific device MAC."""
        if proximity_estimator is None:
            raise HTTPException(status_code=503, detail="Proximity estimator not available")
        # Validate MAC format (basic sanitization)
        clean_mac = device_mac.strip().lower()
        if len(clean_mac) > 40:
            raise HTTPException(status_code=400, detail="Invalid MAC address")
        closest = proximity_estimator.get_closest_node(clean_mac)
        if closest is None:
            raise HTTPException(status_code=404, detail="No proximity estimate for device")
        return {"device_mac": clean_mac, "closest_node": closest}

    @router.post("/prune")
    async def prune_stale(max_age: float = 3600.0):
        """Prune stale records and decay old correlation scores."""
        pruned = correlator.prune_stale(max_age=max_age)
        if proximity_estimator is not None:
            pruned += proximity_estimator.prune_stale(max_age=max_age)
        return {"pruned": pruned, "status": correlator.get_status()}

    return router
