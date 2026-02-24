"""TurretBehavior -- stationary turret combat AI.

Stationary. Rotate toward nearest hostile in range. Fire when aimed.
Uses lead_target() to aim ahead of moving hostiles so projectiles
intersect their predicted position rather than where they are now.

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
    from engine.comms.event_bus import EventBus
    from ..combat import CombatSystem
    from ..target import SimulationTarget


class TurretBehavior:
    """Stationary turret combat AI. Called each tick to decide actions."""

    def __init__(self, combat_system: CombatSystem) -> None:
        self._combat = combat_system

    def tick(
        self,
        turret: SimulationTarget,
        hostiles: dict[str, SimulationTarget],
    ) -> None:
        """Rotate toward nearest hostile in range. Fire when aimed."""
        target = nearest_in_range(turret, hostiles)
        if target is None:
            return

        # Compute lead point for moving targets
        tvel = target_velocity(target.heading, target.speed)
        aim_pos = lead_target(
            turret.position, target.position, tvel, 25.0,
        )

        # Update heading to face the lead point
        dx = aim_pos[0] - turret.position[0]
        dy = aim_pos[1] - turret.position[1]
        turret.heading = math.degrees(math.atan2(dx, dy))

        # Only fire when FSM is in engaging state (or no FSM)
        if turret.fsm_state in (None, "engaging", "tracking"):
            # Check degradation before firing
            apply_degradation(turret)
            # Use effective cooldown for fire-readiness
            effective_cd = get_effective_cooldown(turret)
            now = _time.time()
            if (now - turret.last_fired) < effective_cd:
                return
            if not can_fire_degraded(turret):
                # Weapon jammed due to damage
                self._combat._event_bus.publish("weapon_jam", {
                    "target_id": turret.target_id,
                    "target_name": turret.name,
                    "degradation": turret.degradation,
                })
                return
            self._combat.fire(turret, target, aim_pos=aim_pos)
