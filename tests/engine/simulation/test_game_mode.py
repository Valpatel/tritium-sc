# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for GameMode and wave controller."""

from __future__ import annotations

import queue
import threading
import time

import pytest

from engine.simulation.combat import CombatSystem
from engine.simulation.engine import SimulationEngine
from engine.simulation.game_mode import (
    GameMode,
    WaveConfig,
    WAVE_CONFIGS,
    _COUNTDOWN_DURATION,
    _WAVE_ADVANCE_DELAY,
)
from engine.simulation.target import SimulationTarget


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)

    def subscribe(self, topic: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(topic, []).append(q)
        return q


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Wave configuration
# --------------------------------------------------------------------------

class TestWaveConfigs:
    def test_ten_waves_defined(self):
        assert len(WAVE_CONFIGS) == 10

    def test_wave_names_unique(self):
        names = [w.name for w in WAVE_CONFIGS]
        assert len(set(names)) == 10

    def test_waves_increase_difficulty(self):
        # Hostile count should generally trend upward
        assert WAVE_CONFIGS[0].count < WAVE_CONFIGS[-1].count

    def test_final_wave_name(self):
        assert WAVE_CONFIGS[-1].name == "FINAL STAND"

    def test_first_wave_easier(self):
        first = WAVE_CONFIGS[0]
        assert first.speed_mult < 1.0
        assert first.health_mult < 1.0


# --------------------------------------------------------------------------
# GameMode state machine
# --------------------------------------------------------------------------

class TestGameModeInitialState:
    def test_starts_in_setup(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        assert gm.state == "setup"
        assert gm.wave == 0
        assert gm.score == 0
        assert gm.total_eliminations == 0

    def test_valid_states(self):
        assert "setup" in GameMode.STATES
        assert "countdown" in GameMode.STATES
        assert "active" in GameMode.STATES
        assert "wave_complete" in GameMode.STATES
        assert "victory" in GameMode.STATES
        assert "defeat" in GameMode.STATES


class TestGameModeBeginWar:
    def test_begin_war_transitions_to_countdown(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        state_sub = bus.subscribe("game_state_change")

        gm.begin_war()
        assert gm.state == "countdown"
        assert gm.wave == 1

        event = state_sub.get(timeout=1.0)
        assert event["state"] == "countdown"
        assert event["wave"] == 1

    def test_begin_war_only_from_setup(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.state = "active"
        gm.begin_war()
        # Should not change state
        assert gm.state == "active"

    def test_begin_war_resets_score(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.score = 500
        gm.total_eliminations = 10
        gm.begin_war()
        assert gm.score == 0
        assert gm.total_eliminations == 0


class TestGameModeCountdown:
    def test_countdown_decrements(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        gm.begin_war()
        initial = gm._countdown_remaining
        gm.tick(1.0)
        assert gm._countdown_remaining == initial - 1.0

    def test_countdown_transitions_to_active(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        wave_sub = bus.subscribe("wave_start")
        gm.begin_war()

        # Tick past the countdown
        gm.tick(_COUNTDOWN_DURATION + 1.0)
        assert gm.state == "active"

        event = wave_sub.get(timeout=1.0)
        assert event["wave_number"] == 1
        assert event["wave_name"] == "Scout Party"


class TestGameModeActive:
    def test_defeat_when_no_friendlies(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        game_over_sub = bus.subscribe("game_over")

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)
        assert gm.state == "active"

        # No friendly combatants — should transition to defeat
        # Wait for spawn thread to finish or check quickly
        gm._spawn_thread = None  # pretend spawning is done
        gm.tick(0.1)
        assert gm.state == "defeat"

        event = game_over_sub.get(timeout=1.0)
        assert event["result"] == "defeat"
        assert event["waves_completed"] == 0

    def test_no_defeat_with_friendlies(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        # Add a friendly combatant
        friendly = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            is_combatant=True, status="stationary",
        )
        engine.add_target(friendly)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)
        assert gm.state == "active"
        gm.tick(0.1)
        # Should still be active (friendly exists)
        assert gm.state == "active"


class TestGameModeWaveComplete:
    def test_wave_complete_when_all_hostiles_gone(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        wave_complete_sub = bus.subscribe("wave_complete")

        # Add a friendly
        friendly = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            is_combatant=True, status="stationary",
        )
        engine.add_target(friendly)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)
        assert gm.state == "active"

        # Pretend wave spawning is done and no hostiles alive
        gm._spawn_thread = None
        gm._wave_hostile_ids.clear()
        gm.tick(0.1)
        assert gm.state == "wave_complete"

        event = wave_complete_sub.get(timeout=1.0)
        assert event["wave_number"] == 1

    def test_wave_complete_advances_to_next(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        friendly = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            is_combatant=True, status="stationary",
        )
        engine.add_target(friendly)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)
        gm._spawn_thread = None
        gm._wave_hostile_ids.clear()
        gm.tick(0.1)
        assert gm.state == "wave_complete"

        # Advance time past the delay
        gm._wave_complete_time = time.time() - _WAVE_ADVANCE_DELAY - 1
        gm.tick(0.1)
        assert gm.state == "active"
        assert gm.wave == 2


class TestGameModeVictory:
    def test_victory_after_all_waves(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        game_over_sub = bus.subscribe("game_over")

        friendly = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            is_combatant=True, status="stationary",
        )
        engine.add_target(friendly)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)

        # Simulate clearing all 10 waves
        for wave_num in range(1, len(WAVE_CONFIGS) + 1):
            gm._spawn_thread = None
            gm._wave_hostile_ids.clear()
            gm.tick(0.1)
            if gm.state == "wave_complete":
                gm._wave_complete_time = time.time() - _WAVE_ADVANCE_DELAY - 1
                gm.tick(0.1)

        # Should be victory after wave 10
        assert gm.state == "victory"
        event = game_over_sub.get(timeout=1.0)
        assert event["result"] == "victory"
        assert event["waves_completed"] == 10


class TestGameModeScoring:
    def test_on_target_eliminated_adds_score(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        friendly = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            is_combatant=True, status="stationary",
        )
        engine.add_target(friendly)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)

        # Add a hostile to the wave tracker
        gm._wave_hostile_ids.add("h1")
        gm.on_target_eliminated("h1")
        assert gm.wave_eliminations == 1
        assert gm.total_eliminations == 1
        assert gm.score == 100

    def test_non_wave_targets_score_but_dont_count_wave_elims(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        friendly = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            is_combatant=True, status="stationary",
        )
        engine.add_target(friendly)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)

        # Eliminate a non-wave target — scores points but no wave elimination
        gm.on_target_eliminated("random_id")
        assert gm.wave_eliminations == 0
        assert gm.total_eliminations == 1
        assert gm.score == 100

    def test_scoring_only_in_active_state(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        gm._wave_hostile_ids.add("h1")
        gm.on_target_eliminated("h1")
        # Not in active state, should be ignored
        assert gm.wave_eliminations == 0


class TestGameModeReset:
    def test_reset_returns_to_setup(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        gm.begin_war()
        gm.score = 500
        gm.total_eliminations = 10
        gm.wave = 3

        gm.reset()
        assert gm.state == "setup"
        assert gm.wave == 0
        assert gm.score == 0
        assert gm.total_eliminations == 0
        assert len(gm._wave_hostile_ids) == 0


class TestGameModeGetState:
    def test_get_state_returns_dict(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        state = gm.get_state()
        assert state["state"] == "setup"
        assert state["wave"] == 0
        assert state["total_waves"] == 10
        assert state["score"] == 0
        assert state["total_eliminations"] == 0

    def test_get_state_during_countdown(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        gm.begin_war()
        state = gm.get_state()
        assert state["state"] == "countdown"
        assert state["wave"] == 1
        assert state["countdown"] > 0

    def test_get_state_active_has_wave_name(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)
        state = gm.get_state()
        assert state["wave_name"] == "Scout Party"


# --------------------------------------------------------------------------
# Engine integration
# --------------------------------------------------------------------------

class TestEngineGameModeIntegration:
    def test_engine_has_game_mode(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        assert engine.game_mode is not None
        assert engine.game_mode.state == "setup"

    def test_engine_has_combat_system(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        assert engine.combat is not None

    def test_engine_has_behaviors(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        assert engine.behaviors is not None

    def test_engine_begin_war(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        engine.begin_war()
        assert engine.game_mode.state == "countdown"

    def test_engine_get_game_state(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        state = engine.get_game_state()
        assert state["state"] == "setup"

    def test_engine_reset_game(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)

        # Add some hostiles
        engine.spawn_hostile()
        engine.spawn_hostile()
        hostiles_before = sum(1 for t in engine.get_targets() if t.alliance == "hostile")
        assert hostiles_before == 2

        engine.reset_game()
        hostiles_after = sum(1 for t in engine.get_targets() if t.alliance == "hostile")
        assert hostiles_after == 0
        assert engine.game_mode.state == "setup"

    def test_spawn_hostile_applies_combat_profile(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        h = engine.spawn_hostile()
        # Should have hostile person combat profile
        assert h.health == 80.0
        assert h.weapon_range == 40.0
        assert h.weapon_cooldown == 2.5
        assert h.is_combatant is True


# --------------------------------------------------------------------------
# New feature: begin_war resets friendly health
# --------------------------------------------------------------------------

class TestBeginWarResetsHealth:
    def test_begin_resets_friendly_health(self):
        """begin_war() should reset all friendly combatants to full health."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        # Add damaged friendlies
        turret = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            is_combatant=True, status="stationary",
            health=30.0, max_health=100.0,
        )
        rover = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(5.0, 0.0),
            is_combatant=True, status="active",
            health=50.0, max_health=120.0,
        )
        engine.add_target(turret)
        engine.add_target(rover)

        gm.begin_war()

        assert turret.health == turret.max_health, "Turret health should be reset to max"
        assert rover.health == rover.max_health, "Rover health should be reset to max"

    def test_begin_resets_friendly_battery(self):
        """begin_war() should reset battery to 1.0."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        drone = SimulationTarget(
            target_id="d1", name="Drone", alliance="friendly",
            asset_type="drone", position=(0.0, 0.0),
            is_combatant=True, status="active",
            battery=0.3,
        )
        engine.add_target(drone)

        gm.begin_war()
        assert drone.battery == 1.0, "Battery should be reset to 1.0"

    def test_begin_reactivates_low_battery_units(self):
        """begin_war() should reactivate low_battery/idle friendly units."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        unit = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            is_combatant=True, status="low_battery",
            health=50.0, max_health=100.0, battery=0.1,
        )
        engine.add_target(unit)

        gm.begin_war()
        assert unit.status == "active", "low_battery unit should be reactivated"
        assert unit.health == 100.0
        assert unit.battery == 1.0

    def test_begin_does_not_reset_non_combatants(self):
        """begin_war() should only reset combatant friendlies, not civilians."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        civilian = SimulationTarget(
            target_id="c1", name="Neighbor", alliance="friendly",
            asset_type="person", position=(0.0, 0.0),
            is_combatant=False, status="active",
            health=50.0, max_health=100.0,
        )
        engine.add_target(civilian)

        gm.begin_war()
        assert civilian.health == 50.0, "Non-combatant health unchanged"


# --------------------------------------------------------------------------
# New feature: low_battery counts as alive for defeat check
# --------------------------------------------------------------------------

class TestLowBatteryDefeatCheck:
    def test_low_battery_unit_prevents_defeat(self):
        """A low_battery friendly should prevent defeat condition."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        unit = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            is_combatant=True, status="low_battery",
        )
        engine.add_target(unit)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)
        assert gm.state == "active"

        gm._spawn_thread = None
        gm.tick(0.1)
        # low_battery is still alive — should NOT be defeat
        assert gm.state != "defeat", "low_battery unit should prevent defeat"

    def test_eliminated_friendly_allows_defeat(self):
        """When all friendlies are eliminated (not low_battery), defeat triggers."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        unit = SimulationTarget(
            target_id="r1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            is_combatant=True, status="eliminated",
        )
        engine.add_target(unit)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)
        gm._spawn_thread = None
        gm.tick(0.1)
        assert gm.state == "defeat"


# --------------------------------------------------------------------------
# Non-wave hostile scoring
# --------------------------------------------------------------------------

class TestNonWaveHostileScoring:
    def test_non_wave_hostile_scores_100_points(self):
        """Non-wave hostiles (ambient) score points when eliminated."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        friendly = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            is_combatant=True, status="stationary",
        )
        engine.add_target(friendly)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)

        # Eliminate a non-wave hostile
        gm.on_target_eliminated("ambient_hostile_1")
        assert gm.total_eliminations == 1
        assert gm.score == 100
        assert gm.wave_eliminations == 0  # not a wave hostile

    def test_wave_hostile_counts_for_both_score_and_wave(self):
        """Wave hostiles count toward both score AND wave completion."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        friendly = SimulationTarget(
            target_id="t1", name="Turret", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0),
            is_combatant=True, status="stationary",
        )
        engine.add_target(friendly)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)

        gm._wave_hostile_ids.add("wave_h1")
        gm.on_target_eliminated("wave_h1")
        assert gm.total_eliminations == 1
        assert gm.score == 100
        assert gm.wave_eliminations == 1  # IS a wave hostile


# --------------------------------------------------------------------------
# Mixed-type wave composition
# --------------------------------------------------------------------------

class TestMixedWaveComposition:
    """Test that waves with composition field spawn diverse unit types."""

    def test_early_waves_have_no_composition(self):
        """Waves 1-2 should have no composition (all person)."""
        assert WAVE_CONFIGS[0].composition is None
        assert WAVE_CONFIGS[1].composition is None

    def test_later_waves_have_composition(self):
        """Waves 3+ should have mixed-type compositions."""
        for i in range(2, len(WAVE_CONFIGS)):
            config = WAVE_CONFIGS[i]
            assert config.composition is not None, (
                f"Wave {i+1} ({config.name}) should have composition"
            )

    def test_composition_counts_sum_to_total(self):
        """Composition type counts should sum to config.count."""
        for i, config in enumerate(WAVE_CONFIGS):
            if config.composition is not None:
                comp_total = sum(c for _, c in config.composition)
                assert comp_total == config.count, (
                    f"Wave {i+1} ({config.name}): composition sum {comp_total} "
                    f"!= count {config.count}"
                )

    def test_composition_has_valid_types(self):
        """All asset types in compositions should be valid hostile types."""
        valid_types = {
            "person", "hostile_vehicle", "hostile_leader",
            "swarm_drone", "hostile_person",
        }
        for i, config in enumerate(WAVE_CONFIGS):
            if config.composition is not None:
                for asset_type, count in config.composition:
                    assert asset_type in valid_types, (
                        f"Wave {i+1}: invalid type '{asset_type}'"
                    )
                    assert count > 0, f"Wave {i+1}: count must be > 0"

    def test_final_wave_has_most_types(self):
        """FINAL STAND should have the most unit type variety."""
        final = WAVE_CONFIGS[-1]
        assert final.composition is not None
        types_in_final = {t for t, _ in final.composition}
        assert len(types_in_final) >= 3, "Final wave should have 3+ unit types"

    def test_spawn_mixed_wave_creates_typed_hostiles(self):
        """_spawn_mixed_wave() should create units of each specified type."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        config = WaveConfig(
            name="Test Mixed",
            count=5,
            speed_mult=1.0,
            health_mult=1.0,
            composition=[("person", 3), ("hostile_vehicle", 2)],
        )

        gm.state = "active"
        gm._spawn_mixed_wave(config)

        targets = engine.get_targets()
        types = [t.asset_type for t in targets if t.alliance == "hostile"]
        assert types.count("person") == 3
        assert types.count("hostile_vehicle") == 2
        assert len(gm._wave_hostile_ids) == 5

    def test_spawn_mixed_wave_applies_speed_mult(self):
        """Speed multiplier should be applied to mixed wave units."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        config = WaveConfig(
            name="Fast Mix",
            count=2,
            speed_mult=1.5,
            health_mult=1.0,
            composition=[("person", 1), ("hostile_vehicle", 1)],
        )

        gm.state = "active"
        gm._spawn_mixed_wave(config)

        targets = engine.get_targets()
        for t in targets:
            if t.alliance == "hostile":
                # Base speed should be multiplied by 1.5
                assert t.speed > 1.0, f"{t.asset_type} speed should be > 1.0"

    def test_spawn_mixed_wave_applies_health_mult(self):
        """Health multiplier should be applied to mixed wave units."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        config = WaveConfig(
            name="Tough Mix",
            count=2,
            speed_mult=1.0,
            health_mult=2.0,
            composition=[("person", 1), ("hostile_vehicle", 1)],
        )

        gm.state = "active"
        gm._spawn_mixed_wave(config)

        for t in engine.get_targets():
            if t.alliance == "hostile":
                # Health should be 2x base
                assert t.health > 80.0 or t.asset_type != "person", (
                    f"{t.asset_type} health {t.health} should reflect 2x mult"
                )

    def test_no_composition_falls_back_to_person(self):
        """Waves without composition should spawn all person type."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)

        config = WaveConfig(
            name="All Person",
            count=3,
            speed_mult=1.0,
            health_mult=1.0,
            composition=None,
        )

        gm.state = "active"
        gm._spawn_wave_hostiles(config)
        time.sleep(1.5)  # wait for staggered spawning

        targets = engine.get_targets()
        hostiles = [t for t in targets if t.alliance == "hostile"]
        assert len(hostiles) == 3
        for h in hostiles:
            assert h.asset_type == "person"

    def test_wave_config_composition_field_default_none(self):
        """WaveConfig.composition should default to None."""
        config = WaveConfig("Test", count=5, speed_mult=1.0, health_mult=1.0)
        assert config.composition is None
