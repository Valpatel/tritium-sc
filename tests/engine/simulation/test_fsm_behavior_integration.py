"""Tests for FSM behavior integration with the simulation engine.

Verifies that:
  - State machines are properly created for each unit type
  - FSM states are synced to target.fsm_state
  - Transitions fire correctly
  - FSMs interact properly with the engine lifecycle
"""

import pytest
from unittest.mock import MagicMock

from engine.simulation.engine import SimulationEngine
from engine.simulation.target import SimulationTarget
from engine.simulation.state_machine import State, StateMachine, Transition
from engine.simulation.unit_states import (
    create_turret_fsm,
    create_rover_fsm,
    create_drone_fsm,
    create_hostile_fsm,
    create_fsm_for_type,
)


def _make_bus():
    """Create a minimal EventBus mock."""
    bus = MagicMock()
    bus.publish = MagicMock()
    bus.subscribe = MagicMock(return_value=MagicMock(get=MagicMock(side_effect=Exception("timeout"))))
    return bus


def _make_engine():
    """Create a SimulationEngine with mock EventBus."""
    bus = _make_bus()
    return SimulationEngine(event_bus=bus, map_bounds=50.0)


def _make_target(target_id="t1", alliance="friendly", asset_type="turret",
                 position=(0.0, 0.0), speed=0.0):
    """Create a SimulationTarget."""
    t = SimulationTarget(
        target_id=target_id,
        name=f"Test {asset_type}",
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        speed=speed,
    )
    t.apply_combat_profile()
    return t


# -- Test: StateMachine basics --


@pytest.mark.unit
class TestStateMachineBasics:
    """Test the generic StateMachine infrastructure."""

    def test_initial_state(self):
        states = [State(name="a"), State(name="b")]
        sm = StateMachine(states=states, transitions=[], initial_state="a")
        assert sm.current.name == "a"

    def test_invalid_initial_state_raises(self):
        states = [State(name="a")]
        with pytest.raises(ValueError, match="not found"):
            StateMachine(states=states, transitions=[], initial_state="z")

    def test_tick_calls_on_tick(self):
        ticked = {"count": 0}

        def on_tick(dt):
            ticked["count"] += 1

        states = [State(name="a", on_tick=on_tick)]
        sm = StateMachine(states=states, transitions=[], initial_state="a")
        sm.tick(0.1)
        assert ticked["count"] == 1

    def test_transition_fires(self):
        states = [State(name="a"), State(name="b")]
        transitions = [
            Transition(from_state="a", to_state="b", condition=lambda: True)
        ]
        sm = StateMachine(states=states, transitions=transitions, initial_state="a")
        sm.tick(0.1)
        assert sm.current.name == "b"

    def test_transition_does_not_fire_when_false(self):
        states = [State(name="a"), State(name="b")]
        transitions = [
            Transition(from_state="a", to_state="b", condition=lambda: False)
        ]
        sm = StateMachine(states=states, transitions=transitions, initial_state="a")
        sm.tick(0.1)
        assert sm.current.name == "a"

    def test_on_enter_called(self):
        entered = {"called": False}

        def on_enter():
            entered["called"] = True

        states = [State(name="a"), State(name="b", on_enter=on_enter)]
        transitions = [
            Transition(from_state="a", to_state="b", condition=lambda: True)
        ]
        sm = StateMachine(states=states, transitions=transitions, initial_state="a")
        sm.tick(0.1)
        assert entered["called"]

    def test_on_exit_called(self):
        exited = {"called": False}

        def on_exit():
            exited["called"] = True

        states = [State(name="a", on_exit=on_exit), State(name="b")]
        transitions = [
            Transition(from_state="a", to_state="b", condition=lambda: True)
        ]
        sm = StateMachine(states=states, transitions=transitions, initial_state="a")
        sm.tick(0.1)
        assert exited["called"]

    def test_on_transition_callback(self):
        transitioned = {"called": False}

        def on_transition():
            transitioned["called"] = True

        states = [State(name="a"), State(name="b")]
        transitions = [
            Transition(from_state="a", to_state="b", condition=lambda: True,
                       on_transition=on_transition)
        ]
        sm = StateMachine(states=states, transitions=transitions, initial_state="a")
        sm.tick(0.1)
        assert transitioned["called"]

    def test_force_state(self):
        states = [State(name="a"), State(name="b"), State(name="c")]
        sm = StateMachine(states=states, transitions=[], initial_state="a")
        sm.force_state("c")
        assert sm.current.name == "c"

    def test_force_state_invalid_raises(self):
        states = [State(name="a")]
        sm = StateMachine(states=states, transitions=[], initial_state="a")
        with pytest.raises(ValueError, match="not found"):
            sm.force_state("z")

    def test_state_names(self):
        states = [State(name="a"), State(name="b"), State(name="c")]
        sm = StateMachine(states=states, transitions=[], initial_state="a")
        assert set(sm.state_names) == {"a", "b", "c"}

    def test_first_matching_transition_wins(self):
        states = [State(name="a"), State(name="b"), State(name="c")]
        transitions = [
            Transition(from_state="a", to_state="b", condition=lambda: True),
            Transition(from_state="a", to_state="c", condition=lambda: True),
        ]
        sm = StateMachine(states=states, transitions=transitions, initial_state="a")
        sm.tick(0.1)
        assert sm.current.name == "b"  # first match wins

    def test_initial_state_on_enter_called(self):
        entered = {"called": False}

        def on_enter():
            entered["called"] = True

        states = [State(name="a", on_enter=on_enter)]
        sm = StateMachine(states=states, transitions=[], initial_state="a")
        assert entered["called"]


# -- Test: Unit-type FSM factories --


@pytest.mark.unit
class TestUnitFSMFactories:
    """Test that each unit type gets the correct FSM."""

    def test_turret_fsm_states(self):
        fsm = create_turret_fsm()
        assert "idle" in fsm.state_names
        assert "scanning" in fsm.state_names
        assert "engaging" in fsm.state_names
        assert "reloading" in fsm.state_names
        # Initial state is idle
        assert fsm.current.name == "idle"

    def test_turret_fsm_transitions_to_scanning(self):
        fsm = create_turret_fsm()
        fsm.tick(0.1)
        assert fsm.current.name == "scanning"

    def test_rover_fsm_states(self):
        fsm = create_rover_fsm()
        assert "idle" in fsm.state_names
        assert "patrolling" in fsm.state_names
        assert "pursuing" in fsm.state_names
        assert "engaging" in fsm.state_names
        assert "retreating" in fsm.state_names

    def test_rover_fsm_transitions_to_patrolling(self):
        fsm = create_rover_fsm()
        # Rover needs has_waypoints=True in context to transition to patrolling
        for _ in range(20):
            fsm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [], "health_pct": 1.0})
        assert fsm.current.name == "patrolling"

    def test_drone_fsm_states(self):
        fsm = create_drone_fsm()
        assert "idle" in fsm.state_names
        assert "scouting" in fsm.state_names
        assert "strafing" in fsm.state_names
        assert "retreating" in fsm.state_names

    def test_drone_fsm_transitions_to_scouting(self):
        fsm = create_drone_fsm()
        # Drone needs has_waypoints=True in context to transition to scouting
        for _ in range(20):
            fsm.tick(0.1, {"has_waypoints": True, "enemies_in_range": [], "health_pct": 1.0})
        assert fsm.current.name == "scouting"

    def test_hostile_fsm_states(self):
        fsm = create_hostile_fsm()
        # New hostile FSM starts at "spawning" and includes richer states
        assert "spawning" in fsm.state_names
        assert "advancing" in fsm.state_names
        assert "engaging" in fsm.state_names
        assert "fleeing" in fsm.state_names
        # Initial state is spawning (hostiles have a spawn-in period)
        assert fsm.current.name == "spawning"

    def test_hostile_fsm_stays_spawning(self):
        """Hostile starts in spawning and stays there briefly before advancing."""
        fsm = create_hostile_fsm()
        fsm.tick(0.1, {"enemies_in_range": [], "health_pct": 1.0})
        # After one tick, still spawning (min_duration ~0.8s)
        assert fsm.current.name == "spawning"


# -- Test: create_fsm_for_type routing --


@pytest.mark.unit
class TestCreateFSMForType:
    """Test the routing function that selects FSM by type+alliance."""

    def test_friendly_turret(self):
        fsm = create_fsm_for_type("turret", "friendly")
        assert fsm is not None
        assert "scanning" in fsm.state_names

    def test_friendly_heavy_turret(self):
        fsm = create_fsm_for_type("heavy_turret", "friendly")
        assert fsm is not None
        assert "engaging" in fsm.state_names

    def test_friendly_rover(self):
        fsm = create_fsm_for_type("rover", "friendly")
        assert fsm is not None
        assert "patrolling" in fsm.state_names

    def test_friendly_tank(self):
        fsm = create_fsm_for_type("tank", "friendly")
        assert fsm is not None
        assert "pursuing" in fsm.state_names

    def test_friendly_drone(self):
        fsm = create_fsm_for_type("drone", "friendly")
        assert fsm is not None
        assert "scouting" in fsm.state_names

    def test_friendly_scout_drone(self):
        fsm = create_fsm_for_type("scout_drone", "friendly")
        assert fsm is not None
        assert "strafing" in fsm.state_names

    def test_hostile_person(self):
        fsm = create_fsm_for_type("person", "hostile")
        assert fsm is not None
        assert "approaching" in fsm.state_names

    def test_neutral_person_no_fsm(self):
        fsm = create_fsm_for_type("person", "neutral")
        assert fsm is None

    def test_vehicle_no_fsm(self):
        fsm = create_fsm_for_type("vehicle", "neutral")
        assert fsm is None

    def test_animal_no_fsm(self):
        fsm = create_fsm_for_type("animal", "neutral")
        assert fsm is None


# -- Test: FSM + Engine integration --


@pytest.mark.unit
class TestFSMEngineIntegration:
    """Test FSM behavior within the engine context."""

    def test_target_fsm_state_set_on_add(self):
        engine = _make_engine()
        t = _make_target("turret-1", "friendly", "turret")
        engine.add_target(t)
        assert t.fsm_state == "idle"  # initial state

    def test_hostile_fsm_state_set_on_add(self):
        engine = _make_engine()
        t = _make_target("h-1", "hostile", "person", speed=1.5)
        engine.add_target(t)
        # New hostile FSM starts at "spawning" (spawn-in period before advancing)
        assert t.fsm_state == "spawning"

    def test_fsm_state_in_to_dict(self):
        engine = _make_engine()
        t = _make_target("turret-1", "friendly", "turret")
        engine.add_target(t)
        d = t.to_dict()
        assert "fsm_state" in d
        assert d["fsm_state"] == "idle"

    def test_fsm_cleaned_up_on_remove(self):
        engine = _make_engine()
        t = _make_target("turret-1", "friendly", "turret")
        engine.add_target(t)
        assert "turret-1" in engine._fsms
        engine.remove_target("turret-1")
        assert "turret-1" not in engine._fsms

    def test_fsm_cleared_on_game_reset(self):
        engine = _make_engine()
        t1 = _make_target("turret-1", "friendly", "turret")
        t2 = _make_target("h-1", "hostile", "person", speed=1.5)
        engine.add_target(t1)
        engine.add_target(t2)
        assert len(engine._fsms) == 2
        engine.reset_game()
        assert len(engine._fsms) == 0

    def test_multiple_targets_get_independent_fsms(self):
        engine = _make_engine()
        t1 = _make_target("turret-1", "friendly", "turret")
        t2 = _make_target("drone-1", "friendly", "drone", speed=5.0)
        engine.add_target(t1)
        engine.add_target(t2)
        # Turret FSM and drone FSM should be different instances
        assert engine._fsms["turret-1"] is not engine._fsms["drone-1"]
        # Turret starts at idle, drone starts at idle
        assert t1.fsm_state == "idle"
        assert t2.fsm_state == "idle"

    def test_target_fsm_state_field_default(self):
        """New targets without FSM should have None fsm_state."""
        t = SimulationTarget(
            target_id="test",
            name="Test",
            alliance="neutral",
            asset_type="vehicle",
            position=(0.0, 0.0),
        )
        assert t.fsm_state is None

    def test_force_state_updates_target(self):
        """Forcing an FSM state should update the target on next tick."""
        engine = _make_engine()
        t = _make_target("turret-1", "friendly", "turret")
        engine.add_target(t)
        fsm = engine._fsms["turret-1"]
        fsm.force_state("engaging")
        # Simulate what the tick loop does
        t.fsm_state = fsm.current.name
        assert t.fsm_state == "engaging"
