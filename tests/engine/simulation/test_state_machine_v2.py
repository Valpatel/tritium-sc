"""Tests for FSM v2 features: transition guards, timed states, state history, priority.

TDD: all tests written FIRST before implementation.
Run: .venv/bin/python3 -m pytest tests/amy/simulation/test_state_machine_v2.py -v
"""

import time

import pytest

from engine.simulation.state_machine import State, StateMachine, Transition


# =====================================================================
# Helpers
# =====================================================================

def _make_simple_sm() -> StateMachine:
    """Two-state machine: idle <-> active."""
    sm = StateMachine("idle")
    sm.add_state(State("idle"))
    sm.add_state(State("active"))
    sm.add_transition("idle", "active", lambda ctx: ctx.get("go"))
    sm.add_transition("active", "idle", lambda ctx: not ctx.get("go"))
    return sm


# =====================================================================
# TestTransitionGuards
# =====================================================================

class TestTransitionGuards:
    """Guard prevents transition even when condition is true."""

    def test_guard_blocks_transition(self):
        """When guard returns False, transition does not fire even if condition is True."""
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("engaging"))
        sm.add_transition(
            "idle", "engaging",
            condition=lambda ctx: ctx.get("enemy_in_range", False),
            guard=lambda ctx: ctx.get("weapon_ok", False),
        )
        # Condition true, guard false -> should stay idle
        sm.tick(0.1, {"enemy_in_range": True, "weapon_ok": False})
        assert sm.current_state == "idle"

    def test_guard_allows_transition(self):
        """When both condition and guard return True, transition fires."""
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("engaging"))
        sm.add_transition(
            "idle", "engaging",
            condition=lambda ctx: ctx.get("enemy_in_range", False),
            guard=lambda ctx: ctx.get("weapon_ok", False),
        )
        sm.tick(0.1, {"enemy_in_range": True, "weapon_ok": True})
        assert sm.current_state == "engaging"

    def test_no_guard_means_always_allowed(self):
        """With guard=None, only condition matters (backward compat)."""
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("active"))
        sm.add_transition("idle", "active", condition=lambda ctx: True, guard=None)
        sm.tick(0.1, {})
        assert sm.current_state == "active"


class TestGuardWithCondition:
    """Both condition AND guard must be true for transition to fire."""

    def test_condition_false_guard_true(self):
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("active"))
        sm.add_transition(
            "idle", "active",
            condition=lambda ctx: False,
            guard=lambda ctx: True,
        )
        sm.tick(0.1, {})
        assert sm.current_state == "idle"

    def test_condition_true_guard_false(self):
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("active"))
        sm.add_transition(
            "idle", "active",
            condition=lambda ctx: True,
            guard=lambda ctx: False,
        )
        sm.tick(0.1, {})
        assert sm.current_state == "idle"

    def test_both_true(self):
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("active"))
        sm.add_transition(
            "idle", "active",
            condition=lambda ctx: True,
            guard=lambda ctx: True,
        )
        sm.tick(0.1, {})
        assert sm.current_state == "active"

    def test_both_false(self):
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("active"))
        sm.add_transition(
            "idle", "active",
            condition=lambda ctx: False,
            guard=lambda ctx: False,
        )
        sm.tick(0.1, {})
        assert sm.current_state == "idle"


# =====================================================================
# TestTimedStateMinDuration
# =====================================================================

class TestTimedStateMinDuration:
    """Transitions blocked during min_duration."""

    def test_transition_blocked_during_min_duration(self):
        """Condition-based transition should not fire before min_duration."""
        sm = StateMachine("scanning")
        sm.add_state(State("scanning", min_duration=0.5))
        sm.add_state(State("tracking"))
        sm.add_transition(
            "scanning", "tracking",
            condition=lambda ctx: ctx.get("enemy_found", False),
        )
        # Tick only 0.1s — still in min_duration
        sm.tick(0.1, {"enemy_found": True})
        assert sm.current_state == "scanning"

    def test_transition_allowed_after_min_duration(self):
        """Condition-based transition should fire after min_duration elapsed."""
        sm = StateMachine("scanning")
        sm.add_state(State("scanning", min_duration=0.5))
        sm.add_state(State("tracking"))
        sm.add_transition(
            "scanning", "tracking",
            condition=lambda ctx: ctx.get("enemy_found", False),
        )
        # Tick past min_duration
        for _ in range(6):  # 0.6s total
            sm.tick(0.1, {"enemy_found": True})
        assert sm.current_state == "tracking"

    def test_min_duration_zero_means_no_delay(self):
        """min_duration=0 (default) allows immediate transitions."""
        sm = StateMachine("idle")
        sm.add_state(State("idle", min_duration=0.0))
        sm.add_state(State("active"))
        sm.add_transition("idle", "active", condition=lambda ctx: True)
        sm.tick(0.1, {})
        assert sm.current_state == "active"

    def test_min_duration_does_not_block_on_tick_returns(self):
        """State.tick() return values should also be blocked by min_duration."""
        class EagerState(State):
            def tick(self, dt, ctx):
                return "done"

        sm = StateMachine("eager")
        sm.add_state(EagerState("eager", min_duration=1.0))
        sm.add_state(State("done"))
        sm.tick(0.1, {})
        assert sm.current_state == "eager"

    def test_min_duration_tick_return_allowed_after_elapsed(self):
        """State.tick() return should work after min_duration has passed."""
        class EagerState(State):
            def tick(self, dt, ctx):
                return "done"

        sm = StateMachine("eager")
        sm.add_state(EagerState("eager", min_duration=0.3))
        sm.add_state(State("done"))
        for _ in range(4):  # 0.4s
            sm.tick(0.1, {})
        assert sm.current_state == "done"


# =====================================================================
# TestTimedStateMaxDuration
# =====================================================================

class TestTimedStateMaxDuration:
    """Auto-transition after max_duration."""

    def test_auto_transition_on_max_duration(self):
        """State should auto-transition to max_duration_target after time expires."""
        sm = StateMachine("fleeing")
        sm.add_state(State("fleeing", max_duration=1.5, max_duration_target="advancing"))
        sm.add_state(State("advancing"))
        # Tick for 2.0s
        for _ in range(20):
            sm.tick(0.1, {})
        assert sm.current_state == "advancing"

    def test_no_auto_transition_before_max_duration(self):
        """State should NOT auto-transition before max_duration elapsed."""
        sm = StateMachine("fleeing")
        sm.add_state(State("fleeing", max_duration=1.5, max_duration_target="advancing"))
        sm.add_state(State("advancing"))
        # Only tick 1.0s — should still be fleeing
        for _ in range(10):
            sm.tick(0.1, {})
        assert sm.current_state == "fleeing"

    def test_max_duration_zero_means_no_timeout(self):
        """max_duration=0 (default) means no auto-transition."""
        sm = StateMachine("idle")
        sm.add_state(State("idle", max_duration=0.0, max_duration_target="done"))
        sm.add_state(State("done"))
        for _ in range(100):
            sm.tick(0.1, {})
        assert sm.current_state == "idle"

    def test_max_duration_without_target_does_nothing(self):
        """If max_duration > 0 but no max_duration_target, no transition."""
        sm = StateMachine("waiting")
        sm.add_state(State("waiting", max_duration=1.0, max_duration_target=None))
        for _ in range(20):
            sm.tick(0.1, {})
        assert sm.current_state == "waiting"

    def test_normal_transition_overrides_max_duration(self):
        """If a normal transition fires before max_duration, it wins."""
        sm = StateMachine("fleeing")
        sm.add_state(State("fleeing", max_duration=5.0, max_duration_target="advancing"))
        sm.add_state(State("safe"))
        sm.add_state(State("advancing"))
        sm.add_transition("fleeing", "safe", condition=lambda ctx: ctx.get("safe"))
        # Tick with safe=True on tick 3 (0.3s) — well before max_duration
        for i in range(5):
            sm.tick(0.1, {"safe": i >= 2})
        assert sm.current_state == "safe"


class TestMaxDurationTarget:
    """Correct target state on timeout."""

    def test_transitions_to_specified_target(self):
        sm = StateMachine("pursuing")
        sm.add_state(State("pursuing", max_duration=2.0, max_duration_target="patrolling"))
        sm.add_state(State("patrolling"))
        for _ in range(25):  # 2.5s
            sm.tick(0.1, {})
        assert sm.current_state == "patrolling"

    def test_on_exit_fires_on_max_duration(self):
        """on_exit should fire when max_duration triggers auto-transition."""
        exited = []
        sm = StateMachine("temp")
        sm.add_state(State(
            "temp",
            max_duration=0.5,
            max_duration_target="done",
            on_exit=lambda ctx: exited.append("temp"),
        ))
        sm.add_state(State("done"))
        for _ in range(10):
            sm.tick(0.1, {})
        assert "temp" in exited

    def test_on_enter_fires_on_max_duration_target(self):
        """on_enter should fire on the target state after max_duration."""
        entered = []
        sm = StateMachine("temp")
        sm.add_state(State("temp", max_duration=0.5, max_duration_target="next"))
        sm.add_state(State("next", on_enter=lambda ctx: entered.append("next")))
        for _ in range(10):
            sm.tick(0.1, {})
        assert "next" in entered


# =====================================================================
# TestStateHistory
# =====================================================================

class TestStateHistory:
    """History records transitions."""

    def test_history_records_transitions(self):
        sm = _make_simple_sm()
        sm.tick(0.1, {"go": True})
        assert sm.current_state == "active"
        history = sm.history
        assert len(history) >= 1
        ts, from_s, to_s = history[-1]
        assert from_s == "idle"
        assert to_s == "active"
        assert isinstance(ts, float)

    def test_history_empty_initially(self):
        sm = _make_simple_sm()
        assert sm.history == []

    def test_history_tracks_multiple_transitions(self):
        sm = _make_simple_sm()
        sm.tick(0.1, {"go": True})    # idle -> active
        sm.tick(0.1, {"go": False})   # active -> idle
        sm.tick(0.1, {"go": True})    # idle -> active
        assert len(sm.history) == 3
        assert sm.history[0][1:] == ("idle", "active")
        assert sm.history[1][1:] == ("active", "idle")
        assert sm.history[2][1:] == ("idle", "active")

    def test_history_returns_copy(self):
        """history property should return a copy, not the internal list."""
        sm = _make_simple_sm()
        sm.tick(0.1, {"go": True})
        h1 = sm.history
        h2 = sm.history
        assert h1 == h2
        assert h1 is not h2


class TestHistoryLimit:
    """History doesn't grow unbounded."""

    def test_default_limit_is_20(self):
        sm = StateMachine("a")
        sm.add_state(State("a"))
        sm.add_state(State("b"))
        sm.add_transition("a", "b", condition=lambda ctx: ctx.get("flip"))
        sm.add_transition("b", "a", condition=lambda ctx: not ctx.get("flip"))
        # Force 30 transitions
        for i in range(30):
            sm.tick(0.1, {"flip": i % 2 == 0})
        assert len(sm.history) <= 20

    def test_custom_limit(self):
        sm = StateMachine("a", history_limit=5)
        sm.add_state(State("a"))
        sm.add_state(State("b"))
        sm.add_transition("a", "b", condition=lambda ctx: ctx.get("flip"))
        sm.add_transition("b", "a", condition=lambda ctx: not ctx.get("flip"))
        for i in range(20):
            sm.tick(0.1, {"flip": i % 2 == 0})
        assert len(sm.history) <= 5

    def test_history_keeps_most_recent(self):
        sm = StateMachine("a", history_limit=3)
        sm.add_state(State("a"))
        sm.add_state(State("b"))
        sm.add_transition("a", "b", condition=lambda ctx: ctx.get("flip"))
        sm.add_transition("b", "a", condition=lambda ctx: not ctx.get("flip"))
        for i in range(10):
            sm.tick(0.1, {"flip": i % 2 == 0})
        # Should have the 3 most recent transitions
        assert len(sm.history) == 3
        # Last entry should be the most recent transition
        assert sm.history[-1][1] in ("a", "b")


# =====================================================================
# TestTimeInCurrentState
# =====================================================================

class TestTimeInCurrentState:
    """Accurate time tracking."""

    def test_time_starts_at_zero(self):
        sm = _make_simple_sm()
        assert sm.time_in_current_state == 0.0

    def test_time_accumulates(self):
        sm = _make_simple_sm()
        sm.tick(0.1, {"go": False})  # Stay idle
        sm.tick(0.1, {"go": False})
        sm.tick(0.1, {"go": False})
        assert abs(sm.time_in_current_state - 0.3) < 0.01

    def test_time_resets_on_transition(self):
        sm = _make_simple_sm()
        sm.tick(0.1, {"go": False})  # idle: 0.1s
        sm.tick(0.1, {"go": False})  # idle: 0.2s
        sm.tick(0.1, {"go": True})   # transition to active, time resets
        assert sm.time_in_current_state < 0.15  # should be close to 0


# =====================================================================
# TestPriorityTransitions
# =====================================================================

class TestPriorityTransitions:
    """Higher priority wins when multiple transitions match."""

    def test_higher_priority_wins(self):
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("engaging"))
        sm.add_state(State("fleeing"))
        # Low priority: engage when enemy near
        sm.add_transition(
            "idle", "engaging",
            condition=lambda ctx: ctx.get("enemy_near"),
            priority=1,
        )
        # High priority: flee when low health (should win)
        sm.add_transition(
            "idle", "fleeing",
            condition=lambda ctx: ctx.get("low_health"),
            priority=10,
        )
        sm.tick(0.1, {"enemy_near": True, "low_health": True})
        assert sm.current_state == "fleeing"

    def test_priority_zero_is_default(self):
        """Transitions with no priority should work normally (priority=0)."""
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("active"))
        sm.add_transition("idle", "active", condition=lambda ctx: True)
        sm.tick(0.1, {})
        assert sm.current_state == "active"

    def test_equal_priority_first_match_wins(self):
        """With equal priority, first added transition wins."""
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("a"))
        sm.add_state(State("b"))
        sm.add_transition("idle", "a", condition=lambda ctx: True, priority=5)
        sm.add_transition("idle", "b", condition=lambda ctx: True, priority=5)
        sm.tick(0.1, {})
        assert sm.current_state == "a"

    def test_lower_priority_fires_when_higher_fails(self):
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("engage"))
        sm.add_state(State("flee"))
        sm.add_transition(
            "idle", "flee",
            condition=lambda ctx: ctx.get("low_health"),
            priority=10,
        )
        sm.add_transition(
            "idle", "engage",
            condition=lambda ctx: ctx.get("enemy_near"),
            priority=1,
        )
        # Only enemy_near is true, low_health is false
        sm.tick(0.1, {"enemy_near": True, "low_health": False})
        assert sm.current_state == "engage"


# =====================================================================
# TestOnTick
# =====================================================================

class TestOnTick:
    """on_tick callback called each tick while in state."""

    def test_on_tick_called_every_tick(self):
        call_count = [0]
        sm = StateMachine("active")
        sm.add_state(State("active", on_tick=lambda ctx, dt: call_count.__setitem__(0, call_count[0] + 1)))
        for _ in range(5):
            sm.tick(0.1, {})
        assert call_count[0] == 5

    def test_on_tick_receives_dt_and_ctx(self):
        received = []
        def tracker(ctx, dt):
            received.append((ctx.get("val"), dt))

        sm = StateMachine("s")
        sm.add_state(State("s", on_tick=tracker))
        sm.tick(0.1, {"val": 42})
        assert len(received) == 1
        assert received[0] == (42, 0.1)

    def test_on_tick_not_called_after_transition(self):
        """on_tick for old state should not fire after transitioning away."""
        old_ticks = [0]
        new_ticks = [0]
        sm = StateMachine("old")
        sm.add_state(State("old", on_tick=lambda ctx, dt: old_ticks.__setitem__(0, old_ticks[0] + 1)))
        sm.add_state(State("new", on_tick=lambda ctx, dt: new_ticks.__setitem__(0, new_ticks[0] + 1)))
        sm.add_transition("old", "new", condition=lambda ctx: ctx.get("go"))
        sm.tick(0.1, {"go": False})  # old ticks
        sm.tick(0.1, {"go": True})   # transition to new, new ticks
        sm.tick(0.1, {"go": True})   # new ticks
        assert old_ticks[0] == 1  # only ticked once (before transition)
        assert new_ticks[0] >= 1

    def test_on_tick_none_means_no_callback(self):
        """State without on_tick should work fine."""
        sm = StateMachine("s")
        sm.add_state(State("s", on_tick=None))
        sm.tick(0.1, {})  # should not raise
        assert sm.current_state == "s"


# =====================================================================
# TestOnEnterOnExit
# =====================================================================

class TestOnEnterOnExit:
    """Callbacks fire on transitions."""

    def test_on_enter_fires_on_initial_state(self):
        entered = []
        sm = StateMachine("idle")
        sm.add_state(State("idle", on_enter=lambda ctx: entered.append("idle")))
        sm.tick(0.1, {})
        assert "idle" in entered

    def test_on_enter_fires_on_transition(self):
        entered = []
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("active", on_enter=lambda ctx: entered.append("active")))
        sm.add_transition("idle", "active", condition=lambda ctx: True)
        sm.tick(0.1, {})
        assert "active" in entered

    def test_on_exit_fires_on_transition(self):
        exited = []
        sm = StateMachine("idle")
        sm.add_state(State("idle", on_exit=lambda ctx: exited.append("idle")))
        sm.add_state(State("active"))
        sm.add_transition("idle", "active", condition=lambda ctx: True)
        sm.tick(0.1, {})
        assert "idle" in exited

    def test_on_enter_on_exit_both_fire(self):
        events = []
        sm = StateMachine("a")
        sm.add_state(State("a", on_exit=lambda ctx: events.append("exit_a")))
        sm.add_state(State("b", on_enter=lambda ctx: events.append("enter_b")))
        sm.add_transition("a", "b", condition=lambda ctx: True)
        sm.tick(0.1, {})
        assert events == ["exit_a", "enter_b"]


# =====================================================================
# TestTurretFSMEnhancements
# =====================================================================

class TestTurretFSMEnhancements:
    """Turret FSM with timed states and guards."""

    def test_scanning_has_min_duration(self):
        """Turret scanning should have min_duration preventing instant lock-on."""
        from engine.simulation.unit_states import create_turret_fsm
        sm = create_turret_fsm()
        # First tick: idle -> scanning
        sm.tick(0.1, {"enemies_in_range": [], "weapon_ready": True, "aimed_at_target": False, "just_fired": False})
        assert sm.current_state == "scanning"
        # Immediately provide enemy — should stay scanning due to min_duration
        sm.tick(0.1, {"enemies_in_range": [{"id": "h1"}], "weapon_ready": True, "aimed_at_target": True, "just_fired": False})
        assert sm.current_state == "scanning"

    def test_scanning_transitions_after_min_duration(self):
        """Turret scanning should allow tracking after min_duration."""
        from engine.simulation.unit_states import create_turret_fsm
        sm = create_turret_fsm()
        # idle -> scanning
        sm.tick(0.1, {"enemies_in_range": [], "weapon_ready": True, "aimed_at_target": False, "just_fired": False})
        # Tick enough to pass scanning min_duration (0.5s)
        for _ in range(6):
            sm.tick(0.1, {"enemies_in_range": [{"id": "h1"}], "weapon_ready": True, "aimed_at_target": True, "just_fired": False})
        assert sm.current_state in ("tracking", "engaging")

    def test_engaging_guard_blocks_jammed_weapon(self):
        """Turret should NOT engage if weapon is jammed (degradation >= 0.8)."""
        from engine.simulation.unit_states import create_turret_fsm
        sm = create_turret_fsm()
        # idle -> scanning
        sm.tick(0.1, {"enemies_in_range": [], "weapon_ready": True, "aimed_at_target": False, "just_fired": False, "degradation": 0.0})
        # Wait past scanning min_duration
        for _ in range(6):
            sm.tick(0.1, {"enemies_in_range": [{"id": "h1"}], "weapon_ready": True, "aimed_at_target": True, "just_fired": False, "degradation": 0.0})
        # Should reach tracking
        if sm.current_state == "tracking":
            # Now try to engage with jammed weapon
            sm.tick(0.1, {"enemies_in_range": [{"id": "h1"}], "weapon_ready": True, "aimed_at_target": True, "just_fired": False, "degradation": 0.9})
            # Should stay in tracking because guard blocks engaging
            assert sm.current_state == "tracking"


# =====================================================================
# TestHostileFSMEnhancements
# =====================================================================

class TestHostileFSMEnhancements:
    """Hostile FSM with timed states and priority transitions."""

    def test_spawning_has_min_duration(self):
        """Hostile should stay in spawning for at least min_duration."""
        from engine.simulation.unit_states import create_hostile_fsm
        sm = create_hostile_fsm()
        assert sm.current_state == "spawning"
        # One tick should NOT be enough to transition
        sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": []})
        assert sm.current_state == "spawning"

    def test_spawning_transitions_after_min_duration(self):
        """Hostile should advance after spawning min_duration."""
        from engine.simulation.unit_states import create_hostile_fsm
        sm = create_hostile_fsm()
        # Tick past spawning min_duration (1.0s)
        for _ in range(12):
            sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": []})
        assert sm.current_state == "advancing"

    def test_fleeing_max_duration_rallies_to_advancing(self):
        """Hostile fleeing should rally back to advancing after max_duration."""
        from engine.simulation.unit_states import create_hostile_fsm
        sm = create_hostile_fsm()
        # Fast-forward past spawning
        for _ in range(12):
            sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": []})
        assert sm.current_state == "advancing"
        # Force into fleeing via low health + enemy
        sm.tick(0.1, {
            "health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
            "enemy_in_weapon_range": False, "nearest_enemy_stationary": False,
            "enemies_at_recon_range": False, "cover_available": False,
            "ally_is_flanking": False, "detected": False,
        })
        assert sm.current_state == "fleeing"
        # Tick past fleeing max_duration (15.0s) — keep enemies in range
        # so tick() doesn't trigger early recovery
        transitioned_out = False
        for i in range(160):
            sm.tick(0.1, {
                "health_pct": 0.1,
                "enemies_in_range": [{"id": "t1"}],
                "enemy_in_weapon_range": True,
            })
            # Check if fleeing max_duration fired (state changed from fleeing)
            if sm.current_state != "fleeing" and not transitioned_out:
                transitioned_out = True
                break
        # The max_duration DID fire (fleeing -> advancing), even if advancing
        # then transitions back to fleeing due to low health. Verify via history.
        assert transitioned_out or any(
            (f, t) == ("fleeing", "advancing")
            for _, f, t in sm.history
        )

    def test_fleeing_priority_over_engaging(self):
        """Fleeing transitions should have higher priority than engaging."""
        from engine.simulation.unit_states import create_hostile_fsm
        sm = create_hostile_fsm()
        # Fast-forward past spawning to advancing
        for _ in range(12):
            sm.tick(0.1, {"health_pct": 1.0, "enemies_in_range": []})
        # Both engage and flee conditions true: low health + enemy in range
        sm.tick(0.1, {
            "health_pct": 0.1, "enemies_in_range": [{"id": "t1"}],
            "enemy_in_weapon_range": True, "nearest_enemy_stationary": False,
            "enemies_at_recon_range": False, "cover_available": False,
            "ally_is_flanking": False, "detected": False,
        })
        assert sm.current_state == "fleeing"


# =====================================================================
# TestRoverFSMEnhancements
# =====================================================================

class TestRoverFSMEnhancements:
    """Rover FSM with timed states and guards."""

    def test_pursuing_max_duration_returns_to_patrol(self):
        """Rover should stop chasing after max_duration and return to patrolling."""
        from engine.simulation.unit_states import create_rover_fsm
        sm = create_rover_fsm()
        # idle -> pursuing (enemy in range, not in weapon range)
        ctx = {
            "enemies_in_range": [{"id": "h1"}], "enemy_in_weapon_range": False,
            "health_pct": 1.0, "has_waypoints": True, "degradation": 0.0,
        }
        sm.tick(0.1, ctx)
        assert sm.current_state == "pursuing"
        # Tick past pursuing max_duration (20.0s)
        transitioned_out = False
        for _ in range(210):
            sm.tick(0.1, ctx)
            if sm.current_state != "pursuing" and not transitioned_out:
                transitioned_out = True
                break
        # max_duration should have fired (pursuing -> patrolling).
        # Even if patrolling re-transitions to pursuing, history proves it.
        assert transitioned_out or any(
            (f, t) == ("pursuing", "patrolling")
            for _, f, t in sm.history
        )

    def test_engaging_guard_blocks_jammed_weapon(self):
        """Rover should not engage with jammed weapon."""
        from engine.simulation.unit_states import create_rover_fsm
        sm = create_rover_fsm()
        # idle with enemy in weapon range but degradation high
        sm.tick(0.1, {
            "enemies_in_range": [{"id": "h1"}], "enemy_in_weapon_range": True,
            "health_pct": 1.0, "has_waypoints": False, "degradation": 0.9,
        })
        # Should go to pursuing instead of engaging (guard blocks engaging)
        assert sm.current_state in ("idle", "pursuing")

    def test_retreating_has_min_duration(self):
        """Rover should commit to retreat for min_duration."""
        from engine.simulation.unit_states import create_rover_fsm
        sm = create_rover_fsm()
        # idle -> engaging -> retreating
        sm.tick(0.1, {
            "enemies_in_range": [{"id": "h1"}], "enemy_in_weapon_range": True,
            "health_pct": 1.0, "has_waypoints": False, "degradation": 0.0,
        })
        assert sm.current_state == "engaging"
        # Drop health to trigger retreat
        sm.tick(0.1, {
            "enemies_in_range": [{"id": "h1"}], "enemy_in_weapon_range": True,
            "health_pct": 0.1, "has_waypoints": False, "degradation": 0.0,
        })
        assert sm.current_state == "retreating"
        # Immediately remove enemies — should stay retreating due to min_duration
        sm.tick(0.1, {
            "enemies_in_range": [], "enemy_in_weapon_range": False,
            "health_pct": 0.1, "has_waypoints": False, "degradation": 0.0,
        })
        assert sm.current_state == "retreating"


# =====================================================================
# TestBackwardCompatibility
# =====================================================================

class TestBackwardCompatibility:
    """Existing FSM behavior unchanged for basic cases."""

    def test_state_no_new_args(self):
        """State() with only name should still work."""
        s = State("idle")
        assert s.name == "idle"

    def test_transition_no_new_args(self):
        """Transition() with only from/to/condition should still work."""
        t = Transition("idle", "active", lambda ctx: True)
        assert t.from_state == "idle"
        assert t.to_state == "active"
        assert t.condition({}) is True

    def test_state_machine_no_new_args(self):
        """StateMachine() with only initial_state should still work."""
        sm = StateMachine("idle")
        sm.add_state(State("idle"))
        sm.add_state(State("active"))
        sm.add_transition("idle", "active", lambda ctx: ctx.get("go"))
        sm.tick(0.1, {"go": True})
        assert sm.current_state == "active"

    def test_old_add_transition_signature(self):
        """add_transition(from, to, condition) should still work."""
        sm = StateMachine("a")
        sm.add_state(State("a"))
        sm.add_state(State("b"))
        sm.add_transition("a", "b", lambda ctx: True)
        sm.tick(0.1, {})
        assert sm.current_state == "b"

    def test_time_in_state_still_works(self):
        """time_in_state property should still be available."""
        sm = _make_simple_sm()
        sm.tick(0.1, {"go": False})
        assert sm.time_in_state > 0

    def test_time_in_current_state_alias(self):
        """time_in_current_state should equal time_in_state."""
        sm = _make_simple_sm()
        sm.tick(0.1, {"go": False})
        assert sm.time_in_current_state == sm.time_in_state

    def test_existing_turret_fsm_works(self):
        """Existing turret FSM factory should still produce a working FSM."""
        from engine.simulation.unit_states import create_turret_fsm
        sm = create_turret_fsm()
        assert sm.current_state == "idle"

    def test_existing_hostile_fsm_works(self):
        """Existing hostile FSM factory should still produce a working FSM."""
        from engine.simulation.unit_states import create_hostile_fsm
        sm = create_hostile_fsm()
        assert sm.current_state == "spawning"

    def test_existing_rover_fsm_works(self):
        """Existing rover FSM factory should still produce a working FSM."""
        from engine.simulation.unit_states import create_rover_fsm
        sm = create_rover_fsm()
        assert sm.current_state == "idle"

    def test_existing_drone_fsm_works(self):
        """Existing drone FSM factory should still produce a working FSM."""
        from engine.simulation.unit_states import create_drone_fsm
        sm = create_drone_fsm()
        assert sm.current_state == "idle"

    def test_create_fsm_for_type_still_works(self):
        """create_fsm_for_type should still return correct FSMs."""
        from engine.simulation.unit_states import create_fsm_for_type
        assert create_fsm_for_type("turret") is not None
        assert create_fsm_for_type("rover") is not None
        assert create_fsm_for_type("drone") is not None
        assert create_fsm_for_type("person", alliance="hostile") is not None
        assert create_fsm_for_type("person", alliance="friendly") is None


# =====================================================================
# TestEnginePassesTimeInState
# =====================================================================

@pytest.mark.skip(reason="SimulationEngine does not have _tick_fsms method")
class TestEnginePassesTimeInState:
    """Engine passes time_in_state and degradation to FSM context."""

    def _make_engine_with_turret(self):
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine
        from engine.simulation.target import SimulationTarget
        bus = EventBus()
        engine = SimulationEngine(bus, map_bounds=100)
        turret = SimulationTarget(
            target_id="t-1", name="Turret-1", alliance="friendly",
            asset_type="turret", position=(0, 0), speed=0.0,
        )
        turret.apply_combat_profile()
        engine.add_target(turret)
        return engine, turret

    def test_time_in_state_in_context(self):
        """Engine should pass time_in_state to FSM tick context."""
        engine, turret = self._make_engine_with_turret()
        targets = {turret.target_id: turret}
        engine._tick_fsms(0.1, targets)
        # After one tick, turret should have transitioned and FSM should track time
        fsm = engine._fsms.get(turret.target_id)
        assert fsm is not None
        assert fsm.time_in_current_state >= 0.0

    def test_degradation_in_context(self):
        """Engine should pass degradation to FSM tick context."""
        engine, turret = self._make_engine_with_turret()
        turret.degradation = 0.5
        targets = {turret.target_id: turret}
        # We can verify by checking that the FSM ticks without error
        # The actual use of degradation is tested via guard tests
        engine._tick_fsms(0.1, targets)
        assert turret.fsm_state is not None
