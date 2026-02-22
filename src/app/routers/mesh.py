"""Meshtastic mesh radio API — nodes, messages, send, status, discovery."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/mesh", tags=["meshtastic"])


class SendTextRequest(BaseModel):
    text: str
    channel: int = 0
    destination: str | None = None


class ConnectRequest(BaseModel):
    host: str
    port: int = 4403


def _get_bridge(request: Request):
    """Get the meshtastic bridge from app state. Returns None if unavailable."""
    return getattr(request.app.state, "meshtastic_bridge", None)


@router.get("/nodes")
async def mesh_nodes(request: Request):
    """All mesh nodes with position/battery/signal."""
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Meshtastic bridge not available"},
        )

    nodes = bridge.nodes
    result = []
    for node_id, node in nodes.items():
        result.append({
            "node_id": node.node_id,
            "long_name": node.long_name,
            "short_name": node.short_name,
            "hardware": node.hardware,
            "position": node.position,
            "battery": node.battery,
            "voltage": node.voltage,
            "snr": node.snr,
            "rssi": node.rssi,
            "hops": node.hops,
            "last_heard": node.last_heard,
        })
    return {"nodes": result, "count": len(result)}


@router.get("/messages")
async def mesh_messages(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
):
    """Message history (most recent first)."""
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Meshtastic bridge not available"},
        )

    messages = bridge.messages
    # Return most recent first, capped at limit
    recent = list(reversed(messages))[:limit]
    return {"messages": recent, "count": len(recent), "total": len(messages)}


@router.post("/send")
async def mesh_send(request: Request, body: SendTextRequest):
    """Send text message to mesh."""
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Meshtastic bridge not available"},
        )

    ok = bridge.send_text(
        text=body.text,
        channel=body.channel,
        destination=body.destination,
    )
    if ok:
        return {"status": "sent", "text": body.text[:228]}
    return JSONResponse(
        status_code=500,
        content={"error": "Failed to send message"},
    )


@router.post("/connect")
async def mesh_connect(request: Request, body: ConnectRequest):
    """Connect to a meshtastic radio at the given host:port."""
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Meshtastic bridge not available"},
        )

    ok = bridge.connect(host=body.host, port=body.port)
    if ok:
        return {"status": "connected", "host": body.host, "port": body.port}
    return JSONResponse(
        status_code=500,
        content={"error": f"Connection failed: {bridge.stats.get('last_error', 'unknown')}"},
    )


@router.post("/disconnect")
async def mesh_disconnect(request: Request):
    """Disconnect from the current meshtastic radio."""
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Meshtastic bridge not available"},
        )

    bridge.disconnect()
    return {"status": "disconnected"}


@router.get("/channels")
async def mesh_channels(request: Request):
    """List configured channels (0-7) from the connected radio."""
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Meshtastic bridge not available"},
        )

    channels = bridge.get_channels()
    return {"channels": channels, "count": len(channels)}


@router.get("/nodes/{node_id}")
async def mesh_node_detail(request: Request, node_id: str):
    """Detailed info for a specific mesh node."""
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Meshtastic bridge not available"},
        )

    node = bridge.get_node(node_id)
    if node is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"Node {node_id} not found"},
        )
    return node


@router.get("/status")
async def mesh_status(request: Request):
    """Bridge connection status and stats."""
    bridge = _get_bridge(request)
    if bridge is None:
        return {
            "enabled": False,
            "connected": False,
            "error": "Meshtastic bridge not configured",
        }

    stats = bridge.stats
    return {"enabled": True, **stats}


@router.get("/discover")
async def mesh_discover(request: Request):
    """Trigger mDNS scan and return found devices."""
    try:
        from amy.comms.meshtastic_bridge import MeshtasticBridge
        devices = MeshtasticBridge.discover(timeout=3.0)
        return {"devices": devices, "count": len(devices)}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Discovery failed: {e}"},
        )
