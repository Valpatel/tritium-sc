# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""BehaviorCoordinator -- orchestrates all per-unit-type behavior classes.

Architecture
------------
BehaviorCoordinator runs each tick and delegates to the correct behavior
class based on the unit's MovementCategory:

  - STATIONARY -> TurretBehavior
  - AIR        -> DroneBehavior
  - GROUND     -> RoverBehavior
  - hostile    -> HostileBehavior

The coordinator owns all 4 behavior instances and exposes the same public
interface that the old monolithic UnitBehaviors class had, so it is a
drop-in replacement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from engine.units import get_type as _get_unit_type
from engine.units.base import MovementCategory

from .turret import TurretBehavior
from .drone import DroneBehavior
from .rover import RoverBehavior
from .hostile import HostileBehavior

if TYPE_CHECKING:
    from engine.tactical.obstacles import BuildingObstacles
    from ..combat import CombatSystem
    from ..comms import UnitComms
    from ..target import SimulationTarget
    from ..terrain import TerrainMap


class BehaviorCoordinator:
    """Per-unit-type combat AI coordinator. Called each tick to decide actions.

    Drop-in replacement for the old monolithic UnitBehaviors class.
    """

    # Expose class-level constants from HostileBehavior for backward compat
    DETECTED_SPEED_BOOST = HostileBehavior.DETECTED_SPEED_BOOST
    DETECTED_FLANK_STEP = HostileBehavior.DETECTED_FLANK_STEP

    def __init__(self, combat_system: CombatSystem, engine: object | None = None) -> None:
        self._combat = combat_system
        self._engine = engine
        self._turret = TurretBehavior(combat_system)
        self._drone = DroneBehavior(combat_system)
        self._rover = RoverBehavior(combat_system)
        self._hostile = HostileBehavior(combat_system, engine=engine)

    # -- Public properties for backward compatibility -------------------------

    @property
    def _last_dodge(self) -> dict[str, float]:
        return self._hostile._last_dodge

    @_last_dodge.setter
    def _last_dodge(self, val: dict[str, float]) -> None:
        self._hostile._last_dodge = val

    @property
    def _last_flank(self) -> dict[str, float]:
        return self._hostile._last_flank

    @_last_flank.setter
    def _last_flank(self, val: dict[str, float]) -> None:
        self._hostile._last_flank = val

    @property
    def _obstacles(self) -> BuildingObstacles | None:
        return self._hostile._obstacles

    @_obstacles.setter
    def _obstacles(self, val: BuildingObstacles | None) -> None:
        self._hostile._obstacles = val

    @property
    def _group_rush_ids(self) -> set[str]:
        return self._hostile._group_rush_ids

    @_group_rush_ids.setter
    def _group_rush_ids(self, val: set[str]) -> None:
        self._hostile._group_rush_ids = val

    @property
    def _base_speeds(self) -> dict[str, float]:
        return self._hostile._base_speeds

    @_base_speeds.setter
    def _base_speeds(self, val: dict[str, float]) -> None:
        self._hostile._base_speeds = val

    @property
    def _recon_ids(self) -> set[str]:
        return self._hostile._recon_ids

    @_recon_ids.setter
    def _recon_ids(self, val: set[str]) -> None:
        self._hostile._recon_ids = val

    @property
    def _recon_base_speeds(self) -> dict[str, float]:
        return self._hostile._recon_base_speeds

    @_recon_base_speeds.setter
    def _recon_base_speeds(self, val: dict[str, float]) -> None:
        self._hostile._recon_base_speeds = val

    @property
    def _suppress_ids(self) -> set[str]:
        return self._hostile._suppress_ids

    @_suppress_ids.setter
    def _suppress_ids(self, val: set[str]) -> None:
        self._hostile._suppress_ids = val

    @property
    def _suppress_base_cooldowns(self) -> dict[str, float]:
        return self._hostile._suppress_base_cooldowns

    @_suppress_base_cooldowns.setter
    def _suppress_base_cooldowns(self, val: dict[str, float]) -> None:
        self._hostile._suppress_base_cooldowns = val

    @property
    def _detected_ids(self) -> set[str]:
        return self._hostile._detected_ids

    @_detected_ids.setter
    def _detected_ids(self, val: set[str]) -> None:
        self._hostile._detected_ids = val

    @property
    def _detected_base_speeds(self) -> dict[str, float]:
        return self._hostile._detected_base_speeds

    @_detected_base_speeds.setter
    def _detected_base_speeds(self, val: dict[str, float]) -> None:
        self._hostile._detected_base_speeds = val

    # -- Main tick entry point ------------------------------------------------

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
            type_def = _get_unit_type(t.asset_type)
            if type_def is None:
                continue
            cat = type_def.category
            if cat is MovementCategory.STATIONARY:
                self._turret.tick(t, hostiles)
            elif cat is MovementCategory.AIR:
                self._drone.tick(t, hostiles)
            elif cat is MovementCategory.GROUND:
                self._rover.tick(t, hostiles)
            # FOOT friendlies: no auto-engage behavior

        # Check group rush before individual hostile behaviors
        self._hostile.check_group_rush(hostiles)

        for tid, t in hostiles.items():
            self._hostile.tick(t, friendlies)

    # -- Delegated methods for backward compatibility -------------------------

    def set_obstacles(self, obstacles: BuildingObstacles) -> None:
        """Set building obstacles for cover-seeking behavior."""
        self._hostile.set_obstacles(obstacles)

    def set_terrain(self, terrain: TerrainMap) -> None:
        """Set terrain map for terrain-aware speed modifiers and concealment."""
        self._terrain = terrain
        self._hostile.set_terrain(terrain)
        self._rover.set_terrain(terrain)

    def set_comms(self, comms: UnitComms) -> None:
        """Set the unit-to-unit communication system on all behavior classes."""
        self._hostile.set_comms(comms)
        self._rover.set_comms(comms)

    def clear_dodge_state(self) -> None:
        """Reset all dodge timers and tactical state (for game reset)."""
        self._hostile.clear_state()

    def apply_sensor_awareness(self, kid: SimulationTarget) -> None:
        """Apply +20% speed boost to a sensor-detected hostile."""
        self._hostile.apply_sensor_awareness(kid)

    def remove_sensor_awareness(self, kid: SimulationTarget) -> None:
        """Remove sensor-detection speed boost and restore original speed."""
        self._hostile.remove_sensor_awareness(kid)

    # -- Delegated internal methods for tests that reach in --------------------

    def _try_flank(
        self,
        kid: SimulationTarget,
        friendlies: dict[str, SimulationTarget],
    ) -> bool:
        """Delegate to HostileBehavior._try_flank for backward compat."""
        return self._hostile._try_flank(kid, friendlies)

    def _check_group_rush(
        self,
        hostiles: dict[str, SimulationTarget],
    ) -> None:
        """Delegate to HostileBehavior.check_group_rush for backward compat."""
        self._hostile.check_group_rush(hostiles)

    # -- Static helper exposed for backward compat ----------------------------

    @staticmethod
    def _nearest_in_range(
        unit: SimulationTarget,
        enemies: dict[str, SimulationTarget],
    ) -> SimulationTarget | None:
        """Find the nearest enemy within weapon_range."""
        from .base import nearest_in_range
        return nearest_in_range(unit, enemies)

    @staticmethod
    def _nearest_point_on_segment(
        px: float, py: float,
        ax: float, ay: float,
        bx: float, by: float,
    ) -> tuple[float, float]:
        """Find the nearest point on segment AB to point P."""
        return HostileBehavior._nearest_point_on_segment(px, py, ax, ay, bx, by)
