# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Meshtastic plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from .plugin import MeshtasticPlugin


def create_router(plugin: MeshtasticPlugin) -> APIRouter:
    """Create FastAPI router for Meshtastic endpoints."""

    router = APIRouter(prefix="/api/meshtastic", tags=["meshtastic"])

    @router.get("/nodes")
    async def list_nodes():
        """List all known Meshtastic mesh nodes."""
        return {
            "nodes": list(plugin._nodes.values()),
            "count": len(plugin._nodes),
            "connected": plugin._interface is not None,
            "connection_type": plugin._config.connection_type,
        }

    @router.get("/nodes/{node_id}")
    async def get_node(node_id: str):
        """Get details for a specific mesh node."""
        node = plugin._nodes.get(node_id)
        if node is None:
            return {"error": f"Node {node_id} not found"}, 404
        return node

    @router.post("/send")
    async def send_message(text: str, destination: str | None = None):
        """Send a text message via the Meshtastic mesh.

        Short messages only — LoRa payload limit is ~228 bytes.
        """
        if len(text) > 228:
            return {"error": "Message too long (max 228 bytes for LoRa)"}, 400

        ok = plugin.send_text(text, destination)
        return {"sent": ok, "text": text, "destination": destination or "broadcast"}

    @router.post("/waypoint")
    async def send_waypoint(
        lat: float, lng: float, name: str = "", destination: str | None = None
    ):
        """Send a waypoint to a Meshtastic node."""
        ok = plugin.send_waypoint(lat, lng, name, destination)
        return {"sent": ok, "lat": lat, "lng": lng, "name": name}

    @router.get("/status")
    async def status():
        """Meshtastic bridge status."""
        return {
            "enabled": plugin._config.enabled,
            "connected": plugin._interface is not None,
            "connection_type": plugin._config.connection_type,
            "node_count": len(plugin._nodes),
            "healthy": plugin.healthy,
        }

    return router
