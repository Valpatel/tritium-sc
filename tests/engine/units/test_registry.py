"""Tests for the unit type auto-discovery registry."""

from __future__ import annotations

import pytest

from engine.units import (
    all_types,
    flying_type_ids,
    foot_type_ids,
    get_type,
    ground_type_ids,
    mobile_type_ids,
    static_type_ids,
)
from engine.units.base import UnitType


pytestmark = pytest.mark.unit


class TestGetType:
    def test_rover(self):
        cls = get_type("rover")
        assert cls is not None
        assert cls.type_id == "rover"

    def test_drone(self):
        cls = get_type("drone")
        assert cls is not None
        assert cls.type_id == "drone"

    def test_turret(self):
        cls = get_type("turret")
        assert cls is not None
        assert cls.type_id == "turret"

    def test_nonexistent_returns_none(self):
        assert get_type("nonexistent") is None

    def test_empty_string_returns_none(self):
        assert get_type("") is None

    def test_alias_person_hostile(self):
        cls = get_type("person_hostile")
        assert cls is not None
        assert cls.type_id == "hostile_person"

    def test_alias_person_neutral(self):
        cls = get_type("person_neutral")
        assert cls is not None
        assert cls.type_id == "person"


class TestAllTypes:
    def test_non_empty(self):
        types = all_types()
        assert len(types) > 0

    def test_all_have_type_id(self):
        for cls in all_types():
            assert hasattr(cls, "type_id")
            assert cls.type_id, f"{cls} has empty type_id"

    def test_all_subclass_unit_type(self):
        for cls in all_types():
            assert issubclass(cls, UnitType), f"{cls} is not a UnitType"

    def test_no_duplicate_type_ids(self):
        ids = [cls.type_id for cls in all_types()]
        assert len(ids) == len(set(ids)), f"Duplicate type_ids: {ids}"

    def test_sorted_by_type_id(self):
        ids = [cls.type_id for cls in all_types()]
        assert ids == sorted(ids)

    def test_expected_count(self):
        assert len(all_types()) >= 16


class TestMobileTypeIds:
    def test_contains_rover(self):
        assert "rover" in mobile_type_ids()

    def test_contains_drone(self):
        assert "drone" in mobile_type_ids()

    def test_contains_tank(self):
        assert "tank" in mobile_type_ids()

    def test_contains_apc(self):
        assert "apc" in mobile_type_ids()

    def test_contains_person(self):
        assert "person" in mobile_type_ids()

    def test_excludes_turret(self):
        assert "turret" not in mobile_type_ids()

    def test_excludes_camera(self):
        assert "camera" not in mobile_type_ids()


class TestStaticTypeIds:
    def test_contains_turret(self):
        assert "turret" in static_type_ids()

    def test_contains_heavy_turret(self):
        assert "heavy_turret" in static_type_ids()

    def test_contains_missile_turret(self):
        assert "missile_turret" in static_type_ids()

    def test_contains_camera(self):
        assert "camera" in static_type_ids()

    def test_contains_sensor(self):
        assert "sensor" in static_type_ids()

    def test_excludes_rover(self):
        assert "rover" not in static_type_ids()


class TestFlyingTypeIds:
    def test_contains_drone(self):
        assert "drone" in flying_type_ids()

    def test_contains_scout_drone(self):
        assert "scout_drone" in flying_type_ids()

    def test_excludes_rover(self):
        assert "rover" not in flying_type_ids()

    def test_excludes_turret(self):
        assert "turret" not in flying_type_ids()

    def test_at_least_two_flying(self):
        assert len(flying_type_ids()) >= 2


class TestGroundTypeIds:
    def test_contains_rover(self):
        assert "rover" in ground_type_ids()

    def test_contains_tank(self):
        assert "tank" in ground_type_ids()

    def test_contains_apc(self):
        assert "apc" in ground_type_ids()

    def test_contains_hostile_vehicle(self):
        assert "hostile_vehicle" in ground_type_ids()

    def test_contains_vehicle(self):
        assert "vehicle" in ground_type_ids()

    def test_excludes_drone(self):
        assert "drone" not in ground_type_ids()

    def test_excludes_person(self):
        assert "person" not in ground_type_ids()


class TestFootTypeIds:
    def test_contains_person(self):
        assert "person" in foot_type_ids()

    def test_contains_hostile_person(self):
        assert "hostile_person" in foot_type_ids()

    def test_contains_hostile_leader(self):
        assert "hostile_leader" in foot_type_ids()

    def test_contains_animal(self):
        assert "animal" in foot_type_ids()

    def test_excludes_rover(self):
        assert "rover" not in foot_type_ids()

    def test_excludes_drone(self):
        assert "drone" not in foot_type_ids()
