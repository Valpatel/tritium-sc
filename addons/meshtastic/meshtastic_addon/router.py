# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Meshtastic addon."""

from __future__ import annotations

from fastapi import APIRouter


def _clean_role(role: str) -> str:
    """Strip UNKNOWN() wrapper from role names."""
    if role and role.startswith("UNKNOWN(") and role.endswith(")"):
        return role[8:-1]
    return role


def create_router(connection, node_manager, message_bridge=None) -> APIRouter:
    """Create FastAPI router for Meshtastic addon endpoints."""

    router = APIRouter()

    @router.get("/status")
    async def status():
        """Connection and device status."""
        # Check both our flag AND whether the interface object exists
        connected = (connection.is_connected and connection.interface is not None) if connection else False
        # If interface exists but is_connected is False, we may have a stale flag — trust the interface
        if connection and connection.interface is not None and not connection.is_connected:
            connection.is_connected = True  # Fix stale flag
            connected = True
        return {
            "connected": connected,
            "transport": connection.transport_type if connection else "none",
            "port": connection.port if connection else "",
            "device": connection.device_info if connection else {},
            "node_count": len(node_manager.nodes) if node_manager else 0,
        }

    @router.get("/ports")
    async def detect_ports():
        """Detect available Meshtastic serial ports.

        Scans /dev for USB serial devices matching known Meshtastic VID:PIDs.
        Returns both matched (known Meshtastic VIDs) and all serial ports
        so the frontend can display everything available.
        """
        matched_ports = []
        all_ports = []
        try:
            import serial.tools.list_ports
            known_vids = {0x303a, 0x10c4, 0x1a86, 0x0403}  # Espressif, SiLabs, CH340, FTDI
            for p in serial.tools.list_ports.comports():
                # Skip system serial ports (ttyS*) with no VID — these are noise
                if p.device.startswith("/dev/ttyS") and not p.vid:
                    continue
                port_info = {
                    "port": p.device,
                    "description": p.description or "",
                    "vid": f"{p.vid:04x}" if p.vid else "",
                    "pid": f"{p.pid:04x}" if p.pid else "",
                    "manufacturer": p.manufacturer or "",
                    "serial_number": p.serial_number or "",
                    "meshtastic_match": bool(p.vid and p.vid in known_vids),
                }
                all_ports.append(port_info)
                if p.vid and p.vid in known_vids:
                    matched_ports.append(port_info)
        except ImportError:
            # Fallback: check common paths
            from pathlib import Path
            for path in ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB0", "/dev/ttyUSB1"]:
                if Path(path).exists():
                    port_info = {"port": path, "description": "Serial device", "meshtastic_match": True}
                    matched_ports.append(port_info)
                    all_ports.append(port_info)

        # Also note which port we are currently connected to
        current_port = connection.port if connection and connection.is_connected else ""

        return {
            "ports": matched_ports,
            "all_ports": all_ports,
            "current_port": current_port,
            "count": len(matched_ports),
            "total_count": len(all_ports),
        }

    @router.get("/ble-scan")
    async def ble_scan():
        """Scan for Meshtastic BLE devices. Takes ~5-8 seconds."""
        try:
            from bleak import BleakScanner
            devices = await BleakScanner.discover(timeout=6.0, return_adv=True)
            results = []
            for addr, (device, adv) in devices.items():
                name = device.name or adv.local_name or ""
                if "meshtastic" in name.lower():
                    results.append({
                        "address": device.address,
                        "name": name,
                        "rssi": adv.rssi,
                        "transport": "ble",
                    })
            return {"ble_devices": results, "count": len(results)}
        except ImportError:
            return {"ble_devices": [], "count": 0, "error": "bleak not installed"}
        except Exception as e:
            return {"ble_devices": [], "count": 0, "error": str(e)}

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
                "role": _clean_role(node.get("role", "")),
                "lat": node.get("lat"),
                "lng": node.get("lng"),
                "altitude": node.get("altitude"),
                "battery": node.get("battery"),
                "voltage": node.get("voltage"),
                "snr": node.get("snr"),
                "last_heard": node.get("last_heard"),
                "hops_away": node.get("hops_away"),
                "uptime": node.get("uptime"),
                "channel_util": node.get("channel_util"),
                "air_util": node.get("air_util"),
                "temperature": node.get("temperature"),
                "humidity": node.get("humidity"),
                "pressure": node.get("pressure"),
                "gps_sats": node.get("gps_sats"),
                "neighbors": node.get("neighbors", []),
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
            "transport": "serial"|"tcp"|"ble"|"mqtt",
            "port": "/dev/ttyACM0" or "host:port" or BLE address,
            "timeout": 60  (optional, seconds),
            "noNodes": false  (optional, skip full node list for faster connect),
            "host": "mqtt.meshtastic.org"  (mqtt only),
            "mqtt_port": 1883  (mqtt only),
            "topic": "msh/US/2/e/#"  (mqtt only),
            "username": "meshdev"  (mqtt only),
            "password": "large4cats"  (mqtt only),
            "address": "AA:BB:CC:DD:EE:FF"  (ble only)
        }
        """
        if not connection:
            return {"error": "connection_manager_not_available"}
        body = body or {}
        transport = body.get("transport", "serial")
        port = body.get("port", "")
        timeout = float(body.get("timeout", 60))
        noNodes = body.get("noNodes", False)

        if transport == "serial":
            serial_port = port or "/dev/ttyACM0"
            from pathlib import Path
            if not Path(serial_port).exists():
                return {
                    "connected": False,
                    "error": "port_not_found",
                    "message": f"Serial port {serial_port} does not exist. Is the device plugged in?",
                }
            try:
                await connection.connect_serial(serial_port, timeout=timeout, noNodes=noNodes)
            except Exception as e:
                return {"connected": False, "error": "connect_exception", "message": str(e)}
        elif transport == "tcp":
            host = port or "localhost"
            await connection.connect_tcp(host, timeout=timeout)
        elif transport == "ble":
            address = port or body.get("address", "")
            await connection.connect_ble(address, timeout=timeout, noNodes=noNodes)
        elif transport == "mqtt":
            mqtt_host = port or body.get("host", "mqtt.meshtastic.org")
            mqtt_port = int(body.get("mqtt_port", 1883))
            topic = body.get("topic", "msh/US/2/e/#")
            username = body.get("username", "meshdev")
            password = body.get("password", "large4cats")
            await connection.connect_mqtt(
                mqtt_host, port=mqtt_port, topic=topic,
                username=username, password=password, timeout=timeout,
            )
        else:
            return {"error": f"unsupported transport: {transport}"}

        # Trust the interface object: if it exists, we're connected
        actually_connected = connection.interface is not None
        if actually_connected and not connection.is_connected:
            connection.is_connected = True  # Fix stale flag

        result = {
            "connected": actually_connected,
            "transport": connection.transport_type,
            "port": connection.port,
            "device": connection.device_info,
        }
        if not actually_connected:
            result["error"] = "connection_failed"
            result["message"] = (
                f"Failed to connect via {transport} on {port or 'default'}. "
                f"The device may be busy, unresponsive, or the port may be locked by another process."
            )
        return result

    @router.post("/recover")
    async def recover():
        """Attempt to recover an unresponsive USB device.

        Drains stale serial data, toggles DTR, and retries connection.
        Use this when the device stops responding after rapid connect/disconnect.
        """
        if not connection:
            return {"error": "no_connection_manager"}
        ok = await connection.reset_usb_device()
        if ok:
            return {
                "recovered": True,
                "connected": connection.is_connected,
                "device": connection.device_info,
            }
        return {"recovered": False, "error": "Recovery failed — device may need physical replug"}

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

    @router.get("/stats")
    async def network_stats():
        """Network-level statistics (node counts, avg SNR, etc)."""
        if not node_manager:
            return {"error": "not_available"}
        try:
            return node_manager.get_stats()
        except Exception as e:
            import logging
            logging.getLogger("meshtastic.router").warning(f"Stats error: {e}")
            return {
                "error": str(e),
                "total_nodes": len(node_manager.nodes) if node_manager else 0,
                "online_nodes": 0,
                "offline_nodes": 0,
                "with_gps": 0,
                "routers": 0,
                "avg_snr": None,
                "avg_battery": None,
                "link_count": 0,
                "last_update": 0,
            }

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
