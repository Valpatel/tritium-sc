# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for building entry/exit system.

SKIPPED: The building system (BuildingData, add_building, get_buildings,
get_random_door, _spawn_from_building, _spawn_entering_building) has not
been implemented yet. These tests were written against a planned API that
does not exist in the source.

The loader (amy.simulation.loader) currently skips building/house/shed/garage
types via _SKIP_TYPES. The engine (amy.simulation.engine) has no building
storage or door retrieval. The ambient spawner (amy.simulation.ambient)
has no building-aware spawn methods.

When the building system is implemented, re-enable these tests and update
them to match the actual API.
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.skip(reason="Building system not yet implemented in source")]


class TestBuildingData:
    """Tests for the BuildingData dataclass -- NOT YET IMPLEMENTED."""

    def test_building_data_creation(self):
        pass

    def test_building_data_multiple_doors(self):
        pass

    def test_building_data_empty_footprint(self):
        pass


class TestEngineBuildings:
    """Tests for building storage on SimulationEngine -- NOT YET IMPLEMENTED."""

    def test_add_building(self):
        pass

    def test_add_multiple_buildings(self):
        pass

    def test_get_buildings_returns_copy(self):
        pass

    def test_get_random_door(self):
        pass

    def test_get_random_door_multiple_buildings(self):
        pass

    def test_no_buildings_returns_none(self):
        pass

    def test_buildings_with_no_doors_returns_none(self):
        pass


class TestBuildingLoading:
    """Tests for loading buildings from scenario JSON files -- NOT YET IMPLEMENTED."""

    def test_buildings_loaded_from_scenario(self):
        pass

    def test_multiple_buildings_loaded(self):
        pass

    def test_house_type_loaded(self):
        pass

    def test_shed_type_loaded(self):
        pass

    def test_building_with_no_doors(self):
        pass

    def test_building_not_counted_as_target(self):
        pass

    def test_default_scenario_loads_buildings(self):
        pass


class TestAmbientBuildingSpawn:
    """Tests for building-aware ambient spawning -- NOT YET IMPLEMENTED."""

    def test_engine_with_buildings_has_doors(self):
        pass

    def test_spawn_from_building_creates_target(self):
        pass

    def test_spawn_entering_building_creates_target(self):
        pass

    def test_spawn_from_building_fallback_no_buildings(self):
        pass


class TestHostileBuildingFlee:
    """Tests for hostile flee-to-building behavior -- NOT YET IMPLEMENTED."""

    def test_damaged_hostile_flees_to_building(self):
        pass

    def test_healthy_hostile_does_not_flee(self):
        pass

    def test_flee_only_if_building_within_range(self):
        pass

    def test_no_buildings_no_flee(self):
        pass
