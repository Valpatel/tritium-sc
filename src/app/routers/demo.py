# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Demo mode API router — start/stop/status for synthetic data pipeline.

Endpoints:
  POST /api/demo/start     — activate demo mode
  POST /api/demo/stop      — deactivate demo mode
  GET  /api/demo/status    — current state and generator stats
  GET  /api/demo/scenario  — fusion scenario description + live dossiers
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/demo", tags=["demo"])


def _get_demo_controller(request: Request):
    """Retrieve or create the DemoController from app state."""
    controller = getattr(request.app.state, "demo_controller", None)
    if controller is not None:
        return controller

    # Lazy-create if we have the prerequisites
    amy = getattr(request.app.state, "amy", None)
    if amy is None:
        return None

    event_bus = getattr(amy, "event_bus", None)
    target_tracker = getattr(amy, "target_tracker", None)
    if event_bus is None:
        return None

    # Try to find the camera_feeds plugin for map marker registration
    camera_feeds_plugin = None
    plugin_manager = getattr(request.app.state, "plugin_manager", None)
    if plugin_manager is not None:
        get_fn = getattr(plugin_manager, "get_plugin", None)
        if get_fn is not None:
            try:
                camera_feeds_plugin = get_fn("tritium.camera-feeds")
            except Exception:
                pass
    if camera_feeds_plugin is None:
        camera_feeds_plugin = getattr(request.app.state, "camera_feeds_plugin", None)

    from engine.synthetic.demo_mode import DemoController
    geofence_engine = getattr(request.app.state, "geofence_engine", None)
    controller = DemoController(
        event_bus=event_bus,
        target_tracker=target_tracker,
        geofence_engine=geofence_engine,
        camera_feeds_plugin=camera_feeds_plugin,
    )
    request.app.state.demo_controller = controller
    return controller


@router.post("/start")
async def demo_start(request: Request):
    """POST /api/demo/start — activate demo mode."""
    controller = _get_demo_controller(request)
    if controller is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Amy not available — demo mode requires EventBus"},
        )

    if controller.active:
        return {"status": "already_active", **controller.status()}

    controller.start()
    return {"status": "started", **controller.status()}


@router.post("/stop")
async def demo_stop(request: Request):
    """POST /api/demo/stop — deactivate demo mode."""
    controller = getattr(request.app.state, "demo_controller", None)
    if controller is None or not controller.active:
        return {"status": "not_active"}

    controller.stop()
    return {"status": "stopped", **controller.status()}


@router.get("/status")
async def demo_status(request: Request):
    """GET /api/demo/status — current demo mode state."""
    controller = getattr(request.app.state, "demo_controller", None)
    if controller is None:
        return {
            "active": False,
            "uptime_s": None,
            "generators": [],
            "generator_count": 0,
        }
    return controller.status()


@router.get("/scenario")
async def demo_scenario(request: Request):
    """GET /api/demo/scenario — fusion scenario description + live dossiers.

    Returns the scenario description (actors, capabilities, geofence zone)
    along with the current dossier state if the demo is running.
    """
    controller = getattr(request.app.state, "demo_controller", None)
    if controller is None:
        # Return static description even without a controller
        from engine.synthetic.fusion_scenario import SCENARIO_DESCRIPTION
        info = dict(SCENARIO_DESCRIPTION)
        info["running"] = False
        info["tick_count"] = 0
        info["dossiers"] = []
        return info
    return controller.get_scenario_info()
