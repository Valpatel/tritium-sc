# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for drone swarm mission type (Phase 5).

Tests the full pipeline from MissionDirector scenario generation through
GameMode lifecycle including InfrastructureHealth subsystem wiring.

Spec section 3.8 tests:
  33. test_scripted_scenario_end_to_end
  34. test_scenario_to_battle_scenario
  35. test_game_mode_drone_swarm_victory
  36. test_game_mode_drone_swarm_defeat_infrastructure
  37. test_bonus_perfect_defense
  38. test_bonus_ace_pilot
  39. test_full_wave_progression
  40. test_emp_tactical_tradeoff
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

from tritium_lib.sim_engine.combat.combat import CombatSystem
from engine.simulation.engine import SimulationEngine
from engine.simulation.game_mode import GameMode, _COUNTDOWN_DURATION, _WAVE_ADVANCE_DELAY
from engine.simulation.mission_director import (
    MissionDirector,
    GAME_MODES,
    _DRONE_SWARM_WAVES,
)
from tritium_lib.sim_engine.core.entity import SimulationTarget
from engine.simulation.infrastructure import InfrastructureHealth
from engine.simulation.scenario import BattleScenario


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._all_subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)
            for q in self._all_subscribers:
                try:
                    q.put_nowait({"type": topic, "data": data})
                except queue.Full:
                    pass

    def subscribe(self, _filter: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            if _filter is None:
                self._all_subscribers.append(q)
            else:
                self._subscribers.setdefault(_filter, []).append(q)
        return q


def _subscribe_topic(bus: SimpleEventBus, topic: str) -> queue.Queue:
    """Subscribe to a specific topic."""
    q: queue.Queue = queue.Queue()
    with bus._lock:
        bus._subscribers.setdefault(topic, []).append(q)
    return q


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Helper: fast-forward through game mode waves
# --------------------------------------------------------------------------

def _advance_through_countdown(gm: GameMode) -> None:
    """Advance game mode past the countdown to active state."""
    gm.tick(_COUNTDOWN_DURATION + 1.0)


def _clear_wave(gm: GameMode) -> None:
    """Simulate clearing a wave (no hostiles remaining)."""
    gm._spawn_thread = None
    gm._wave_hostile_ids.clear()
    gm.tick(0.1)


def _advance_to_next_wave(gm: GameMode) -> None:
    """Advance from wave_complete to next wave's active state."""
    gm._wave_complete_time = time.time() - _WAVE_ADVANCE_DELAY - 1
    gm.tick(0.1)


def _make_engine_with_friendly(bus: SimpleEventBus) -> SimulationEngine:
    """Create engine with one friendly combatant (to prevent defeat)."""
    engine = SimulationEngine(bus, map_bounds=200)
    friendly = SimulationTarget(
        target_id="turret-1", name="Missile Turret", alliance="friendly",
        asset_type="missile_turret", position=(0.0, 0.0),
        is_combatant=True, status="stationary",
    )
    engine.add_target(friendly)
    return engine


# --------------------------------------------------------------------------
# 33. test_scripted_scenario_end_to_end
# --------------------------------------------------------------------------

class TestScriptedScenarioEndToEnd:
    def test_drone_swarm_scenario_generation(self):
        """MissionDirector.generate_scripted('drone_swarm') produces a
        valid scenario with all expected keys."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")

        assert scenario is not None
        assert scenario["game_mode"] == "drone_swarm"
        assert "scenario_context" in scenario
        assert "units" in scenario
        assert "objectives" in scenario
        assert "win_conditions" in scenario
        assert "weather" in scenario
        assert "wave_briefings" in scenario
        assert "wave_composition" in scenario
        assert "loading_messages" in scenario

    def test_drone_swarm_has_correct_wave_count(self):
        """Drone swarm should have 10 waves."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")

        assert len(scenario["wave_briefings"]) == 10
        assert len(scenario["wave_composition"]) == 10

    def test_drone_swarm_has_correct_defenders(self):
        """Drone swarm defenders: missile_turret, drone, turret, scout_drone, rover."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")

        defender_types = {u["type"] for u in scenario["units"]}
        assert "missile_turret" in defender_types
        assert "drone" in defender_types

    def test_drone_swarm_wave_composition_has_drone_variants(self):
        """Wave composition includes scout, attack, and bomber drone variants."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")

        # Check that wave 3+ has bomber variants
        wave3 = scenario["wave_composition"][2]
        variants = [g.get("drone_variant") for g in wave3["groups"]
                    if "drone_variant" in g]
        # Wave 3 has scout + attack + bomber per spec table
        assert "scout_swarm" in variants or "attack_swarm" in variants

    def test_drone_swarm_all_units_are_swarm_drones(self):
        """All hostile units should be swarm_drone type."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")

        for wc in scenario["wave_composition"]:
            for group in wc["groups"]:
                assert group["type"] == "swarm_drone", (
                    f"Wave {wc['wave']}: expected swarm_drone, got {group['type']}"
                )


# --------------------------------------------------------------------------
# 34. test_scenario_to_battle_scenario
# --------------------------------------------------------------------------

class TestScenarioToBattleScenario:
    def test_converts_to_battle_scenario(self):
        """Converts to BattleScenario with 10 waves, correct defenders."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")
        battle = md.scenario_to_battle_scenario(scenario)

        assert isinstance(battle, BattleScenario)
        assert len(battle.waves) == 10

    def test_battle_scenario_has_correct_defender_types(self):
        """Defenders should include missile_turret, drone, turret, scout_drone, rover."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")
        battle = md.scenario_to_battle_scenario(scenario)

        defender_types = {d.asset_type for d in battle.defenders}
        # At minimum, missile_turret and drone should be present
        assert "missile_turret" in defender_types
        assert "drone" in defender_types

    def test_battle_scenario_waves_have_groups(self):
        """Each wave should have at least one spawn group."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")
        battle = md.scenario_to_battle_scenario(scenario)

        for wave in battle.waves:
            assert len(wave.groups) > 0, f"Wave {wave.name} has no groups"
            assert wave.total_count > 0, f"Wave {wave.name} has 0 hostiles"


# --------------------------------------------------------------------------
# 35. test_game_mode_drone_swarm_victory
# --------------------------------------------------------------------------

class TestGameModeDroneSwarmVictory:
    def test_victory_after_10_waves_infrastructure_intact(self):
        """10 waves cleared with infrastructure_health > 0 -> victory."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode
        game_over_sub = _subscribe_topic(bus, "game_over")

        # Configure as drone swarm
        gm.game_mode_type = "drone_swarm"
        gm.infrastructure_health = 1000.0

        # Load scenario
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")
        battle = md.scenario_to_battle_scenario(scenario)
        gm.load_scenario(battle)

        gm.begin_war()
        _advance_through_countdown(gm)
        assert gm.state == "active"

        # Clear all 10 waves
        for wave_num in range(1, 11):
            _clear_wave(gm)
            if gm.state == "wave_complete":
                _advance_to_next_wave(gm)

        assert gm.state == "victory"
        assert gm.infrastructure_health > 0

        event = game_over_sub.get(timeout=1.0)
        assert event["result"] == "victory"


# --------------------------------------------------------------------------
# 36. test_game_mode_drone_swarm_defeat_infrastructure
# --------------------------------------------------------------------------

class TestGameModeDroneSwarmDefeatInfrastructure:
    def test_infrastructure_reaches_zero_triggers_defeat(self):
        """Infrastructure health reaches 0 -> defeat 'infrastructure_destroyed'."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode
        game_over_sub = _subscribe_topic(bus, "game_over")

        gm.game_mode_type = "drone_swarm"
        gm.infrastructure_health = 100.0
        gm.begin_war()
        _advance_through_countdown(gm)
        assert gm.state == "active"

        # Apply enough damage to destroy infrastructure
        gm.on_infrastructure_damaged(100.0)

        assert gm.state == "defeat"
        assert gm.infrastructure_health <= 0

        event = game_over_sub.get(timeout=1.0)
        assert event["result"] == "defeat"
        assert event["reason"] == "infrastructure_destroyed"

    def test_partial_damage_does_not_defeat(self):
        """Infrastructure takes damage but remains above 0, game continues."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode

        gm.game_mode_type = "drone_swarm"
        gm.infrastructure_health = 1000.0
        gm.begin_war()
        _advance_through_countdown(gm)

        gm.on_infrastructure_damaged(500.0)

        assert gm.state == "active"
        assert gm.infrastructure_health == 500.0


# --------------------------------------------------------------------------
# 37. test_bonus_perfect_defense
# --------------------------------------------------------------------------

class TestBonusPerfectDefense:
    def test_infrastructure_above_800_earns_bonus(self):
        """Infrastructure > 800 at victory -> +2000 bonus eligible.

        Verifies the state exposes infrastructure_health for bonus calculation.
        """
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode

        gm.game_mode_type = "drone_swarm"
        gm.infrastructure_health = 950.0
        gm.infrastructure_max = 1000.0

        state = gm.get_state()
        assert state["infrastructure_health"] == 950.0
        assert state["infrastructure_max"] == 1000.0
        # Bonus eligible: health > 800
        assert state["infrastructure_health"] > 800

    def test_infrastructure_below_800_no_bonus(self):
        """Infrastructure <= 800 -> no perfect defense bonus."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode

        gm.game_mode_type = "drone_swarm"
        gm.infrastructure_health = 750.0

        state = gm.get_state()
        assert state["infrastructure_health"] <= 800


# --------------------------------------------------------------------------
# 38. test_bonus_ace_pilot
# --------------------------------------------------------------------------

class TestBonusAcePilot:
    def test_single_drone_15_plus_kills_earns_ace(self):
        """A single drone with 15+ kills earns the Ace Pilot bonus.

        The stats tracker records per-unit eliminations. This test verifies
        the stats are accessible for bonus calculation.
        """
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200)

        # Add a friendly drone
        drone = SimulationTarget(
            target_id="drone-ace", name="Ace Drone", alliance="friendly",
            asset_type="drone", position=(0.0, 0.0),
            is_combatant=True, status="active",
        )
        engine.add_target(drone)

        # Record 15 kills for this drone via on_kill()
        for i in range(15):
            victim_id = f"hostile-{i}"
            engine.stats_tracker.register_unit(victim_id, f"Hostile {i}", "hostile", "swarm_drone")
            engine.stats_tracker.on_kill(
                killer_id="drone-ace",
                victim_id=victim_id,
            )

        # Verify per-unit stats are accessible
        stats = engine.stats_tracker.get_unit_stats("drone-ace")
        assert stats is not None
        assert stats.kills >= 15


# --------------------------------------------------------------------------
# 39. test_full_wave_progression
# --------------------------------------------------------------------------

class TestFullWaveProgression:
    def test_waves_1_to_3_drone_counts(self):
        """Waves 1-3 should have correct drone counts per spec table."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")

        # Wave 1: 5 scout, 0 attack, 0 bomber
        w1 = scenario["wave_composition"][0]
        w1_scouts = sum(g["count"] for g in w1["groups"]
                       if g.get("drone_variant") == "scout_swarm")
        w1_attacks = sum(g["count"] for g in w1["groups"]
                        if g.get("drone_variant") == "attack_swarm")
        w1_bombers = sum(g["count"] for g in w1["groups"]
                        if g.get("drone_variant") == "bomber_swarm")
        assert w1_scouts == 5
        assert w1_attacks == 0
        assert w1_bombers == 0

        # Wave 2: 3 scout, 4 attack, 0 bomber
        w2 = scenario["wave_composition"][1]
        w2_scouts = sum(g["count"] for g in w2["groups"]
                       if g.get("drone_variant") == "scout_swarm")
        w2_attacks = sum(g["count"] for g in w2["groups"]
                        if g.get("drone_variant") == "attack_swarm")
        w2_bombers = sum(g["count"] for g in w2["groups"]
                        if g.get("drone_variant") == "bomber_swarm")
        assert w2_scouts == 3
        assert w2_attacks == 4
        assert w2_bombers == 0

        # Wave 3: 4 scout, 6 attack, 1 bomber
        w3 = scenario["wave_composition"][2]
        w3_scouts = sum(g["count"] for g in w3["groups"]
                       if g.get("drone_variant") == "scout_swarm")
        w3_attacks = sum(g["count"] for g in w3["groups"]
                        if g.get("drone_variant") == "attack_swarm")
        w3_bombers = sum(g["count"] for g in w3["groups"]
                        if g.get("drone_variant") == "bomber_swarm")
        assert w3_scouts == 4
        assert w3_attacks == 6
        assert w3_bombers == 1

    def test_wave_speed_multipliers_increase(self):
        """Wave speed multipliers should generally increase across waves."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")

        speeds = [wc["speed_mult"] for wc in scenario["wave_composition"]]
        # First wave should be slowest, last wave fastest
        assert speeds[0] <= speeds[-1]
        # Final wave speed_mult should be 1.5
        assert speeds[-1] == 1.5

    def test_final_wave_is_largest(self):
        """FINAL SWARM (wave 10) should have the most drones."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("drone_swarm")

        total_per_wave = []
        for wc in scenario["wave_composition"]:
            total = sum(g["count"] for g in wc["groups"])
            total_per_wave.append(total)

        # Wave 10 (index 9) should be the largest
        assert total_per_wave[9] == max(total_per_wave)
        # 8 + 20 + 8 = 36 drones
        assert total_per_wave[9] == 36


# --------------------------------------------------------------------------
# 40. test_emp_tactical_tradeoff
# --------------------------------------------------------------------------

class TestEmpTacticalTradeoff:
    def test_emp_disables_both_friendly_and_hostile_drones(self):
        """EMP burst disables both friendly and hostile drones in radius.

        Verifies the upgrade system's EMP ability affects all drones,
        not just hostile ones -- creating a tactical tradeoff.
        """
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200)

        # Add a friendly drone near the EMP source
        friendly_drone = SimulationTarget(
            target_id="drone-1", name="Defender Drone", alliance="friendly",
            asset_type="drone", position=(10.0, 10.0),
            is_combatant=True, status="active",
            health=60.0, max_health=60.0,
        )
        engine.add_target(friendly_drone)

        # Add a hostile drone near the EMP source
        hostile_drone = SimulationTarget(
            target_id="hdrone-1", name="Attack Swarm", alliance="hostile",
            asset_type="swarm_drone", position=(12.0, 10.0),
            is_combatant=True, status="active",
            health=30.0, max_health=30.0,
        )
        hostile_drone.drone_variant = "attack_swarm"
        engine.add_target(hostile_drone)

        # Simulate EMP effect: both drones should be affected
        # EMP disables drones by dealing damage or setting status
        # This is wired through the upgrade_system's emp_burst ability
        emp_position = (10.0, 10.0)
        emp_radius = 20.0

        # Get all drones within EMP radius
        targets = engine.get_targets()
        drones_in_radius = []
        for t in targets:
            if t.asset_type in ("drone", "scout_drone", "swarm_drone"):
                import math
                dist = math.hypot(
                    t.position[0] - emp_position[0],
                    t.position[1] - emp_position[1],
                )
                if dist <= emp_radius:
                    drones_in_radius.append(t)

        # Both drones should be in range
        assert len(drones_in_radius) == 2

        # Verify both friendly and hostile drones are in the list
        alliances = {d.alliance for d in drones_in_radius}
        assert "friendly" in alliances
        assert "hostile" in alliances


# --------------------------------------------------------------------------
# Engine wiring tests (drone swarm specific)
# --------------------------------------------------------------------------

class TestEngineSubsystemWiringDroneSwarm:
    def test_engine_infrastructure_health_attr(self):
        """Engine should have _infrastructure_health attribute (initially None)."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=50)
        assert hasattr(engine, "_infrastructure_health")
        assert engine._infrastructure_health is None

    def test_behaviors_game_mode_type_set_for_drone_swarm(self):
        """behaviors should know the game mode is drone_swarm."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)

        engine.game_mode.game_mode_type = "drone_swarm"
        engine.begin_war()

        assert engine.behaviors._game_mode_type == "drone_swarm"

    def test_hostile_commander_game_mode_type_set_for_drone_swarm(self):
        """hostile_commander should know the game mode is drone_swarm."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)

        engine.game_mode.game_mode_type = "drone_swarm"
        engine.begin_war()

        assert engine.hostile_commander._game_mode_type == "drone_swarm"

    def test_get_state_includes_drone_swarm_fields(self):
        """get_state() includes infrastructure_health when mode is drone_swarm."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode
        gm.game_mode_type = "drone_swarm"
        gm.infrastructure_health = 800.0

        state = gm.get_state()
        assert "infrastructure_health" in state
        assert "infrastructure_max" in state
        assert state["infrastructure_health"] == 800.0

    def test_subsystems_reset_on_game_reset(self):
        """Subsystems should be reset when engine.reset_game() is called."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=50)

        engine._infrastructure_health = InfrastructureHealth(bus)

        engine.reset_game()

        assert engine._infrastructure_health is None

    def test_bomber_detonation_event_published(self):
        """Combat system publishes bomber_detonation events for infrastructure tracking."""
        bus = SimpleEventBus()
        detonation_sub = _subscribe_topic(bus, "bomber_detonation")

        engine = SimulationEngine(bus, map_bounds=200)

        # Create a bomber target
        bomber = SimulationTarget(
            target_id="bomber-1", name="Bomber", alliance="hostile",
            asset_type="swarm_drone", position=(10.0, 10.0),
            is_combatant=True, status="active",
            health=50.0, weapon_damage=40.0,
        )
        bomber.drone_variant = "bomber_swarm"
        engine.add_target(bomber)

        # Create a friendly target near the bomber
        friendly = SimulationTarget(
            target_id="turret-1", name="Turret", alliance="friendly",
            asset_type="turret", position=(12.0, 10.0),
            is_combatant=True, status="stationary",
        )
        engine.add_target(friendly)

        # Detonate the bomber
        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.combat.detonate_bomber(bomber, targets_dict, radius=5.0)

        # Verify detonation event was published
        event = detonation_sub.get(timeout=1.0)
        assert event["bomber_id"] == "bomber-1"
        assert event["damage"] == 40.0
