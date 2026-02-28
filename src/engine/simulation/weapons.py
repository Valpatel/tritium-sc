# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""WeaponSystem -- per-unit weapon state with ammo, accuracy, and weapon class.

Each unit can have a weapon assigned with specific stats.  The weapon system
tracks ammo counts and provides the combat system with damage, range, cooldown,
accuracy, and weapon class information.

Weapon classes:
  - ballistic  -- standard projectile (nerf dart), has travel time
  - beam       -- instant hit (laser pointer), no projectile
  - aoe        -- area of effect (water balloon), blast radius
  - missile    -- tracking projectile, follows target
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus


@dataclass
class Weapon:
    """Weapon configuration and state."""

    name: str = "nerf_blaster"
    damage: float = 10.0
    weapon_range: float = 15.0
    cooldown: float = 2.0
    accuracy: float = 0.85  # 0.0-1.0, probability of hit
    ammo: int = 30
    max_ammo: int = 30
    weapon_class: str = "ballistic"  # ballistic, beam, aoe, missile
    blast_radius: float = 0.0  # only for aoe weapons


# Default weapon loadouts by asset type
_DEFAULT_WEAPONS: dict[str, Weapon] = {
    "turret": Weapon(
        name="nerf_turret_gun", damage=15.0, weapon_range=20.0,
        cooldown=1.5, accuracy=0.9, ammo=100, max_ammo=100,
    ),
    "drone": Weapon(
        name="nerf_dart_gun", damage=8.0, weapon_range=12.0,
        cooldown=1.0, accuracy=0.75, ammo=20, max_ammo=20,
    ),
    "rover": Weapon(
        name="nerf_cannon", damage=12.0, weapon_range=10.0,
        cooldown=2.0, accuracy=0.85, ammo=40, max_ammo=40,
    ),
    "person_hostile": Weapon(
        name="nerf_pistol", damage=10.0, weapon_range=8.0,
        cooldown=2.5, accuracy=0.6, ammo=15, max_ammo=15,
    ),
    "tank": Weapon(
        name="nerf_tank_cannon", damage=30.0, weapon_range=25.0,
        cooldown=3.0, accuracy=0.8, ammo=20, max_ammo=20,
        weapon_class="aoe", blast_radius=3.0,
    ),
    "apc": Weapon(
        name="nerf_apc_mg", damage=8.0, weapon_range=15.0,
        cooldown=1.0, accuracy=0.7, ammo=60, max_ammo=60,
    ),
    "heavy_turret": Weapon(
        name="nerf_heavy_turret", damage=25.0, weapon_range=30.0,
        cooldown=2.5, accuracy=0.85, ammo=50, max_ammo=50,
    ),
    "missile_turret": Weapon(
        name="nerf_missile_launcher", damage=50.0, weapon_range=35.0,
        cooldown=5.0, accuracy=0.95, ammo=10, max_ammo=10,
        weapon_class="missile",
    ),
    "scout_drone": Weapon(
        name="nerf_scout_gun", damage=5.0, weapon_range=8.0,
        cooldown=1.5, accuracy=0.65, ammo=15, max_ammo=15,
    ),
}


class WeaponSystem:
    """Manages per-unit weapon state and provides weapon data to combat."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._weapons: dict[str, Weapon] = {}
        self._unit_weapons: dict[str, Weapon] = self._weapons  # Alias for test compat
        self._event_bus = event_bus
        self._reload_timers: dict[str, float] = {}  # target_id -> remaining reload time
        self._reload_duration: float = 3.0  # Default reload time in seconds

    def equip(self, target_id: str, asset_type: str) -> None:
        """Equip a weapon for the given unit based on asset type.

        Uses the default weapon loadout for the asset type.
        If asset_type is unknown, equips a generic blaster.
        """
        self.assign_default_weapon(target_id, asset_type)
        # If no default exists, equip a generic weapon
        if target_id not in self._weapons:
            self._weapons[target_id] = Weapon()

    def get_ammo(self, target_id: str) -> int:
        """Return current ammo count for a unit (0 if not equipped)."""
        weapon = self._weapons.get(target_id)
        if weapon is None:
            return 0
        return weapon.ammo

    def is_reloading(self, target_id: str) -> bool:
        """Return whether a unit is currently reloading."""
        return target_id in self._reload_timers

    def assign_weapon(self, target_id: str, weapon: Weapon) -> None:
        """Assign a specific weapon to a unit."""
        self._weapons[target_id] = weapon

    def assign_default_weapon(self, target_id: str, asset_type: str, alliance: str = "friendly") -> None:
        """Assign the default weapon for a given asset type."""
        key = asset_type
        if asset_type == "person" and alliance == "hostile":
            key = "person_hostile"
        template = _DEFAULT_WEAPONS.get(key)
        if template is not None:
            # Create a copy so units don't share state
            import dataclasses
            self._weapons[target_id] = dataclasses.replace(template)

    def get_weapon(self, target_id: str) -> Weapon | None:
        """Return the weapon assigned to *target_id*, or None."""
        return self._weapons.get(target_id)

    def consume_ammo(self, target_id: str) -> bool:
        """Consume one round of ammo. Returns False if empty.

        Publishes ``ammo_depleted`` when ammo reaches zero.
        Publishes ``ammo_low`` when ammo drops below 20%.
        """
        weapon = self._weapons.get(target_id)
        if weapon is None:
            return True  # no weapon system = infinite ammo (legacy)
        if weapon.ammo <= 0:
            return False
        weapon.ammo -= 1
        if weapon.ammo == 0 and self._event_bus is not None:
            self._event_bus.publish("ammo_depleted", {
                "target_id": target_id,
                "weapon_name": weapon.name,
            })
        elif weapon.max_ammo > 0 and weapon.ammo / weapon.max_ammo < 0.2:
            if self._event_bus is not None:
                self._event_bus.publish("ammo_low", {
                    "target_id": target_id,
                    "weapon_name": weapon.name,
                    "ammo_remaining": weapon.ammo,
                    "ammo_pct": weapon.ammo / weapon.max_ammo,
                })
        return True

    def get_ammo_pct(self, target_id: str) -> float:
        """Return ammo percentage (0.0-1.0) for a unit, 1.0 if no weapon."""
        weapon = self._weapons.get(target_id)
        if weapon is None or weapon.max_ammo == 0:
            return 1.0
        return weapon.ammo / weapon.max_ammo

    def tick(self, dt: float) -> None:
        """Process reload timers.

        When ammo is 0, start a reload. When reload completes, refill ammo.
        """
        # Check for units that need reloading
        for tid, weapon in self._weapons.items():
            if weapon.ammo <= 0 and tid not in self._reload_timers:
                self._reload_timers[tid] = self._reload_duration

        # Process active reloads
        completed: list[str] = []
        for tid in list(self._reload_timers):
            self._reload_timers[tid] -= dt
            if self._reload_timers[tid] <= 0:
                completed.append(tid)

        for tid in completed:
            del self._reload_timers[tid]
            weapon = self._weapons.get(tid)
            if weapon is not None:
                weapon.ammo = weapon.max_ammo

    def reset(self) -> None:
        """Clear all weapon assignments and reload timers."""
        self._weapons.clear()
        self._reload_timers.clear()
