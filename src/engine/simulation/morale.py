"""MoraleSystem -- per-unit morale tracking and effects.

Morale ranges from 0.0 (broken) to 1.0 (fully emboldened).  It decays
under fire (incoming damage events) and recovers slowly when safe.

Thresholds:
  - < 0.1  broken   -- unit flees regardless of orders
  - < 0.3  suppressed -- reduced fire rate, increased dodge
  - > 0.9  emboldened -- +20% damage, faster movement

For friendly units, morale < 0.3 reduces engagement range by 30%.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .target import SimulationTarget

# Default starting morale for all units
DEFAULT_MORALE = 0.7

# Recovery rate per second when not under fire
_RECOVERY_RATE = 0.02

# Morale loss per point of incoming damage
_DAMAGE_MORALE_LOSS = 0.005

# Morale loss when a nearby ally is eliminated
_ALLY_ELIMINATED_LOSS = 0.15

# Morale boost for nearby allies when an enemy is eliminated
_ENEMY_ELIMINATED_BOOST = 0.1

# Thresholds
BROKEN_THRESHOLD = 0.1
SUPPRESSED_THRESHOLD = 0.3
EMBOLDENED_THRESHOLD = 0.9


class MoraleSystem:
    """Tracks per-unit morale values and applies morale effects."""

    def __init__(self) -> None:
        self._morale: dict[str, float] = {}
        self._last_hit_time: dict[str, float] = {}

    def get_morale(self, target_id: str) -> float:
        """Return the current morale for *target_id*.

        Returns 1.0 (full morale) if the unit has no entry in the morale dict.
        Units are initialized to DEFAULT_MORALE when first set or when they
        take damage.  After reset(), all entries are cleared and queries
        return 1.0.
        """
        return self._morale.get(target_id, 1.0)

    def set_morale(self, target_id: str, value: float) -> None:
        """Set morale for *target_id*, clamped to [0.0, 1.0]."""
        self._morale[target_id] = max(0.0, min(1.0, value))

    def on_damage_taken(self, target_id: str, damage: float) -> None:
        """Reduce morale when a unit takes damage."""
        current = self.get_morale(target_id)
        loss = damage * _DAMAGE_MORALE_LOSS
        self.set_morale(target_id, current - loss)
        self._last_hit_time[target_id] = time.time()

    def on_ally_eliminated(self, target_id: str) -> None:
        """Reduce morale when a nearby ally is eliminated."""
        current = self.get_morale(target_id)
        self.set_morale(target_id, current - _ALLY_ELIMINATED_LOSS)

    def on_enemy_eliminated(self, target_id: str) -> None:
        """Boost morale when a nearby enemy is eliminated."""
        current = self.get_morale(target_id)
        self.set_morale(target_id, current + _ENEMY_ELIMINATED_BOOST)

    def tick(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """Recover morale for units not recently under fire."""
        now = time.time()
        for tid, t in targets.items():
            if t.status in ("eliminated", "destroyed", "neutralized"):
                continue
            last_hit = self._last_hit_time.get(tid, 0.0)
            if now - last_hit > 3.0:
                # Slowly recover morale when safe
                current = self.get_morale(tid)
                if current < DEFAULT_MORALE:
                    self.set_morale(tid, current + _RECOVERY_RATE * dt)

    def is_broken(self, target_id: str) -> bool:
        """Return True if the unit's morale is below the broken threshold."""
        return self.get_morale(target_id) < BROKEN_THRESHOLD

    def is_suppressed(self, target_id: str) -> bool:
        """Return True if the unit's morale is below the suppressed threshold."""
        return self.get_morale(target_id) < SUPPRESSED_THRESHOLD

    def is_emboldened(self, target_id: str) -> bool:
        """Return True if the unit's morale is above the emboldened threshold."""
        return self.get_morale(target_id) > EMBOLDENED_THRESHOLD

    def reset(self) -> None:
        """Clear all morale state."""
        self._morale.clear()
        self._last_hit_time.clear()
