# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""DegradationSystem -- health-based performance degradation.

As a unit takes damage, its combat effectiveness degrades:
  - Movement speed scales with health percentage
  - Fire rate (cooldown) increases as health drops
  - Heavily damaged units may fail to fire entirely

Degradation kicks in below 50% health and gets worse linearly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .target import SimulationTarget

# Health fraction below which degradation begins
_DEGRADATION_THRESHOLD = 0.5

# At minimum health, speed is this fraction of normal
_MIN_SPEED_FACTOR = 0.4

# At minimum health, cooldown is this multiple of normal
_MAX_COOLDOWN_FACTOR = 2.0

# Below this health fraction, unit cannot fire at all
_FIRE_DISABLED_THRESHOLD = 0.1


class DegradationSystem:
    """Computes performance degradation based on health."""

    def __init__(self) -> None:
        self._degradation: dict[str, dict] = {}

    def get_health_fraction(self, target: SimulationTarget) -> float:
        """Return health as fraction of max_health (0.0-1.0)."""
        if target.max_health <= 0:
            return 0.0
        return max(0.0, min(1.0, target.health / target.max_health))

    def get_degradation_factor(self, target: SimulationTarget) -> float:
        """Return degradation factor (0.0 = fully degraded, 1.0 = no degradation).

        Degradation is linear below _DEGRADATION_THRESHOLD.
        """
        health_frac = self.get_health_fraction(target)
        if health_frac >= _DEGRADATION_THRESHOLD:
            return 1.0
        # Linear interpolation: at threshold -> 1.0, at 0 -> 0.0
        return health_frac / _DEGRADATION_THRESHOLD

    def get_effective_speed(self, target: SimulationTarget) -> float:
        """Return the effective speed after degradation.

        Speed scales from full to _MIN_SPEED_FACTOR as health drops below threshold.
        """
        factor = self.get_degradation_factor(target)
        speed_factor = _MIN_SPEED_FACTOR + (1.0 - _MIN_SPEED_FACTOR) * factor
        return target.speed * speed_factor

    def get_effective_cooldown(self, target: SimulationTarget) -> float:
        """Return the effective weapon cooldown after degradation.

        Cooldown increases from normal to _MAX_COOLDOWN_FACTOR * normal as health drops.
        """
        factor = self.get_degradation_factor(target)
        cooldown_mult = 1.0 + (_MAX_COOLDOWN_FACTOR - 1.0) * (1.0 - factor)
        return target.weapon_cooldown * cooldown_mult

    def can_fire_degraded(self, target: SimulationTarget) -> bool:
        """Return True if the unit is healthy enough to fire.

        Units below _FIRE_DISABLED_THRESHOLD cannot fire.
        """
        return self.get_health_fraction(target) >= _FIRE_DISABLED_THRESHOLD

    def tick(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """Tick is a no-op -- degradation is computed on demand from health."""
        pass

    def reset(self) -> None:
        """Clear all degradation state."""
        self._degradation.clear()


# ---------------------------------------------------------------------------
# Module-level convenience functions using a shared singleton instance.
# Behavior modules (turret, drone, rover, hostile) import these directly:
#   from ..degradation import apply_degradation, can_fire_degraded, get_effective_cooldown
# ---------------------------------------------------------------------------

_default_system = DegradationSystem()


def apply_degradation(target: SimulationTarget) -> None:
    """Update the target's degradation field based on current health.

    Sets ``target.degradation`` to a 0.0-1.0 value where 0.0 is pristine
    and 1.0 is fully degraded.  This is the inverse of the degradation
    factor (1.0 = no degradation).
    """
    factor = _default_system.get_degradation_factor(target)
    target.degradation = 1.0 - factor


def can_fire_degraded(target: SimulationTarget) -> bool:
    """Return True if the unit is healthy enough to fire."""
    return _default_system.can_fire_degraded(target)


def get_effective_cooldown(target: SimulationTarget) -> float:
    """Return the effective weapon cooldown after degradation."""
    return _default_system.get_effective_cooldown(target)
