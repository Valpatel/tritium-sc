# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""VisionSystem -- per-unit visibility computation.

Determines what each unit can see each tick based on:
  - Ambient radius: 360-degree close-range awareness
  - Cone vision: directional detection with optional sweep rotation
  - Omnidirectional: full vision_radius when cone_range == 0
  - Line-of-sight: blocked by buildings via TerrainMap
  - Drone relay: targets seen by drones shared with all friendlies
  - External sightings: camera/robot reports merged into visibility

Integration:
  - Engine creates VisionSystem on init, ticks it each frame
  - Behaviors filter targets to only engage visible enemies
  - Combat checks LOS before allowing fire
  - Frontend receives visible/detected_by via target telemetry
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.units import get_type

if TYPE_CHECKING:
    from .spatial import SpatialGrid
    from .target import SimulationTarget
    from .terrain import TerrainMap


@dataclass
class SightingReport:
    """A sighting report from a camera, robot, or other external source."""
    observer_id: str
    target_id: str
    observer_type: str = "sim_unit"  # "sim_unit", "camera", "robot"
    confidence: float = 1.0
    position: tuple[float, float] | None = None
    timestamp: float = 0.0


@dataclass
class VisibilityState:
    """Result of a vision tick -- who can see what."""
    visible_to: dict[str, set[str]] = field(default_factory=dict)   # target_id -> observer_ids
    can_see: dict[str, list[str]] = field(default_factory=dict)     # observer_id -> target_ids
    friendly_visible: set[str] = field(default_factory=set)         # union of all friendly vision
    drone_relayed: set[str] = field(default_factory=set)            # targets shared via drone relay


# Types that relay vision to all friendlies
_DRONE_TYPES = {"drone", "scout_drone"}


class VisionSystem:
    """Computes per-unit visibility each tick.

    Algorithm per friendly unit:
      1. Resolve vision params from unit type registry
      2. Get candidates from spatial grid within max range
      3. For each enemy candidate:
         a. Ambient check (dist <= ambient_radius, LOS)
         b. Cone check (cone_range > 0, dist <= cone_range, arc, LOS)
         c. Omni check (cone_range == 0, dist <= vision_radius, LOS)
      4. Drone relay: drone-seen targets go to friendly_visible
      5. External sightings merged, then cleared
    """

    def __init__(self, terrain_map: TerrainMap | None = None) -> None:
        self._terrain_map = terrain_map
        self._sweep_angles: dict[str, float] = {}
        self._external_sightings: list[SightingReport] = []
        self._last_state: VisibilityState | None = None

    def set_terrain(self, terrain_map: TerrainMap) -> None:
        """Update the terrain map used for LOS checks."""
        self._terrain_map = terrain_map

    def add_sighting(self, report: SightingReport) -> None:
        """Queue an external sighting report (camera, robot, etc.)."""
        self._external_sightings.append(report)

    def tick(
        self,
        dt: float,
        targets: dict[str, SimulationTarget],
        spatial_grid: SpatialGrid,
    ) -> VisibilityState:
        """Compute visibility for all units this tick."""
        state = VisibilityState()

        # Separate friendlies and hostiles
        friendlies: list[SimulationTarget] = []
        enemies: dict[str, SimulationTarget] = {}
        for t in targets.values():
            if t.status in ("destroyed", "eliminated", "neutralized", "despawned"):
                continue
            if t.alliance == "friendly":
                friendlies.append(t)
            elif t.alliance == "hostile":
                enemies[t.target_id] = t

        # Process each friendly unit
        for unit in friendlies:
            utype = get_type(unit.asset_type)
            if utype is None:
                # Unknown type -- use basic defaults
                vision_radius = 15.0
                ambient_radius = 10.0
                cone_range = 0.0
                cone_angle = 0.0
                cone_sweeps = False
                cone_sweep_rpm = 0.0
            else:
                vision_radius = utype.vision_radius
                ambient_radius = utype.ambient_radius
                cone_range = utype.cone_range
                cone_angle = utype.cone_angle
                cone_sweeps = utype.cone_sweeps
                cone_sweep_rpm = utype.cone_sweep_rpm

            # Update sweep angle for sweeping units
            if cone_sweeps and cone_sweep_rpm > 0:
                prev = self._sweep_angles.get(unit.target_id, unit.heading)
                self._sweep_angles[unit.target_id] = prev + cone_sweep_rpm * 360.0 * dt / 60.0

            # Determine the maximum detection range for spatial query
            max_range = max(vision_radius, cone_range, ambient_radius)
            candidates = spatial_grid.query_radius(unit.position, max_range)

            is_drone = unit.asset_type in _DRONE_TYPES

            # Check each candidate
            for candidate in candidates:
                if candidate.target_id == unit.target_id:
                    continue
                if candidate.alliance != "hostile":
                    continue
                if candidate.status in ("destroyed", "eliminated", "neutralized", "despawned"):
                    continue

                dx = candidate.position[0] - unit.position[0]
                dy = candidate.position[1] - unit.position[1]
                dist = math.hypot(dx, dy)

                detected = False

                # Check ambient (close range, 360 degrees)
                if dist <= ambient_radius:
                    if self._check_los(unit.position, candidate.position):
                        detected = True

                # Check cone or omni if not already detected
                if not detected:
                    if cone_range > 0 and dist <= cone_range:
                        # Directional cone check
                        if self._in_cone(unit, dx, dy, cone_angle, cone_sweeps):
                            if self._check_los(unit.position, candidate.position):
                                detected = True
                    elif cone_range == 0 and dist <= vision_radius:
                        # Omnidirectional vision
                        if self._check_los(unit.position, candidate.position):
                            detected = True

                if detected:
                    tid = candidate.target_id
                    uid = unit.target_id

                    # Update visible_to
                    if tid not in state.visible_to:
                        state.visible_to[tid] = set()
                    state.visible_to[tid].add(uid)

                    # Update can_see
                    if uid not in state.can_see:
                        state.can_see[uid] = []
                    state.can_see[uid].append(tid)

                    # Add to friendly visible
                    state.friendly_visible.add(tid)

                    # Drone relay
                    if is_drone:
                        state.drone_relayed.add(tid)

        # Drone relay: add relayed targets to friendly_visible
        state.friendly_visible.update(state.drone_relayed)

        # Process external sightings
        for report in self._external_sightings:
            tid = report.target_id
            oid = report.observer_id
            if tid not in state.visible_to:
                state.visible_to[tid] = set()
            state.visible_to[tid].add(oid)
            if oid not in state.can_see:
                state.can_see[oid] = []
            state.can_see[oid].append(tid)
            state.friendly_visible.add(tid)

        # Clear external sightings after processing
        self._external_sightings.clear()

        self._last_state = state
        return state

    def can_see(self, observer_id: str, target_id: str) -> bool:
        """Check if observer can currently see target (from last tick)."""
        if self._last_state is None:
            return False
        return target_id in (self._last_state.can_see.get(observer_id) or [])

    def _in_cone(
        self,
        unit: SimulationTarget,
        dx: float,
        dy: float,
        cone_angle: float,
        cone_sweeps: bool,
    ) -> bool:
        """Check if direction (dx, dy) falls within the unit's vision cone.

        Uses 0=north convention: angle_to = atan2(dx, dy) in degrees.
        """
        angle_to = math.degrees(math.atan2(dx, dy))

        # Determine facing direction
        if cone_sweeps and unit.target_id in self._sweep_angles:
            facing = self._sweep_angles[unit.target_id]
        else:
            facing = unit.heading

        # Normalize angle difference to [-180, 180]
        diff = (angle_to - facing + 180.0) % 360.0 - 180.0
        return abs(diff) <= cone_angle / 2.0

    def _check_los(
        self,
        pos_a: tuple[float, float],
        pos_b: tuple[float, float],
    ) -> bool:
        """Check line of sight between two positions."""
        if self._terrain_map is None:
            return True
        return self._terrain_map.line_of_sight(pos_a, pos_b)
