"""Tests for the unit type base classes."""

from __future__ import annotations

import pytest

from engine.units.base import CombatStats, MovementCategory, UnitType


pytestmark = pytest.mark.unit


class TestMovementCategory:
    def test_enum_values(self):
        assert MovementCategory.STATIONARY.value == "stationary"
        assert MovementCategory.GROUND.value == "ground"
        assert MovementCategory.FOOT.value == "foot"
        assert MovementCategory.AIR.value == "air"

    def test_enum_members(self):
        members = set(MovementCategory)
        assert len(members) == 4
        assert MovementCategory.STATIONARY in members
        assert MovementCategory.GROUND in members
        assert MovementCategory.FOOT in members
        assert MovementCategory.AIR in members


class TestCombatStats:
    def test_frozen_dataclass(self):
        stats = CombatStats(
            health=100, max_health=100,
            weapon_range=10.0, weapon_cooldown=1.5, weapon_damage=12,
            is_combatant=True,
        )
        assert stats.health == 100
        assert stats.max_health == 100
        assert stats.weapon_range == 10.0
        assert stats.weapon_cooldown == 1.5
        assert stats.weapon_damage == 12
        assert stats.is_combatant is True

    def test_frozen_immutable(self):
        stats = CombatStats(
            health=100, max_health=100,
            weapon_range=10.0, weapon_cooldown=1.0, weapon_damage=8,
            is_combatant=True,
        )
        with pytest.raises(AttributeError):
            stats.health = 200  # type: ignore[misc]

    def test_equality(self):
        a = CombatStats(100, 100, 10.0, 1.5, 12, True)
        b = CombatStats(100, 100, 10.0, 1.5, 12, True)
        assert a == b

    def test_non_combatant(self):
        stats = CombatStats(50, 50, 0.0, 0.0, 0, False)
        assert stats.is_combatant is False
        assert stats.weapon_range == 0.0
        assert stats.weapon_damage == 0


class TestUnitTypeClassMethods:
    """Test UnitType helper methods using a concrete subclass."""

    def _make_type(self, category: MovementCategory):
        """Create a minimal concrete UnitType subclass for testing."""
        return type("TestUnit", (UnitType,), {
            "type_id": "test",
            "display_name": "Test",
            "icon": "X",
            "category": category,
            "speed": 1.0,
            "drain_rate": 0.0,
            "vision_radius": 10.0,
            "combat": CombatStats(50, 50, 0.0, 0.0, 0, False),
        })

    def test_is_mobile_stationary(self):
        cls = self._make_type(MovementCategory.STATIONARY)
        assert cls.is_mobile() is False

    def test_is_mobile_ground(self):
        cls = self._make_type(MovementCategory.GROUND)
        assert cls.is_mobile() is True

    def test_is_mobile_air(self):
        cls = self._make_type(MovementCategory.AIR)
        assert cls.is_mobile() is True

    def test_is_mobile_foot(self):
        cls = self._make_type(MovementCategory.FOOT)
        assert cls.is_mobile() is True

    def test_is_flying_air(self):
        cls = self._make_type(MovementCategory.AIR)
        assert cls.is_flying() is True

    def test_is_flying_ground(self):
        cls = self._make_type(MovementCategory.GROUND)
        assert cls.is_flying() is False

    def test_is_ground(self):
        cls = self._make_type(MovementCategory.GROUND)
        assert cls.is_ground() is True

    def test_is_ground_air(self):
        cls = self._make_type(MovementCategory.AIR)
        assert cls.is_ground() is False

    def test_is_foot(self):
        cls = self._make_type(MovementCategory.FOOT)
        assert cls.is_foot() is True

    def test_is_foot_ground(self):
        cls = self._make_type(MovementCategory.GROUND)
        assert cls.is_foot() is False

    def test_is_stationary(self):
        cls = self._make_type(MovementCategory.STATIONARY)
        assert cls.is_stationary() is True

    def test_is_stationary_mobile(self):
        cls = self._make_type(MovementCategory.GROUND)
        assert cls.is_stationary() is False

    def test_repr(self):
        cls = self._make_type(MovementCategory.GROUND)
        assert "test" in repr(cls())
