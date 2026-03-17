# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Meshtastic plugin.

Provides REST API for mesh node queries, messaging, and bridge status.
The frontend mesh panel consumes these endpoints.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

if TYPE_CHECKING:
    from .plugin import MeshtasticPlugin


def create_router(plugin: MeshtasticPlugin) -> APIRouter:
    """Create FastAPI router for Meshtastic endpoints."""

    router = APIRouter(prefix="/api/meshtastic", tags=["meshtastic"])

    # Also register under /api/mesh for backward compatibility
    compat_router = APIRouter(prefix="/api/mesh", tags=["meshtastic"])

    @router.get("/nodes")
    @compat_router.get("/nodes")
    async def list_nodes(
        sort_by: str = Query("last_heard", description="Sort field"),
        has_gps: bool = Query(False, description="Only nodes with GPS"),
        limit: int = Query(0, description="Max nodes to return (0=all)"),
    ):
        """List all known Meshtastic mesh nodes with extended data."""
        nodes_list = list(plugin._nodes.values())

        # Filter
        if has_gps:
            nodes_list = [
                n for n in nodes_list
                if n.get("lat") is not None and n.get("lng") is not None
                and (n["lat"] != 0.0 or n["lng"] != 0.0)
            ]

        # Sort
        now = int(time.time())
        if sort_by == "last_heard":
            nodes_list.sort(key=lambda n: n.get("last_heard") or 0, reverse=True)
        elif sort_by == "name":
            nodes_list.sort(key=lambda n: (n.get("name") or "").lower())
        elif sort_by == "battery":
            nodes_list.sort(key=lambda n: n.get("battery") or 0, reverse=True)
        elif sort_by == "snr":
            nodes_list.sort(key=lambda n: n.get("snr") or -999, reverse=True)

        if limit > 0:
            nodes_list = nodes_list[:limit]

        # Compute aggregate stats
        total = len(plugin._nodes)
        with_gps = sum(
            1 for n in plugin._nodes.values()
            if n.get("lat") is not None and n.get("lng") is not None
            and (n["lat"] != 0.0 or n["lng"] != 0.0)
        )
        with_battery = sum(
            1 for n in plugin._nodes.values()
            if n.get("battery") is not None
        )
        recently_heard = sum(
            1 for n in plugin._nodes.values()
            if n.get("last_heard") and (now - n["last_heard"]) < 3600
        )

        return {
            "nodes": nodes_list,
            "count": len(nodes_list),
            "total": total,
            "stats": {
                "total_nodes": total,
                "with_gps": with_gps,
                "with_battery": with_battery,
                "recently_heard_1h": recently_heard,
            },
            "connected": plugin._interface is not None,
            "bridge_online": plugin._bridge_online,
            "connection_type": plugin._config.connection_type,
        }

    @router.get("/nodes/{node_id}")
    @compat_router.get("/nodes/{node_id}")
    async def get_node(node_id: str):
        """Get details for a specific mesh node."""
        # Try exact match first, then try with ! prefix
        node = plugin._nodes.get(node_id)
        if node is None and not node_id.startswith("!"):
            node = plugin._nodes.get(f"!{node_id}")
        if node is None:
            return {"error": f"Node {node_id} not found"}, 404
        return node

    @router.get("/messages")
    @compat_router.get("/messages")
    async def list_messages(
        limit: int = Query(50, description="Max messages to return"),
        channel: int = Query(-1, description="Filter by channel (-1=all)"),
    ):
        """List recent mesh text messages."""
        msgs = plugin._messages
        if channel >= 0:
            msgs = [m for m in msgs if m.get("channel") == channel]
        return {
            "messages": msgs[-limit:],
            "total": len(msgs),
        }

    @router.post("/send")
    @compat_router.post("/send")
    async def send_message(text: str, destination: str | None = None):
        """Send a text message via the Meshtastic mesh.

        Short messages only -- LoRa payload limit is ~228 bytes.
        """
        if len(text) > 228:
            return {"error": "Message too long (max 228 bytes for LoRa)"}, 400

        ok = plugin.send_text(text, destination)
        return {"sent": ok, "text": text, "destination": destination or "broadcast"}

    @router.post("/chat")
    @compat_router.post("/chat")
    async def operator_chat_to_mesh(text: str, sender: str = "SC Operator"):
        """Send a message from the operator chat panel to the mesh network.

        Enables SC operators to communicate with mesh radio users.
        The message is sent via the Meshtastic radio and also logged
        in the local message buffer.
        """
        if not text:
            return {"error": "Empty message"}
        if len(text) > 228:
            return {"error": "Message too long (max 228 bytes for LoRa)"}, 400

        # Send to mesh
        ok = plugin.send_text(text)

        # Log in local buffer
        import time as time_mod
        msg = {
            "from_name": sender,
            "text": text,
            "channel": 0,
            "timestamp": time_mod.time(),
            "source": "operator",
        }
        plugin._messages.append(msg)
        if len(plugin._messages) > plugin._max_messages:
            plugin._messages = plugin._messages[-plugin._max_messages:]

        return {"sent": ok, "text": text, "sender": sender}

    @router.post("/waypoint")
    @compat_router.post("/waypoint")
    async def send_waypoint(
        lat: float, lng: float, name: str = "", destination: str | None = None
    ):
        """Send a waypoint to a Meshtastic node."""
        ok = plugin.send_waypoint(lat, lng, name, destination)
        return {"sent": ok, "lat": lat, "lng": lng, "name": name}

    @router.get("/nodes/{node_id}/telemetry-history")
    @compat_router.get("/nodes/{node_id}/telemetry-history")
    async def get_node_telemetry_history(node_id: str):
        """Get telemetry history for a specific node (for sparkline charts).

        Returns time-series data points with battery, voltage, temperature,
        humidity, and channel utilization values.
        """
        # Try exact match first, then with ! prefix
        history = plugin.get_telemetry_history(node_id)
        if not history and not node_id.startswith("!"):
            history = plugin.get_telemetry_history(f"!{node_id}")

        return {
            "node_id": node_id,
            "points": history,
            "count": len(history),
        }

    @router.get("/environment")
    @compat_router.get("/environment")
    async def environment():
        """Get environment readings from mesh nodes with sensors."""
        readings = []
        for node_id, node in plugin._nodes.items():
            temp = node.get("temperature")
            humidity = node.get("humidity")
            pressure = node.get("pressure")
            if temp is not None or humidity is not None or pressure is not None:
                readings.append({
                    "source_id": node_id,
                    "source_name": node.get("name") or node.get("short_name") or node_id,
                    "temperature_c": temp,
                    "humidity_pct": humidity,
                    "pressure_hpa": pressure,
                    "last_heard": node.get("last_heard"),
                    "lat": node.get("lat"),
                    "lng": node.get("lng"),
                })
        return {
            "readings": readings,
            "count": len(readings),
        }

    @router.get("/status")
    @compat_router.get("/status")
    async def status():
        """Meshtastic bridge status."""
        total = len(plugin._nodes)
        now = int(time.time())
        recently_heard = sum(
            1 for n in plugin._nodes.values()
            if n.get("last_heard") and (now - n["last_heard"]) < 3600
        )

        return {
            "enabled": plugin._config.enabled,
            "connected": plugin._interface is not None,
            "bridge_online": plugin._bridge_online,
            "connection_type": plugin._config.connection_type,
            "node_count": total,
            "recently_heard_1h": recently_heard,
            "message_count": len(plugin._messages),
            "healthy": plugin.healthy,
        }

    # Register the compat router on the plugin's app
    if plugin._app:
        plugin._app.include_router(compat_router)

    return router
