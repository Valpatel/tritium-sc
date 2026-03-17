# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Meshtastic addon."""

from __future__ import annotations

from fastapi import APIRouter


def create_router(connection, node_manager) -> APIRouter:
    """Create FastAPI router for Meshtastic addon endpoints."""

    router = APIRouter()

    @router.get("/status")
    async def status():
        """Connection and device status."""
        return {
            "connected": connection.is_connected if connection else False,
            "transport": connection.transport_type if connection else "none",
            "port": connection.port if connection else "",
            "device": connection.device_info if connection else {},
            "node_count": len(node_manager.nodes) if node_manager else 0,
        }

    @router.get("/nodes")
    async def get_nodes():
        """All known mesh nodes."""
        if not node_manager:
            return {"nodes": []}
        nodes = []
        for nid, node in node_manager.nodes.items():
            nodes.append({
                "node_id": nid,
                "long_name": node.get("long_name", ""),
                "short_name": node.get("short_name", ""),
                "hw_model": node.get("hw_model", ""),
                "lat": node.get("lat"),
                "lng": node.get("lng"),
                "altitude": node.get("altitude"),
                "battery": node.get("battery"),
                "voltage": node.get("voltage"),
                "snr": node.get("snr"),
                "last_heard": node.get("last_heard"),
                "uptime": node.get("uptime"),
                "channel_util": node.get("channel_util"),
                "air_util": node.get("air_util"),
            })
        return {"nodes": nodes, "count": len(nodes)}

    @router.get("/nodes/{node_id}")
    async def get_node(node_id: str):
        """Single node details."""
        if not node_manager:
            return {"error": "not_available"}
        node = node_manager.get_node(node_id)
        if not node:
            return {"error": "not_found"}
        return node

    @router.get("/links")
    async def get_links():
        """Mesh network links between nodes."""
        if not node_manager:
            return {"links": []}
        return {"links": node_manager.get_links()}

    @router.get("/targets")
    async def get_targets():
        """Nodes as Tritium target format."""
        if not node_manager:
            return {"targets": []}
        return {"targets": node_manager.get_targets()}

    @router.post("/connect")
    async def connect(body: dict = None):
        """Connect to a Meshtastic device.

        Body: { "transport": "serial"|"tcp"|"ble", "port": "/dev/ttyACM0" or "host:port" }
        """
        if not connection:
            return {"error": "connection_manager_not_available"}
        body = body or {}
        transport = body.get("transport", "serial")
        port = body.get("port", "")

        if transport == "serial":
            await connection.connect_serial(port or "/dev/ttyACM0")
        elif transport == "tcp":
            host = port or "localhost"
            await connection.connect_tcp(host)
        else:
            return {"error": f"unsupported transport: {transport}"}

        return {
            "connected": connection.is_connected,
            "transport": connection.transport_type,
            "port": connection.port,
            "device": connection.device_info,
        }

    @router.post("/disconnect")
    async def disconnect():
        """Disconnect from the current device."""
        if connection:
            await connection.disconnect()
        return {"connected": False}

    @router.post("/send")
    async def send_message(body: dict):
        """Send a text message via the mesh.

        Body: { "text": "Hello mesh!", "destination": "!ba33ff38" (optional) }
        """
        if not connection:
            return {"error": "not_connected"}
        text = body.get("text", "")
        dest = body.get("destination")
        if not text:
            return {"error": "empty_message"}
        ok = await connection.send_text(text, destination=dest)
        return {"sent": ok, "text": text, "destination": dest}

    @router.get("/health")
    async def health():
        """Addon health check."""
        return {
            "status": "ok" if (connection and connection.is_connected) else "degraded",
            "connected": connection.is_connected if connection else False,
            "node_count": len(node_manager.nodes) if node_manager else 0,
        }

    return router
