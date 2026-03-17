# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Meshtastic addon."""

from __future__ import annotations

from fastapi import APIRouter


def create_router(connection, node_manager, message_bridge=None) -> APIRouter:
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

        Body: {
            "transport": "serial"|"tcp"|"ble",
            "port": "/dev/ttyACM0" or "host:port",
            "timeout": 30  (optional, seconds)
        }
        """
        if not connection:
            return {"error": "connection_manager_not_available"}
        body = body or {}
        transport = body.get("transport", "serial")
        port = body.get("port", "")
        timeout = float(body.get("timeout", 30))

        if transport == "serial":
            serial_port = port or "/dev/ttyACM0"
            from pathlib import Path
            if not Path(serial_port).exists():
                return {
                    "connected": False,
                    "error": f"port_not_found",
                    "message": f"Serial port {serial_port} does not exist. Is the device plugged in?",
                }
            await connection.connect_serial(serial_port, timeout=timeout)
        elif transport == "tcp":
            host = port or "localhost"
            await connection.connect_tcp(host, timeout=timeout)
        else:
            return {"error": f"unsupported transport: {transport}"}

        result = {
            "connected": connection.is_connected,
            "transport": connection.transport_type,
            "port": connection.port,
            "device": connection.device_info,
        }
        if not connection.is_connected:
            result["error"] = "connection_failed"
            result["message"] = (
                f"Failed to connect via {transport} on {port or 'default'}. "
                f"The device may be busy, unresponsive, or the port may be locked by another process."
            )
        return result

    @router.post("/disconnect")
    async def disconnect():
        """Disconnect from the current device."""
        if connection:
            await connection.disconnect()
        return {"connected": False}

    @router.get("/messages")
    async def get_messages(
        limit: int = 100,
        type: str = None,
        since: float = None,
    ):
        """Message history from the mesh bridge.

        Query params:
            limit: Max messages to return (default 100).
            type: Filter by type ('text', 'position', 'telemetry').
            since: Only messages after this Unix timestamp.
        """
        if not message_bridge:
            return {"messages": [], "count": 0}
        msgs = message_bridge.get_messages(limit=limit, msg_type=type, since=since)
        return {"messages": msgs, "count": len(msgs)}

    @router.post("/send")
    async def send_message(body: dict):
        """Send a text message via the mesh.

        Body: {
            "text": "Hello mesh!",
            "destination": "!ba33ff38" (optional, omit for broadcast),
            "channel": 0 (optional, default primary channel)
        }
        """
        text = body.get("text", "")
        dest = body.get("destination")
        channel = body.get("channel", 0)
        if not text:
            return {"error": "empty_message"}

        # Use message bridge if available (records history + events)
        if message_bridge:
            ok = await message_bridge.send_text(
                text, destination=dest, channel=channel,
            )
            return {"sent": ok, "text": text, "destination": dest, "channel": channel}

        # Fallback to direct connection send
        if not connection:
            return {"error": "not_connected"}
        ok = await connection.send_text(text, destination=dest)
        return {"sent": ok, "text": text, "destination": dest}

    @router.get("/bridge/stats")
    async def bridge_stats():
        """Message bridge statistics."""
        if not message_bridge:
            return {"error": "bridge_not_available"}
        return message_bridge.get_stats()

    @router.get("/health")
    async def health():
        """Addon health check."""
        return {
            "status": "ok" if (connection and connection.is_connected) else "degraded",
            "connected": connection.is_connected if connection else False,
            "node_count": len(node_manager.nodes) if node_manager else 0,
        }

    return router


def create_compat_router(connection, node_manager) -> APIRouter:
    """Backward-compatible router at /api/meshtastic for existing mesh-layer.js.

    The existing frontend mesh layer fetches from /api/meshtastic/nodes.
    This router serves the same data at the old path.
    """
    compat = APIRouter()

    @compat.get("/nodes")
    async def compat_nodes(has_gps: bool = False):
        """Backward-compatible node endpoint for mesh-layer.js."""
        if not node_manager:
            return {"nodes": []}
        nodes = []
        for nid, node in node_manager.nodes.items():
            if has_gps and node.get("lat") is None:
                continue
            nodes.append({
                "num": node.get("num", 0),
                "user": {
                    "id": nid,
                    "longName": node.get("long_name", ""),
                    "shortName": node.get("short_name", ""),
                    "hwModel": node.get("hw_model", ""),
                },
                "position": {
                    "latitude": node.get("lat"),
                    "longitude": node.get("lng"),
                    "altitude": node.get("altitude", 0),
                } if node.get("lat") is not None else {},
                "deviceMetrics": {
                    "batteryLevel": node.get("battery", 0),
                    "voltage": node.get("voltage", 0),
                    "channelUtilization": node.get("channel_util", 0),
                    "airUtilTx": node.get("air_util", 0),
                },
                "lastHeard": node.get("last_heard", 0),
                "snr": node.get("snr"),
            })
        return {"nodes": nodes, "count": len(nodes)}

    @compat.get("/status")
    async def compat_status():
        return {
            "connected": connection.is_connected if connection else False,
            "node_count": len(node_manager.nodes) if node_manager else 0,
        }

    return compat
