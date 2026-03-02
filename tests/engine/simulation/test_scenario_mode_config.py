# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for BattleScenario mode_config field (Phase 1 data model)."""

from __future__ import annotations

import pytest

from engine.simulation.scenario import BattleScenario, WaveDefinition, SpawnGroup, DefenderConfig


pytestmark = pytest.mark.unit


class TestBattleScenarioModeConfig:
    def test_mode_config_default_none(self):
        """BattleScenario has mode_config=None by default."""
        scenario = BattleScenario(
            scenario_id="test-1",
            name="Test Scenario",
            description="Test",
            map_bounds=200.0,
            waves=[
                WaveDefinition(
                    name="Wave 1",
                    groups=[SpawnGroup(asset_type="person", count=5)],
                ),
            ],
        )
        assert scenario.mode_config is None

    def test_mode_config_civil_unrest(self):
        """BattleScenario accepts mode_config for civil unrest."""
        config = {
            "civilian_harm_limit": 5,
            "de_escalation_weight": 0.7,
            "game_mode_type": "civil_unrest",
        }
        scenario = BattleScenario(
            scenario_id="cu-1",
            name="Civil Unrest Test",
            description="Crowd control scenario",
            map_bounds=200.0,
            waves=[
                WaveDefinition(
                    name="Phase 1",
                    groups=[SpawnGroup(asset_type="person", count=15)],
                ),
            ],
            mode_config=config,
        )
        assert scenario.mode_config is not None
        assert scenario.mode_config["game_mode_type"] == "civil_unrest"
        assert scenario.mode_config["civilian_harm_limit"] == 5

    def test_mode_config_drone_swarm(self):
        """BattleScenario accepts mode_config for drone swarm."""
        config = {
            "infrastructure_health": 1000.0,
            "game_mode_type": "drone_swarm",
        }
        scenario = BattleScenario(
            scenario_id="ds-1",
            name="Drone Swarm Test",
            description="AA defense scenario",
            map_bounds=250.0,
            waves=[
                WaveDefinition(
                    name="Wave 1",
                    groups=[SpawnGroup(asset_type="swarm_drone", count=5)],
                ),
            ],
            mode_config=config,
        )
        assert scenario.mode_config["game_mode_type"] == "drone_swarm"
        assert scenario.mode_config["infrastructure_health"] == 1000.0

    def test_mode_config_serialization(self):
        """mode_config round-trips through to_dict()/from_dict()."""
        config = {
            "civilian_harm_limit": 5,
            "game_mode_type": "civil_unrest",
        }
        scenario = BattleScenario(
            scenario_id="cu-2",
            name="Round-trip Test",
            description="Test serialization",
            map_bounds=200.0,
            waves=[
                WaveDefinition(
                    name="Wave 1",
                    groups=[SpawnGroup(asset_type="person", count=10)],
                ),
            ],
            mode_config=config,
        )
        d = scenario.to_dict()
        assert "mode_config" in d
        assert d["mode_config"]["game_mode_type"] == "civil_unrest"

        restored = BattleScenario.from_dict(d)
        assert restored.mode_config is not None
        assert restored.mode_config["game_mode_type"] == "civil_unrest"
        assert restored.mode_config["civilian_harm_limit"] == 5

    def test_mode_config_omitted_in_serialization_when_none(self):
        """mode_config is omitted from to_dict() when None."""
        scenario = BattleScenario(
            scenario_id="plain-1",
            name="Plain Battle",
            description="No special mode",
            map_bounds=200.0,
            waves=[
                WaveDefinition(
                    name="Wave 1",
                    groups=[SpawnGroup(asset_type="person", count=5)],
                ),
            ],
        )
        d = scenario.to_dict()
        # mode_config should not be present (or should be None)
        # Either approach is acceptable; we accept both
        if "mode_config" in d:
            assert d["mode_config"] is None
        # from_dict should handle missing mode_config
        restored = BattleScenario.from_dict(d)
        assert restored.mode_config is None

    def test_from_dict_without_mode_config_key(self):
        """from_dict() handles dict without mode_config key gracefully."""
        data = {
            "scenario_id": "old-1",
            "name": "Legacy Scenario",
            "description": "Before mode_config existed",
            "map_bounds": 200.0,
            "waves": [
                {
                    "name": "Wave 1",
                    "groups": [{"asset_type": "person", "count": 5}],
                }
            ],
        }
        scenario = BattleScenario.from_dict(data)
        assert scenario.mode_config is None
