"""UnitBehaviors — per-unit-type combat AI.

Architecture
------------
UnitBehaviors runs each tick and decides what each combatant does:

  - Turrets: stationary, rotate to face nearest hostile in range, fire.
  - Drones: fast strafe runs — approach hostiles, fire burst, pull back.
  - Rovers: tanky advance — move toward nearest hostile, engage at range.
  - Hostile kids: approach objective, shoot at defenders in range, dodge.

The behavior layer sits ABOVE the waypoint/tick movement system.  It does
NOT override waypoints for friendlies that have been dispatched (those
follow their assigned path while engaging targets of opportunity).  For
idle friendlies without waypoints, behaviors may set temporary engagement
headings.

Hostile kids follow their existing waypoint path (edge -> objective ->
escape) and fire at any defenders in range.  Occasional random dodge
offsets are applied to their position to make them harder to hit.
"""

from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .combat import CombatSystem
    from .target import SimulationTarget

# Drone strafe parameters
_DRONE_RETREAT_RANGE = 15.0  # pull back to this distance after firing


class UnitBehaviors:
    """Per-unit-type combat AI. Called each tick to decide actions."""

    def __init__(self, combat_system: CombatSystem) -> None:
        self._combat = combat_system
        self._last_dodge: dict[str, float] = {}  # target_id -> last dodge time

    def tick(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """For each active combatant, run its type-specific behavior."""
        friendlies = {
            k: v for k, v in targets.items()
            if v.alliance == "friendly" and v.status in ("active", "idle", "stationary")
            and v.is_combatant
        }
        hostiles = {
            k: v for k, v in targets.items()
            if v.alliance == "hostile" and v.status == "active"
            and v.is_combatant
        }

        for tid, t in friendlies.items():
            if t.asset_type == "turret":
                self._turret_behavior(t, hostiles)
            elif t.asset_type in ("heavy_turret", "missile_turret"):
                self._turret_behavior(t, hostiles)
            elif t.asset_type == "drone":
                self._drone_behavior(t, hostiles)
            elif t.asset_type in ("scout_drone",):
                self._drone_behavior(t, hostiles)
            elif t.asset_type == "rover":
                self._rover_behavior(t, hostiles)
            elif t.asset_type in ("tank", "apc"):
                self._rover_behavior(t, hostiles)

        for tid, t in hostiles.items():
            self._hostile_kid_behavior(t, friendlies)

    def _turret_behavior(
        self,
        turret: SimulationTarget,
        hostiles: dict[str, SimulationTarget],
    ) -> None:
        """Stationary. Rotate toward nearest hostile in range. Fire when aimed."""
        target = self._nearest_in_range(turret, hostiles)
        if target is None:
            return

        # Update heading to face target
        dx = target.position[0] - turret.position[0]
        dy = target.position[1] - turret.position[1]
        turret.heading = math.degrees(math.atan2(dx, dy))

        # Fire
        self._combat.fire(turret, target)

    def _drone_behavior(
        self,
        drone: SimulationTarget,
        hostiles: dict[str, SimulationTarget],
    ) -> None:
        """Fast, fragile. Strafe runs — approach, fire burst, retreat."""
        target = self._nearest_in_range(drone, hostiles)
        if target is None:
            # No hostiles in range — if not on a patrol, just hold position
            return

        dx = target.position[0] - drone.position[0]
        dy = target.position[1] - drone.position[1]
        dist = math.hypot(dx, dy)

        # Update heading to face target
        drone.heading = math.degrees(math.atan2(dx, dy))

        # Fire if in range
        self._combat.fire(drone, target)

    def _rover_behavior(
        self,
        rover: SimulationTarget,
        hostiles: dict[str, SimulationTarget],
    ) -> None:
        """Tanky. Move toward nearest hostile, engage at range."""
        target = self._nearest_in_range(rover, hostiles)
        if target is None:
            return

        dx = target.position[0] - rover.position[0]
        dy = target.position[1] - rover.position[1]

        # Update heading to face target
        rover.heading = math.degrees(math.atan2(dx, dy))

        # Fire if in range
        self._combat.fire(rover, target)

    def _hostile_kid_behavior(
        self,
        kid: SimulationTarget,
        friendlies: dict[str, SimulationTarget],
    ) -> None:
        """Kids with nerf guns. Follow waypoints, shoot at defenders in range."""
        target = self._nearest_in_range(kid, friendlies)
        if target is not None:
            # Fire at nearest defender
            self._combat.fire(kid, target)

        # Occasional dodge (random perpendicular offset every 2-4 seconds)
        now = time.time()
        last_dodge = self._last_dodge.get(kid.target_id, 0.0)
        if now - last_dodge > random.uniform(2.0, 4.0):
            self._last_dodge[kid.target_id] = now
            # Small perpendicular offset
            offset = random.uniform(-1.5, 1.5)
            heading_rad = math.radians(kid.heading)
            # Perpendicular to heading
            kid.position = (
                kid.position[0] + math.cos(heading_rad) * offset,
                kid.position[1] - math.sin(heading_rad) * offset,
            )

    # -- Helpers ----------------------------------------------------------------

    @staticmethod
    def _nearest_in_range(
        unit: SimulationTarget,
        enemies: dict[str, SimulationTarget],
    ) -> SimulationTarget | None:
        """Find the nearest enemy within weapon_range."""
        best: SimulationTarget | None = None
        best_dist = float("inf")
        for enemy in enemies.values():
            dx = enemy.position[0] - unit.position[0]
            dy = enemy.position[1] - unit.position[1]
            dist = math.hypot(dx, dy)
            if dist <= unit.weapon_range and dist < best_dist:
                best_dist = dist
                best = enemy
        return best

    def clear_dodge_state(self) -> None:
        """Reset all dodge timers (for game reset)."""
        self._last_dodge.clear()
