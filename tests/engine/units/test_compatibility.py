# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Verify that the units registry contains all expected types and values.

These tests ensure the registry holds the canonical data that was previously
scattered across _DRAIN_RATES, _COMBAT_PROFILES, and pathfinding sets.
"""

from __future__ import annotations

import pytest

from engine.units import get_type, all_types, flying_type_ids, ground_type_ids, static_type_ids, foot_type_ids


pytestmark = pytest.mark.unit


class TestExpectedDrainRates:
    """Verify drain rates match the canonical values from the old _DRAIN_RATES dict."""

    _EXPECTED = {
        "rover": 0.001, "drone": 0.002, "turret": 0.0005,
        "scout_drone": 0.0025, "person": 0.0, "vehicle": 0.0,
        "animal": 0.0, "heavy_turret": 0.0004, "missile_turret": 0.0003,
        "tank": 0.0008, "apc": 0.0010,
    }

    def test_all_drain_rates_present(self):
        for asset_type, expected_drain in self._EXPECTED.items():
            cls = get_type(asset_type)
            assert cls is not None, f"No registry entry for {asset_type!r}"
            assert cls.drain_rate == pytest.approx(expected_drain), (
                f"{asset_type}: drain {cls.drain_rate} != {expected_drain}"
            )


class TestExpectedCombatProfiles:
    """Verify combat profiles match the old _COMBAT_PROFILES dict."""

    _EXPECTED = {
        "turret":           (200, 200,  80.0, 1.5, 15, True),
        "drone":            (60,  60,   50.0, 1.0,  8, True),
        "rover":            (150, 150,  60.0, 2.0, 12, True),
        "person_hostile":   (80,  80,   40.0, 2.5, 10, True),
        "person_neutral":   (50,  50,    0.0, 0.0,  0, False),
        "vehicle":          (300, 300,   0.0, 0.0,  0, False),
        "animal":           (30,  30,    0.0, 0.0,  0, False),
        "tank":             (400, 400, 100.0, 3.0, 30, True),
        "apc":              (300, 300,  60.0, 1.0,  8, True),
        "heavy_turret":     (350, 350, 120.0, 2.5, 25, True),
        "missile_turret":   (200, 200, 150.0, 5.0, 50, True),
        "scout_drone":      (40,  40,   40.0, 1.5,  5, True),
        "hostile_vehicle":  (200, 200,  70.0, 2.0, 15, True),
        "hostile_leader":   (150, 150,  50.0, 2.0, 12, True),
    }

    def test_all_combat_profiles_present(self):
        for key, (hp, max_hp, wrange, wcd, wdmg, is_comb) in self._EXPECTED.items():
            # person_hostile/person_neutral are aliases in the registry
            cls = get_type(key)
            assert cls is not None, f"No registry entry for {key!r}"
            stats = cls.combat
            assert stats is not None, f"{key}: no combat stats"
            assert stats.health == pytest.approx(hp), f"{key}: health"
            assert stats.max_health == pytest.approx(max_hp), f"{key}: max_health"
            assert stats.weapon_range == pytest.approx(wrange), f"{key}: range"
            assert stats.weapon_cooldown == pytest.approx(wcd), f"{key}: cooldown"
            assert stats.weapon_damage == pytest.approx(wdmg), f"{key}: damage"
            assert stats.is_combatant is is_comb, f"{key}: combatant"


class TestPathfindingCategories:
    """Verify routing categories match the old pathfinding sets."""

    def test_stationary_types(self):
        expected = {"turret", "heavy_turret", "missile_turret"}
        for type_id in expected:
            assert type_id in static_type_ids(), (
                f"{type_id} should be static"
            )

    def test_flying_types(self):
        expected = {"drone", "scout_drone"}
        for type_id in expected:
            assert type_id in flying_type_ids(), (
                f"{type_id} should be flying"
            )

    def test_road_types(self):
        expected = {"rover", "tank", "apc"}
        for type_id in expected:
            assert type_id in ground_type_ids(), (
                f"{type_id} should be ground"
            )

    def test_foot_types(self):
        expected = {"person", "hostile_person", "hostile_leader"}
        for type_id in expected:
            assert type_id in foot_type_ids(), (
                f"{type_id} should be foot"
            )
