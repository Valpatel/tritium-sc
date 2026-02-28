# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Diagnostic tests for the simulation position pipeline.

Verifies that:
1. Targets have non-zero, varied positions after spawning
2. to_dict() produces correct position format {x, y}
3. Positions stay within map bounds
4. Batch telemetry contains all targets with valid positions
5. Friendly defenders start at their configured positions

Run: .venv/bin/python3 -m pytest tests/engine/simulation/test_position_pipeline.py -v
"""

from __future__ import annotations

import math
import time

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.engine import SimulationEngine
from engine.simulation.target import SimulationTarget


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def engine(bus):
    eng = SimulationEngine(bus, map_bounds=100.0, max_hostiles=50)
    yield eng
    eng.stop()


@pytest.mark.unit
class TestTargetPositionFormat:
    """Verify to_dict() produces correct position format."""

    def test_to_dict_has_position_dict(self):
        t = SimulationTarget(
            target_id="test-1",
            name="Test",
            alliance="friendly",
            asset_type="rover",
            position=(50.0, -30.0),
            speed=2.0,
            waypoints=[],
            status="idle",
        )
        d = t.to_dict()
        assert "position" in d
        assert isinstance(d["position"], dict)
        assert "x" in d["position"]
        assert "y" in d["position"]

    def test_to_dict_position_values(self):
        t = SimulationTarget(
            target_id="test-2",
            name="Test",
            alliance="friendly",
            asset_type="rover",
            position=(75.5, -44.3),
            speed=2.0,
            waypoints=[],
            status="idle",
        )
        d = t.to_dict()
        assert d["position"]["x"] == 75.5
        assert d["position"]["y"] == -44.3

    def test_to_dict_zero_position(self):
        t = SimulationTarget(
            target_id="test-3",
            name="Test",
            alliance="friendly",
            asset_type="turret",
            position=(0.0, 0.0),
            speed=0.0,
            waypoints=[],
            status="stationary",
        )
        d = t.to_dict()
        assert d["position"]["x"] == 0.0
        assert d["position"]["y"] == 0.0

    def test_to_dict_negative_position(self):
        t = SimulationTarget(
            target_id="test-4",
            name="Test",
            alliance="hostile",
            asset_type="person",
            position=(-100.0, -100.0),
            speed=1.5,
            waypoints=[],
            status="active",
        )
        d = t.to_dict()
        assert d["position"]["x"] == -100.0
        assert d["position"]["y"] == -100.0

    def test_to_dict_has_all_required_fields(self):
        """Verify all fields the frontend expects are present."""
        t = SimulationTarget(
            target_id="test-5",
            name="Test",
            alliance="friendly",
            asset_type="rover",
            position=(10.0, 20.0),
            speed=2.0,
            waypoints=[],
            status="active",
        )
        t.apply_combat_profile()
        d = t.to_dict()
        required = [
            "target_id", "name", "alliance", "asset_type", "position",
            "heading", "speed", "status", "health", "max_health",
            "kills", "is_combatant", "fsm_state",
        ]
        for field in required:
            assert field in d, f"Missing field: {field}"

    def test_to_dict_includes_weapon_range(self):
        """weapon_range must be in to_dict — frontend reads it for range circles."""
        t = SimulationTarget(
            target_id="wr-1",
            name="Turret",
            alliance="friendly",
            asset_type="turret",
            position=(0.0, 0.0),
            speed=0.0,
            waypoints=[],
        )
        t.apply_combat_profile()
        d = t.to_dict()
        assert "weapon_range" in d, "to_dict missing weapon_range field"
        assert d["weapon_range"] > 0, "weapon_range should be positive for combatants"

    def test_to_dict_weapon_range_matches_attribute(self):
        """weapon_range in dict must match the target's actual attribute."""
        t = SimulationTarget(
            target_id="wr-2",
            name="Rover",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=2.0,
            waypoints=[],
        )
        t.weapon_range = 42.5
        d = t.to_dict()
        assert "weapon_range" in d, "to_dict missing weapon_range"
        assert d["weapon_range"] == 42.5, f"Expected 42.5, got {d['weapon_range']}"


@pytest.mark.unit
class TestSpawnPositions:
    """Verify spawned targets have correct positions."""

    def test_hostile_spawns_at_edge(self, engine):
        """Hostiles should spawn at map edge (±100m)."""
        h = engine.spawn_hostile()
        x, y = h.position
        at_edge = (
            abs(abs(x) - 100.0) < 1.0 or  # near x edge
            abs(abs(y) - 100.0) < 1.0      # near y edge
        )
        assert at_edge, f"Hostile should be at edge, got ({x:.1f}, {y:.1f})"

    def test_hostile_positions_varied(self, engine):
        """Multiple hostiles should NOT all be at the same position."""
        hostiles = [engine.spawn_hostile() for _ in range(10)]
        positions = [(h.position[0], h.position[1]) for h in hostiles]
        unique_x = len(set(round(p[0], 1) for p in positions))
        unique_y = len(set(round(p[1], 1) for p in positions))
        assert unique_x > 1 or unique_y > 1, "Hostile positions should be varied"

    def test_hostile_typed_spawn(self, engine):
        """Typed hostile spawning produces correct asset types."""
        p = engine.spawn_hostile_typed("person")
        assert p.asset_type == "person"
        assert p.alliance == "hostile"

    def test_hostile_at_explicit_position(self, engine):
        """Hostile at explicit position stays there."""
        h = engine.spawn_hostile(position=(25.0, -50.0))
        assert h.position[0] == 25.0
        assert h.position[1] == -50.0

    def test_defender_position_preserved(self, bus):
        """Friendly defender placed at (0, 0) stays at (0, 0)."""
        eng = SimulationEngine(bus, map_bounds=100.0)
        t = SimulationTarget(
            target_id="rover-test",
            name="RoboDog-1",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=2.0,
            waypoints=[],
            status="idle",
        )
        t.apply_combat_profile()
        eng.add_target(t)
        d = t.to_dict()
        assert d["position"]["x"] == 0.0
        assert d["position"]["y"] == 0.0
        eng.stop()


@pytest.mark.unit
class TestBatchTelemetry:
    """Verify batch telemetry events contain valid position data."""

    def test_batch_contains_all_targets(self, engine):
        """Batch telemetry should include all active targets."""
        # Add some targets
        engine.spawn_hostile(position=(50, 50))
        engine.spawn_hostile(position=(-50, -50))
        t = SimulationTarget(
            target_id="rover-bat",
            name="Rover-1",
            alliance="friendly",
            asset_type="rover",
            position=(0, 0),
            speed=2.0,
            waypoints=[],
            status="idle",
        )
        t.apply_combat_profile()
        engine.add_target(t)

        # Subscribe to batch events
        sub = engine._event_bus.subscribe()
        engine._tick_counter = 0
        engine._idle_ticks.clear()
        engine._last_snapshot.clear()

        # Run one tick
        engine._do_tick(0.1)

        # Collect batch
        batch_data = None
        while True:
            try:
                msg = sub.get(timeout=1)
                if msg.get("type") == "sim_telemetry_batch":
                    batch_data = msg.get("data")
                    break
            except Exception:
                break

        assert batch_data is not None, "Should receive sim_telemetry_batch event"
        assert isinstance(batch_data, list), "Batch data should be a list"
        assert len(batch_data) >= 3, f"Batch should have at least 3 targets, got {len(batch_data)}"

    def test_batch_positions_are_dicts(self, engine):
        """Each item in the batch should have position as {x, y} dict."""
        engine.spawn_hostile(position=(30, -70))
        t = SimulationTarget(
            target_id="rover-pos",
            name="Rover",
            alliance="friendly",
            asset_type="rover",
            position=(0, 0),
            speed=2.0,
            waypoints=[],
            status="idle",
        )
        t.apply_combat_profile()
        engine.add_target(t)

        sub = engine._event_bus.subscribe()
        engine._tick_counter = 0
        engine._idle_ticks.clear()
        engine._last_snapshot.clear()
        engine._do_tick(0.1)

        batch_data = None
        while True:
            try:
                msg = sub.get(timeout=1)
                if msg.get("type") == "sim_telemetry_batch":
                    batch_data = msg.get("data")
                    break
            except Exception:
                break

        assert batch_data is not None
        for item in batch_data:
            assert "position" in item, f"Item {item.get('target_id')} missing position"
            pos = item["position"]
            assert isinstance(pos, dict), f"Position should be dict, got {type(pos)}"
            assert "x" in pos, f"Position missing 'x'"
            assert "y" in pos, f"Position missing 'y'"
            assert isinstance(pos["x"], (int, float)), f"Position x should be number"
            assert isinstance(pos["y"], (int, float)), f"Position y should be number"

    def test_batch_positions_within_bounds(self, engine):
        """All positions should be within or near map bounds."""
        for _ in range(5):
            engine.spawn_hostile()

        sub = engine._event_bus.subscribe()
        engine._tick_counter = 0
        engine._idle_ticks.clear()
        engine._last_snapshot.clear()
        engine._do_tick(0.1)

        batch_data = None
        while True:
            try:
                msg = sub.get(timeout=1)
                if msg.get("type") == "sim_telemetry_batch":
                    batch_data = msg.get("data")
                    break
            except Exception:
                break

        assert batch_data is not None
        bounds = 110  # slightly larger than 100 to account for movement
        for item in batch_data:
            x = item["position"]["x"]
            y = item["position"]["y"]
            assert abs(x) <= bounds, f"Position x={x} exceeds bounds ±{bounds}"
            assert abs(y) <= bounds, f"Position y={y} exceeds bounds ±{bounds}"


@pytest.mark.unit
class TestScenarioPositions:
    """Verify scenario loading preserves defender positions."""

    def test_street_combat_defender_at_origin(self, bus):
        """Street combat scenario places rover at (0, 0)."""
        from pathlib import Path
        scenario_file = Path(__file__).resolve().parents[3] / "scenarios" / "battle" / "street_combat.json"
        if not scenario_file.is_file():
            pytest.skip("street_combat.json not found")

        from engine.simulation.scenario import load_battle_scenario
        scenario = load_battle_scenario(str(scenario_file))

        assert len(scenario.defenders) >= 1
        d = scenario.defenders[0]
        assert d.asset_type == "rover"
        assert d.position == (0.0, 0.0), f"Defender position should be (0, 0), got {d.position}"

    def test_scenario_positions_in_to_dict(self, bus):
        """Defenders placed from scenario should have correct to_dict position."""
        eng = SimulationEngine(bus, map_bounds=100.0)
        t = SimulationTarget(
            target_id="rover-scen",
            name="RoboDog-1",
            alliance="friendly",
            asset_type="rover",
            position=(0.0, 0.0),
            speed=2.0,
            waypoints=[],
            status="idle",
        )
        t.apply_combat_profile()
        eng.add_target(t)

        d = t.to_dict()
        assert d["target_id"] == "rover-scen"
        assert d["position"]["x"] == 0.0
        assert d["position"]["y"] == 0.0
        assert d["alliance"] == "friendly"
        assert d["asset_type"] == "rover"
        eng.stop()
