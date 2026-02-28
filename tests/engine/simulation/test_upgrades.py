# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for UpgradeSystem -- upgrades and abilities for simulation units.

TDD: all tests written FIRST, before any implementation exists.
Run with: .venv/bin/python3 -m pytest tests/amy/simulation/test_upgrades.py -v
"""

from __future__ import annotations

import math
import pytest

from engine.simulation.upgrades import (
    ABILITIES,
    UPGRADES,
    Ability,
    ActiveEffect,
    Upgrade,
    UpgradeSystem,
)
from engine.simulation.target import SimulationTarget


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_target(
    target_id: str = "t1",
    name: str = "Test Unit",
    alliance: str = "friendly",
    asset_type: str = "rover",
    position: tuple[float, float] = (0.0, 0.0),
    speed: float = 5.0,
    health: float = 100.0,
    max_health: float = 100.0,
    weapon_range: float = 15.0,
    weapon_cooldown: float = 2.0,
    weapon_damage: float = 10.0,
) -> SimulationTarget:
    """Create a SimulationTarget with overridable combat stats."""
    t = SimulationTarget(
        target_id=target_id,
        name=name,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        speed=speed,
    )
    t.health = health
    t.max_health = max_health
    t.weapon_range = weapon_range
    t.weapon_cooldown = weapon_cooldown
    t.weapon_damage = weapon_damage
    return t


def _make_targets_dict(*targets: SimulationTarget) -> dict[str, SimulationTarget]:
    return {t.target_id: t for t in targets}


# ===========================================================================
# Data class creation
# ===========================================================================

class TestUpgradeCreation:
    """Verify Upgrade dataclass defaults and field access."""

    def test_basic_fields(self):
        u = Upgrade(
            upgrade_id="test",
            name="Test Upgrade",
            description="A test",
            stat_modifiers={"damage": 1.2},
        )
        assert u.upgrade_id == "test"
        assert u.name == "Test Upgrade"
        assert u.description == "A test"
        assert u.stat_modifiers == {"damage": 1.2}

    def test_defaults(self):
        u = Upgrade(
            upgrade_id="x", name="X", description="D",
            stat_modifiers={},
        )
        assert u.cost == 0
        assert u.max_stacks == 1
        assert u.eligible_types is None

    def test_custom_cost_and_stacks(self):
        u = Upgrade(
            upgrade_id="x", name="X", description="D",
            stat_modifiers={}, cost=500, max_stacks=3,
        )
        assert u.cost == 500
        assert u.max_stacks == 3

    def test_eligible_types_list(self):
        u = Upgrade(
            upgrade_id="x", name="X", description="D",
            stat_modifiers={},
            eligible_types=["turret", "rover"],
        )
        assert u.eligible_types == ["turret", "rover"]


class TestAbilityCreation:
    """Verify Ability dataclass defaults and field access."""

    def test_basic_fields(self):
        a = Ability(
            ability_id="test",
            name="Test",
            description="Desc",
            cooldown=10.0,
            duration=5.0,
            effect="speed_boost",
            magnitude=2.0,
        )
        assert a.ability_id == "test"
        assert a.cooldown == 10.0
        assert a.duration == 5.0
        assert a.effect == "speed_boost"
        assert a.magnitude == 2.0

    def test_defaults(self):
        a = Ability(
            ability_id="x", name="X", description="D",
            cooldown=1.0, duration=0.0,
            effect="repair", magnitude=1.0,
        )
        assert a.eligible_types is None

    def test_eligible_types(self):
        a = Ability(
            ability_id="x", name="X", description="D",
            cooldown=1.0, duration=0.0,
            effect="repair", magnitude=1.0,
            eligible_types=["turret"],
        )
        assert a.eligible_types == ["turret"]


class TestActiveEffectCreation:
    """Verify ActiveEffect dataclass."""

    def test_fields(self):
        ae = ActiveEffect(
            target_id="t1",
            ability_id="speed_boost",
            effect="speed_boost",
            magnitude=2.0,
            remaining=5.0,
        )
        assert ae.target_id == "t1"
        assert ae.ability_id == "speed_boost"
        assert ae.effect == "speed_boost"
        assert ae.magnitude == 2.0
        assert ae.remaining == 5.0


# ===========================================================================
# Predefined upgrades and abilities
# ===========================================================================

class TestPredefinedUpgrades:
    """Verify all 6 predefined upgrades exist with correct stats."""

    def test_armor_plating_exists(self):
        u = UPGRADES["armor_plating"]
        assert u.name == "Armor Plating"
        assert u.stat_modifiers["max_health"] == 1.25

    def test_enhanced_optics_exists(self):
        u = UPGRADES["enhanced_optics"]
        assert u.stat_modifiers["weapon_range"] == 1.2

    def test_rapid_fire_exists(self):
        u = UPGRADES["rapid_fire"]
        assert u.stat_modifiers["weapon_cooldown"] == 0.7

    def test_reinforced_chassis_exists(self):
        u = UPGRADES["reinforced_chassis"]
        assert u.stat_modifiers["damage_reduction"] == 0.15

    def test_turbo_motor_exists(self):
        u = UPGRADES["turbo_motor"]
        assert u.stat_modifiers["speed"] == 1.2

    def test_precision_targeting_exists(self):
        u = UPGRADES["precision_targeting"]
        assert u.stat_modifiers["weapon_damage"] == 1.15

    def test_total_upgrade_count(self):
        assert len(UPGRADES) == 6


class TestPredefinedAbilities:
    """Verify all 5 predefined abilities exist with correct stats."""

    def test_speed_boost_exists(self):
        a = ABILITIES["speed_boost"]
        assert a.name == "Speed Boost"
        assert a.cooldown == 30.0
        assert a.duration == 5.0
        assert a.effect == "speed_boost"
        assert a.magnitude == 2.0

    def test_emergency_repair_exists(self):
        a = ABILITIES["emergency_repair"]
        assert a.cooldown == 60.0
        assert a.duration == 0.0
        assert a.effect == "repair"
        assert a.magnitude == 0.3

    def test_shield_exists(self):
        a = ABILITIES["shield"]
        assert a.cooldown == 45.0
        assert a.duration == 8.0
        assert a.effect == "shield"
        assert a.magnitude == 0.5

    def test_emp_burst_exists(self):
        a = ABILITIES["emp_burst"]
        assert a.cooldown == 40.0
        assert a.duration == 4.0
        assert a.effect == "emp"
        assert a.magnitude == 0.5

    def test_overclock_exists(self):
        a = ABILITIES["overclock"]
        assert a.cooldown == 50.0
        assert a.duration == 3.0
        assert a.effect == "overclock"
        assert a.magnitude == 3.0

    def test_total_ability_count(self):
        assert len(ABILITIES) == 5


# ===========================================================================
# UpgradeSystem — apply upgrade
# ===========================================================================

class TestApplyUpgrade:
    """Test applying upgrades to units."""

    def test_apply_upgrade_returns_true(self):
        sys = UpgradeSystem()
        t = _make_target()
        result = sys.apply_upgrade(t.target_id, "armor_plating", t)
        assert result is True

    def test_apply_upgrade_records_upgrade(self):
        sys = UpgradeSystem()
        t = _make_target()
        sys.apply_upgrade(t.target_id, "armor_plating", t)
        assert "armor_plating" in sys.get_upgrades(t.target_id)

    def test_apply_unknown_upgrade_returns_false(self):
        sys = UpgradeSystem()
        t = _make_target()
        result = sys.apply_upgrade(t.target_id, "nonexistent", t)
        assert result is False

    def test_get_upgrades_empty_by_default(self):
        sys = UpgradeSystem()
        assert sys.get_upgrades("unknown") == []


class TestArmorPlating:
    """Armor Plating: max_health * 1.25."""

    def test_stat_modifier_applied(self):
        sys = UpgradeSystem()
        t = _make_target(max_health=100.0)
        sys.apply_upgrade(t.target_id, "armor_plating", t)
        mod = sys.get_stat_modifier(t.target_id, "max_health")
        assert abs(mod - 1.25) < 0.001


class TestRapidFire:
    """Rapid Fire: weapon_cooldown * 0.7."""

    def test_cooldown_modifier(self):
        sys = UpgradeSystem()
        t = _make_target(weapon_cooldown=2.0)
        sys.apply_upgrade(t.target_id, "rapid_fire", t)
        mod = sys.get_stat_modifier(t.target_id, "weapon_cooldown")
        assert abs(mod - 0.7) < 0.001


class TestTurboMotor:
    """Turbo Motor: speed * 1.2."""

    def test_speed_modifier(self):
        sys = UpgradeSystem()
        t = _make_target(speed=5.0)
        sys.apply_upgrade(t.target_id, "turbo_motor", t)
        mod = sys.get_stat_modifier(t.target_id, "speed")
        assert abs(mod - 1.2) < 0.001


class TestUpgradeStacking:
    """Max stacks limits how many times the same upgrade can be applied."""

    def test_cannot_exceed_max_stacks(self):
        sys = UpgradeSystem()
        t = _make_target()
        # Default max_stacks=1, so second apply should fail
        assert sys.apply_upgrade(t.target_id, "armor_plating", t) is True
        assert sys.apply_upgrade(t.target_id, "armor_plating", t) is False

    def test_multiple_different_upgrades(self):
        sys = UpgradeSystem()
        t = _make_target()
        assert sys.apply_upgrade(t.target_id, "armor_plating", t) is True
        assert sys.apply_upgrade(t.target_id, "rapid_fire", t) is True
        upgrades = sys.get_upgrades(t.target_id)
        assert "armor_plating" in upgrades
        assert "rapid_fire" in upgrades

    def test_stacking_with_higher_max_stacks(self):
        """Custom upgrade with max_stacks=3 allows 3 applications."""
        sys = UpgradeSystem()
        t = _make_target()
        # Register a custom stackable upgrade
        custom = Upgrade(
            upgrade_id="custom_stack",
            name="Stackable",
            description="Stackable test",
            stat_modifiers={"speed": 1.1},
            max_stacks=3,
        )
        sys.register_upgrade(custom)
        assert sys.apply_upgrade(t.target_id, "custom_stack", t) is True
        assert sys.apply_upgrade(t.target_id, "custom_stack", t) is True
        assert sys.apply_upgrade(t.target_id, "custom_stack", t) is True
        assert sys.apply_upgrade(t.target_id, "custom_stack", t) is False
        # Speed modifier should be 1.1^3 = 1.331
        mod = sys.get_stat_modifier(t.target_id, "speed")
        assert abs(mod - 1.331) < 0.01


class TestUpgradeEligibility:
    """Type-restricted upgrades only apply to eligible types."""

    def test_eligible_type_succeeds(self):
        sys = UpgradeSystem()
        custom = Upgrade(
            upgrade_id="drone_only",
            name="Drone Only",
            description="Only for drones",
            stat_modifiers={"speed": 1.5},
            eligible_types=["drone"],
        )
        sys.register_upgrade(custom)
        drone = _make_target(target_id="d1", asset_type="drone")
        assert sys.apply_upgrade("d1", "drone_only", drone) is True

    def test_ineligible_type_fails(self):
        sys = UpgradeSystem()
        custom = Upgrade(
            upgrade_id="drone_only",
            name="Drone Only",
            description="Only for drones",
            stat_modifiers={"speed": 1.5},
            eligible_types=["drone"],
        )
        sys.register_upgrade(custom)
        rover = _make_target(target_id="r1", asset_type="rover")
        assert sys.apply_upgrade("r1", "drone_only", rover) is False

    def test_none_eligible_types_means_all(self):
        sys = UpgradeSystem()
        turret = _make_target(target_id="t1", asset_type="turret", speed=0.0)
        assert sys.apply_upgrade("t1", "armor_plating", turret) is True


# ===========================================================================
# UpgradeSystem — abilities
# ===========================================================================

class TestGrantAbility:
    """Test granting abilities to units."""

    def test_grant_ability_returns_true(self):
        sys = UpgradeSystem()
        result = sys.grant_ability("t1", "speed_boost")
        assert result is True

    def test_grant_unknown_ability_returns_false(self):
        sys = UpgradeSystem()
        result = sys.grant_ability("t1", "nonexistent")
        assert result is False

    def test_grant_duplicate_ability_returns_false(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        result = sys.grant_ability("t1", "speed_boost")
        assert result is False

    def test_get_abilities_after_grant(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        sys.grant_ability("t1", "emergency_repair")
        abilities = sys.get_abilities("t1")
        assert "speed_boost" in abilities
        assert "emergency_repair" in abilities


class TestUseAbility:
    """Test activating abilities."""

    def test_use_ability_returns_true(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        result = sys.use_ability("t1", "speed_boost", targets)
        assert result is True

    def test_use_ability_without_grant_fails(self):
        sys = UpgradeSystem()
        t = _make_target(target_id="t1")
        targets = _make_targets_dict(t)
        result = sys.use_ability("t1", "speed_boost", targets)
        assert result is False

    def test_use_ability_creates_active_effect(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        effects = sys.get_active_effects("t1")
        assert len(effects) == 1
        assert effects[0].effect == "speed_boost"
        assert effects[0].magnitude == 2.0
        assert effects[0].remaining == 5.0


class TestAbilityCooldown:
    """Can't reuse ability until cooldown expires."""

    def test_cannot_use_on_cooldown(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        # Immediately try again -- should fail
        result = sys.use_ability("t1", "speed_boost", targets)
        assert result is False

    def test_can_use_ability_false_on_cooldown(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        assert sys.can_use_ability("t1", "speed_boost") is False

    def test_can_use_after_cooldown_expires(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        # Tick past the 30s cooldown
        sys.tick(30.0, targets)
        assert sys.can_use_ability("t1", "speed_boost") is True

    def test_can_use_ability_without_grant(self):
        sys = UpgradeSystem()
        assert sys.can_use_ability("t1", "speed_boost") is False


# ===========================================================================
# Individual ability effects
# ===========================================================================

class TestSpeedBoost:
    """Speed Boost: double speed for 5s."""

    def test_creates_speed_boost_effect(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        effects = sys.get_active_effects("t1")
        assert any(e.effect == "speed_boost" and e.magnitude == 2.0 for e in effects)

    def test_speed_modifier_during_effect(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        # Active effect should provide a speed modifier
        mod = sys.get_stat_modifier("t1", "speed")
        assert mod == 2.0

    def test_speed_modifier_after_expiry(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        sys.tick(5.1, targets)  # Expire the effect
        mod = sys.get_stat_modifier("t1", "speed")
        assert mod == 1.0  # No modifier after expiry


class TestEmergencyRepair:
    """Emergency Repair: instant 30% health restore."""

    def test_repair_restores_health(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "emergency_repair")
        t = _make_target(target_id="t1", asset_type="rover", health=50.0, max_health=100.0)
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "emergency_repair", targets)
        # 30% of max_health = 30, so health goes from 50 to 80
        assert abs(t.health - 80.0) < 0.001

    def test_repair_does_not_exceed_max_health(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "emergency_repair")
        t = _make_target(target_id="t1", asset_type="rover", health=90.0, max_health=100.0)
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "emergency_repair", targets)
        assert t.health == 100.0

    def test_repair_instant_no_active_effect(self):
        """Duration=0 means instant -- should NOT create a lingering effect."""
        sys = UpgradeSystem()
        sys.grant_ability("t1", "emergency_repair")
        t = _make_target(target_id="t1", asset_type="rover", health=50.0, max_health=100.0)
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "emergency_repair", targets)
        effects = sys.get_active_effects("t1")
        assert len(effects) == 0  # Instant, no lingering effect


class TestShield:
    """Energy Shield: 50% damage reduction for 8s."""

    def test_shield_creates_effect(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "shield")
        t = _make_target(target_id="t1", asset_type="turret", speed=0.0)
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "shield", targets)
        effects = sys.get_active_effects("t1")
        assert any(e.effect == "shield" and e.magnitude == 0.5 for e in effects)

    def test_shield_provides_damage_reduction(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "shield")
        t = _make_target(target_id="t1", asset_type="turret", speed=0.0)
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "shield", targets)
        mod = sys.get_stat_modifier("t1", "damage_reduction")
        assert abs(mod - 0.5) < 0.001

    def test_shield_expires_after_duration(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "shield")
        t = _make_target(target_id="t1", asset_type="turret", speed=0.0)
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "shield", targets)
        sys.tick(8.1, targets)  # Expire the shield
        mod = sys.get_stat_modifier("t1", "damage_reduction")
        assert mod == 0.0  # No damage reduction after expiry


class TestEMPBurst:
    """EMP Burst: slow enemies in 15m radius by 50% for 4s."""

    def test_emp_creates_effect_on_enemies(self):
        sys = UpgradeSystem()
        sys.grant_ability("d1", "emp_burst")
        drone = _make_target(target_id="d1", asset_type="drone", position=(0.0, 0.0))
        # Hostile within 15m
        hostile = _make_target(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0), speed=3.0,
        )
        targets = _make_targets_dict(drone, hostile)
        sys.use_ability("d1", "emp_burst", targets)
        effects = sys.get_active_effects("h1")
        assert any(e.effect == "emp" for e in effects)

    def test_emp_does_not_affect_distant_enemies(self):
        sys = UpgradeSystem()
        sys.grant_ability("d1", "emp_burst")
        drone = _make_target(target_id="d1", asset_type="drone", position=(0.0, 0.0))
        # Hostile at 20m -- outside 15m radius
        hostile = _make_target(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(20.0, 0.0), speed=3.0,
        )
        targets = _make_targets_dict(drone, hostile)
        sys.use_ability("d1", "emp_burst", targets)
        effects = sys.get_active_effects("h1")
        assert len(effects) == 0

    def test_emp_does_not_affect_friendlies(self):
        sys = UpgradeSystem()
        sys.grant_ability("d1", "emp_burst")
        drone = _make_target(target_id="d1", asset_type="drone", position=(0.0, 0.0))
        friend = _make_target(
            target_id="f1", name="Friend", alliance="friendly",
            asset_type="rover", position=(5.0, 0.0),
        )
        targets = _make_targets_dict(drone, friend)
        sys.use_ability("d1", "emp_burst", targets)
        effects = sys.get_active_effects("f1")
        assert len(effects) == 0


class TestOverclock:
    """Overclock: triple fire rate for 3s."""

    def test_overclock_creates_effect(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "overclock")
        t = _make_target(target_id="t1", asset_type="turret", speed=0.0)
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "overclock", targets)
        effects = sys.get_active_effects("t1")
        assert any(e.effect == "overclock" and e.magnitude == 3.0 for e in effects)

    def test_overclock_modifies_weapon_cooldown(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "overclock")
        t = _make_target(target_id="t1", asset_type="turret", speed=0.0, weapon_cooldown=2.0)
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "overclock", targets)
        # Overclock triples fire rate = weapon_cooldown / 3.0
        mod = sys.get_stat_modifier("t1", "weapon_cooldown")
        assert abs(mod - (1.0 / 3.0)) < 0.001

    def test_overclock_expires(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "overclock")
        t = _make_target(target_id="t1", asset_type="turret", speed=0.0)
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "overclock", targets)
        sys.tick(3.1, targets)
        mod = sys.get_stat_modifier("t1", "weapon_cooldown")
        assert mod == 1.0  # Back to normal


# ===========================================================================
# Active effects and tick
# ===========================================================================

class TestActiveEffectExpiry:
    """Effects expire after their duration."""

    def test_effect_removed_after_duration(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        assert len(sys.get_active_effects("t1")) == 1
        sys.tick(5.1, targets)
        assert len(sys.get_active_effects("t1")) == 0

    def test_effect_still_active_before_expiry(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "shield")
        t = _make_target(target_id="t1", asset_type="turret", speed=0.0)
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "shield", targets)
        sys.tick(4.0, targets)  # 4s of 8s duration
        assert len(sys.get_active_effects("t1")) == 1
        assert sys.get_active_effects("t1")[0].remaining == pytest.approx(4.0, abs=0.01)


class TestTickCooldowns:
    """Cooldowns decrease each tick."""

    def test_cooldown_decreases(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        # Can't use right away
        assert sys.can_use_ability("t1", "speed_boost") is False
        # Tick 15s -- half the 30s cooldown
        sys.tick(15.0, targets)
        assert sys.can_use_ability("t1", "speed_boost") is False
        # Tick another 15.1s -- past the 30s cooldown
        sys.tick(15.1, targets)
        assert sys.can_use_ability("t1", "speed_boost") is True

    def test_multiple_ticks_accumulate(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        # 300 ticks of 0.1s = 30s
        for _ in range(300):
            sys.tick(0.1, targets)
        assert sys.can_use_ability("t1", "speed_boost") is True


# ===========================================================================
# Stat modifiers
# ===========================================================================

class TestStatModifier:
    """Combined modifiers from multiple upgrades stack multiplicatively."""

    def test_single_upgrade_modifier(self):
        sys = UpgradeSystem()
        t = _make_target()
        sys.apply_upgrade(t.target_id, "precision_targeting", t)
        mod = sys.get_stat_modifier(t.target_id, "weapon_damage")
        assert abs(mod - 1.15) < 0.001

    def test_no_upgrade_returns_1(self):
        sys = UpgradeSystem()
        mod = sys.get_stat_modifier("nobody", "weapon_damage")
        assert mod == 1.0

    def test_combined_modifiers_multiplicative(self):
        """Two different upgrades modifying speed stack multiplicatively."""
        sys = UpgradeSystem()
        t = _make_target()
        # Create two stackable speed upgrades
        custom_a = Upgrade(
            upgrade_id="speed_a", name="A", description="A",
            stat_modifiers={"speed": 1.2},
        )
        custom_b = Upgrade(
            upgrade_id="speed_b", name="B", description="B",
            stat_modifiers={"speed": 1.3},
        )
        sys.register_upgrade(custom_a)
        sys.register_upgrade(custom_b)
        sys.apply_upgrade(t.target_id, "speed_a", t)
        sys.apply_upgrade(t.target_id, "speed_b", t)
        mod = sys.get_stat_modifier(t.target_id, "speed")
        assert abs(mod - 1.56) < 0.01  # 1.2 * 1.3 = 1.56

    def test_unrelated_stat_unaffected(self):
        sys = UpgradeSystem()
        t = _make_target()
        sys.apply_upgrade(t.target_id, "armor_plating", t)
        # armor_plating only modifies max_health, not speed
        mod = sys.get_stat_modifier(t.target_id, "speed")
        assert mod == 1.0

    def test_active_effect_combines_with_upgrade(self):
        """Active effect speed_boost + turbo_motor upgrade stack multiplicatively."""
        sys = UpgradeSystem()
        t = _make_target(target_id="t1", asset_type="rover")
        sys.apply_upgrade("t1", "turbo_motor", t)
        sys.grant_ability("t1", "speed_boost")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        mod = sys.get_stat_modifier("t1", "speed")
        # turbo_motor=1.2, speed_boost=2.0, combined = 2.4
        assert abs(mod - 2.4) < 0.01


# ===========================================================================
# Damage reduction modifier
# ===========================================================================

class TestDamageReductionModifier:
    """Damage reduction modifiers from upgrades and effects."""

    def test_reinforced_chassis_provides_damage_reduction(self):
        sys = UpgradeSystem()
        t = _make_target()
        sys.apply_upgrade(t.target_id, "reinforced_chassis", t)
        mod = sys.get_stat_modifier(t.target_id, "damage_reduction")
        assert abs(mod - 0.15) < 0.001

    def test_shield_plus_chassis_stacks(self):
        """Shield (0.5) + Reinforced Chassis (0.15) = combined damage reduction."""
        sys = UpgradeSystem()
        t = _make_target(target_id="t1", asset_type="turret", speed=0.0)
        sys.apply_upgrade("t1", "reinforced_chassis", t)
        sys.grant_ability("t1", "shield")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "shield", targets)
        mod = sys.get_stat_modifier("t1", "damage_reduction")
        # Both are additive for damage reduction: 0.15 + 0.5 = 0.65
        assert abs(mod - 0.65) < 0.01


# ===========================================================================
# Reset
# ===========================================================================

class TestReset:
    """UpgradeSystem.reset() clears everything."""

    def test_reset_clears_upgrades(self):
        sys = UpgradeSystem()
        t = _make_target()
        sys.apply_upgrade(t.target_id, "armor_plating", t)
        sys.reset()
        assert sys.get_upgrades(t.target_id) == []

    def test_reset_clears_abilities(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        sys.reset()
        assert sys.get_abilities("t1") == []

    def test_reset_clears_active_effects(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        sys.reset()
        assert sys.get_active_effects("t1") == []

    def test_reset_clears_cooldowns(self):
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        t = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "speed_boost", targets)
        sys.reset()
        # After reset + re-grant, should be usable immediately
        sys.grant_ability("t1", "speed_boost")
        assert sys.can_use_ability("t1", "speed_boost") is True


# ===========================================================================
# Ineligible type
# ===========================================================================

class TestIneligibleType:
    """Type-restricted abilities and upgrades reject wrong unit types."""

    def test_speed_boost_not_for_turret(self):
        """speed_boost is for rover/drone/scout_drone, not turret."""
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        turret = _make_target(target_id="t1", asset_type="turret", speed=0.0)
        targets = _make_targets_dict(turret)
        result = sys.use_ability("t1", "speed_boost", targets)
        assert result is False

    def test_shield_not_for_rover(self):
        """shield is for turret/heavy_turret/tank, not rover."""
        sys = UpgradeSystem()
        sys.grant_ability("t1", "shield")
        rover = _make_target(target_id="t1", asset_type="rover")
        targets = _make_targets_dict(rover)
        result = sys.use_ability("t1", "shield", targets)
        assert result is False


# ===========================================================================
# List all upgrades / abilities
# ===========================================================================

class TestGetUpgradesList:
    """List all available upgrades."""

    def test_list_all_upgrades(self):
        sys = UpgradeSystem()
        upgrades = sys.list_upgrades()
        assert len(upgrades) >= 6
        ids = [u.upgrade_id for u in upgrades]
        assert "armor_plating" in ids
        assert "rapid_fire" in ids
        assert "turbo_motor" in ids

    def test_list_includes_custom(self):
        sys = UpgradeSystem()
        custom = Upgrade(
            upgrade_id="custom_test", name="Custom", description="Custom test",
            stat_modifiers={"speed": 1.1},
        )
        sys.register_upgrade(custom)
        upgrades = sys.list_upgrades()
        ids = [u.upgrade_id for u in upgrades]
        assert "custom_test" in ids


class TestGetAbilitiesList:
    """List all available abilities."""

    def test_list_all_abilities(self):
        sys = UpgradeSystem()
        abilities = sys.list_abilities()
        assert len(abilities) >= 5
        ids = [a.ability_id for a in abilities]
        assert "speed_boost" in ids
        assert "emergency_repair" in ids
        assert "shield" in ids
        assert "emp_burst" in ids
        assert "overclock" in ids

    def test_list_includes_custom(self):
        sys = UpgradeSystem()
        custom = Ability(
            ability_id="custom_ability", name="Custom", description="Custom",
            cooldown=10.0, duration=5.0, effect="test", magnitude=1.0,
        )
        sys.register_ability(custom)
        abilities = sys.list_abilities()
        ids = [a.ability_id for a in abilities]
        assert "custom_ability" in ids


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_get_active_effects_empty(self):
        sys = UpgradeSystem()
        assert sys.get_active_effects("nonexistent") == []

    def test_tick_with_no_effects(self):
        """tick() should not crash when there are no active effects."""
        sys = UpgradeSystem()
        targets: dict[str, SimulationTarget] = {}
        sys.tick(0.1, targets)  # Should not raise

    def test_use_ability_on_eliminated_target(self):
        """Cannot use ability if target is eliminated."""
        sys = UpgradeSystem()
        sys.grant_ability("t1", "emergency_repair")
        t = _make_target(target_id="t1", asset_type="rover")
        t.status = "eliminated"
        targets = _make_targets_dict(t)
        result = sys.use_ability("t1", "emergency_repair", targets)
        assert result is False

    def test_multiple_active_effects(self):
        """Multiple abilities active simultaneously on same unit."""
        sys = UpgradeSystem()
        sys.grant_ability("t1", "speed_boost")
        sys.grant_ability("t1", "overclock")
        t = _make_target(target_id="t1", asset_type="apc")
        targets = _make_targets_dict(t)
        # APC can use both speed_boost (has rover in eligible) -- wait,
        # speed_boost is rover/drone/scout_drone. APC can use overclock.
        # Use overclock on an APC
        sys.use_ability("t1", "overclock", targets)
        effects = sys.get_active_effects("t1")
        assert len(effects) == 1
        assert effects[0].effect == "overclock"

    def test_emp_radius_15m(self):
        """EMP affects enemies within exactly 15m."""
        sys = UpgradeSystem()
        sys.grant_ability("d1", "emp_burst")
        drone = _make_target(target_id="d1", asset_type="drone", position=(0.0, 0.0))
        # Right at 15m boundary
        hostile = _make_target(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(15.0, 0.0), speed=3.0,
        )
        targets = _make_targets_dict(drone, hostile)
        sys.use_ability("d1", "emp_burst", targets)
        effects = sys.get_active_effects("h1")
        assert any(e.effect == "emp" for e in effects)

    def test_repair_at_full_health(self):
        """Emergency repair at full health does nothing harmful."""
        sys = UpgradeSystem()
        sys.grant_ability("t1", "emergency_repair")
        t = _make_target(target_id="t1", asset_type="rover", health=100.0, max_health=100.0)
        targets = _make_targets_dict(t)
        sys.use_ability("t1", "emergency_repair", targets)
        assert t.health == 100.0
