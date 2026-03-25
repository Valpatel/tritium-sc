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
    async def generate_demo_city(
        radius: float = 300,
        block_size: float = 60,
        seed: int = 42,
    ):
        """Generate a procedural city for demo/offline mode.

        Returns city-data format JSON with buildings, roads, trees, and parks.
        No OSM data or internet connection needed.
        """
        import math
        import random

        rng = random.Random(seed)
        buildings = []
        roads = []
        trees = []
        landuse_list = []

        grid_spacing = block_size + 12  # road width = 12m
        half = radius * 0.8
        cols = int(half * 2 / grid_spacing)
        rows = int(half * 2 / grid_spacing)
        start_x = -half

        road_id = 1
        bldg_id = 1

        # Horizontal roads
        for r in range(rows + 1):
            z = start_x + r * grid_spacing
            is_main = r == rows // 2
            roads.append({
                "id": road_id, "points": [[-half, z], [half, z]],
                "class": "primary" if is_main else "residential",
                "name": f"{r + 1}th St", "width": 14.0 if is_main else 8.0,
                "lanes": 4 if is_main else 2, "surface": "asphalt",
                "oneway": False, "bridge": False, "tunnel": False, "maxspeed": "",
            })
            road_id += 1

        # Vertical roads
        for c in range(cols + 1):
            x = start_x + c * grid_spacing
            is_main = c == cols // 2
            roads.append({
                "id": road_id, "points": [[x, -half], [x, half]],
                "class": "secondary" if is_main else "residential",
                "name": f"{chr(65 + c % 26)} Ave", "width": 10.0 if is_main else 8.0,
                "lanes": 3 if is_main else 2, "surface": "asphalt",
                "oneway": False, "bridge": False, "tunnel": False, "maxspeed": "",
            })
            road_id += 1

        # Buildings and parks per block
        zone_types = ["residential", "commercial", "industrial"]
        for r in range(rows):
            for c in range(cols):
                bx = start_x + c * grid_spacing + 6
                bz = start_x + r * grid_spacing + 6
                bw = block_size
                bh = block_size

                dist = math.sqrt((bx + bw / 2) ** 2 + (bz + bh / 2) ** 2)
                zone = "commercial" if dist < radius * 0.2 else rng.choice(zone_types)

                # 15% chance of park
                if rng.random() < 0.15:
                    landuse_list.append({
                        "id": bldg_id, "type": "park", "name": f"Park {bldg_id}",
                        "polygon": [[bx + 2, bz + 2], [bx + bw - 2, bz + 2],
                                    [bx + bw - 2, bz + bh - 2], [bx + 2, bz + bh - 2]],
                    })
                    bldg_id += 1
                    for _ in range(rng.randint(3, 7)):
                        trees.append({
                            "pos": [bx + 4 + rng.random() * (bw - 8), bz + 4 + rng.random() * (bh - 8)],
                            "species": rng.choice(["oak", "maple", "birch"]),
                            "height": 5 + rng.random() * 7, "leaf_type": "broadleaved",
                        })
                    continue

                num_bldgs = 1 if zone == "industrial" else rng.randint(1, 3)
                for _ in range(num_bldgs):
                    w = rng.uniform(10, min(35, bw * 0.7))
                    d = rng.uniform(10, min(25, bh * 0.7))
                    ox = (rng.random() - 0.5) * (bw - w - 4)
                    oz = (rng.random() - 0.5) * (bh - d - 4)
                    cx, cz = bx + bw / 2 + ox, bz + bh / 2 + oz

                    h = {"commercial": 12 + rng.random() * 35,
                         "industrial": 6 + rng.random() * 8,
                         "residential": 5 + rng.random() * 15}[zone]

                    cat = {"commercial": "commercial", "industrial": "industrial",
                           "residential": "residential"}[zone]

                    buildings.append({
                        "id": bldg_id,
                        "polygon": [[cx - w / 2, cz - d / 2], [cx + w / 2, cz - d / 2],
                                    [cx + w / 2, cz + d / 2], [cx - w / 2, cz + d / 2]],
                        "height": round(h, 1), "type": zone,
                        "category": cat, "name": "", "levels": max(1, int(h / 3)),
                        "roof_shape": "gabled" if cat == "residential" and h < 12 else "flat",
                        "colour": "", "material": "",
                        "address": str(rng.randint(100, 999)),
                        "street": f"{chr(65 + c % 26)} Ave",
                    })
                    bldg_id += 1

        return {
            "center": {"lat": 0, "lng": 0},
            "radius": radius, "schema_version": 2,
            "buildings": buildings, "roads": roads, "trees": trees,
            "landuse": landuse_list, "barriers": [], "water": [],
            "entrances": [], "pois": [],
            "stats": {
                "buildings": len(buildings), "roads": len(roads),
                "trees": len(trees), "landuse": len(landuse_list),
                "barriers": 0, "water": 0, "entrances": 0, "pois": 0,
            },
            "_procedural": True,
        }

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
