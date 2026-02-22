"""Load a TritiumLevelFormat JSON file into the simulation engine.

Architecture
------------
The loader bridges the static level definition (JSON) and the runtime
simulation.  It performs a two-pass parse:

  Pass 1: Create SimulationTargets from object definitions.  Object types
  are mapped via _SPECIFIC_TYPES (exact match) or keyword heuristics
  (contains "robot", "drone", etc.).  Non-target objects (cameras, walls,
  roads) are silently skipped.  Zone objects are collected separately by
  load_zones() for the ThreatClassifier.

  Pass 2: Assign free-standing waypoint objects to the nearest created
  target (by Euclidean distance).  This allows level designers to place
  patrol_waypoint markers near a rover without explicit ID references.

The loader is intentionally stateless — it reads a file and populates an
engine, with no side effects or caching.  Multiple layouts can be loaded
into the same engine (additive).
"""

from __future__ import annotations

import json
import math
import uuid
from typing import TYPE_CHECKING

from .target import SimulationTarget

if TYPE_CHECKING:
    from .engine import SimulationEngine

# Asset types that are not simulation targets — skip silently
_SKIP_TYPES = {
    "camera", "cam", "structure", "wall", "floor", "ceiling", "light",
    "security_camera", "ptz_camera", "dome_camera",
    "street", "sidewalk", "curb", "fence", "gate",
    "motion_sensor", "microphone_sensor", "speaker", "floodlight",
    "building", "house", "shed", "garage", "road", "driveway", "path",
}

# Zone types — collected separately, not spawned as targets
_ZONE_TYPES = {"activity_zone", "entry_exit_zone", "tripwire", "restricted_area"}

# Waypoint types — collected and assigned to nearest target
_WAYPOINT_TYPES = {"patrol_waypoint", "observation_point"}

# Specific asset type → (alliance, asset_type, speed)
_SPECIFIC_TYPES: dict[str, tuple[str, str, float]] = {
    "patrol_rover": ("friendly", "rover", 2.0),
    "interceptor_bot": ("friendly", "rover", 3.5),
    "sentry_turret": ("friendly", "turret", 0.0),
    "recon_drone": ("friendly", "drone", 5.0),
    "heavy_drone": ("friendly", "drone", 2.5),
    "scout_drone": ("friendly", "scout_drone", 4.0),
    # Heavy units
    "tank": ("friendly", "tank", 3.0),
    "apc": ("friendly", "apc", 5.0),
    "heavy_turret": ("friendly", "heavy_turret", 0.0),
    "missile_turret": ("friendly", "missile_turret", 0.0),
    # Hostile variants
    "hostile_vehicle": ("hostile", "hostile_vehicle", 6.0),
    "hostile_leader": ("hostile", "hostile_leader", 1.8),
}


def _obj_position(obj: dict) -> tuple[float, float]:
    """Extract (x, z) position from an object dict."""
    pos_data = obj.get("position", {})
    return (
        float(pos_data.get("x", 0.0)),
        float(pos_data.get("z", 0.0)),
    )


def load_layout(path: str, engine: SimulationEngine) -> int:
    """Read a TritiumLevelFormat JSON file and populate *engine* with targets.

    Returns the number of targets created.
    """
    with open(path, "r") as f:
        data = json.load(f)

    objects = data.get("objects", [])
    count = 0
    created_targets: list[tuple[SimulationTarget, tuple[float, float]]] = []
    waypoint_objects: list[dict] = []

    for obj in objects:
        obj_type: str = obj.get("type", "").lower()

        # Collect waypoints for second pass
        if obj_type in _WAYPOINT_TYPES:
            waypoint_objects.append(obj)
            continue

        # Skip zone types (handled by load_zones)
        if obj_type in _ZONE_TYPES:
            continue

        # Skip non-target types
        if obj_type in _SKIP_TYPES or any(skip in obj_type for skip in _SKIP_TYPES):
            continue

        # Determine alliance, asset_type, and speed
        alliance: str
        asset_type: str
        speed: float

        if obj_type in _SPECIFIC_TYPES:
            alliance, asset_type, speed = _SPECIFIC_TYPES[obj_type]
        elif "robot" in obj_type or "rover" in obj_type:
            alliance = "friendly"
            asset_type = "rover"
            speed = 2.0
        elif "drone" in obj_type:
            alliance = "friendly"
            asset_type = "drone"
            speed = 4.0
        elif "turret" in obj_type:
            alliance = "friendly"
            asset_type = "turret"
            speed = 0.0
        elif "person" in obj_type or "intruder" in obj_type:
            alliance = "hostile"
            asset_type = "person"
            speed = 1.5
        else:
            # Unknown type — skip
            continue

        # Position: (x, z) from 3D coords (y is height)
        position = _obj_position(obj)

        # Waypoints from properties
        props = obj.get("properties", {})
        waypoints: list[tuple[float, float]] = []
        raw_waypoints = props.get("patrol_waypoints", [])
        for wp in raw_waypoints:
            waypoints.append((float(wp.get("x", 0.0)), float(wp.get("z", 0.0))))

        name = props.get("name", obj.get("name", f"{asset_type}-{count}"))

        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=name,
            alliance=alliance,
            asset_type=asset_type,
            position=position,
            speed=speed,
            waypoints=waypoints,
            loop_waypoints=(alliance == "friendly" and speed > 0),
        )
        engine.add_target(target)
        created_targets.append((target, position))
        count += 1

    # Second pass: assign waypoint objects to nearest created target
    if waypoint_objects and created_targets:
        for wp_obj in waypoint_objects:
            wp_pos = _obj_position(wp_obj)
            best_target: SimulationTarget | None = None
            best_dist = float("inf")
            for target, tpos in created_targets:
                dx = wp_pos[0] - tpos[0]
                dz = wp_pos[1] - tpos[1]
                dist = math.sqrt(dx * dx + dz * dz)
                if dist < best_dist:
                    best_dist = dist
                    best_target = target
            if best_target is not None:
                best_target.waypoints.append(wp_pos)

    return count


def load_zones(path: str) -> list[dict]:
    """Extract zone objects from a TritiumLevelFormat JSON file.

    Returns a list of dicts with ``type``, ``position``, and ``properties``.
    """
    with open(path, "r") as f:
        data = json.load(f)

    zones: list[dict] = []
    for obj in data.get("objects", []):
        obj_type: str = obj.get("type", "").lower()
        if obj_type not in _ZONE_TYPES:
            continue
        pos = _obj_position(obj)
        zones.append({
            "type": obj_type,
            "position": {"x": pos[0], "z": pos[1]},
            "properties": obj.get("properties", {}),
            "name": obj.get("properties", {}).get("name", obj.get("name", obj_type)),
        })

    return zones
