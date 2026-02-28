# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the weapon variety system.

Tests cover:
  - Weapon dataclass creation and fields
  - Default weapon loadouts by asset type
  - WeaponSystem assign, get, ammo, reset
  - Ammo consumption and events
  - Backward compatibility
"""

from __future__ import annotations

import dataclasses
import queue
import threading

import pytest

from engine.simulation.target import SimulationTarget
from engine.simulation.weapons import (
    Weapon,
    WeaponSystem,
    _DEFAULT_WEAPONS,
)


class SimpleEventBus:
    """Minimal EventBus for unit testing (same pattern as test_combat.py)."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)

    def subscribe(self, topic: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            if topic is None:
                self._subscribers.setdefault("__all__", []).append(q)
            else:
                self._subscribers.setdefault(topic, []).append(q)
        return q


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Weapon creation and fields
# --------------------------------------------------------------------------

class TestWeaponCreation:
    """Test Weapon dataclass creation and default values."""

    def test_create_basic_weapon(self):
        w = Weapon(name="Test Gun", damage=10.0, weapon_range=15.0, cooldown=2.0)
        assert w.name == "Test Gun"
        assert w.damage == 10.0
        assert w.weapon_range == 15.0
        assert w.cooldown == 2.0

    def test_default_weapon_class(self):
        w = Weapon(name="Test", damage=10.0, weapon_range=15.0, cooldown=2.0)
        assert w.weapon_class == "ballistic"

    def test_default_blast_radius(self):
        w = Weapon(name="Test", damage=10.0, weapon_range=15.0, cooldown=2.0)
        assert w.blast_radius == 0.0

    def test_default_accuracy(self):
        w = Weapon(name="Test", damage=10.0, weapon_range=15.0, cooldown=2.0)
        assert w.accuracy == 0.85

    def test_default_ammo(self):
        w = Weapon(name="Test", damage=10.0, weapon_range=15.0, cooldown=2.0)
        assert w.ammo == 30
        assert w.max_ammo == 30

    def test_custom_fields(self):
        w = Weapon(
            name="Custom", weapon_class="missile",
            damage=40.0, weapon_range=30.0, cooldown=5.0,
            blast_radius=5.0, accuracy=0.8, ammo=4, max_ammo=4,
        )
        assert w.blast_radius == 5.0
        assert w.accuracy == 0.8
        assert w.ammo == 4
        assert w.max_ammo == 4

    def test_aoe_weapon_fields(self):
        w = Weapon(
            name="Tank Cannon", weapon_class="aoe",
            damage=30.0, weapon_range=25.0, cooldown=3.0,
            blast_radius=3.0,
        )
        assert w.weapon_class == "aoe"
        assert w.blast_radius == 3.0

    def test_missile_weapon_class(self):
        w = Weapon(
            name="Missile", weapon_class="missile",
            damage=50.0, weapon_range=35.0, cooldown=5.0,
            accuracy=0.95, ammo=10, max_ammo=10,
        )
        assert w.weapon_class == "missile"


# --------------------------------------------------------------------------
# Predefined default weapons
# --------------------------------------------------------------------------

class TestPredefinedWeapons:
    """Test that default weapon loadouts exist for all expected asset types."""

    def test_default_weapons_has_expected_types(self):
        expected = {"turret", "drone", "rover", "person_hostile", "tank",
                    "apc", "heavy_turret", "missile_turret", "scout_drone"}
        assert set(_DEFAULT_WEAPONS.keys()) == expected

    def test_turret_weapon(self):
        w = _DEFAULT_WEAPONS["turret"]
        assert w.name == "nerf_turret_gun"
        assert w.damage == 15.0
        assert w.weapon_range == 20.0
        assert w.cooldown == 1.5
        assert w.accuracy == 0.9

    def test_drone_weapon(self):
        w = _DEFAULT_WEAPONS["drone"]
        assert w.name == "nerf_dart_gun"
        assert w.damage == 8.0
        assert w.weapon_range == 12.0
        assert w.cooldown == 1.0
        assert w.accuracy == 0.75

    def test_rover_weapon(self):
        w = _DEFAULT_WEAPONS["rover"]
        assert w.name == "nerf_cannon"
        assert w.damage == 12.0
        assert w.weapon_range == 10.0
        assert w.cooldown == 2.0

    def test_person_hostile_weapon(self):
        w = _DEFAULT_WEAPONS["person_hostile"]
        assert w.name == "nerf_pistol"
        assert w.damage == 10.0
        assert w.weapon_range == 8.0
        assert w.accuracy == 0.6

    def test_tank_weapon(self):
        w = _DEFAULT_WEAPONS["tank"]
        assert w.name == "nerf_tank_cannon"
        assert w.damage == 30.0
        assert w.weapon_range == 25.0
        assert w.weapon_class == "aoe"
        assert w.blast_radius == 3.0

    def test_apc_weapon(self):
        w = _DEFAULT_WEAPONS["apc"]
        assert w.name == "nerf_apc_mg"
        assert w.damage == 8.0
        assert w.weapon_range == 15.0
        assert w.cooldown == 1.0

    def test_heavy_turret_weapon(self):
        w = _DEFAULT_WEAPONS["heavy_turret"]
        assert w.name == "nerf_heavy_turret"
        assert w.damage == 25.0
        assert w.weapon_range == 30.0

    def test_missile_turret_weapon(self):
        w = _DEFAULT_WEAPONS["missile_turret"]
        assert w.name == "nerf_missile_launcher"
        assert w.damage == 50.0
        assert w.weapon_range == 35.0
        assert w.weapon_class == "missile"

    def test_scout_drone_weapon(self):
        w = _DEFAULT_WEAPONS["scout_drone"]
        assert w.name == "nerf_scout_gun"
        assert w.damage == 5.0
        assert w.weapon_range == 8.0


# --------------------------------------------------------------------------
# WeaponSystem -- assign, get, reset
# --------------------------------------------------------------------------

class TestWeaponSystemAssign:
    """Test assigning and retrieving weapons."""

    def test_assign_and_get_weapon(self):
        ws = WeaponSystem()
        weapon = Weapon(name="test_gun", damage=10.0, weapon_range=15.0, cooldown=2.0)
        ws.assign_weapon("unit-1", weapon)
        result = ws.get_weapon("unit-1")
        assert result is weapon

    def test_get_weapon_unassigned_returns_none(self):
        ws = WeaponSystem()
        assert ws.get_weapon("unknown-unit") is None

    def test_assign_replaces_previous_weapon(self):
        ws = WeaponSystem()
        w1 = Weapon(name="gun_a", damage=5.0, weapon_range=10.0, cooldown=1.0)
        w2 = Weapon(name="gun_b", damage=15.0, weapon_range=20.0, cooldown=1.5)
        ws.assign_weapon("unit-1", w1)
        ws.assign_weapon("unit-1", w2)
        result = ws.get_weapon("unit-1")
        assert result.name == "gun_b"

    def test_assign_multiple_units(self):
        ws = WeaponSystem()
        w1 = Weapon(name="gun_a", damage=5.0, weapon_range=10.0, cooldown=1.0)
        w2 = Weapon(name="gun_b", damage=15.0, weapon_range=20.0, cooldown=1.5)
        ws.assign_weapon("unit-1", w1)
        ws.assign_weapon("unit-2", w2)
        assert ws.get_weapon("unit-1").name == "gun_a"
        assert ws.get_weapon("unit-2").name == "gun_b"


class TestWeaponSystemDefaultAssignment:
    """Test assign_default_weapon for asset types."""

    def test_assign_default_turret(self):
        ws = WeaponSystem()
        ws.assign_default_weapon("t1", "turret")
        weapon = ws.get_weapon("t1")
        assert weapon is not None
        assert weapon.name == "nerf_turret_gun"

    def test_assign_default_drone(self):
        ws = WeaponSystem()
        ws.assign_default_weapon("d1", "drone")
        weapon = ws.get_weapon("d1")
        assert weapon is not None
        assert weapon.name == "nerf_dart_gun"

    def test_assign_default_rover(self):
        ws = WeaponSystem()
        ws.assign_default_weapon("r1", "rover")
        weapon = ws.get_weapon("r1")
        assert weapon is not None
        assert weapon.name == "nerf_cannon"

    def test_assign_default_hostile_person(self):
        ws = WeaponSystem()
        ws.assign_default_weapon("h1", "person", alliance="hostile")
        weapon = ws.get_weapon("h1")
        assert weapon is not None
        assert weapon.name == "nerf_pistol"

    def test_assign_default_friendly_person_no_weapon(self):
        """Friendly person has no default weapon (not in _DEFAULT_WEAPONS)."""
        ws = WeaponSystem()
        ws.assign_default_weapon("p1", "person", alliance="friendly")
        weapon = ws.get_weapon("p1")
        assert weapon is None

    def test_assign_default_tank(self):
        ws = WeaponSystem()
        ws.assign_default_weapon("t1", "tank")
        weapon = ws.get_weapon("t1")
        assert weapon is not None
        assert weapon.name == "nerf_tank_cannon"

    def test_assign_default_unknown_type_no_weapon(self):
        ws = WeaponSystem()
        ws.assign_default_weapon("x1", "nonexistent")
        weapon = ws.get_weapon("x1")
        assert weapon is None

    def test_default_assignment_creates_copy(self):
        """Each unit should get its own copy, not share state."""
        ws = WeaponSystem()
        ws.assign_default_weapon("t1", "turret")
        ws.assign_default_weapon("t2", "turret")
        w1 = ws.get_weapon("t1")
        w2 = ws.get_weapon("t2")
        assert w1 is not w2
        # Modify one, other unaffected
        w1.ammo = 0
        assert w2.ammo == 100


# --------------------------------------------------------------------------
# WeaponSystem -- ammo tracking
# --------------------------------------------------------------------------

class TestWeaponSystemAmmo:
    """Test ammo tracking via consume_ammo and get_ammo_pct."""

    def test_ammo_pct_full(self):
        ws = WeaponSystem()
        ws.assign_default_weapon("t1", "turret")
        assert ws.get_ammo_pct("t1") == pytest.approx(1.0)

    def test_ammo_pct_after_consumption(self):
        ws = WeaponSystem()
        w = Weapon(name="test", damage=10.0, weapon_range=15.0, cooldown=2.0,
                   ammo=10, max_ammo=10)
        ws.assign_weapon("t1", w)
        ws.consume_ammo("t1")
        assert ws.get_ammo_pct("t1") == pytest.approx(0.9)

    def test_ammo_pct_unassigned_returns_1(self):
        ws = WeaponSystem()
        assert ws.get_ammo_pct("unknown") == pytest.approx(1.0)

    def test_consume_ammo_returns_true_with_ammo(self):
        ws = WeaponSystem()
        w = Weapon(name="test", damage=10.0, weapon_range=15.0, cooldown=2.0,
                   ammo=5, max_ammo=5)
        ws.assign_weapon("t1", w)
        assert ws.consume_ammo("t1") is True
        assert w.ammo == 4

    def test_consume_ammo_returns_false_when_empty(self):
        ws = WeaponSystem()
        w = Weapon(name="test", damage=10.0, weapon_range=15.0, cooldown=2.0,
                   ammo=1, max_ammo=1)
        ws.assign_weapon("t1", w)
        assert ws.consume_ammo("t1") is True  # Last round
        assert ws.consume_ammo("t1") is False  # Empty

    def test_consume_ammo_no_weapon_returns_true(self):
        """No weapon system = infinite ammo (legacy behavior)."""
        ws = WeaponSystem()
        assert ws.consume_ammo("no-weapon-unit") is True


class TestWeaponSystemAmmoEvents:
    """Test ammo-related event bus publications."""

    def test_ammo_depleted_event(self):
        bus = SimpleEventBus()
        ws = WeaponSystem(event_bus=bus)
        sub = bus.subscribe("ammo_depleted")
        w = Weapon(name="test", damage=10.0, weapon_range=15.0, cooldown=2.0,
                   ammo=1, max_ammo=1)
        ws.assign_weapon("t1", w)
        ws.consume_ammo("t1")
        msg = sub.get(timeout=1.0)
        assert msg["target_id"] == "t1"
        assert msg["weapon_name"] == "test"

    def test_ammo_low_event(self):
        bus = SimpleEventBus()
        ws = WeaponSystem(event_bus=bus)
        sub = bus.subscribe("ammo_low")
        w = Weapon(name="test", damage=10.0, weapon_range=15.0, cooldown=2.0,
                   ammo=2, max_ammo=10)
        ws.assign_weapon("t1", w)
        # ammo goes from 2 -> 1, which is 10% < 20% threshold
        ws.consume_ammo("t1")
        msg = sub.get(timeout=1.0)
        assert msg["target_id"] == "t1"
        assert msg["ammo_remaining"] == 1


# --------------------------------------------------------------------------
# WeaponSystem -- reset
# --------------------------------------------------------------------------

class TestWeaponReset:
    """Test clearing all weapon assignments."""

    def test_reset_clears_all(self):
        ws = WeaponSystem()
        ws.assign_default_weapon("t1", "turret")
        ws.assign_default_weapon("t2", "drone")
        ws.reset()
        assert ws.get_weapon("t1") is None
        assert ws.get_weapon("t2") is None

    def test_reset_clears_ammo_pct(self):
        ws = WeaponSystem()
        w = Weapon(name="test", damage=10.0, weapon_range=15.0, cooldown=2.0,
                   ammo=5, max_ammo=5)
        ws.assign_weapon("t1", w)
        ws.consume_ammo("t1")
        ws.reset()
        # After reset, no weapon assigned -> get_ammo_pct returns 1.0
        assert ws.get_ammo_pct("t1") == pytest.approx(1.0)


# --------------------------------------------------------------------------
# CombatStats weapon_id integration
# --------------------------------------------------------------------------

class TestCombatStatsWeaponId:
    """Test that CombatStats has a weapon_id field."""

    def test_combat_stats_default_weapon_id(self):
        from engine.units.base import CombatStats
        cs = CombatStats(
            health=100, max_health=100,
            weapon_range=15.0, weapon_cooldown=2.0, weapon_damage=10,
            is_combatant=True,
        )
        assert cs.weapon_id == ""

    def test_combat_stats_custom_weapon_id(self):
        from engine.units.base import CombatStats
        cs = CombatStats(
            health=100, max_health=100,
            weapon_range=15.0, weapon_cooldown=2.0, weapon_damage=10,
            is_combatant=True, weapon_id="turret_cannon",
        )
        assert cs.weapon_id == "turret_cannon"


# --------------------------------------------------------------------------
# Backward compatibility -- combat works without WeaponSystem
# --------------------------------------------------------------------------

class TestBackwardCompat:
    """Combat system should work without WeaponSystem involvement."""

    def test_combat_works_without_weapon_system(self):
        """Existing behavior: CombatSystem uses source target fields for damage/speed."""
        from engine.simulation.combat import CombatSystem

        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(1.0, 0.0), health=100.0,
        )

        proj = combat.fire(source, target)
        assert proj is not None
        assert proj.damage == 15.0
        assert proj.speed == 80.0  # Projectile speed

        targets = {"t1": source, "h1": target}
        combat.tick(0.1, targets)
        assert target.health == 85.0

    def test_combat_without_weapon_system_uses_default_speed(self):
        """Without weapon_system, projectile speed should be 80.0."""
        from engine.simulation.combat import CombatSystem

        bus = SimpleEventBus()
        combat = CombatSystem(bus)

        source = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            weapon_range=20.0, weapon_damage=15.0,
            weapon_cooldown=1.0, last_fired=0.0,
        )
        target = SimulationTarget(
            target_id="h1", name="Hostile", alliance="hostile",
            asset_type="person", position=(10.0, 0.0), health=100.0,
        )

        proj = combat.fire(source, target)
        assert proj.speed == 80.0
