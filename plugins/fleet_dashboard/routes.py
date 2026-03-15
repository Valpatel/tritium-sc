# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Fleet Dashboard plugin.

Includes fleet coordination, analytics, and config template endpoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .plugin import FleetDashboardPlugin


class FleetCommandRequest(BaseModel):
    """Request body for POST /api/fleet/command."""
    target_group: str
    command_type: str  # reboot, scan_burst, increase_rate, decrease_rate, ota_update, apply_template
    payload: dict = Field(default_factory=dict)


class ConfigTemplateRequest(BaseModel):
    """Request body for POST /api/fleet/templates."""
    name: str
    description: str = ""
    ble_scan_interval_ms: int = 10000
    wifi_scan_interval_ms: int = 30000
    heartbeat_interval_ms: int = 30000
    sighting_interval_ms: int = 15000
    power_mode: str = "normal"
    settings: dict = Field(default_factory=dict)


class DeviceStateRequest(BaseModel):
    """Request body for POST /api/fleet/devices/{device_id}/state."""
    state: str
    reason: str = ""
    operator: str = "api"


class ApplyTemplateRequest(BaseModel):
    """Request body for POST /api/fleet/templates/{template_id}/apply."""
    target_group: str


def create_router(plugin: FleetDashboardPlugin) -> APIRouter:
    """Build and return the fleet dashboard APIRouter."""

    router = APIRouter(prefix="/api/fleet", tags=["fleet-dashboard"])

    @router.get("/devices")
    async def list_devices():
        """List all tracked fleet devices with status."""
        devices = plugin.get_devices()
        return {"devices": devices, "count": len(devices)}

    @router.get("/devices/{device_id}")
    async def get_device(device_id: str):
        """Get a single fleet device by ID."""
        device = plugin.get_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        return {"device": device}

    @router.get("/summary")
    async def get_summary():
        """Fleet summary: online/offline/stale counts, avg battery, totals."""
        return plugin.get_summary()

    @router.get("/health-summary")
    async def get_health_summary():
        """Aggregate fleet health: total devices, online/offline/stale counts,
        average battery, average sighting rate, sensor health summary,
        and lifecycle state distribution."""
        return plugin.get_health_summary()

    # -- Device lifecycle routes -------------------------------------------

    @router.get("/devices/{device_id}/lifecycle")
    async def get_device_lifecycle(device_id: str):
        """Get lifecycle state for a specific device."""
        lc = plugin.get_device_lifecycle(device_id)
        if lc is None:
            return {"device_id": device_id, "state": "active", "history": []}
        return lc

    @router.post("/devices/{device_id}/state")
    async def set_device_state(device_id: str, request: DeviceStateRequest):
        """Transition a device to a new lifecycle state.

        Valid states: provisioning, active, maintenance, retired, error.
        Transitions are validated against allowed state machine rules.
        """
        result = plugin.set_device_state(
            device_id=device_id,
            new_state=request.state,
            reason=request.reason,
            operator=request.operator,
        )
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    @router.get("/lifecycle")
    async def get_all_lifecycle():
        """Get lifecycle states for all tracked devices."""
        states = plugin.get_all_lifecycle_states()
        return {"devices": states, "count": len(states)}

    @router.get("/devices/{device_id}/sparkline")
    async def get_device_sparkline(device_id: str):
        """Get target count history for a device, suitable for sparkline rendering.

        Returns an array of {ts, count} entries over the last hour.
        """
        history = plugin.get_target_history(device_id)
        return {"device_id": device_id, "history": history, "count": len(history)}

    @router.get("/sparklines")
    async def get_all_sparklines():
        """Get target count sparkline data for all devices."""
        histories = plugin.get_all_target_histories()
        return {
            "sparklines": {
                did: {"history": h, "count": len(h)}
                for did, h in histories.items()
            },
            "device_count": len(histories),
        }

    @router.get("/topology")
    async def get_topology():
        """Return network topology: nodes with positions and links between peers.

        Builds topology from fleet heartbeat data.  Each device becomes a node,
        and mesh_peers/connected_peers from heartbeat data become links.
        Used by the comm-link map layer to visualize network connectivity.
        """
        topology = plugin.get_topology()
        return topology

    # -- Fleet coordination routes -----------------------------------------

    @router.post("/command")
    async def send_fleet_command(request: FleetCommandRequest):
        """Send a command to all devices in a group.

        Supported command_type values:
        - reboot: Restart all devices in the group
        - scan_burst: Trigger an immediate scan cycle
        - increase_rate: Increase scan/report frequency
        - decrease_rate: Decrease scan/report frequency
        - ota_update: Initiate OTA update
        - apply_template: Apply a config template (requires template_id in payload)
        """
        valid_types = {
            "reboot", "scan_burst", "increase_rate", "decrease_rate",
            "ota_update", "apply_template", "set_group", "identify", "sleep",
        }
        if request.command_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid command_type: {request.command_type}. "
                       f"Valid types: {', '.join(sorted(valid_types))}",
            )

        result = plugin.send_fleet_command(
            target_group=request.target_group,
            command_type=request.command_type,
            payload=request.payload,
        )
        return result

    @router.get("/commands")
    async def list_fleet_commands(limit: int = 50):
        """List recent fleet commands with status."""
        commands = plugin.get_fleet_commands(limit=limit)
        return {"commands": commands, "count": len(commands)}

    @router.get("/groups")
    async def list_groups():
        """List all device groups with their member devices."""
        groups = plugin.get_groups()
        return {
            "groups": {
                name: {"devices": devs, "count": len(devs)}
                for name, devs in groups.items()
            },
            "group_count": len(groups),
        }

    @router.get("/groups/{group_name}/devices")
    async def get_group_devices(group_name: str):
        """List devices in a specific group."""
        devices = plugin.get_devices_in_group(group_name)
        return {"group": group_name, "devices": devices, "count": len(devices)}

    # -- Config template routes --------------------------------------------

    @router.get("/templates")
    async def list_templates():
        """List all configuration templates (built-in and custom)."""
        templates = plugin.get_config_templates()
        return {"templates": templates, "count": len(templates)}

    @router.get("/templates/{template_id}")
    async def get_template(template_id: str):
        """Get a specific configuration template."""
        template = plugin.get_config_template(template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        return {"template": template}

    @router.post("/templates")
    async def create_template(request: ConfigTemplateRequest):
        """Create a new custom configuration template."""
        template = plugin.create_config_template(request.model_dump())
        return {"template": template}

    @router.post("/templates/{template_id}/apply")
    async def apply_template(template_id: str, request: ApplyTemplateRequest):
        """Apply a configuration template to all devices in a group.

        Sends config_update commands to each device with template parameters.
        """
        result = plugin.apply_template_to_group(template_id, request.target_group)
        if result.get("error"):
            raise HTTPException(status_code=404, detail=result["error"])
        return result

    # -- Fleet analytics routes --------------------------------------------

    @router.get("/analytics")
    async def get_analytics():
        """Get current fleet analytics snapshot.

        Returns device uptime trends, sighting rates, coverage data,
        and group distribution.
        """
        snapshot = plugin.get_analytics_snapshot()
        return snapshot

    @router.get("/analytics/history")
    async def get_analytics_history(hours: int = 24):
        """Get historical fleet analytics snapshots."""
        history = plugin.get_analytics_history(hours=hours)
        return {"snapshots": history, "count": len(history), "hours": hours}

    @router.get("/coverage")
    async def get_coverage_map():
        """Get sensor coverage map showing device positions and overlap."""
        coverage = plugin.get_coverage_map()
        return {"coverage": coverage, "count": len(coverage)}

    return router
