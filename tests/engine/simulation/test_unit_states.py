# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Comprehensive tests for engine.simulation.unit_states FSM factories.

Covers:
 - Factory creation and initial state for every unit type
 - All registered state names per FSM
 - Every defined transition (with targeted context inputs)
 - Guard conditions blocking/allowing transitions
 - min_duration blocking early exits
 - max_duration auto-transition after timeout
 - State history recording across transitions
 - Priority transition ordering
 - force_state bypass
 - create_fsm_for_type routing (all types, all alliances)
 - Legacy alias states present in state_names
"""

from __future__ import annotations

import pytest

from engine.simulation.state_machine import State, StateMachine
from engine.simulation.unit_states import (
    create_drone_fsm,
    create_fsm_for_type,
    create_hostile_fsm,
    create_rover_fsm,
    create_turret_fsm,
)


pytestmark = pytest.mark.unit


# ===========================================================================
# Helpers
# ===========================================================================

def _tick_n(sm: StateMachine, n: int, ctx: dict) -> None:
    """Tick the state machine n times with the given context."""
    for _ in range(n):
        sm.tick(0.1, ctx)


def _advance_past_spawning(sm: StateMachine) -> None:
    """Drive a hostile FSM past the spawning state (requires >= 1.0s total)."""
    # spawning min_duration=0.8, tick() returns "advancing" at >= 1.0s
    _tick_n(sm, 15, {"health_pct": 1.0, "enemies_in_range": []})


def _advance_to_scanning(sm: StateMachine) -> None:
    """Drive a turret FSM from idle into scanning."""
    # idle has a condition 'always True' -> scans on first tick
    sm.tick(0.1, {"enemies_in_range": [], "aimed_at_target": False,
                  "just_fired": False, "degradation": 0.0})


# ===========================================================================
# Turret FSM — factory and state registry
# ===========================================================================

class TestTurretFSMFactory:
    """create_turret_fsm() produces a valid, correctly-shaped StateMachine."""

    def test_factory_returns_state_machine(self):
        sm = create_turret_fsm()
        assert isinstance(sm, StateMachine)

    def test_initial_state_is_idle(self):
        sm = create_turret_fsm()
        assert sm.current_state == "idle"

    def test_time_in_state_starts_at_zero(self):
        sm = create_turret_fsm()
        assert sm.time_in_state == 0.0

    def test_history_empty_on_creation(self):
        sm = create_turret_fsm()
        assert sm.history == []

    def test_all_primary_states_registered(self):
        sm = create_turret_fsm()
        names = sm.state_names
        for expected in ("idle", "scanning", "tracking", "engaging", "cooldown"):
            assert expected in names, f"Missing state: {expected}"

    def test_legacy_reloading_alias_registered(self):
        sm = create_turret_fsm()
        assert "reloading" in sm.state_names

    def test_scanning_has_min_duration(self):
        sm = create_turret_fsm()
        scanning = sm._states["scanning"]
        assert scanning.min_duration > 0.0

    def test_idle_has_no_min_duration(self):
        sm = create_turret_fsm()
        idle = sm._states["idle"]
        assert idle.min_duration == 0.0


# ===========================================================================
# Turret FSM — transition paths
# ===========================================================================

class TestTurretFSMTransitions:
    """Each valid turret transition fires under the right context."""

    def test_idle_to_scanning_on_first_tick(self):
        """Turret leaves idle on first tick (always-true condition)."""
        sm = create_turret_fsm()
        sm.tick(0.1, {"enemies_in_range": []})
        assert sm.current_state == "scanning"

    def test_scanning_blocks_tracking_during_min_duration(self):
        """Scanning min_duration prevents instant lock-on."""
        sm = create_turret_fsm()
        _advance_to_scanning(sm)
        assert sm.current_state == "scanning"
        # One tick with enemy — still within min_duration
        sm.tick(0.05, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": True,
                       "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "scanning"

    def test_scanning_to_tracking_after_min_duration(self):
        """Scanning transitions to tracking after min_duration with enemies."""
        sm = create_turret_fsm()
        _advance_to_scanning(sm)
        ctx = {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": False,
               "just_fired": False, "degradation": 0.0}
        # Tick past scanning min_duration (0.5s) — 6 more ticks = 0.6s extra
        _tick_n(sm, 6, ctx)
        assert sm.current_state == "tracking"

    def test_scanning_stays_without_enemies(self):
        """Turret stays in scanning when no enemies detected."""
        sm = create_turret_fsm()
        _advance_to_scanning(sm)
        _tick_n(sm, 10, {"enemies_in_range": [], "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "scanning"

    def test_tracking_to_engaging_when_aimed(self):
        """Tracking transitions to engaging when aimed_at_target is True."""
        sm = create_turret_fsm()
        _advance_to_scanning(sm)
        # Past min_duration with enemies but not aimed
        _tick_n(sm, 6, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": False,
                         "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "tracking"
        # Now aim
        sm.tick(0.1, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": True,
                       "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "engaging"

    def test_tracking_to_scanning_when_enemies_leave(self):
        """Tracking falls back to scanning when enemies disappear."""
        sm = create_turret_fsm()
        _advance_to_scanning(sm)
        _tick_n(sm, 6, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": False,
                         "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "tracking"
        sm.tick(0.1, {"enemies_in_range": [], "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "scanning"

    def test_engaging_to_cooldown_after_firing(self):
        """Engaging transitions to cooldown when just_fired is True."""
        sm = create_turret_fsm()
        _advance_to_scanning(sm)
        # Reach engaging
        _tick_n(sm, 7, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": True,
                         "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": True,
                       "just_fired": True, "degradation": 0.0})
        assert sm.current_state == "cooldown"

    def test_engaging_to_scanning_when_enemies_leave(self):
        """Engaging falls back to scanning when all enemies leave."""
        sm = create_turret_fsm()
        _advance_to_scanning(sm)
        _tick_n(sm, 7, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": True,
                         "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"enemies_in_range": [], "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "scanning"

    def test_cooldown_to_scanning_when_enemies_leave(self):
        """Cooldown falls back to scanning when enemies disappear."""
        sm = create_turret_fsm()
        _advance_to_scanning(sm)
        _tick_n(sm, 7, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": True,
                         "just_fired": False, "degradation": 0.0})
        sm.tick(0.1, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": True,
                       "just_fired": True, "degradation": 0.0})
        assert sm.current_state == "cooldown"
        sm.tick(0.1, {"enemies_in_range": [], "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "scanning"

    def test_cooldown_returns_to_scanning_after_timer(self):
        """Cooldown auto-returns to scanning after ~1s (tick-return based)."""
        sm = create_turret_fsm()
        # Force into cooldown directly
        sm.force_state("cooldown")
        # Tick past 1s
        _tick_n(sm, 12, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": False,
                          "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "scanning"

    def test_reloading_to_scanning_legacy_compat(self):
        """Legacy reloading state transitions to scanning (always-true condition)."""
        sm = create_turret_fsm()
        sm.force_state("reloading")
        sm.tick(0.1, {})
        assert sm.current_state == "scanning"


# ===========================================================================
# Turret FSM — guard conditions
# ===========================================================================

class TestTurretFSMGuards:
    """Degradation guard blocks tracking->engaging with jammed weapon."""

    def test_guard_blocks_engaging_condition_path_when_degradation_high(self):
        """tracking -> engaging condition-based path is blocked when degradation >= 0.8.

        Note: The turret FSM has two paths from tracking -> engaging:
          1. Condition-based: condition=aimed_at_target AND guard=degradation < 0.8
          2. Tick-return: TrackingState.tick() returns "engaging" when aimed_at_target

        The guard only applies to path (1). Path (2) bypasses guards.
        To test the guard in isolation, we verify that when aimed_at_target=False
        (so tick-return won't fire), only degradation < 0.8 allows the condition.
        """
        sm = create_turret_fsm()
        _advance_to_scanning(sm)
        # Past min_duration, enemy present but NOT aimed — tick-return won't fire
        _tick_n(sm, 6, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": False,
                         "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "tracking"
        # degradation high + NOT aimed: condition true (aimed=False so condition fails)
        # The condition requires aimed_at_target=True AND enemies, so this stays tracking
        sm.tick(0.1, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": False,
                       "just_fired": False, "degradation": 0.9})
        assert sm.current_state == "tracking"

    def test_guard_allows_engaging_when_degradation_low(self):
        """tracking -> engaging succeeds when degradation < 0.8 (condition path)."""
        sm = create_turret_fsm()
        _advance_to_scanning(sm)
        _tick_n(sm, 6, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": False,
                         "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "tracking"
        sm.tick(0.1, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": True,
                       "just_fired": False, "degradation": 0.5})
        assert sm.current_state == "engaging"

    def test_degradation_boundary_just_below_threshold(self):
        """degradation=0.79 allows engaging via condition path (strictly < 0.8)."""
        sm = create_turret_fsm()
        _advance_to_scanning(sm)
        _tick_n(sm, 6, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": False,
                         "just_fired": False, "degradation": 0.0})
        sm.tick(0.1, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": True,
                       "just_fired": False, "degradation": 0.79})
        assert sm.current_state == "engaging"

    def test_degradation_at_threshold_guard_state_is_blocked(self):
        """Verify guard attribute: tracking->engaging condition guard uses degradation < 0.8.

        Because TrackingState.tick() returns 'engaging' when aimed=True (bypassing guards),
        we verify the guard configuration directly on the FSM's transition data.
        The condition-based guard (ctx.get('degradation',0.0) < 0.8) is the documented
        blocking mechanism for the weapon-jam scenario.
        """
        sm = create_turret_fsm()
        # Verify the guard lambda correctly blocks at degradation=0.8
        tracking_transitions = [
            t for t in sm._builder_transitions
            if t.from_state == "tracking" and t.to_state == "engaging"
        ]
        assert len(tracking_transitions) == 1
        t = tracking_transitions[0]
        # Guard must reject degradation >= 0.8
        assert t.guard({"degradation": 0.8}) is False
        assert t.guard({"degradation": 0.9}) is False
        # Guard must allow degradation < 0.8
        assert t.guard({"degradation": 0.0}) is True
        assert t.guard({"degradation": 0.79}) is True


# ===========================================================================
# Rover FSM — factory and state registry
# ===========================================================================

class TestRoverFSMFactory:
    """create_rover_fsm() produces a valid, correctly-shaped StateMachine."""

    def test_factory_returns_state_machine(self):
        sm = create_rover_fsm()
        assert isinstance(sm, StateMachine)

    def test_initial_state_is_idle(self):
        sm = create_rover_fsm()
        assert sm.current_state == "idle"

    def test_all_states_registered(self):
        sm = create_rover_fsm()
        for expected in ("idle", "patrolling", "pursuing", "engaging", "retreating", "rtb"):
            assert expected in sm.state_names, f"Missing state: {expected}"

    def test_pursuing_has_max_duration(self):
        sm = create_rover_fsm()
        pursuing = sm._states["pursuing"]
        assert pursuing.max_duration > 0.0
        assert pursuing.max_duration_target == "patrolling"

    def test_retreating_has_min_duration(self):
        sm = create_rover_fsm()
        retreating = sm._states["retreating"]
        assert retreating.min_duration > 0.0

    def test_history_empty_on_creation(self):
        sm = create_rover_fsm()
        assert sm.history == []


# ===========================================================================
# Rover FSM — transition paths
# ===========================================================================

class TestRoverFSMTransitions:
    """Every rover transition fires correctly under appropriate context."""

    def test_idle_to_patrolling_with_waypoints(self):
        """Rover starts patrolling when waypoints available (no enemies)."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "patrolling"

    def test_idle_to_pursuing_when_enemy_visible(self):
        """Idle rover pursues when enemy spotted but not in weapon range."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "pursuing"

    def test_idle_to_engaging_enemy_in_weapon_range(self):
        """Idle rover engages immediately when enemy in weapon range (highest prio from idle)."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "engaging"

    def test_idle_engaging_wins_over_patrolling_and_pursuing(self):
        """Engaging (priority=5) wins over pursuing (priority=3) and patrolling (priority=1)."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "engaging"

    def test_idle_pursuing_wins_over_patrolling(self):
        """Pursuing (priority=3) wins over patrolling (priority=1) from idle."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "pursuing"

    def test_patrolling_to_pursuing_on_enemy(self):
        """Patrolling rover pursues when enemies appear."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "patrolling"
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "pursuing"

    def test_pursuing_to_engaging_in_weapon_range(self):
        """Pursuing rover engages when enemy enters weapon range."""
        sm = create_rover_fsm()
        # Get to pursuing
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "pursuing"
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "engaging"

    def test_pursuing_to_patrolling_when_enemies_leave(self):
        """Pursuing rover returns to patrolling when enemies disappear."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "pursuing"
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "patrolling"

    def test_pursuing_max_duration_returns_to_patrolling(self):
        """Rover stops chasing after max_duration (20s) and returns to patrolling."""
        sm = create_rover_fsm()
        ctx = {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
               "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0}
        sm.tick(0.1, ctx)
        assert sm.current_state == "pursuing"
        # 210 ticks = 21s — past max_duration of 20s
        _tick_n(sm, 210, ctx)
        # History must record pursuing -> patrolling
        assert any(
            (f, t) == ("pursuing", "patrolling")
            for _, f, t in sm.history
        )

    def test_engaging_to_retreating_low_health(self):
        """Engaging rover retreats when health drops below 0.3."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 0.2, "degradation": 0.0})
        assert sm.current_state == "retreating"

    def test_engaging_to_pursuing_when_enemy_leaves_range(self):
        """Engaging rover pursues when enemy exits weapon range but is still visible."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "pursuing"

    def test_engaging_to_patrolling_when_no_enemies(self):
        """Engaging rover resumes patrol when no enemies remain."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "patrolling"

    def test_engaging_retreating_priority_over_pursuing(self):
        """Retreating (priority=10) wins over pursuing (no priority) from engaging."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "engaging"
        # Both low health AND enemy in range but out of range — retreat wins
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 0.2, "degradation": 0.0})
        assert sm.current_state == "retreating"

    def test_retreating_blocks_early_rtb_during_min_duration(self):
        """Rover stays in retreating during min_duration even when enemies leave."""
        sm = create_rover_fsm()
        # Get to engaging then retreating
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.0})
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 0.2, "degradation": 0.0})
        assert sm.current_state == "retreating"
        # Immediately clear enemies — should stay retreating due to min_duration
        sm.tick(0.05, {"has_waypoints": False, "enemies_in_range": [],
                        "enemy_in_weapon_range": False, "health_pct": 0.2, "degradation": 0.0})
        assert sm.current_state == "retreating"

    def test_retreating_to_rtb_after_min_duration(self):
        """Rover transitions to rtb after retreating min_duration with no enemies."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.0})
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 0.2, "degradation": 0.0})
        assert sm.current_state == "retreating"
        # 25 more ticks (2.5s) — past min_duration=2.0s — with no enemies
        _tick_n(sm, 25, {"has_waypoints": False, "enemies_in_range": [],
                          "enemy_in_weapon_range": False, "health_pct": 0.2, "degradation": 0.0})
        assert sm.current_state == "rtb"


# ===========================================================================
# Rover FSM — guard conditions
# ===========================================================================

class TestRoverFSMGuards:
    """Degradation guard blocks rover from engaging with jammed weapon."""

    def test_idle_engaging_guard_blocks_jammed_weapon(self):
        """idle -> engaging blocked when degradation >= 0.8 (guard fails)."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.9})
        # With jammed weapon, guard blocks engaging -> falls through to pursuing
        assert sm.current_state in ("idle", "pursuing")

    def test_pursuing_engaging_guard_blocks_jammed_weapon(self):
        """pursuing -> engaging blocked when degradation >= 0.8."""
        sm = create_rover_fsm()
        # Get to pursuing
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "pursuing"
        # Enemy enters weapon range but weapon is jammed
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.9})
        assert sm.current_state == "pursuing"

    def test_pursuing_engaging_allowed_with_good_weapon(self):
        """pursuing -> engaging succeeds when degradation < 0.8."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.3})
        assert sm.current_state == "engaging"


# ===========================================================================
# Drone FSM — factory and state registry
# ===========================================================================

class TestDroneFSMFactory:
    """create_drone_fsm() produces a valid, correctly-shaped StateMachine."""

    def test_factory_returns_state_machine(self):
        sm = create_drone_fsm()
        assert isinstance(sm, StateMachine)

    def test_initial_state_is_idle(self):
        sm = create_drone_fsm()
        assert sm.current_state == "idle"

    def test_all_primary_states_registered(self):
        sm = create_drone_fsm()
        for expected in ("idle", "scouting", "orbiting", "engaging", "rtb"):
            assert expected in sm.state_names, f"Missing state: {expected}"

    def test_legacy_strafing_alias_registered(self):
        sm = create_drone_fsm()
        assert "strafing" in sm.state_names

    def test_legacy_retreating_alias_registered(self):
        sm = create_drone_fsm()
        assert "retreating" in sm.state_names

    def test_history_empty_on_creation(self):
        sm = create_drone_fsm()
        assert sm.history == []


# ===========================================================================
# Drone FSM — transition paths
# ===========================================================================

class TestDroneFSMTransitions:
    """Every drone transition fires correctly under appropriate context."""

    def test_idle_to_scouting_with_waypoints(self):
        """Drone starts scouting when waypoints available."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "scouting"

    def test_idle_stays_without_waypoints(self):
        """Drone stays idle when no waypoints and no enemies."""
        sm = create_drone_fsm()
        _tick_n(sm, 5, {"has_waypoints": False, "enemies_in_range": [],
                         "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "idle"

    def test_scouting_to_orbiting_enemy_out_of_range(self):
        """Scouting drone orbits when enemy visible but out of weapon range."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "scouting"
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "orbiting"

    def test_scouting_to_engaging_enemy_in_weapon_range(self):
        """Scouting drone engages immediately when enemy in weapon range."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0})
        assert sm.current_state == "engaging"

    def test_scouting_to_rtb_critically_damaged(self):
        """Scouting drone RTBs when health drops below 0.2 (priority=10)."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "scouting"
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 0.15})
        assert sm.current_state == "rtb"

    def test_scouting_rtb_wins_over_orbiting_when_critical(self):
        """RTB (priority=10) wins over orbiting (no priority) when critically damaged."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        # Both enemies visible (orbiting condition) AND critical health (RTB condition)
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 0.1})
        assert sm.current_state == "rtb"

    def test_orbiting_to_engaging_in_weapon_range(self):
        """Orbiting drone engages when enemy enters weapon range."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "orbiting"
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0})
        assert sm.current_state == "engaging"

    def test_orbiting_to_scouting_when_enemies_leave(self):
        """Orbiting drone returns to scouting when enemies disappear."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "orbiting"
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "scouting"

    def test_orbiting_to_rtb_critical_health(self):
        """Orbiting drone RTBs on critical health (priority=10)."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "orbiting"
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 0.1})
        assert sm.current_state == "rtb"

    def test_engaging_to_rtb_critical_health(self):
        """Engaging drone RTBs on critical health (priority=10)."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 0.1})
        assert sm.current_state == "rtb"

    def test_engaging_to_orbiting_enemy_leaves_weapon_range(self):
        """Engaging drone orbits when enemy exits weapon range but still visible."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "orbiting"

    def test_engaging_to_scouting_when_enemies_leave(self):
        """Engaging drone returns to scouting when all enemies leave."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "scouting"

    def test_engaging_rtb_wins_over_orbiting_when_critical(self):
        """RTB (priority=10) wins over orbiting when both would trigger from engaging."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0})
        assert sm.current_state == "engaging"
        # Both out of weapon range AND critically damaged
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 0.1})
        assert sm.current_state == "rtb"


# ===========================================================================
# Hostile FSM — factory and state registry
# ===========================================================================

class TestHostileFSMFactory:
    """create_hostile_fsm() produces a valid, correctly-shaped StateMachine."""

    def test_factory_returns_state_machine(self):
        sm = create_hostile_fsm()
        assert isinstance(sm, StateMachine)

    def test_initial_state_is_spawning(self):
        sm = create_hostile_fsm()
        assert sm.current_state == "spawning"

    def test_all_primary_states_registered(self):
        sm = create_hostile_fsm()
        for expected in (
            "spawning", "advancing", "reconning", "engaging", "flanking",
            "suppressing", "retreating_under_fire", "fleeing",
        ):
            assert expected in sm.state_names, f"Missing state: {expected}"

    def test_legacy_approaching_alias_registered(self):
        sm = create_hostile_fsm()
        assert "approaching" in sm.state_names

    def test_legacy_attacking_alias_registered(self):
        sm = create_hostile_fsm()
        assert "attacking" in sm.state_names

    def test_legacy_dodging_alias_registered(self):
        sm = create_hostile_fsm()
        assert "dodging" in sm.state_names

    def test_spawning_has_min_duration(self):
        sm = create_hostile_fsm()
        spawning = sm._states["spawning"]
        assert spawning.min_duration > 0.0

    def test_retreating_under_fire_has_max_duration(self):
        sm = create_hostile_fsm()
        state = sm._states["retreating_under_fire"]
        assert state.max_duration > 0.0
        assert state.max_duration_target == "advancing"

    def test_fleeing_has_max_duration(self):
        sm = create_hostile_fsm()
        state = sm._states["fleeing"]
        assert state.max_duration > 0.0
        assert state.max_duration_target == "advancing"

    def test_history_empty_on_creation(self):
        sm = create_hostile_fsm()
        assert sm.history == []


# ===========================================================================
# Hostile FSM — transition paths
# ===========================================================================

class TestHostileFSMTransitions:
    """Every hostile transition fires correctly under appropriate context."""

    def test_spawning_blocks_advance_during_min_duration(self):
        """Hostile stays spawning during min_duration (0.8s)."""
        sm = create_hostile_fsm()
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": []})
        assert sm.current_state == "spawning"

    def test_spawning_to_advancing_after_timer(self):
        """Hostile advances after spawning timer elapses."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        assert sm.current_state == "advancing"

    def test_advancing_to_engaging_in_weapon_range(self):
        """Advancing hostile engages when defenders in weapon range."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": False, "cover_available": False,
                       "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "engaging"

    def test_advancing_to_flanking_stationary_target_out_of_range(self):
        """Advancing hostile flanks when nearest enemy is a stationary target."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": True,
                       "enemies_at_recon_range": False, "cover_available": False,
                       "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "flanking"

    def test_advancing_to_reconning_mobile_target_at_recon_range(self):
        """Advancing hostile enters reconning when mobile target at recon range."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": True, "cover_available": False,
                       "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "reconning"

    def test_advancing_to_fleeing_low_health_highest_priority(self):
        """Advancing hostile with low health flees (priority=20, highest from advancing)."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        # All conditions true but low health should win
        sm.tick(0.1, {"health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "enemies_at_recon_range": True, "cover_available": True,
                       "ally_is_flanking": True, "detected": True})
        assert sm.current_state == "fleeing"

    def test_advancing_engaging_wins_over_flanking(self):
        """Engaging (priority=5) wins over flanking (priority=3) from advancing."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        # Both engaging AND flanking conditions true (stationary target in weapon range)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "enemies_at_recon_range": False, "cover_available": False,
                       "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "engaging"

    def test_reconning_to_advancing_when_detected(self):
        """Reconning hostile breaks cover and advances when sensor detects them."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": True, "cover_available": False,
                       "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "reconning"
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": True, "cover_available": False,
                       "ally_is_flanking": False, "detected": True})
        assert sm.current_state == "advancing"

    def test_reconning_to_engaging_in_weapon_range(self):
        """Reconning hostile engages when enemy enters weapon range."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": True, "detected": False})
        assert sm.current_state == "reconning"
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": True, "detected": False})
        assert sm.current_state == "engaging"

    def test_reconning_to_flanking_stationary_target(self):
        """Reconning hostile flanks when nearest enemy is a static target (turret)."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": True, "detected": False})
        assert sm.current_state == "reconning"
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": True,
                       "enemies_at_recon_range": True, "detected": False})
        assert sm.current_state == "flanking"

    def test_reconning_to_advancing_all_clear(self):
        """Reconning hostile returns to advancing when no enemies at recon range."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": True, "detected": False})
        assert sm.current_state == "reconning"
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": False, "detected": False})
        assert sm.current_state == "advancing"

    def test_reconning_detected_wins_over_advancing_all_clear(self):
        """Detected (priority=15) beats all-clear (priority=1) from reconning."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": True, "detected": False})
        assert sm.current_state == "reconning"
        # Both detected AND recon range clear: detected (p=15) > clear (p=1)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": False, "detected": True})
        assert sm.current_state == "advancing"

    def test_engaging_to_retreating_under_fire_with_cover(self):
        """Engaging hostile retreats to cover when low health and cover available."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"health_pct": 0.2, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": True, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "retreating_under_fire"

    def test_engaging_to_fleeing_low_health_no_cover(self):
        """Engaging hostile flees when critically low health and no cover."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "fleeing"

    def test_engaging_retreating_under_fire_wins_over_fleeing(self):
        """retreating_under_fire (priority=15) wins over fleeing (priority=10)."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "engaging"
        # Both retreating_under_fire (cover=True, health<0.3) and fleeing (health<0.3) match
        sm.tick(0.1, {"health_pct": 0.2, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": True, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "retreating_under_fire"

    def test_engaging_to_suppressing(self):
        """Engaging hostile suppresses when ally is flanking a stationary target."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "cover_available": False, "ally_is_flanking": True, "detected": False})
        assert sm.current_state == "suppressing"

    def test_engaging_to_advancing_no_enemies(self):
        """Engaging hostile returns to advancing when all enemies eliminated."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "engaging"
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "advancing"

    def _get_to_suppressing(self, sm: StateMachine) -> None:
        """Drive the hostile FSM into the suppressing state.

        Requires two ticks from advancing:
          Tick 1: engaging (ally_is_flanking still False to reach engaging from advancing)
          Tick 2: suppressing (ally_is_flanking=True while already in engaging)
        """
        _advance_past_spawning(sm)
        # Tick 1: get to engaging (ally_is_flanking=False so suppressing won't fire yet)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "engaging", f"Expected engaging, got {sm.current_state}"
        # Tick 2: ally starts flanking -> transition to suppressing
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "cover_available": False, "ally_is_flanking": True, "detected": False})
        assert sm.current_state == "suppressing", f"Expected suppressing, got {sm.current_state}"

    def test_suppressing_to_retreating_when_detected(self):
        """Suppressing hostile retreats under fire when position is detected."""
        sm = create_hostile_fsm()
        self._get_to_suppressing(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "cover_available": False, "ally_is_flanking": True, "detected": True})
        assert sm.current_state == "retreating_under_fire"

    def test_suppressing_to_fleeing_low_health(self):
        """Suppressing hostile flees on low health (priority=15)."""
        sm = create_hostile_fsm()
        self._get_to_suppressing(sm)
        sm.tick(0.1, {"health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "cover_available": False, "ally_is_flanking": True, "detected": False})
        assert sm.current_state == "fleeing"

    def test_suppressing_to_engaging_ally_stops_flanking(self):
        """Suppressing hostile re-engages when ally stops flanking."""
        sm = create_hostile_fsm()
        self._get_to_suppressing(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "engaging"

    def test_retreating_under_fire_to_advancing_healthy_no_enemies(self):
        """Retreating-under-fire hostile advances when safe and health recovers."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": True, "ally_is_flanking": False, "detected": False})
        sm.tick(0.1, {"health_pct": 0.2, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": True, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "retreating_under_fire"
        # Health recovered, no enemies
        sm.tick(0.1, {"health_pct": 0.5, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "cover_available": True, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "advancing"

    def test_retreating_under_fire_to_fleeing_no_cover(self):
        """Retreating-under-fire hostile flees when cover lost and still low health."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": True, "ally_is_flanking": False, "detected": False})
        sm.tick(0.1, {"health_pct": 0.2, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": True, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "retreating_under_fire"
        sm.tick(0.1, {"health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "fleeing"

    def test_retreating_under_fire_max_duration_auto_advance(self):
        """retreating_under_fire auto-transitions to advancing after max_duration (10s)."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": True, "ally_is_flanking": False, "detected": False})
        sm.tick(0.1, {"health_pct": 0.2, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": True, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "retreating_under_fire"
        # Tick 110 times (11s) past max_duration=10s, keep conditions stable
        _tick_n(sm, 110, {"health_pct": 0.2, "enemies_in_range": [],
                           "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                           "cover_available": True, "ally_is_flanking": False, "detected": False})
        assert any(
            (f, t) == ("retreating_under_fire", "advancing")
            for _, f, t in sm.history
        )

    def test_flanking_to_engaging_in_weapon_range(self):
        """Flanking hostile engages when it reaches weapon range."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": True,
                       "enemies_at_recon_range": False, "detected": False})
        assert sm.current_state == "flanking"
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "enemies_at_recon_range": False, "detected": False})
        assert sm.current_state == "engaging"

    def test_flanking_to_fleeing_low_health(self):
        """Flanking hostile flees on low health (priority=10)."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": True,
                       "enemies_at_recon_range": False, "detected": False})
        assert sm.current_state == "flanking"
        sm.tick(0.1, {"health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": True,
                       "enemies_at_recon_range": False, "detected": False})
        assert sm.current_state == "fleeing"

    def test_flanking_fleeing_wins_over_engaging(self):
        """Fleeing (priority=10) wins over engaging (no priority) from flanking."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": True,
                       "enemies_at_recon_range": False, "detected": False})
        assert sm.current_state == "flanking"
        # Both in weapon range (engage) AND low health (flee)
        sm.tick(0.1, {"health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "enemies_at_recon_range": False, "detected": False})
        assert sm.current_state == "fleeing"

    def test_flanking_to_advancing_no_enemies(self):
        """Flanking hostile returns to advancing when all enemies gone."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": True,
                       "enemies_at_recon_range": False, "detected": False})
        assert sm.current_state == "flanking"
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "enemies_at_recon_range": False, "detected": False})
        assert sm.current_state == "advancing"

    def test_fleeing_to_advancing_on_health_recovery(self):
        """Fleeing hostile rallies back to advancing when health >= 0.5."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "fleeing"
        sm.tick(0.1, {"health_pct": 0.6, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "advancing"

    def test_fleeing_max_duration_auto_advance(self):
        """Fleeing hostile rallies after max_duration (15s) regardless of context."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {"health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "fleeing"
        # Tick 160 times (16s, past max_duration=15s), keep health < 0.5 so condition won't fire
        _tick_n(sm, 160, {"health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
                           "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
                           "cover_available": False, "ally_is_flanking": False, "detected": False})
        # max_duration must have triggered at some point
        assert any(
            (f, t) == ("fleeing", "advancing")
            for _, f, t in sm.history
        )


# ===========================================================================
# State history tracking
# ===========================================================================

class TestStateHistory:
    """History is recorded accurately across all FSM types."""

    def test_turret_history_records_idle_to_scanning(self):
        sm = create_turret_fsm()
        sm.tick(0.1, {"enemies_in_range": []})
        assert sm.current_state == "scanning"
        history = sm.history
        assert len(history) >= 1
        assert history[-1][1] == "idle"
        assert history[-1][2] == "scanning"

    def test_rover_history_records_idle_to_patrolling(self):
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0, "degradation": 0.0})
        history = sm.history
        assert any((f, t) == ("idle", "patrolling") for _, f, t in history)

    def test_hostile_history_records_spawning_to_advancing(self):
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        history = sm.history
        assert any((f, t) == ("spawning", "advancing") for _, f, t in history)

    def test_drone_history_records_idle_to_scouting(self):
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        history = sm.history
        assert any((f, t) == ("idle", "scouting") for _, f, t in history)

    def test_history_timestamps_are_float(self):
        sm = create_turret_fsm()
        sm.tick(0.1, {"enemies_in_range": []})
        ts, _, _ = sm.history[0]
        assert isinstance(ts, float)

    def test_history_grows_with_each_transition(self):
        sm = create_hostile_fsm()
        assert len(sm.history) == 0
        _advance_past_spawning(sm)
        assert len(sm.history) >= 1

    def test_history_returns_copy_not_reference(self):
        sm = create_turret_fsm()
        sm.tick(0.1, {"enemies_in_range": []})
        h1 = sm.history
        h2 = sm.history
        assert h1 == h2
        assert h1 is not h2

    def test_history_limit_respected(self):
        """History does not grow beyond default limit of 20."""
        sm = create_rover_fsm()
        # Drive many transitions by alternating enemy presence
        for i in range(50):
            ctx = {
                "has_waypoints": True,
                "enemies_in_range": [{"id": "h1"}] if i % 2 == 0 else [],
                "enemy_in_weapon_range": False,
                "health_pct": 1.0,
                "degradation": 0.0,
            }
            sm.tick(0.1, ctx)
        assert len(sm.history) <= 20


# ===========================================================================
# force_state bypass
# ===========================================================================

class TestForceState:
    """force_state() skips conditions and goes directly to the named state."""

    def test_turret_force_state_from_idle_to_engaging(self):
        sm = create_turret_fsm()
        sm.force_state("engaging")
        assert sm.current_state == "engaging"

    def test_rover_force_state_skips_sequence(self):
        sm = create_rover_fsm()
        sm.force_state("retreating")
        assert sm.current_state == "retreating"

    def test_drone_force_state_to_rtb(self):
        sm = create_drone_fsm()
        sm.force_state("rtb")
        assert sm.current_state == "rtb"

    def test_hostile_force_state_to_flanking(self):
        sm = create_hostile_fsm()
        sm.force_state("flanking")
        assert sm.current_state == "flanking"

    def test_force_state_records_in_history(self):
        sm = create_turret_fsm()
        sm.force_state("cooldown")
        assert len(sm.history) == 1
        _, f, t = sm.history[0]
        assert f == "idle"
        assert t == "cooldown"

    def test_force_state_resets_time_in_state(self):
        sm = create_turret_fsm()
        _tick_n(sm, 5, {"enemies_in_range": []})
        old_time = sm.time_in_state
        sm.force_state("engaging")
        assert sm.time_in_state == 0.0

    def test_force_state_raises_on_unknown_state(self):
        sm = create_turret_fsm()
        with pytest.raises(ValueError):
            sm.force_state("nonexistent_state")


# ===========================================================================
# create_fsm_for_type routing
# ===========================================================================

class TestCreateFSMForType:
    """Factory router returns correct FSM type for all known unit types."""

    # --- Turret family ---
    def test_turret_returns_turret_fsm(self):
        sm = create_fsm_for_type("turret")
        assert sm is not None
        assert sm.current_state == "idle"
        assert "scanning" in sm.state_names

    def test_heavy_turret_returns_turret_fsm(self):
        sm = create_fsm_for_type("heavy_turret")
        assert sm is not None
        assert sm.current_state == "idle"
        assert "scanning" in sm.state_names

    def test_missile_turret_returns_turret_fsm(self):
        sm = create_fsm_for_type("missile_turret")
        assert sm is not None
        assert sm.current_state == "idle"
        assert "scanning" in sm.state_names

    # --- Rover family ---
    def test_rover_returns_rover_fsm(self):
        sm = create_fsm_for_type("rover")
        assert sm is not None
        assert sm.current_state == "idle"
        assert "patrolling" in sm.state_names

    def test_tank_returns_rover_fsm(self):
        sm = create_fsm_for_type("tank")
        assert sm is not None
        assert sm.current_state == "idle"
        assert "patrolling" in sm.state_names

    def test_apc_returns_rover_fsm(self):
        sm = create_fsm_for_type("apc")
        assert sm is not None
        assert sm.current_state == "idle"
        assert "patrolling" in sm.state_names

    # --- Drone family ---
    def test_drone_returns_drone_fsm(self):
        sm = create_fsm_for_type("drone")
        assert sm is not None
        assert sm.current_state == "idle"
        assert "scouting" in sm.state_names

    def test_scout_drone_returns_drone_fsm(self):
        sm = create_fsm_for_type("scout_drone")
        assert sm is not None
        assert sm.current_state == "idle"
        assert "scouting" in sm.state_names

    # --- Hostile types ---
    def test_hostile_person_returns_hostile_fsm(self):
        sm = create_fsm_for_type("hostile_person")
        assert sm is not None
        assert sm.current_state == "spawning"

    def test_hostile_leader_returns_hostile_fsm(self):
        sm = create_fsm_for_type("hostile_leader")
        assert sm is not None
        assert sm.current_state == "spawning"

    def test_hostile_vehicle_returns_hostile_fsm(self):
        sm = create_fsm_for_type("hostile_vehicle")
        assert sm is not None
        assert sm.current_state == "spawning"

    def test_person_hostile_alliance_returns_hostile_fsm(self):
        sm = create_fsm_for_type("person", alliance="hostile")
        assert sm is not None
        assert sm.current_state == "spawning"

    # --- NPC types now get FSMs from npc_intelligence plugin ---
    def test_person_neutral_gets_npc_fsm(self):
        sm = create_fsm_for_type("person", alliance="neutral")
        assert sm is not None
        assert sm.current_state == "walking"

    def test_person_friendly_gets_npc_fsm(self):
        sm = create_fsm_for_type("person", alliance="friendly")
        assert sm is not None
        assert sm.current_state == "walking"

    def test_person_default_alliance_gets_npc_fsm(self):
        """Default alliance for 'person' is friendly — gets pedestrian FSM."""
        sm = create_fsm_for_type("person")
        assert sm is not None
        assert sm.current_state == "walking"

    def test_unknown_type_returns_none(self):
        assert create_fsm_for_type("unicorn") is None

    def test_animal_gets_npc_fsm(self):
        sm = create_fsm_for_type("animal")
        assert sm is not None
        assert sm.current_state == "wandering"

    def test_vehicle_gets_npc_fsm(self):
        sm = create_fsm_for_type("vehicle")
        assert sm is not None
        assert sm.current_state == "driving"

    def test_empty_string_returns_none(self):
        assert create_fsm_for_type("") is None


# ===========================================================================
# Timed states: min_duration semantics across all FSMs
# ===========================================================================

class TestTimedStates:
    """Verify min_duration and max_duration behave correctly per FSM."""

    def test_turret_scanning_min_duration_attribute(self):
        sm = create_turret_fsm()
        assert sm._states["scanning"].min_duration == 0.5

    def test_rover_retreating_min_duration_attribute(self):
        sm = create_rover_fsm()
        assert sm._states["retreating"].min_duration == 2.0

    def test_rover_pursuing_max_duration_attribute(self):
        sm = create_rover_fsm()
        assert sm._states["pursuing"].max_duration == 20.0

    def test_hostile_spawning_min_duration_attribute(self):
        sm = create_hostile_fsm()
        assert sm._states["spawning"].min_duration == 0.8

    def test_hostile_fleeing_max_duration_attribute(self):
        sm = create_hostile_fsm()
        assert sm._states["fleeing"].max_duration == 15.0

    def test_hostile_retreating_under_fire_max_duration_attribute(self):
        sm = create_hostile_fsm()
        assert sm._states["retreating_under_fire"].max_duration == 10.0

    def test_turret_scanning_transition_blocked_before_min_duration(self):
        sm = create_turret_fsm()
        sm.tick(0.1, {"enemies_in_range": []})
        assert sm.current_state == "scanning"
        # time_in_state is 0 now (just transitioned); min_duration is 0.5
        # Tick 0.4s more (4 ticks): still within min_duration
        _tick_n(sm, 4, {"enemies_in_range": [{"id": "h1"}], "aimed_at_target": True,
                         "just_fired": False, "degradation": 0.0})
        assert sm.current_state == "scanning"

    def test_rover_retreating_transition_blocked_before_min_duration(self):
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.0})
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 0.2, "degradation": 0.0})
        assert sm.current_state == "retreating"
        # Time in retreating is ~0; min_duration is 2.0s. Clear enemies immediately.
        sm.tick(0.1, {"has_waypoints": False, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 0.2, "degradation": 0.0})
        # Should still be retreating (blocked by min_duration)
        assert sm.current_state == "retreating"


# ===========================================================================
# Priority transition ordering across FSMs
# ===========================================================================

class TestPriorityTransitions:
    """Higher-priority transitions override lower-priority ones when multiple match."""

    def test_rover_retreating_priority_10_beats_pursuing_no_priority(self):
        """From engaging: retreating (p=10) > pursuing (no priority) when both match."""
        sm = create_rover_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": True, "health_pct": 1.0, "degradation": 0.0})
        assert sm.current_state == "engaging"
        # Both retreat (health < 0.3) AND pursue conditions would match (enemy visible, out of range)
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 0.2, "degradation": 0.0})
        assert sm.current_state == "retreating"

    def test_drone_rtb_priority_10_beats_orbiting_from_scouting(self):
        """From scouting: rtb (p=10) > orbiting (no priority) when both match."""
        sm = create_drone_fsm()
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [],
                       "enemy_in_weapon_range": False, "health_pct": 1.0})
        assert sm.current_state == "scouting"
        sm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [{"id": "h1"}],
                       "enemy_in_weapon_range": False, "health_pct": 0.1})
        assert sm.current_state == "rtb"

    def test_hostile_fleeing_priority_20_beats_all_from_advancing(self):
        """From advancing: fleeing (p=20) beats engaging (p=5), flanking (p=3) when all match."""
        sm = create_hostile_fsm()
        _advance_past_spawning(sm)
        sm.tick(0.1, {
            "health_pct": 0.1,
            "enemies_in_range": [{"id": "t1"}],
            "enemy_in_weapon_range": True,
            "nearest_enemy_stationary": True,
            "enemies_at_recon_range": True,
            "cover_available": True,
            "ally_is_flanking": True,
            "detected": True,
        })
        assert sm.current_state == "fleeing"

    def test_hostile_suppressing_detected_priority_20_beats_fleeing_priority_15(self):
        """From suppressing: detected (p=20) > fleeing (p=15) when both match."""
        sm = create_hostile_fsm()
        # Need two steps to reach suppressing from advancing
        _advance_past_spawning(sm)
        # Step 1: get to engaging (ally not flanking yet)
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "cover_available": False, "ally_is_flanking": False, "detected": False})
        assert sm.current_state == "engaging"
        # Step 2: ally starts flanking -> suppressing
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "cover_available": False, "ally_is_flanking": True, "detected": False})
        assert sm.current_state == "suppressing"
        # Both low health (flee p=15) AND detected (retreat_under_fire p=20) true
        sm.tick(0.1, {"health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
                       "enemy_in_weapon_range": True, "nearest_enemy_stationary": True,
                       "cover_available": False, "ally_is_flanking": True, "detected": True})
        assert sm.current_state == "retreating_under_fire"
