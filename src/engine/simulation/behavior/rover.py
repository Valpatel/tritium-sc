# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""RoverBehavior -- tanky ground unit combat AI.

Tanky. Move toward nearest hostile, engage at range.
Uses predict_intercept() to aim toward where the hostile will be,
and lead_target() for projectile fire.

Degradation integration: checks can_fire_degraded() before firing and
uses get_effective_cooldown() for fire-readiness checks.  Publishes a
``weapon_jam`` event when the weapon jams due to damage.

Pursuit-evasion integration (via PursuitSystem):
  - Fleeing hostiles get higher targeting priority.
  - Rovers calculate intercept waypoints to cut off fleeing hostiles.
  - Anti-dogpile: at most 2 rovers chase the same hostile.
"""

from __future__ import annotations

import math
import time as _time
from typing import TYPE_CHECKING

from ..degradation import apply_degradation, can_fire_degraded, get_effective_cooldown
from ..intercept import lead_target, predict_intercept, target_velocity
from ..pursuit import PursuitSystem
from .base import nearest_in_range

if TYPE_CHECKING:
    from ..combat import CombatSystem
    from ..comms import UnitComms
    from ..target import SimulationTarget


class RoverBehavior:
    """Rover tanky combat AI. Called each tick to decide actions."""

    def __init__(self, combat_system: CombatSystem) -> None:
        self._combat = combat_system
        self._pursuit: PursuitSystem | None = None
        self._map_bounds: float = 200.0
        # Unit-to-unit tactical communication system (optional)
        self._comms: UnitComms | None = None

    def set_pursuit(self, pursuit: PursuitSystem, map_bounds: float = 200.0) -> None:
        """Set the pursuit-evasion system for intercept calculations."""
        self._pursuit = pursuit
        self._map_bounds = map_bounds

    def set_comms(self, comms: UnitComms) -> None:
        """Set the unit-to-unit communication system."""
        self._comms = comms

    def set_terrain(self, terrain: object) -> None:
        """Set terrain map for terrain-aware speed modifiers on roads."""
        self._terrain = terrain

    def tick(
        self,
        rover: SimulationTarget,
        hostiles: dict[str, SimulationTarget],
    ) -> None:
        """Move toward nearest hostile, engage at range.

        When PursuitSystem is available, fleeing hostiles get higher
        targeting priority and rovers calculate intercept waypoints.
        """
        # Retreating/RTB rovers don't engage
        if rover.fsm_state in ("retreating", "rtb"):
            return

        # Target selection: pursuit system prioritizes fleeing hostiles
        target = None
        if self._pursuit is not None:
            target = self._pursuit.select_pursuit_target(rover, hostiles)
        if target is None:
            target = nearest_in_range(rover, hostiles)
        if target is None:
            return

        # Compute target velocity and predicted intercept for pursuit
        tvel = target_velocity(target.heading, target.speed)

        # For fleeing targets, use PursuitSystem intercept waypoint
        if (
            self._pursuit is not None
            and target.fsm_state == "fleeing"
        ):
            intercept_pt = self._pursuit.calculate_intercept_waypoint(
                rover.position, rover.speed,
                target.position, target.heading, target.speed,
                self._map_bounds,
            )
        else:
            intercept_pt = predict_intercept(
                rover.position, rover.speed, target.position, tvel,
            )

        # Update heading to face predicted intercept point
        dx = intercept_pt[0] - rover.position[0]
        dy = intercept_pt[1] - rover.position[1]
        rover.heading = math.degrees(math.atan2(dx, dy))

        # Lead targeting for projectile fire
        aim_pos = lead_target(
            rover.position, target.position, tvel, 25.0,
        )

        # Only fire when FSM allows (engaging/pursuing/patrolling, not retreating/rtb)
        if rover.fsm_state in (None, "engaging", "pursuing", "patrolling", "idle"):
            # Check degradation before firing
            apply_degradation(rover)
            effective_cd = get_effective_cooldown(rover)
            now = _time.time()
            if (now - rover.last_fired) < effective_cd:
                return
            if not can_fire_degraded(rover):
                self._combat._event_bus.publish("weapon_jam", {
                    "target_id": rover.target_id,
                    "target_name": rover.name,
                    "degradation": rover.degradation,
                })
                return
            self._combat.fire(rover, target, aim_pos=aim_pos)
