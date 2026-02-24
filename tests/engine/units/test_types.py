"""Tests for every individual unit type definition."""

from __future__ import annotations

import pytest

from engine.units import all_types, get_type
from engine.units.base import CombatStats, MovementCategory


pytestmark = pytest.mark.unit


class TestAllTypesSanity:
    """Common invariants every type must satisfy."""

    def test_every_type_has_non_empty_type_id(self):
        for cls in all_types():
            assert isinstance(cls.type_id, str)
            assert len(cls.type_id) > 0

    def test_every_type_has_display_name(self):
        for cls in all_types():
            assert isinstance(cls.display_name, str)
            assert len(cls.display_name) > 0

    def test_every_type_has_single_char_icon(self):
        for cls in all_types():
            assert isinstance(cls.icon, str)
            assert len(cls.icon) == 1, f"{cls.type_id} icon={cls.icon!r}"

    def test_every_type_has_combat_stats(self):
        for cls in all_types():
            assert isinstance(cls.combat, CombatStats), f"{cls.type_id} missing combat"

    def test_every_type_has_positive_vision(self):
        for cls in all_types():
            assert cls.vision_radius > 0, f"{cls.type_id} vision={cls.vision_radius}"

    def test_every_type_has_valid_category(self):
        for cls in all_types():
            assert isinstance(cls.category, MovementCategory)

    def test_combatant_types_have_positive_stats(self):
        for cls in all_types():
            if cls.combat.is_combatant:
                assert cls.combat.weapon_range > 0, f"{cls.type_id} range=0"
                assert cls.combat.weapon_cooldown > 0, f"{cls.type_id} cooldown=0"
                assert cls.combat.weapon_damage > 0, f"{cls.type_id} damage=0"

    def test_non_combatant_types_have_zero_damage(self):
        for cls in all_types():
            if not cls.combat.is_combatant:
                assert cls.combat.weapon_damage == 0, (
                    f"{cls.type_id} non-combatant but damage={cls.combat.weapon_damage}"
                )

    def test_stationary_types_have_zero_speed(self):
        for cls in all_types():
            if cls.category is MovementCategory.STATIONARY:
                assert cls.speed == 0.0, f"{cls.type_id} stationary but speed={cls.speed}"


class TestRover:
    def test_type_id(self):
        assert get_type("rover").type_id == "rover"

    def test_category(self):
        assert get_type("rover").category is MovementCategory.GROUND

    def test_speed(self):
        assert get_type("rover").speed == 2.0

    def test_drain_rate(self):
        assert get_type("rover").drain_rate == 0.001

    def test_health(self):
        assert get_type("rover").combat.health == 150

    def test_weapon_range(self):
        assert get_type("rover").combat.weapon_range == 10.0

    def test_weapon_damage(self):
        assert get_type("rover").combat.weapon_damage == 12

    def test_icon(self):
        assert get_type("rover").icon == "R"

    def test_vision(self):
        assert get_type("rover").vision_radius == 40.0

    def test_placeable(self):
        assert get_type("rover").placeable is True


class TestDrone:
    def test_type_id(self):
        assert get_type("drone").type_id == "drone"

    def test_category(self):
        assert get_type("drone").category is MovementCategory.AIR

    def test_speed(self):
        assert get_type("drone").speed == 4.0

    def test_drain_rate(self):
        assert get_type("drone").drain_rate == 0.002

    def test_health(self):
        assert get_type("drone").combat.health == 60

    def test_weapon_range(self):
        assert get_type("drone").combat.weapon_range == 12.0

    def test_weapon_damage(self):
        assert get_type("drone").combat.weapon_damage == 8

    def test_icon(self):
        assert get_type("drone").icon == "D"

    def test_vision(self):
        assert get_type("drone").vision_radius == 60.0


class TestScoutDrone:
    def test_type_id(self):
        assert get_type("scout_drone").type_id == "scout_drone"

    def test_category(self):
        assert get_type("scout_drone").category is MovementCategory.AIR

    def test_speed(self):
        assert get_type("scout_drone").speed == 5.0

    def test_drain_rate(self):
        assert get_type("scout_drone").drain_rate == 0.0025

    def test_health(self):
        assert get_type("scout_drone").combat.health == 40

    def test_weapon_damage(self):
        assert get_type("scout_drone").combat.weapon_damage == 5


class TestTurret:
    def test_type_id(self):
        assert get_type("turret").type_id == "turret"

    def test_category(self):
        assert get_type("turret").category is MovementCategory.STATIONARY

    def test_speed(self):
        assert get_type("turret").speed == 0.0

    def test_drain_rate(self):
        assert get_type("turret").drain_rate == 0.0005

    def test_health(self):
        assert get_type("turret").combat.health == 200

    def test_weapon_range(self):
        assert get_type("turret").combat.weapon_range == 20.0

    def test_weapon_damage(self):
        assert get_type("turret").combat.weapon_damage == 15

    def test_icon(self):
        assert get_type("turret").icon == "T"

    def test_vision(self):
        assert get_type("turret").vision_radius == 50.0


class TestHeavyTurret:
    def test_type_id(self):
        assert get_type("heavy_turret").type_id == "heavy_turret"

    def test_health(self):
        assert get_type("heavy_turret").combat.health == 350

    def test_weapon_range(self):
        assert get_type("heavy_turret").combat.weapon_range == 30.0

    def test_weapon_damage(self):
        assert get_type("heavy_turret").combat.weapon_damage == 25


class TestMissileTurret:
    def test_type_id(self):
        assert get_type("missile_turret").type_id == "missile_turret"

    def test_health(self):
        assert get_type("missile_turret").combat.health == 200

    def test_weapon_range(self):
        assert get_type("missile_turret").combat.weapon_range == 35.0

    def test_weapon_damage(self):
        assert get_type("missile_turret").combat.weapon_damage == 50

    def test_cooldown(self):
        assert get_type("missile_turret").combat.weapon_cooldown == 5.0


class TestTank:
    def test_type_id(self):
        assert get_type("tank").type_id == "tank"

    def test_category(self):
        assert get_type("tank").category is MovementCategory.GROUND

    def test_speed(self):
        assert get_type("tank").speed == 1.5

    def test_health(self):
        assert get_type("tank").combat.health == 400

    def test_weapon_damage(self):
        assert get_type("tank").combat.weapon_damage == 30

    def test_icon(self):
        assert get_type("tank").icon == "K"


class TestAPC:
    def test_type_id(self):
        assert get_type("apc").type_id == "apc"

    def test_category(self):
        assert get_type("apc").category is MovementCategory.GROUND

    def test_speed(self):
        assert get_type("apc").speed == 2.5

    def test_health(self):
        assert get_type("apc").combat.health == 300

    def test_weapon_damage(self):
        assert get_type("apc").combat.weapon_damage == 8

    def test_icon(self):
        assert get_type("apc").icon == "A"


class TestPerson:
    def test_type_id(self):
        assert get_type("person").type_id == "person"

    def test_category(self):
        assert get_type("person").category is MovementCategory.FOOT

    def test_speed(self):
        assert get_type("person").speed == 1.5

    def test_non_combatant(self):
        assert get_type("person").combat.is_combatant is False

    def test_zero_drain(self):
        assert get_type("person").drain_rate == 0.0

    def test_icon(self):
        assert get_type("person").icon == "P"


class TestHostilePerson:
    def test_type_id(self):
        assert get_type("hostile_person").type_id == "hostile_person"

    def test_category(self):
        assert get_type("hostile_person").category is MovementCategory.FOOT

    def test_combatant(self):
        assert get_type("hostile_person").combat.is_combatant is True

    def test_health(self):
        assert get_type("hostile_person").combat.health == 80

    def test_weapon_damage(self):
        assert get_type("hostile_person").combat.weapon_damage == 10

    def test_icon(self):
        assert get_type("hostile_person").icon == "H"


class TestHostileVehicle:
    def test_type_id(self):
        assert get_type("hostile_vehicle").type_id == "hostile_vehicle"

    def test_category(self):
        assert get_type("hostile_vehicle").category is MovementCategory.GROUND

    def test_speed(self):
        assert get_type("hostile_vehicle").speed == 6.0

    def test_health(self):
        assert get_type("hostile_vehicle").combat.health == 200

    def test_icon(self):
        assert get_type("hostile_vehicle").icon == "V"


class TestHostileLeader:
    def test_type_id(self):
        assert get_type("hostile_leader").type_id == "hostile_leader"

    def test_category(self):
        assert get_type("hostile_leader").category is MovementCategory.FOOT

    def test_speed(self):
        assert get_type("hostile_leader").speed == 1.8

    def test_health(self):
        assert get_type("hostile_leader").combat.health == 150

    def test_icon(self):
        assert get_type("hostile_leader").icon == "L"


class TestVehicle:
    def test_type_id(self):
        assert get_type("vehicle").type_id == "vehicle"

    def test_non_combatant(self):
        assert get_type("vehicle").combat.is_combatant is False

    def test_health(self):
        assert get_type("vehicle").combat.health == 300


class TestAnimal:
    def test_type_id(self):
        assert get_type("animal").type_id == "animal"

    def test_non_combatant(self):
        assert get_type("animal").combat.is_combatant is False

    def test_health(self):
        assert get_type("animal").combat.health == 30


class TestCamera:
    def test_type_id(self):
        assert get_type("camera").type_id == "camera"

    def test_stationary(self):
        assert get_type("camera").category is MovementCategory.STATIONARY

    def test_non_combatant(self):
        assert get_type("camera").combat.is_combatant is False

    def test_icon(self):
        assert get_type("camera").icon == "C"

    def test_vision(self):
        assert get_type("camera").vision_radius == 30.0


class TestMotionSensor:
    def test_type_id(self):
        assert get_type("sensor").type_id == "sensor"

    def test_stationary(self):
        assert get_type("sensor").category is MovementCategory.STATIONARY

    def test_non_combatant(self):
        assert get_type("sensor").combat.is_combatant is False

    def test_icon(self):
        assert get_type("sensor").icon == "S"

    def test_vision(self):
        assert get_type("sensor").vision_radius == 30.0
