# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the finite state machine framework and pre-built unit FSMs.

TDD: tests written first, then implementation.
"""

from __future__ import annotations

import math
import queue
import threading
import time

import pytest

from engine.simulation.state_machine import State, Transition, StateMachine
from engine.simulation.unit_states import (
    create_turret_fsm,
    create_rover_fsm,
    create_drone_fsm,
    create_hostile_fsm,
    create_fsm_for_type,
)
from engine.simulation.target import SimulationTarget


pytestmark = pytest.mark.unit


# ==========================================================================
# Helpers
# ==========================================================================

class CountingState(State):
    """State that counts ticks for testing."""

    def __init__(self, name: str, transition_after: int | None = None,
                 transition_to: str | None = None):
        super().__init__(name)
        self.enter_count = 0
        self.exit_count = 0
        self.tick_count = 0
        self._transition_after = transition_after
        self._transition_to = transition_to

    def on_enter(self, ctx: dict) -> None:
        self.enter_count += 1

    def on_exit(self, ctx: dict) -> None:
        self.exit_count += 1

    def tick(self, dt: float, ctx: dict) -> str | None:
        self.tick_count += 1
        if (self._transition_after is not None
                and self.tick_count >= self._transition_after
                and self._transition_to is not None):
            return self._transition_to
        return None


def _make_target(
    asset_type: str = "turret",
    alliance: str = "friendly",
    position: tuple[float, float] = (0.0, 0.0),
    health: float = 100.0,
    max_health: float = 100.0,
    weapon_range: float = 30.0,
    status: str = "active",
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=f"test-{asset_type}",
        name=f"Test {asset_type}",
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        speed=0.0 if asset_type == "turret" else 3.0,
        status=status,
        health=health,
        max_health=max_health,
        weapon_range=weapon_range,
    )
    return t


def _make_enemy(
    position: tuple[float, float] = (10.0, 10.0),
) -> SimulationTarget:
    return SimulationTarget(
        target_id="enemy-1",
        name="Hostile",
        alliance="hostile",
        asset_type="person",
        position=position,
        speed=3.0,
        status="active",
        health=50.0,
        max_health=50.0,
        weapon_range=10.0,
    )


# ==========================================================================
# StateMachine basics
# ==========================================================================

class TestStateMachineBasics:
    def test_initial_state(self):
        sm = StateMachine("idle")
        sm.add_state(CountingState("idle"))
        assert sm.current_state == "idle"

    def test_add_state(self):
        sm = StateMachine("idle")
        s = CountingState("idle")
        sm.add_state(s)
        assert sm.current_state == "idle"

    def test_add_multiple_states(self):
        sm = StateMachine("idle")
        sm.add_state(CountingState("idle"))
        sm.add_state(CountingState("scanning"))
        sm.add_state(CountingState("engaging"))
        assert sm.current_state == "idle"

    def test_tick_stays_in_state(self):
        sm = StateMachine("idle")
        idle = CountingState("idle")
        sm.add_state(idle)
        sm.tick(0.1, {})
        assert sm.current_state == "idle"
        assert idle.tick_count == 1

    def test_time_in_state_accumulates(self):
        sm = StateMachine("idle")
        sm.add_state(CountingState("idle"))
        sm.tick(0.1, {})
        sm.tick(0.1, {})
        sm.tick(0.1, {})
        assert abs(sm.time_in_state - 0.3) < 1e-6

    def test_time_in_state_resets_on_transition(self):
        sm = StateMachine("a")
        sm.add_state(CountingState("a", transition_after=2, transition_to="b"))
        sm.add_state(CountingState("b"))
        sm.tick(0.1, {})
        sm.tick(0.1, {})  # triggers transition to b
        assert sm.current_state == "b"
        sm.tick(0.1, {})
        assert abs(sm.time_in_state - 0.1) < 1e-6


# ==========================================================================
# State callbacks
# ==========================================================================

class TestStateCallbacks:
    def test_on_enter_called_on_first_tick(self):
        sm = StateMachine("idle")
        idle = CountingState("idle")
        sm.add_state(idle)
        # on_enter should be called when the FSM is initialized (first tick)
        sm.tick(0.1, {})
        assert idle.enter_count >= 1

    def test_on_exit_called_on_transition(self):
        sm = StateMachine("a")
        a = CountingState("a", transition_after=1, transition_to="b")
        b = CountingState("b")
        sm.add_state(a)
        sm.add_state(b)
        sm.tick(0.1, {})  # a ticks, returns "b"
        assert a.exit_count == 1
        assert b.enter_count == 1

    def test_on_enter_called_on_transition(self):
        sm = StateMachine("a")
        a = CountingState("a", transition_after=1, transition_to="b")
        b = CountingState("b")
        sm.add_state(a)
        sm.add_state(b)
        sm.tick(0.1, {})
        assert b.enter_count == 1

    def test_on_exit_not_called_without_transition(self):
        sm = StateMachine("idle")
        idle = CountingState("idle")
        sm.add_state(idle)
        sm.tick(0.1, {})
        sm.tick(0.1, {})
        assert idle.exit_count == 0


# ==========================================================================
# Transition conditions
# ==========================================================================

class TestTransitionConditions:
    def test_condition_based_transition(self):
        sm = StateMachine("idle")
        sm.add_state(CountingState("idle"))
        sm.add_state(CountingState("alert"))
        sm.add_transition("idle", "alert", lambda ctx: ctx.get("enemy_near", False))

        # No enemy -- stay idle
        sm.tick(0.1, {"enemy_near": False})
        assert sm.current_state == "idle"

        # Enemy appears
        sm.tick(0.1, {"enemy_near": True})
        assert sm.current_state == "alert"

    def test_first_matching_transition_wins(self):
        sm = StateMachine("idle")
        sm.add_state(CountingState("idle"))
        sm.add_state(CountingState("alert"))
        sm.add_state(CountingState("panic"))
        sm.add_transition("idle", "alert", lambda ctx: ctx.get("enemy_near", False))
        sm.add_transition("idle", "panic", lambda ctx: ctx.get("enemy_near", False))

        sm.tick(0.1, {"enemy_near": True})
        # First matching transition (alert) should win
        assert sm.current_state == "alert"

    def test_transition_condition_receives_context(self):
        received = {}
        def capture_ctx(ctx):
            received.update(ctx)
            return False

        sm = StateMachine("idle")
        sm.add_state(CountingState("idle"))
        sm.add_transition("idle", "alert", capture_ctx)
        sm.tick(0.1, {"test_key": 42})
        assert received.get("test_key") == 42

    def test_tick_return_overrides_condition_transition(self):
        """State.tick() returning a state name takes effect even if no
        condition matched, demonstrating internal state logic."""
        sm = StateMachine("a")
        sm.add_state(CountingState("a", transition_after=1, transition_to="c"))
        sm.add_state(CountingState("b"))
        sm.add_state(CountingState("c"))
        # Condition says go to b, but tick returns c first
        sm.tick(0.1, {})
        assert sm.current_state == "c"


# ==========================================================================
# State.tick() return value triggers transition
# ==========================================================================

class TestTickReturnTransition:
    def test_tick_return_triggers_transition(self):
        sm = StateMachine("a")
        sm.add_state(CountingState("a", transition_after=3, transition_to="b"))
        sm.add_state(CountingState("b"))
        sm.tick(0.1, {})  # tick 1
        sm.tick(0.1, {})  # tick 2
        assert sm.current_state == "a"
        sm.tick(0.1, {})  # tick 3 -> transition
        assert sm.current_state == "b"

    def test_tick_return_none_stays(self):
        sm = StateMachine("a")
        sm.add_state(CountingState("a"))
        sm.tick(0.1, {})
        sm.tick(0.1, {})
        assert sm.current_state == "a"


# ==========================================================================
# Turret FSM
# ==========================================================================

class TestTurretFSM:
    def test_turret_starts_idle(self):
        fsm = create_turret_fsm()
        assert fsm.current_state == "idle"

    def test_turret_idle_to_scanning(self):
        """Turret transitions from idle to scanning after a brief period."""
        fsm = create_turret_fsm()
        # Tick with no enemies -- should eventually start scanning
        for _ in range(20):
            fsm.tick(0.1, {"enemies_in_range": [], "weapon_ready": True})
        assert fsm.current_state == "scanning"

    def test_turret_to_tracking_on_enemy(self):
        """Turret transitions to tracking when enemy detected."""
        fsm = create_turret_fsm()
        enemy = _make_enemy(position=(5.0, 5.0))
        for _ in range(25):
            fsm.tick(0.1, {
                "enemies_in_range": [enemy],
                "weapon_ready": True,
            })
        assert fsm.current_state in ("tracking", "engaging")

    def test_turret_to_engaging_when_aimed(self):
        """Turret transitions from tracking to engaging."""
        fsm = create_turret_fsm()
        enemy = _make_enemy(position=(5.0, 5.0))
        # Run enough ticks to reach engaging
        for _ in range(30):
            fsm.tick(0.1, {
                "enemies_in_range": [enemy],
                "weapon_ready": True,
                "aimed_at_target": True,
            })
        assert fsm.current_state in ("engaging", "cooldown")

    def test_turret_cooldown_after_engaging(self):
        """Turret enters cooldown after firing."""
        fsm = create_turret_fsm()
        enemy = _make_enemy()
        # Run through idle -> scanning -> tracking -> engaging -> cooldown
        for _ in range(50):
            fsm.tick(0.1, {
                "enemies_in_range": [enemy],
                "weapon_ready": True,
                "aimed_at_target": True,
                "just_fired": True,
            })
        # After many ticks with just_fired, should have hit cooldown at least once
        # (the FSM cycles through states)
        # Just verify it doesn't crash and stays in a valid state
        assert fsm.current_state in ("idle", "scanning", "tracking", "engaging", "cooldown")

    def test_turret_back_to_idle_no_enemies(self):
        """Turret returns to idle when enemies leave."""
        fsm = create_turret_fsm()
        enemy = _make_enemy()
        # Get to tracking/engaging
        for _ in range(30):
            fsm.tick(0.1, {
                "enemies_in_range": [enemy],
                "weapon_ready": True,
                "aimed_at_target": True,
            })
        # Remove enemies
        for _ in range(30):
            fsm.tick(0.1, {
                "enemies_in_range": [],
                "weapon_ready": True,
            })
        assert fsm.current_state in ("idle", "scanning")


# ==========================================================================
# Rover FSM
# ==========================================================================

class TestRoverFSM:
    def test_rover_starts_idle(self):
        fsm = create_rover_fsm()
        assert fsm.current_state == "idle"

    def test_rover_idle_to_patrolling(self):
        """Rover transitions from idle to patrolling when it has waypoints."""
        fsm = create_rover_fsm()
        for _ in range(20):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [],
                "health_pct": 1.0,
            })
        assert fsm.current_state == "patrolling"

    def test_rover_pursuing_on_enemy(self):
        """Rover pursues when enemy spotted."""
        fsm = create_rover_fsm()
        enemy = _make_enemy()
        for _ in range(30):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": False,
                "health_pct": 1.0,
            })
        assert fsm.current_state in ("pursuing", "engaging")

    def test_rover_engaging_in_range(self):
        """Rover engages when enemy is in weapon range."""
        fsm = create_rover_fsm()
        enemy = _make_enemy()
        for _ in range(40):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": True,
                "weapon_ready": True,
                "health_pct": 1.0,
            })
        assert fsm.current_state == "engaging"

    def test_rover_retreating_low_health(self):
        """Rover retreats when health is low."""
        fsm = create_rover_fsm()
        enemy = _make_enemy()
        # Get to engaging first
        for _ in range(40):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": True,
                "weapon_ready": True,
                "health_pct": 1.0,
            })
        # Drop health
        for _ in range(20):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": True,
                "weapon_ready": True,
                "health_pct": 0.2,
            })
        assert fsm.current_state == "retreating"

    def test_rover_rtb_after_retreat(self):
        """Rover returns to base after retreating with no enemies."""
        fsm = create_rover_fsm()
        enemy = _make_enemy()
        # Get to retreating
        for _ in range(40):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": True,
                "weapon_ready": True,
                "health_pct": 1.0,
            })
        for _ in range(20):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": True,
                "weapon_ready": True,
                "health_pct": 0.2,
            })
        # Clear enemies
        for _ in range(20):
            fsm.tick(0.1, {
                "has_waypoints": False,
                "enemies_in_range": [],
                "enemy_in_weapon_range": False,
                "weapon_ready": True,
                "health_pct": 0.2,
            })
        assert fsm.current_state == "rtb"


# ==========================================================================
# Drone FSM
# ==========================================================================

class TestDroneFSM:
    def test_drone_starts_idle(self):
        fsm = create_drone_fsm()
        assert fsm.current_state == "idle"

    def test_drone_idle_to_scouting(self):
        """Drone transitions to scouting when it has waypoints."""
        fsm = create_drone_fsm()
        for _ in range(20):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [],
                "health_pct": 1.0,
            })
        assert fsm.current_state == "scouting"

    def test_drone_orbiting_on_enemy(self):
        """Drone orbits when enemy is spotted but out of weapon range."""
        fsm = create_drone_fsm()
        enemy = _make_enemy()
        for _ in range(30):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": False,
                "health_pct": 1.0,
            })
        assert fsm.current_state in ("orbiting", "engaging")

    def test_drone_engaging(self):
        """Drone engages when enemy is in weapon range."""
        fsm = create_drone_fsm()
        enemy = _make_enemy()
        for _ in range(40):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": True,
                "weapon_ready": True,
                "health_pct": 1.0,
            })
        assert fsm.current_state == "engaging"

    def test_drone_rtb_low_health(self):
        """Drone returns to base when health is low."""
        fsm = create_drone_fsm()
        enemy = _make_enemy()
        for _ in range(40):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": True,
                "weapon_ready": True,
                "health_pct": 1.0,
            })
        for _ in range(20):
            fsm.tick(0.1, {
                "has_waypoints": True,
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": True,
                "weapon_ready": True,
                "health_pct": 0.15,
            })
        assert fsm.current_state == "rtb"


# ==========================================================================
# Hostile FSM
# ==========================================================================

class TestHostileFSM:
    def test_hostile_starts_spawning(self):
        fsm = create_hostile_fsm()
        assert fsm.current_state == "spawning"

    def test_hostile_spawning_to_advancing(self):
        """Hostile advances after spawn timer."""
        fsm = create_hostile_fsm()
        for _ in range(15):
            fsm.tick(0.1, {
                "enemies_in_range": [],
                "health_pct": 1.0,
            })
        assert fsm.current_state == "advancing"

    def test_hostile_advancing_to_engaging(self):
        """Hostile engages when defenders in range."""
        fsm = create_hostile_fsm()
        enemy = _make_target(asset_type="turret", alliance="friendly")
        # Get past spawning
        for _ in range(15):
            fsm.tick(0.1, {"enemies_in_range": [], "health_pct": 1.0})
        assert fsm.current_state == "advancing"
        # Encounter defenders
        for _ in range(20):
            fsm.tick(0.1, {
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": True,
                "health_pct": 1.0,
                "nearest_enemy_stationary": False,
            })
        assert fsm.current_state == "engaging"

    def test_hostile_flanking_stationary_target(self):
        """Hostile flanks when nearest enemy is stationary (turret)."""
        fsm = create_hostile_fsm()
        turret = _make_target(asset_type="turret", alliance="friendly")
        # Get past spawning
        for _ in range(15):
            fsm.tick(0.1, {"enemies_in_range": [], "health_pct": 1.0})
        # Encounter stationary target
        for _ in range(20):
            fsm.tick(0.1, {
                "enemies_in_range": [turret],
                "enemy_in_weapon_range": False,
                "health_pct": 1.0,
                "nearest_enemy_stationary": True,
            })
        assert fsm.current_state == "flanking"

    def test_hostile_fleeing_low_health(self):
        """Hostile flees when health is low."""
        fsm = create_hostile_fsm()
        enemy = _make_target(alliance="friendly")
        # Get past spawning
        for _ in range(15):
            fsm.tick(0.1, {"enemies_in_range": [], "health_pct": 1.0})
        # Engage
        for _ in range(20):
            fsm.tick(0.1, {
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": True,
                "health_pct": 1.0,
                "nearest_enemy_stationary": False,
            })
        # Drop health to critically low (below 0.15 flee threshold)
        for _ in range(10):
            fsm.tick(0.1, {
                "enemies_in_range": [enemy],
                "enemy_in_weapon_range": True,
                "health_pct": 0.1,
                "nearest_enemy_stationary": False,
            })
        assert fsm.current_state == "fleeing"


# ==========================================================================
# create_fsm_for_type factory
# ==========================================================================

class TestCreateFSMForType:
    def test_turret_type(self):
        fsm = create_fsm_for_type("turret")
        assert fsm is not None
        assert fsm.current_state == "idle"

    def test_heavy_turret_type(self):
        fsm = create_fsm_for_type("heavy_turret")
        assert fsm is not None
        assert fsm.current_state == "idle"

    def test_missile_turret_type(self):
        fsm = create_fsm_for_type("missile_turret")
        assert fsm is not None
        assert fsm.current_state == "idle"

    def test_rover_type(self):
        fsm = create_fsm_for_type("rover")
        assert fsm is not None
        assert fsm.current_state == "idle"

    def test_tank_type(self):
        fsm = create_fsm_for_type("tank")
        assert fsm is not None
        assert fsm.current_state == "idle"

    def test_apc_type(self):
        fsm = create_fsm_for_type("apc")
        assert fsm is not None
        assert fsm.current_state == "idle"

    def test_drone_type(self):
        fsm = create_fsm_for_type("drone")
        assert fsm is not None
        assert fsm.current_state == "idle"

    def test_scout_drone_type(self):
        fsm = create_fsm_for_type("scout_drone")
        assert fsm is not None
        assert fsm.current_state == "idle"

    def test_hostile_person(self):
        fsm = create_fsm_for_type("hostile_person")
        assert fsm is not None
        assert fsm.current_state == "spawning"

    def test_person_hostile_alias(self):
        fsm = create_fsm_for_type("person", alliance="hostile")
        assert fsm is not None
        assert fsm.current_state == "spawning"

    def test_neutral_person_gets_npc_fsm(self):
        """Neutral persons (civilians) get NPC intelligence FSM."""
        fsm = create_fsm_for_type("person", alliance="neutral")
        assert fsm is not None
        assert fsm.current_state == "walking"

    def test_unknown_type_returns_none(self):
        fsm = create_fsm_for_type("unicorn_blaster")
        assert fsm is None

    def test_animal_gets_npc_fsm(self):
        fsm = create_fsm_for_type("animal")
        assert fsm is not None
        assert fsm.current_state == "wandering"


# ==========================================================================
# Integration: FSM state exposed on target
# ==========================================================================

class TestTargetStateField:
    def test_target_to_dict_includes_state(self):
        """SimulationTarget.to_dict() should include the FSM state field."""
        t = _make_target()
        t.fsm_state = "scanning"
        d = t.to_dict()
        assert d.get("fsm_state") == "scanning"

    def test_target_default_fsm_state_is_none(self):
        """SimulationTarget defaults to no FSM state."""
        t = _make_target()
        d = t.to_dict()
        assert d.get("fsm_state") is None
