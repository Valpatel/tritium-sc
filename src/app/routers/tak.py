# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TAK (Team Awareness Kit) API — status, clients, send, alert."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/tak", tags=["tak"])


class SendCotRequest(BaseModel):
    cot_xml: str


class AlertRequest(BaseModel):
    callsign: str
    lat: float
    lng: float
    alt: float = 0.0
    remarks: str = ""


class ChatRequest(BaseModel):
    message: str
    to_callsign: str = "All Chat Rooms"


def _get_bridge(request: Request):
    """Get the TAK bridge from app state. Returns None if unavailable."""
    return getattr(request.app.state, "tak_bridge", None)


@router.get("/status")
async def tak_status(request: Request):
    """Bridge connection status and stats."""
    bridge = _get_bridge(request)
    if bridge is None:
        return {
            "enabled": False,
            "connected": False,
            "error": "TAK bridge not configured",
        }
    stats = bridge.stats
    return {"enabled": True, **stats}


@router.get("/clients")
async def tak_clients(request: Request):
    """Discovered TAK clients (ATAK phones, WinTAK stations)."""
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "TAK bridge not available"},
        )
    clients = bridge.clients
    result = [
        {
            "uid": uid,
            "callsign": info.get("callsign", uid),
            "lat": info.get("lat", 0.0),
            "lng": info.get("lng", 0.0),
            "alt": info.get("alt", 0.0),
            "alliance": info.get("alliance", "unknown"),
            "asset_type": info.get("asset_type", "person"),
            "speed": info.get("speed", 0.0),
            "heading": info.get("heading", 0.0),
            "last_seen": info.get("last_seen", 0),
        }
        for uid, info in clients.items()
    ]
    return {"clients": result, "count": len(result)}


@router.post("/send")
async def tak_send(request: Request, body: SendCotRequest):
    """Send raw CoT XML to the TAK server."""
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "TAK bridge not available"},
        )
    bridge.send_cot(body.cot_xml)
    return {"status": "queued"}


@router.post("/alert")
async def tak_alert(request: Request, body: AlertRequest):
    """Send a threat alert marker to the TAK server.

    Creates a hostile marker CoT event at the given coordinates.
    """
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "TAK bridge not available"},
        )

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", f"tritium-alert-{body.callsign}")
    event.set("type", "a-h-G-U-C-I")
    event.set("how", "h-e")
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)

    point = ET.SubElement(event, "point")
    point.set("lat", str(body.lat))
    point.set("lon", str(body.lng))
    point.set("hae", str(body.alt))
    point.set("ce", "15.0")
    point.set("le", "15.0")

    detail = ET.SubElement(event, "detail")
    contact = ET.SubElement(detail, "contact")
    contact.set("callsign", body.callsign)
    group = ET.SubElement(detail, "__group")
    group.set("name", "Red")
    group.set("role", "Team Member")
    if body.remarks:
        remarks = ET.SubElement(detail, "remarks")
        remarks.text = body.remarks

    xml_str = ET.tostring(event, encoding="unicode", xml_declaration=False)
    bridge.send_cot(xml_str)
    return {"status": "sent", "callsign": body.callsign}


@router.post("/chat")
async def tak_chat(request: Request, body: ChatRequest):
    """Send a GeoChat message to the TAK network."""
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "TAK bridge not available"},
        )
    if not body.message:
        return JSONResponse(
            status_code=400,
            content={"error": "Message cannot be empty"},
        )
    bridge.send_geochat(body.message, to_callsign=body.to_callsign)
    return {"status": "sent", "message": body.message}


@router.get("/chat/messages")
async def tak_chat_messages(request: Request, limit: int = 50):
    """Get recent GeoChat message history."""
    bridge = _get_bridge(request)
    if bridge is None:
        return JSONResponse(
            status_code=503,
            content={"error": "TAK bridge not available"},
        )
    messages = bridge.chat_history[-limit:]
    return {"messages": messages, "count": len(messages)}


@router.get("/history")
async def tak_history(request: Request, limit: int = 100):
    """Get TAK event history."""
    bridge = _get_bridge(request)
    if bridge is not None:
        events = bridge.get_history(limit=limit)
    else:
        events = []
    return {"events": events, "count": len(events)}
