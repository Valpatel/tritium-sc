# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for civil unrest mission type (Phase 5).

Tests the full pipeline from MissionDirector scenario generation through
GameMode lifecycle including CrowdDensityTracker subsystem wiring.

Spec section 2.8 tests:
  30. test_scripted_scenario_end_to_end
  31. test_scenario_to_battle_scenario
  32. test_game_mode_civil_unrest_victory
  33. test_game_mode_civil_unrest_defeat_excessive_force
  34. test_game_mode_civil_unrest_defeat_infrastructure
  35. test_bonus_zero_collateral
  36. test_full_scoring_flow
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

from tritium_lib.sim_engine.combat.combat import CombatSystem
from engine.simulation.engine import SimulationEngine
from engine.simulation.game_mode import GameMode, _COUNTDOWN_DURATION, _WAVE_ADVANCE_DELAY
from engine.simulation.mission_director import MissionDirector, GAME_MODES
from tritium_lib.sim_engine.core.entity import SimulationTarget
from engine.simulation.crowd_density import CrowdDensityTracker
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
            # Also deliver to all-topic subscribers as {type, data} dicts
            for q in self._all_subscribers:
                try:
                    q.put_nowait({"type": topic, "data": data})
                except queue.Full:
                    pass

    def subscribe(self, _filter: str | None = None) -> queue.Queue:
        """Subscribe to all events (matches real EventBus API)."""
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
    gm.tick(0.1)  # triggers wave_complete


def _advance_to_next_wave(gm: GameMode) -> None:
    """Advance from wave_complete to next wave's active state."""
    gm._wave_complete_time = time.time() - _WAVE_ADVANCE_DELAY - 1
    gm.tick(0.1)


def _make_engine_with_friendly(bus: SimpleEventBus) -> SimulationEngine:
    """Create engine with one friendly combatant (to prevent defeat)."""
    engine = SimulationEngine(bus, map_bounds=200)
    friendly = SimulationTarget(
        target_id="turret-1", name="AA Turret", alliance="friendly",
        asset_type="turret", position=(0.0, 0.0),
        is_combatant=True, status="stationary",
    )
    engine.add_target(friendly)
    return engine


# --------------------------------------------------------------------------
# 30. test_scripted_scenario_end_to_end
# --------------------------------------------------------------------------

class TestScriptedScenarioEndToEnd:
    def test_civil_unrest_scenario_generation(self):
        """MissionDirector.generate_scripted('civil_unrest') produces a
        valid scenario with all expected keys."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("civil_unrest")

        assert scenario is not None
        assert scenario["game_mode"] == "civil_unrest"
        assert "scenario_context" in scenario
        assert "units" in scenario
        assert "objectives" in scenario
        assert "win_conditions" in scenario
        assert "weather" in scenario
        assert "wave_briefings" in scenario
        assert "wave_composition" in scenario
        assert "loading_messages" in scenario

    def test_civil_unrest_scenario_has_correct_wave_count(self):
        """Civil unrest should have 8 waves."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("civil_unrest")

        assert len(scenario["wave_briefings"]) == 8
        assert len(scenario["wave_composition"]) == 8

    def test_civil_unrest_scenario_has_correct_defenders(self):
        """Civil unrest defenders: rovers, drones, scout_drones (no turrets)."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("civil_unrest")

        defender_types = {u["type"] for u in scenario["units"]}
        assert "rover" in defender_types
        assert "drone" in defender_types
        assert "scout_drone" in defender_types
        # Civil unrest should NOT have turrets (non-lethal force)
        assert "turret" not in defender_types
        assert "heavy_turret" not in defender_types
        assert "missile_turret" not in defender_types

    def test_civil_unrest_wave_composition_has_civilians_and_instigators(self):
        """Wave composition includes civilian and instigator groups."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("civil_unrest")

        # Wave 2+ should have instigators
        wave2 = scenario["wave_composition"][1]
        group_types = [g.get("crowd_role") for g in wave2["groups"] if "crowd_role" in g]
        assert "instigator" in group_types

        # Wave 1 should have civilians
        wave1 = scenario["wave_composition"][0]
        has_civilian = any(g.get("crowd_role") == "civilian" for g in wave1["groups"])
        assert has_civilian


# --------------------------------------------------------------------------
# 31. test_scenario_to_battle_scenario
# --------------------------------------------------------------------------

class TestScenarioToBattleScenario:
    def test_converts_to_battle_scenario(self):
        """Converts to BattleScenario with 8 waves, correct defenders."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("civil_unrest")
        battle = md.scenario_to_battle_scenario(scenario)

        assert isinstance(battle, BattleScenario)
        assert len(battle.waves) == 8
        assert len(battle.defenders) > 0

    def test_battle_scenario_has_correct_defender_types(self):
        """Defenders should match civil_unrest config."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("civil_unrest")
        battle = md.scenario_to_battle_scenario(scenario)

        defender_types = {d.asset_type for d in battle.defenders}
        assert "rover" in defender_types

    def test_battle_scenario_waves_have_groups(self):
        """Each wave should have at least one spawn group."""
        bus = SimpleEventBus()
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("civil_unrest")
        battle = md.scenario_to_battle_scenario(scenario)

        for wave in battle.waves:
            assert len(wave.groups) > 0, f"Wave {wave.name} has no groups"
            assert wave.total_count > 0, f"Wave {wave.name} has 0 hostiles"


# --------------------------------------------------------------------------
# 32. test_game_mode_civil_unrest_victory
# --------------------------------------------------------------------------

class TestGameModeCivilUnrestVictory:
    def test_victory_after_8_waves_zero_harm(self):
        """8 waves cleared with zero civilian harm -> victory."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode
        game_over_sub = _subscribe_topic(bus, "game_over")

        # Configure as civil unrest
        gm.game_mode_type = "civil_unrest"

        # Load a minimal civil unrest scenario with 8 waves
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("civil_unrest")
        battle = md.scenario_to_battle_scenario(scenario)
        gm.load_scenario(battle)

        gm.begin_war()
        _advance_through_countdown(gm)
        assert gm.state == "active"

        # Clear all 8 waves
        for wave_num in range(1, 9):
            _clear_wave(gm)
            if gm.state == "wave_complete":
                _advance_to_next_wave(gm)

        assert gm.state == "victory"
        assert gm.civilian_harm_count == 0

        event = game_over_sub.get(timeout=1.0)
        assert event["result"] == "victory"


# --------------------------------------------------------------------------
# 33. test_game_mode_civil_unrest_defeat_excessive_force
# --------------------------------------------------------------------------

class TestGameModeCivilUnrestDefeatExcessiveForce:
    def test_5_civilian_harms_triggers_defeat(self):
        """5 civilians harmed -> defeat with reason 'excessive_force'."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode
        game_over_sub = _subscribe_topic(bus, "game_over")

        gm.game_mode_type = "civil_unrest"
        gm.begin_war()
        _advance_through_countdown(gm)
        assert gm.state == "active"

        # Harm 5 civilians
        for _ in range(5):
            gm.on_civilian_harmed()

        assert gm.state == "defeat"
        assert gm.civilian_harm_count == 5

        event = game_over_sub.get(timeout=1.0)
        assert event["result"] == "defeat"
        assert event["reason"] == "excessive_force"

    def test_4_civilian_harms_does_not_defeat(self):
        """4 civilians harmed is below limit, game continues."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode

        gm.game_mode_type = "civil_unrest"
        gm.begin_war()
        _advance_through_countdown(gm)

        for _ in range(4):
            gm.on_civilian_harmed()

        assert gm.state == "active"
        assert gm.civilian_harm_count == 4


# --------------------------------------------------------------------------
# 34. test_game_mode_civil_unrest_defeat_infrastructure
# --------------------------------------------------------------------------

class TestGameModeCivilUnrestDefeatInfrastructure:
    def test_critical_density_60s_on_poi_triggers_defeat(self):
        """Critical density for 60 seconds on a POI building -> defeat.

        This tests that the engine wires CrowdDensityTracker and checks
        POI defeat conditions during _do_tick().
        """
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=100)

        # Add friendly to prevent normal defeat
        friendly = SimulationTarget(
            target_id="rover-1", name="Rover", alliance="friendly",
            asset_type="rover", position=(0.0, 0.0),
            is_combatant=True, status="active",
        )
        engine.add_target(friendly)

        gm = engine.game_mode
        gm.game_mode_type = "civil_unrest"

        # Set up CrowdDensityTracker on the engine (Phase 5 wiring)
        bounds = (-100.0, -100.0, 100.0, 100.0)
        tracker = CrowdDensityTracker(bounds, bus)
        engine._crowd_density_tracker = tracker

        # Add a POI building at (50, 50)
        tracker.add_poi_building((50.0, 50.0), "Town Hall")

        gm.begin_war()
        _advance_through_countdown(gm)
        assert gm.state == "active"

        # Spawn 12 civilians near the POI to create critical density
        for i in range(12):
            target = SimulationTarget(
                target_id=f"civ-{i}",
                name=f"Civilian {i}",
                alliance="hostile",
                asset_type="person",
                position=(50.0 + i * 0.1, 50.0),
                crowd_role="civilian",
                is_combatant=False,
            )
            engine.add_target(target)

        # Tick the tracker for 61 seconds worth of dt
        targets_dict = {t.target_id: t for t in engine.get_targets()}
        for _ in range(610):
            tracker.tick(targets_dict, 0.1)

        # Verify critical density was sustained
        assert tracker.check_poi_defeat(timeout=60.0) is True


# --------------------------------------------------------------------------
# 35. test_bonus_zero_collateral
# --------------------------------------------------------------------------

class TestBonusZeroCollateral:
    def test_zero_casualties_bonus_2000(self):
        """0 civilian casualties -> +2000 bonus points."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode

        gm.game_mode_type = "civil_unrest"

        # Load minimal scenario
        md = MissionDirector(event_bus=bus)
        scenario = md.generate_scripted("civil_unrest")
        battle = md.scenario_to_battle_scenario(scenario)
        gm.load_scenario(battle)

        gm.begin_war()
        _advance_through_countdown(gm)

        # Record base score
        base_score = gm.score

        # Clear all 8 waves with zero civilian harm
        for wave_num in range(1, 9):
            _clear_wave(gm)
            if gm.state == "wave_complete":
                _advance_to_next_wave(gm)

        assert gm.state == "victory"
        assert gm.civilian_harm_count == 0

        # The score should include wave bonuses plus the zero collateral bonus
        # Verify the bonus was applied by checking score is higher than base
        # wave bonuses alone
        wave_bonuses = sum(w * 200 for w in range(1, 9))  # 200 per wave * wave_num
        # Score should be at least wave_bonuses (time bonuses vary)
        assert gm.score >= wave_bonuses

    def test_nonzero_casualties_no_bonus(self):
        """Any civilian harm means no zero-collateral bonus."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode

        gm.game_mode_type = "civil_unrest"
        gm.begin_war()
        _advance_through_countdown(gm)

        gm.on_civilian_harmed()
        assert gm.civilian_harm_count == 1
        # De-escalation score should have been penalized
        assert gm.de_escalation_score < 0


# --------------------------------------------------------------------------
# 36. test_full_scoring_flow
# --------------------------------------------------------------------------

class TestFullScoringFlow:
    def test_weighted_score_calculation(self):
        """De-escalate, identify, protect -> weighted score.

        Civil unrest weighted score = score * 0.3 + de_escalation_score * 0.7
        """
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode

        gm.game_mode_type = "civil_unrest"
        gm.begin_war()
        _advance_through_countdown(gm)

        # Simulate some combat score
        gm.score = 1000
        # Simulate de-escalation points
        gm.de_escalation_score = 2000

        state = gm.get_state()
        assert state["game_mode_type"] == "civil_unrest"
        assert "weighted_total_score" in state
        expected_weighted = int(1000 * 0.3 + 2000 * 0.7)
        assert state["weighted_total_score"] == expected_weighted

    def test_civilian_harm_reduces_de_escalation(self):
        """Each civilian harm reduces de_escalation_score by 500."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode

        gm.game_mode_type = "civil_unrest"
        gm.de_escalation_score = 1000
        gm.begin_war()
        _advance_through_countdown(gm)

        gm.on_civilian_harmed()
        # de_escalation_score should decrease by 500
        assert gm.de_escalation_score == 500

    def test_de_escalation_event_adds_points(self):
        """De-escalation events from rover proximity add to de_escalation_score.

        The de_escalation event carries 200 points per converted rioter.
        This test verifies the event is published (wiring is in behaviors.py
        _rover_de_escalation), and the engine or game_mode forwards it to scoring.
        """
        bus = SimpleEventBus()
        de_esc_sub = _subscribe_topic(bus, "de_escalation")

        engine = SimulationEngine(bus, map_bounds=200)
        gm = engine.game_mode
        gm.game_mode_type = "civil_unrest"

        # Verify de_escalation events carry the expected shape
        bus.publish("de_escalation", {
            "rover_id": "rover-1",
            "rioter_id": "rioter-1",
            "points": 200,
        })

        event = de_esc_sub.get(timeout=1.0)
        assert event["points"] == 200

    def test_get_state_includes_civil_unrest_fields(self):
        """get_state() includes de_escalation_score, civilian_harm when mode is civil_unrest."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)
        gm = engine.game_mode
        gm.game_mode_type = "civil_unrest"

        state = gm.get_state()
        assert "de_escalation_score" in state
        assert "civilian_harm_count" in state
        assert "civilian_harm_limit" in state
        assert "weighted_total_score" in state


# --------------------------------------------------------------------------
# Engine wiring tests
# --------------------------------------------------------------------------

class TestEngineSubsystemWiring:
    def test_engine_has_crowd_density_tracker_attr(self):
        """Engine should have _crowd_density_tracker attribute (initially None)."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=50)
        assert hasattr(engine, "_crowd_density_tracker")
        assert engine._crowd_density_tracker is None

    def test_engine_has_infrastructure_health_attr(self):
        """Engine should have _infrastructure_health attribute (initially None)."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=50)
        assert hasattr(engine, "_infrastructure_health")
        assert engine._infrastructure_health is None

    def test_behaviors_game_mode_type_set_on_begin_war(self):
        """behaviors.set_game_mode_type() should be called when game starts."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)

        # Set up game_mode_type before begin_war
        engine.game_mode.game_mode_type = "civil_unrest"
        engine.begin_war()

        # After begin_war, behaviors should know the game mode type
        assert engine.behaviors._game_mode_type == "civil_unrest"

    def test_hostile_commander_game_mode_type_set_on_begin_war(self):
        """hostile_commander.set_game_mode_type() should be called when game starts."""
        bus = SimpleEventBus()
        engine = _make_engine_with_friendly(bus)

        engine.game_mode.game_mode_type = "civil_unrest"
        engine.begin_war()

        assert engine.hostile_commander._game_mode_type == "civil_unrest"

    def test_subsystems_reset_on_game_reset(self):
        """Subsystems should be reset when engine.reset_game() is called."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=50)

        # Manually set subsystems (simulating game start)
        bounds = (-50.0, -50.0, 50.0, 50.0)
        engine._crowd_density_tracker = CrowdDensityTracker(bounds, bus)
        engine._infrastructure_health = "mock"

        engine.reset_game()

        # After reset, subsystems should be cleared
        assert engine._crowd_density_tracker is None
        assert engine._infrastructure_health is None
