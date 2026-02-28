# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for BattleScenario — city-scale battle scenario system."""

from __future__ import annotations

import json
import os
import queue
import tempfile
import threading

import pytest

from engine.simulation.scenario import (
    BattleScenario,
    DefenderConfig,
    SpawnGroup,
    WaveDefinition,
    load_battle_scenario,
)
from engine.simulation.target import SimulationTarget
from engine.simulation.engine import SimulationEngine


pytestmark = pytest.mark.unit


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object = None) -> None:
        msg = {"type": topic}
        if data is not None:
            msg["data"] = data
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def subscribe(self, _filter: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass


# ──────────────────────────────────────────────────────────────
# Data model tests
# ──────────────────────────────────────────────────────────────

class TestSpawnGroup:
    def test_spawn_group_defaults(self):
        g = SpawnGroup(asset_type="person", count=5)
        assert g.asset_type == "person"
        assert g.count == 5
        assert g.speed == 1.5
        assert g.health == 80.0

    def test_spawn_group_custom(self):
        g = SpawnGroup(asset_type="hostile_vehicle", count=2, speed=6.0, health=200.0)
        assert g.asset_type == "hostile_vehicle"
        assert g.speed == 6.0
        assert g.health == 200.0


class TestWaveDefinition:
    def test_wave_with_single_group(self):
        w = WaveDefinition(
            name="Test Wave",
            groups=[SpawnGroup(asset_type="person", count=3)],
        )
        assert w.name == "Test Wave"
        assert len(w.groups) == 1
        assert w.total_count == 3

    def test_wave_with_mixed_groups(self):
        w = WaveDefinition(
            name="Mixed",
            groups=[
                SpawnGroup(asset_type="person", count=5),
                SpawnGroup(asset_type="hostile_vehicle", count=2),
                SpawnGroup(asset_type="hostile_leader", count=1),
            ],
        )
        assert w.total_count == 8

    def test_wave_speed_mult(self):
        w = WaveDefinition(
            name="Fast",
            groups=[SpawnGroup(asset_type="person", count=3)],
            speed_mult=1.5,
        )
        assert w.speed_mult == 1.5

    def test_wave_health_mult(self):
        w = WaveDefinition(
            name="Tough",
            groups=[SpawnGroup(asset_type="person", count=3)],
            health_mult=2.0,
        )
        assert w.health_mult == 2.0


class TestDefenderConfig:
    def test_defender_defaults(self):
        d = DefenderConfig(asset_type="turret", position=(10.0, 20.0))
        assert d.asset_type == "turret"
        assert d.position == (10.0, 20.0)
        assert d.name is None

    def test_defender_with_name(self):
        d = DefenderConfig(asset_type="rover", position=(0.0, 0.0), name="Alpha Rover")
        assert d.name == "Alpha Rover"


class TestBattleScenario:
    def test_scenario_basic(self):
        s = BattleScenario(
            scenario_id="test-001",
            name="Test Scenario",
            description="A test",
            map_bounds=500.0,
            waves=[
                WaveDefinition(
                    name="Wave 1",
                    groups=[SpawnGroup(asset_type="person", count=5)],
                ),
            ],
        )
        assert s.scenario_id == "test-001"
        assert s.map_bounds == 500.0
        assert len(s.waves) == 1

    def test_scenario_with_defenders(self):
        s = BattleScenario(
            scenario_id="test-002",
            name="With Defenders",
            description="Has pre-placed defenders",
            map_bounds=300.0,
            waves=[
                WaveDefinition(
                    name="W1",
                    groups=[SpawnGroup(asset_type="person", count=3)],
                ),
            ],
            defenders=[
                DefenderConfig(asset_type="turret", position=(0.0, 0.0)),
                DefenderConfig(asset_type="rover", position=(10.0, 10.0)),
            ],
        )
        assert len(s.defenders) == 2

    def test_scenario_serialization_roundtrip(self):
        s = BattleScenario(
            scenario_id="rt-001",
            name="Roundtrip",
            description="Roundtrip test",
            map_bounds=200.0,
            waves=[
                WaveDefinition(
                    name="W1",
                    groups=[
                        SpawnGroup(asset_type="person", count=5),
                        SpawnGroup(asset_type="hostile_vehicle", count=2, speed=6.0, health=200.0),
                    ],
                    speed_mult=1.2,
                    health_mult=1.5,
                ),
            ],
            defenders=[
                DefenderConfig(asset_type="turret", position=(0.0, 0.0), name="Sentry-1"),
            ],
        )
        d = s.to_dict()
        s2 = BattleScenario.from_dict(d)
        assert s2.scenario_id == s.scenario_id
        assert s2.map_bounds == s.map_bounds
        assert len(s2.waves) == 1
        assert s2.waves[0].total_count == 7
        assert len(s2.defenders) == 1


# ──────────────────────────────────────────────────────────────
# JSON loading tests
# ──────────────────────────────────────────────────────────────

class TestLoadBattleScenario:
    def test_load_from_file(self, tmp_path):
        data = {
            "scenario_id": "file-001",
            "name": "From File",
            "description": "Loaded from JSON",
            "map_bounds": 400.0,
            "waves": [
                {
                    "name": "Wave 1",
                    "groups": [
                        {"asset_type": "person", "count": 10},
                    ],
                },
            ],
        }
        path = tmp_path / "test_scenario.json"
        path.write_text(json.dumps(data))
        scenario = load_battle_scenario(str(path))
        assert scenario.scenario_id == "file-001"
        assert scenario.waves[0].total_count == 10

    def test_load_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_battle_scenario("/nonexistent/path/scenario.json")

    def test_load_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json {{{")
        with pytest.raises(Exception):
            load_battle_scenario(str(path))

    def test_load_missing_required_fields(self, tmp_path):
        data = {"name": "Incomplete"}
        path = tmp_path / "incomplete.json"
        path.write_text(json.dumps(data))
        with pytest.raises((KeyError, TypeError)):
            load_battle_scenario(str(path))


# ──────────────────────────────────────────────────────────────
# Engine integration: spawn_hostile_typed
# ──────────────────────────────────────────────────────────────

class TestSpawnHostileTyped:
    def test_spawn_person(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)
        t = engine.spawn_hostile_typed("person")
        assert t.asset_type == "person"
        assert t.alliance == "hostile"
        assert t.status == "active"

    def test_spawn_hostile_vehicle(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)
        t = engine.spawn_hostile_typed("hostile_vehicle")
        assert t.asset_type == "hostile_vehicle"
        assert t.alliance == "hostile"

    def test_spawn_hostile_leader(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)
        t = engine.spawn_hostile_typed("hostile_leader")
        assert t.asset_type == "hostile_leader"
        assert t.alliance == "hostile"
        assert t.is_leader is True

    def test_spawn_typed_custom_position(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)
        t = engine.spawn_hostile_typed("person", position=(50.0, 50.0))
        assert abs(t.position[0] - 50.0) < 0.01
        assert abs(t.position[1] - 50.0) < 0.01

    def test_spawn_typed_custom_name(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)
        t = engine.spawn_hostile_typed("person", name="Big Boss")
        assert t.name == "Big Boss"

    def test_spawn_typed_custom_speed_health(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)
        t = engine.spawn_hostile_typed("person", speed=3.0, health=200.0)
        assert t.speed == 3.0
        assert t.health == 200.0
        assert t.max_health == 200.0

    def test_spawn_typed_is_added_to_engine(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)
        t = engine.spawn_hostile_typed("hostile_vehicle")
        found = engine.get_target(t.target_id)
        assert found is not None
        assert found.target_id == t.target_id


# ──────────────────────────────────────────────────────────────
# Scenario application: load_scenario on GameMode
# ──────────────────────────────────────────────────────────────

class TestGameModeLoadScenario:
    def test_load_scenario_sets_waves(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)
        scenario = BattleScenario(
            scenario_id="gm-001",
            name="GM Test",
            description="Test",
            map_bounds=200.0,
            waves=[
                WaveDefinition(
                    name="W1",
                    groups=[SpawnGroup(asset_type="person", count=5)],
                ),
                WaveDefinition(
                    name="W2",
                    groups=[
                        SpawnGroup(asset_type="person", count=3),
                        SpawnGroup(asset_type="hostile_vehicle", count=2),
                    ],
                    speed_mult=1.3,
                ),
            ],
        )
        engine.game_mode.load_scenario(scenario)
        assert engine.game_mode._scenario is not None
        assert len(engine.game_mode._scenario_waves) == 2

    def test_load_scenario_places_defenders(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)
        scenario = BattleScenario(
            scenario_id="gm-002",
            name="Defender Test",
            description="Test",
            map_bounds=200.0,
            waves=[
                WaveDefinition(
                    name="W1",
                    groups=[SpawnGroup(asset_type="person", count=3)],
                ),
            ],
            defenders=[
                DefenderConfig(asset_type="turret", position=(0.0, 0.0), name="Sentry-A"),
                DefenderConfig(asset_type="rover", position=(10.0, 10.0)),
            ],
        )
        engine.game_mode.load_scenario(scenario)
        targets = engine.get_targets()
        friendly_names = [t.name for t in targets if t.alliance == "friendly"]
        assert "Sentry-A" in friendly_names


class TestBattleScenarioFiles:
    """Test that the bundled scenario JSON files are valid."""

    def test_street_combat_json_valid(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "scenarios", "battle", "street_combat.json"
        )
        if not os.path.exists(path):
            pytest.skip("street_combat.json not yet created")
        s = load_battle_scenario(path)
        assert s.scenario_id == "street_combat"
        assert len(s.waves) >= 3

    def test_riot_json_valid(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "scenarios", "battle", "riot.json"
        )
        if not os.path.exists(path):
            pytest.skip("riot.json not yet created")
        s = load_battle_scenario(path)
        assert s.scenario_id == "riot"
        assert len(s.waves) >= 3
