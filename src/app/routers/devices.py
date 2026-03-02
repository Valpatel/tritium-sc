# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Device command API — routes UI device commands to the appropriate backend.

Sensor, camera, and mesh radio controls in the frontend use
POST /api/devices/{id}/command.  This router translates those into the
correct backend action: Lua dispatch for sensors/cameras, mesh bridge
for radio text, or MQTT publish for real hardware.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"])


class DeviceCommandRequest(BaseModel):
    """Payload for a device command."""

    command: str | None = None
    text: str | None = None
    params: dict | None = None


@router.post("/{device_id}/command")
async def device_command(
    request: Request,
    device_id: str,
    body: DeviceCommandRequest,
):
    """Route a device command to the appropriate backend.

    Sensor commands (enable, disable, test_trigger) and camera commands
    (camera_off) are dispatched as Lua actions through Amy's dispatcher.
    Mesh text messages are routed to the meshtastic bridge.
    """
    # Mesh radio text message
    if body.text is not None:
        bridge = getattr(request.app.state, "meshtastic_bridge", None)
        if bridge is None:
            return JSONResponse(
                status_code=503,
                content={"error": "Meshtastic bridge not available"},
            )
        ok = bridge.send_text(text=body.text)
        if ok:
            return {"status": "sent", "device_id": device_id, "text": body.text[:228]}
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to send mesh message"},
        )

    # Sensor / camera commands -> Lua action dispatch
    cmd = body.command
    if not cmd:
        raise HTTPException(status_code=400, detail="Missing 'command' or 'text' field")

    # Map device UI commands to Lua action strings
    lua_map = {
        "enable": f'sensor_enable("{device_id}")',
        "disable": f'sensor_disable("{device_id}")',
        "test_trigger": f'sensor_test("{device_id}")',
        "camera_off": f'camera_off("{device_id}")',
    }

    lua_str = lua_map.get(cmd)
    if lua_str is None:
        # If the command already contains parentheses (e.g. "fire_nerf()",
        # "motor.aim(10,20)"), pass it as-is to the Lua parser.  Otherwise
        # wrap the device_id as the first argument.
        if "(" in cmd:
            lua_str = cmd
        else:
            lua_str = f'{cmd}("{device_id}")'

    # Try MQTT bridge first for real hardware
    mqtt_bridge = getattr(request.app.state, "mqtt_bridge", None)
    if mqtt_bridge is not None:
        site_id = getattr(request.app.state, "mqtt_site_id", "home")
        topic = f"tritium/{site_id}/devices/{device_id}/command"
        payload = {"command": cmd}
        if body.params:
            payload.update(body.params)
        try:
            import json

            mqtt_bridge.publish(topic, json.dumps(payload))
            logger.info("Device command via MQTT: %s -> %s", device_id, cmd)
            return {"status": "ok", "device_id": device_id, "command": cmd, "via": "mqtt"}
        except Exception as e:
            logger.warning("MQTT publish failed for %s: %s, falling back to Lua", device_id, e)

    # Fall back to Lua dispatch through Amy
    amy = getattr(request.app.state, "amy", None)
    if amy is not None and hasattr(amy, "thinking") and amy.thinking:
        from engine.actions.lua_motor import parse_motor_output

        result = parse_motor_output(lua_str)
        if result.valid:
            import asyncio

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, amy.thinking._dispatch, result)
            logger.info("Device command via Lua: %s -> %s", device_id, cmd)
            return {"status": "ok", "device_id": device_id, "command": cmd, "via": "lua"}

    # No backend available — accept the command but note it's unhandled
    logger.warning("Device command accepted but no backend available: %s -> %s", device_id, cmd)
    return {"status": "accepted", "device_id": device_id, "command": cmd, "via": "none"}
