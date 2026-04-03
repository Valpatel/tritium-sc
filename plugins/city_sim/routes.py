# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""API routes for the City Simulation plugin."""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from .plugin import CitySimPlugin


class CitySimTelemetry(BaseModel):
    """Batch of city sim entity positions from the frontend."""
    vehicles: list[dict[str, Any]] = []
    pedestrians: list[dict[str, Any]] = []


def _entity_to_target(entity: dict[str, Any], source: str) -> dict[str, Any]:
    """Convert a frontend sim entity dict to a sim_telemetry target dict."""
    eid = entity.get("id", "unknown")
    return {
        "target_id": f"csim_{source}_{eid}",
        "position": [entity.get("x", 0.0), entity.get("z", 0.0)],
        "heading": entity.get("heading", 0.0),
        "speed": entity.get("speed", 0.0),
        "health": 100.0,
        "status": "active",
        "alliance": "neutral",
        "asset_type": entity.get("type", source),
        "source": "city_sim",
        "classification": source,
    }


def create_router(plugin: "CitySimPlugin") -> APIRouter:
    router = APIRouter(prefix="/api/city-sim", tags=["city-sim"])

    @router.get("/config")
    async def get_config():
        return plugin._config

    @router.put("/config")
    async def set_config(body: dict):
        # Type-check values against existing config types
        rejected = {}
        for key, value in body.items():
            if key not in plugin._config:
                continue
            expected_type = type(plugin._config[key])
            if not isinstance(value, expected_type):
                # Allow int for float and vice versa
                if isinstance(value, (int, float)) and expected_type in (int, float):
                    plugin._config[key] = expected_type(value)
                else:
                    rejected[key] = f"expected {expected_type.__name__}, got {type(value).__name__}"
                    continue
            else:
                plugin._config[key] = value
        resp = dict(plugin._config)
        if rejected:
            resp["_rejected"] = rejected
        return resp

    @router.get("/status")
    async def get_status():
        return {
            "running": plugin._running,
            "config": plugin._config,
        }

    @router.get("/scenarios")
    async def list_scenarios():
        return {
            "scenarios": [
                {
                    "id": "rush_hour",
                    "name": "Rush Hour",
                    "description": "Heavy traffic, morning commute",
                    "vehicles": 200,
                    "pedestrians": 80,
                    "time": 8.0,
                },
                {
                    "id": "night_patrol",
                    "name": "Night Patrol",
                    "description": "Quiet streets, few vehicles",
                    "vehicles": 20,
                    "pedestrians": 5,
                    "time": 23.0,
                },
                {
                    "id": "lunch_rush",
                    "name": "Lunch Rush",
                    "description": "Moderate traffic, pedestrians going to restaurants",
                    "vehicles": 100,
                    "pedestrians": 60,
                    "time": 12.0,
                },
                {
                    "id": "emergency",
                    "name": "Emergency Response",
                    "description": "Emergency vehicles with priority",
                    "vehicles": 50,
                    "pedestrians": 30,
                    "time": 14.0,
                },
                {
                    "id": "dramatic_day",
                    "name": "Dramatic Day",
                    "description": "Full day: rush hour, accident, protest, riot — events auto-trigger",
                    "vehicles": 200,
                    "pedestrians": 100,
                    "time": 7.0,
                },
            ]
        }

    @router.get("/demo-city")
    async def get_demo_city(
        radius: float = 300,
        block_size: float = 60,
        seed: int = 42,
    ):
        """Generate a procedural city for demo/offline mode.

        Returns city-data format JSON with buildings, roads, trees, and parks.
        No OSM data or internet connection needed.

        Delegates to tritium_lib.sim_engine.world.procedural_city.
        """
        from tritium_lib.sim_engine.world.procedural_city import generate_demo_city
        return generate_demo_city(radius=radius, block_size=block_size, seed=seed)

    @router.post("/protest")
    async def trigger_protest(body: dict):
        """Trigger a protest event in the city simulation.

        Body: { "plazaCenter": {"x": 0, "z": 0}, "participantCount": 50, "legitimacy": 0.3 }
        """
        from app.routers.ws import broadcast_amy_event
        await broadcast_amy_event("city_sim_event", {
            "type": "protest",
            "params": {
                "plazaCenter": body.get("plazaCenter", {"x": 0, "z": 0}),
                "participantCount": body.get("participantCount", 50),
                "legitimacy": body.get("legitimacy", 0.3),
            },
        })
        return {
            "triggered": "protest",
            "participants": body.get("participantCount", 50),
            "legitimacy": body.get("legitimacy", 0.3),
        }

    @router.post("/event")
    async def trigger_event(body: dict):
        """Trigger a city sim event (protest, emergency, etc.).

        The event is broadcast via WebSocket so the frontend EventDirector picks it up.
        Body: { "type": "protest", "params": { "plazaCenter": {"x": 0, "z": 0}, "participantCount": 50 } }
        """
        event_type = body.get("type")
        params = body.get("params", {})
        if not event_type:
            return JSONResponse(status_code=400, content={"error": "missing 'type'"})

        from app.routers.ws import broadcast_amy_event
        await broadcast_amy_event("city_sim_event", {"type": event_type, "params": params})

        return {"triggered": event_type, "params": params}

    @router.post("/telemetry")
    async def post_telemetry(body: CitySimTelemetry):
        """Receive city sim entity positions from the frontend and broadcast via WebSocket.

        The frontend JS sim engine POSTs vehicle/pedestrian positions here.
        We convert them to sim_telemetry_batch format and broadcast to all
        connected WebSocket clients so every operator sees the sim entities.
        """
        batch: list[dict[str, Any]] = []
        for v in body.vehicles:
            batch.append(_entity_to_target(v, "vehicle"))
        for p in body.pedestrians:
            batch.append(_entity_to_target(p, "pedestrian"))

        if not batch:
            return {"accepted": 0}

        # Update target tracker so dossiers show position history
        target_tracker = getattr(plugin._app.state, "target_tracker", None) if plugin._app else None
        if target_tracker is None:
            amy = getattr(plugin._app.state, "amy", None) if plugin._app else None
            target_tracker = getattr(amy, "target_tracker", None) if amy else None

        if target_tracker:
            for t in batch:
                try:
                    # Convert to sim telemetry format expected by update_from_simulation
                    sim_data = {
                        "target_id": t["target_id"],
                        "position": {"x": t["position"][0], "y": t["position"][1]},
                        "heading": t.get("heading", 0),
                        "speed": t.get("speed", 0),
                        "alliance": t.get("alliance", "neutral"),
                        "asset_type": t.get("asset_type", "vehicle"),
                        "status": t.get("status", "active"),
                        "name": t["target_id"][:12],
                    }
                    target_tracker.update_from_simulation(sim_data)
                except Exception:
                    pass

        from app.routers.ws import broadcast_amy_event
        await broadcast_amy_event("sim_telemetry_batch", batch)

        return {"accepted": len(batch)}

    return router
