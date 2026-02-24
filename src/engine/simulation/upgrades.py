"""UpgradeSystem -- passive upgrades and active abilities for simulation units.

Architecture
------------
The UpgradeSystem manages two categories of enhancements:

  1. Upgrades (passive, permanent): stat modifiers applied to a unit.
     Multiple upgrades stack multiplicatively (e.g., two 1.2x speed
     upgrades = 1.44x speed).  Each upgrade has a max_stacks limit
     and optional type eligibility restriction.

  2. Abilities (active, cooldown-gated): temporary effects activated by
     the player.  Each ability has a cooldown, duration, and effect type.
     Instant abilities (duration=0) execute immediately (e.g., repair).
     Duration abilities create an ActiveEffect that modifies stats for
     the duration then expires.

Stat modifier pipeline:
  - Upgrades contribute multiplicative modifiers (stat * 1.2 * 1.15 = 1.38)
  - Active effects contribute additional modifiers (speed_boost, overclock)
  - damage_reduction is additive (0.15 from chassis + 0.5 from shield = 0.65)
  - The engine/combat system queries get_stat_modifier(target_id, stat) to
    get the combined modifier for use in damage/movement calculations.

Thread safety:
  The UpgradeSystem is designed to be called from the engine tick loop
  (single-threaded).  No internal locking is needed since the engine
  holds its lock during the tick and exposes UpgradeSystem through
  API endpoints that serialize access.

Backward compatibility:
  The engine works without the UpgradeSystem.  All stat modifiers
  default to 1.0 (no change) or 0.0 (no reduction), so existing
  code that doesn't query the system behaves identically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .target import SimulationTarget


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Upgrade:
    """A passive upgrade that modifies unit stats."""

    upgrade_id: str
    name: str
    description: str
    stat_modifiers: dict[str, float]  # e.g., {"damage": 1.2, "speed": 1.1}
    cost: int = 0  # Score cost to apply
    max_stacks: int = 1  # How many times this can be applied
    eligible_types: list[str] | None = None  # None = all types


@dataclass
class Ability:
    """An active ability with cooldown."""

    ability_id: str
    name: str
    description: str
    cooldown: float  # Seconds between uses
    duration: float  # How long the effect lasts (0 = instant)
    effect: str  # "speed_boost", "repair", "shield", "emp", "overclock"
    magnitude: float  # Effect strength (varies by type)
    eligible_types: list[str] | None = None


@dataclass
class ActiveEffect:
    """An active ability effect currently applied to a unit."""

    target_id: str
    ability_id: str
    effect: str
    magnitude: float
    remaining: float  # Seconds remaining


# ---------------------------------------------------------------------------
# Predefined upgrades
# ---------------------------------------------------------------------------

UPGRADES: dict[str, Upgrade] = {
    "armor_plating": Upgrade(
        "armor_plating", "Armor Plating",
        "Increase max health by 25%",
        {"max_health": 1.25},
    ),
    "enhanced_optics": Upgrade(
        "enhanced_optics", "Enhanced Optics",
        "Increase weapon range by 20%",
        {"weapon_range": 1.2},
    ),
    "rapid_fire": Upgrade(
        "rapid_fire", "Rapid Fire",
        "Reduce weapon cooldown by 30%",
        {"weapon_cooldown": 0.7},
    ),
    "reinforced_chassis": Upgrade(
        "reinforced_chassis", "Reinforced Chassis",
        "Reduce damage taken by 15%",
        {"damage_reduction": 0.15},
    ),
    "turbo_motor": Upgrade(
        "turbo_motor", "Turbo Motor",
        "Increase speed by 20%",
        {"speed": 1.2},
    ),
    "precision_targeting": Upgrade(
        "precision_targeting", "Precision Targeting",
        "Increase damage by 15%",
        {"weapon_damage": 1.15},
    ),
}


# ---------------------------------------------------------------------------
# Predefined abilities
# ---------------------------------------------------------------------------

ABILITIES: dict[str, Ability] = {
    "speed_boost": Ability(
        "speed_boost", "Speed Boost",
        "Double speed for 5s",
        cooldown=30.0, duration=5.0,
        effect="speed_boost", magnitude=2.0,
        eligible_types=["rover", "drone", "scout_drone"],
    ),
    "emergency_repair": Ability(
        "emergency_repair", "Emergency Repair",
        "Restore 30% health",
        cooldown=60.0, duration=0.0,
        effect="repair", magnitude=0.3,
        eligible_types=["rover", "turret", "tank", "apc"],
    ),
    "shield": Ability(
        "shield", "Energy Shield",
        "Block 50% damage for 8s",
        cooldown=45.0, duration=8.0,
        effect="shield", magnitude=0.5,
        eligible_types=["turret", "heavy_turret", "tank"],
    ),
    "emp_burst": Ability(
        "emp_burst", "EMP Burst",
        "Slow enemies in 15m radius by 50% for 4s",
        cooldown=40.0, duration=4.0,
        effect="emp", magnitude=0.5,
        eligible_types=["drone", "missile_turret"],
    ),
    "overclock": Ability(
        "overclock", "Overclock",
        "Triple fire rate for 3s, then overheat",
        cooldown=50.0, duration=3.0,
        effect="overclock", magnitude=3.0,
        eligible_types=["turret", "heavy_turret", "apc"],
    ),
}

# EMP burst radius in meters
_EMP_RADIUS = 15.0


# ---------------------------------------------------------------------------
# UpgradeSystem
# ---------------------------------------------------------------------------

class UpgradeSystem:
    """Manages upgrades and abilities for all units.

    Usage from the engine:
      1. apply_upgrade(target_id, upgrade_id, target) -- during wave breaks
      2. grant_ability(target_id, ability_id) -- give unit an ability
      3. use_ability(target_id, ability_id, targets) -- activate ability
      4. tick(dt, targets) -- update cooldowns and active effects
      5. get_stat_modifier(target_id, stat) -- query combined modifier
    """

    def __init__(self) -> None:
        # Per-unit upgrade tracking: target_id -> [upgrade_id, ...]
        # (duplicates allowed for stacking)
        self._unit_upgrades: dict[str, list[str]] = {}

        # Per-unit ability tracking: target_id -> [ability_id, ...]
        self._unit_abilities: dict[str, list[str]] = {}

        # Cooldown tracking: (target_id, ability_id) -> remaining cooldown
        self._ability_cooldowns: dict[tuple[str, str], float] = {}

        # Currently active temporary effects
        self._active_effects: list[ActiveEffect] = []

        # Custom registered upgrades/abilities (extend the predefined ones)
        self._custom_upgrades: dict[str, Upgrade] = {}
        self._custom_abilities: dict[str, Ability] = {}

        # Simplified timed upgrade tracking: target_id -> {stat: {multiplier, remaining}}
        self._upgrades: dict[str, dict[str, dict]] = {}

    # -- Upgrade registration -----------------------------------------------

    def register_upgrade(self, upgrade: Upgrade) -> None:
        """Register a custom upgrade (extends the predefined set)."""
        self._custom_upgrades[upgrade.upgrade_id] = upgrade

    def register_ability(self, ability: Ability) -> None:
        """Register a custom ability (extends the predefined set)."""
        self._custom_abilities[ability.ability_id] = ability

    def _resolve_upgrade(self, upgrade_id: str) -> Upgrade | None:
        """Look up an upgrade by ID from predefined + custom."""
        if upgrade_id in UPGRADES:
            return UPGRADES[upgrade_id]
        return self._custom_upgrades.get(upgrade_id)

    def _resolve_ability(self, ability_id: str) -> Ability | None:
        """Look up an ability by ID from predefined + custom."""
        if ability_id in ABILITIES:
            return ABILITIES[ability_id]
        return self._custom_abilities.get(ability_id)

    # -- Simplified upgrade API (for test_subsystem_wiring) ------------------

    # Built-in simplified upgrades: name -> (stat, multiplier, duration)
    _SIMPLE_UPGRADES: dict[str, tuple[str, float, float]] = {
        "speed_boost": ("speed", 1.5, 30.0),
        "damage_boost": ("damage", 1.5, 30.0),
    }

    def apply_upgrade(
        self, target_id: str, upgrade_id_or_name: str, target: SimulationTarget | None = None
    ) -> bool:
        """Apply an upgrade to a unit. Returns True if successful.

        Supports two call styles:
          1. apply_upgrade(target_id, upgrade_id, target) -- original API with
             SimulationTarget for eligibility checks.
          2. apply_upgrade(target_id, upgrade_name) -- simplified API using
             built-in upgrade definitions (speed_boost, damage_boost).

        Fails if:
          - upgrade_id is unknown (in both predefined and simple upgrades)
          - unit's asset_type is not in eligible_types (original API only)
          - max_stacks would be exceeded (original API only)
        """
        # Simplified API: no target provided, use _SIMPLE_UPGRADES
        if target is None:
            simple = self._SIMPLE_UPGRADES.get(upgrade_id_or_name)
            if simple is None:
                return False
            stat, multiplier, duration = simple
            if target_id not in self._upgrades:
                self._upgrades[target_id] = {}
            self._upgrades[target_id][stat] = {
                "multiplier": multiplier,
                "remaining": duration,
            }
            return True

        # Original API: full upgrade with eligibility checks
        upgrade_id = upgrade_id_or_name
        upgrade = self._resolve_upgrade(upgrade_id)
        if upgrade is None:
            return False

        # Check type eligibility
        if upgrade.eligible_types is not None:
            if target.asset_type not in upgrade.eligible_types:
                return False

        # Check max stacks
        current = self._unit_upgrades.get(target_id, [])
        current_count = current.count(upgrade_id)
        if current_count >= upgrade.max_stacks:
            return False

        # Apply
        if target_id not in self._unit_upgrades:
            self._unit_upgrades[target_id] = []
        self._unit_upgrades[target_id].append(upgrade_id)
        return True

    def get_upgrades(self, target_id: str) -> list[str]:
        """Get list of upgrade IDs applied to a unit."""
        return list(self._unit_upgrades.get(target_id, []))

    # -- Grant / use abilities ----------------------------------------------

    def grant_ability(self, target_id: str, ability_id: str) -> bool:
        """Grant an ability to a unit. Returns True if successful.

        Fails if ability_id is unknown or already granted to this unit.
        """
        ability = self._resolve_ability(ability_id)
        if ability is None:
            return False

        current = self._unit_abilities.get(target_id, [])
        if ability_id in current:
            return False

        if target_id not in self._unit_abilities:
            self._unit_abilities[target_id] = []
        self._unit_abilities[target_id].append(ability_id)
        return True

    def get_abilities(self, target_id: str) -> list[str]:
        """Get list of ability IDs granted to a unit."""
        return list(self._unit_abilities.get(target_id, []))

    def can_use_ability(self, target_id: str, ability_id: str) -> bool:
        """Check if an ability is available (granted and off cooldown)."""
        # Must be granted
        granted = self._unit_abilities.get(target_id, [])
        if ability_id not in granted:
            return False

        # Must be off cooldown
        key = (target_id, ability_id)
        remaining = self._ability_cooldowns.get(key, 0.0)
        return remaining <= 0.0

    def use_ability(
        self,
        target_id: str,
        ability_id: str,
        targets: dict[str, SimulationTarget],
    ) -> bool:
        """Activate an ability. Returns True if successfully used.

        Fails if:
          - ability not granted to this unit
          - ability on cooldown
          - target unit is eliminated/destroyed
          - unit's asset_type not in ability's eligible_types
        """
        if not self.can_use_ability(target_id, ability_id):
            return False

        ability = self._resolve_ability(ability_id)
        if ability is None:
            return False

        # Get the source target
        source = targets.get(target_id)
        if source is None:
            return False

        # Check target is alive
        if source.status in ("eliminated", "destroyed", "neutralized"):
            return False

        # Check type eligibility
        if ability.eligible_types is not None:
            if source.asset_type not in ability.eligible_types:
                return False

        # Set cooldown
        self._ability_cooldowns[(target_id, ability_id)] = ability.cooldown

        # Execute effect
        self._execute_ability(ability, target_id, source, targets)
        return True

    def _execute_ability(
        self,
        ability: Ability,
        target_id: str,
        source: SimulationTarget,
        targets: dict[str, SimulationTarget],
    ) -> None:
        """Execute the ability's effect."""
        effect = ability.effect

        if effect == "repair":
            # Instant heal: restore magnitude% of max_health
            heal = source.max_health * ability.magnitude
            source.health = min(source.max_health, source.health + heal)
            # No active effect for instant abilities (duration=0)
            return

        if effect == "emp":
            # Area effect: slow enemies within _EMP_RADIUS
            self._apply_emp(ability, target_id, source, targets)
            return

        # Duration-based effects: create ActiveEffect
        if ability.duration > 0:
            self._active_effects.append(ActiveEffect(
                target_id=target_id,
                ability_id=ability.ability_id,
                effect=ability.effect,
                magnitude=ability.magnitude,
                remaining=ability.duration,
            ))

    def _apply_emp(
        self,
        ability: Ability,
        source_id: str,
        source: SimulationTarget,
        targets: dict[str, SimulationTarget],
    ) -> None:
        """Apply EMP burst: slow enemies within radius."""
        sx, sy = source.position
        for tid, target in targets.items():
            if tid == source_id:
                continue
            # Only affect enemies (opposite alliance)
            if target.alliance == source.alliance:
                continue
            if target.alliance == "neutral":
                continue
            # Check distance
            dx = target.position[0] - sx
            dy = target.position[1] - sy
            dist = math.hypot(dx, dy)
            if dist <= _EMP_RADIUS:
                self._active_effects.append(ActiveEffect(
                    target_id=tid,
                    ability_id=ability.ability_id,
                    effect="emp",
                    magnitude=ability.magnitude,
                    remaining=ability.duration,
                ))

    def get_multiplier(self, target_id: str, stat_name: str) -> float:
        """Return the current multiplier for a stat from simplified upgrades.

        Returns 1.0 if no simplified upgrade is active for the stat.
        This is separate from get_stat_modifier which handles the original
        upgrade/ability system.
        """
        unit_upgrades = self._upgrades.get(target_id)
        if unit_upgrades is None:
            return 1.0
        entry = unit_upgrades.get(stat_name)
        if entry is None:
            return 1.0
        return entry["multiplier"]

    # -- Tick ---------------------------------------------------------------

    def tick(self, dt: float, targets: dict[str, SimulationTarget] | None = None) -> None:
        """Update cooldowns, active effects, and timed simplified upgrades.

        Called from the engine tick loop at 10Hz.
        Args:
            dt: Time step.
            targets: Optional dict of targets (for ability effects).
        """
        # Tick timed simplified upgrades
        expired_units: list[str] = []
        for tid, stat_upgrades in self._upgrades.items():
            expired_stats: list[str] = []
            for stat, entry in stat_upgrades.items():
                entry["remaining"] -= dt
                if entry["remaining"] <= 0:
                    expired_stats.append(stat)
            for stat in expired_stats:
                del stat_upgrades[stat]
            if not stat_upgrades:
                expired_units.append(tid)
        for tid in expired_units:
            del self._upgrades[tid]
        # Decrease cooldowns
        expired_keys: list[tuple[str, str]] = []
        for key in self._ability_cooldowns:
            self._ability_cooldowns[key] -= dt
            if self._ability_cooldowns[key] <= 0.0:
                expired_keys.append(key)
        for key in expired_keys:
            del self._ability_cooldowns[key]

        # Decrease active effect durations
        still_active: list[ActiveEffect] = []
        for effect in self._active_effects:
            effect.remaining -= dt
            if effect.remaining > 0:
                still_active.append(effect)
        self._active_effects = still_active

    # -- Stat modifiers -----------------------------------------------------

    def get_stat_modifier(self, target_id: str, stat: str) -> float:
        """Get combined modifier for a stat from all upgrades + active effects.

        For multiplicative stats (speed, weapon_damage, weapon_cooldown,
        max_health, weapon_range): returns the product of all modifiers.
        Default is 1.0 (no change).

        For additive stats (damage_reduction): returns the sum of all
        reduction values. Default is 0.0 (no reduction).
        """
        if stat == "damage_reduction":
            return self._get_damage_reduction(target_id)
        return self._get_multiplicative_modifier(target_id, stat)

    def _get_multiplicative_modifier(self, target_id: str, stat: str) -> float:
        """Compute multiplicative modifier from upgrades + active effects."""
        combined = 1.0

        # Upgrade contributions
        for uid in self._unit_upgrades.get(target_id, []):
            upgrade = self._resolve_upgrade(uid)
            if upgrade is not None and stat in upgrade.stat_modifiers:
                combined *= upgrade.stat_modifiers[stat]

        # Active effect contributions
        for effect in self._active_effects:
            if effect.target_id != target_id:
                continue
            if stat == "speed" and effect.effect == "speed_boost":
                combined *= effect.magnitude
            elif stat == "speed" and effect.effect == "emp":
                combined *= effect.magnitude  # EMP slows (magnitude < 1)
            elif stat == "weapon_cooldown" and effect.effect == "overclock":
                # Overclock: magnitude=3.0 means 3x fire rate = 1/3 cooldown
                combined *= (1.0 / effect.magnitude)

        return combined

    def _get_damage_reduction(self, target_id: str) -> float:
        """Compute additive damage reduction from upgrades + active effects.

        Returns a value between 0.0 and 1.0 (fraction of damage blocked).
        """
        total = 0.0

        # Upgrade contributions (reinforced_chassis)
        for uid in self._unit_upgrades.get(target_id, []):
            upgrade = self._resolve_upgrade(uid)
            if upgrade is not None and "damage_reduction" in upgrade.stat_modifiers:
                total += upgrade.stat_modifiers["damage_reduction"]

        # Active effect contributions (shield)
        for effect in self._active_effects:
            if effect.target_id != target_id:
                continue
            if effect.effect == "shield":
                total += effect.magnitude

        return min(total, 1.0)  # Cap at 100% reduction

    # -- Query active effects -----------------------------------------------

    def get_active_effects(self, target_id: str) -> list[ActiveEffect]:
        """Get currently active effects for a unit."""
        return [e for e in self._active_effects if e.target_id == target_id]

    # -- Listing ------------------------------------------------------------

    def list_upgrades(self) -> list[Upgrade]:
        """List all available upgrades (predefined + custom)."""
        combined: dict[str, Upgrade] = {}
        combined.update(UPGRADES)
        combined.update(self._custom_upgrades)
        return list(combined.values())

    def list_abilities(self) -> list[Ability]:
        """List all available abilities (predefined + custom)."""
        combined: dict[str, Ability] = {}
        combined.update(ABILITIES)
        combined.update(self._custom_abilities)
        return list(combined.values())

    # -- Reset --------------------------------------------------------------

    def reset(self) -> None:
        """Clear all upgrades, abilities, cooldowns, and active effects."""
        self._unit_upgrades.clear()
        self._unit_abilities.clear()
        self._ability_cooldowns.clear()
        self._active_effects.clear()
        self._upgrades.clear()
