"""DroneBehavior -- fast fragile strafe-run combat AI.

Fast, fragile. Strafe runs -- approach, fire burst, retreat.
Uses lead_target() to aim ahead of moving hostiles.

Degradation integration: checks can_fire_degraded() before firing and
uses get_effective_cooldown() for fire-readiness checks.  Publishes a
``weapon_jam`` event when the weapon jams due to damage.
"""

from __future__ import annotations

import math
import time as _time
from typing import TYPE_CHECKING

from ..degradation import apply_degradation, can_fire_degraded, get_effective_cooldown
from ..intercept import lead_target, target_velocity
from .base import nearest_in_range

if TYPE_CHECKING:
    from ..combat import CombatSystem
    from ..target import SimulationTarget


class DroneBehavior:
    """Drone strafe-run combat AI. Called each tick to decide actions."""

    def __init__(self, combat_system: CombatSystem) -> None:
        self._combat = combat_system

    def tick(
        self,
        drone: SimulationTarget,
        hostiles: dict[str, SimulationTarget],
    ) -> None:
        """Approach nearest hostile, fire burst, retreat."""
        # RTB drones don't engage
        if drone.fsm_state == "rtb":
            return

        target = nearest_in_range(drone, hostiles)
        if target is None:
            return

        # Compute lead point for moving targets
        tvel = target_velocity(target.heading, target.speed)
        aim_pos = lead_target(
            drone.position, target.position, tvel, 25.0,
        )

        dx = aim_pos[0] - drone.position[0]
        dy = aim_pos[1] - drone.position[1]

        # Update heading to face the lead point
        drone.heading = math.degrees(math.atan2(dx, dy))

        # Only fire when FSM allows (engaging/orbiting/scouting, not RTB)
        if drone.fsm_state in (None, "engaging", "orbiting", "scouting", "idle"):
            # Check degradation before firing
            apply_degradation(drone)
            effective_cd = get_effective_cooldown(drone)
            now = _time.time()
            if (now - drone.last_fired) < effective_cd:
                return
            if not can_fire_degraded(drone):
                self._combat._event_bus.publish("weapon_jam", {
                    "target_id": drone.target_id,
                    "target_name": drone.name,
                    "degradation": drone.degradation,
                })
                return
            self._combat.fire(drone, target, aim_pos=aim_pos)
