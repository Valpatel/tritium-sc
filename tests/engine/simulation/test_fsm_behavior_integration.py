# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
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

    def test_neutral_person_gets_npc_fsm(self):
        fsm = create_fsm_for_type("person", "neutral")
        assert fsm is not None
        assert fsm.current_state == "walking"

    def test_vehicle_gets_npc_fsm(self):
        fsm = create_fsm_for_type("vehicle", "neutral")
        assert fsm is not None
        assert fsm.current_state == "driving"

    def test_animal_gets_npc_fsm(self):
        fsm = create_fsm_for_type("animal", "neutral")
        assert fsm is not None
        assert fsm.current_state == "wandering"


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


# --------------------------------------------------------------------------
# FSM-driven behavior: friendly units respect FSM state
# --------------------------------------------------------------------------

@pytest.mark.unit
class TestFSMDrivenBehavior:
    """Verify that friendly behaviors respect FSM state."""

    def _make_combat(self):
        """Create CombatSystem with mock EventBus."""
        from engine.simulation.combat import CombatSystem
        bus = _make_bus()
        return CombatSystem(bus)

    def _make_behaviors(self):
        from engine.simulation.behaviors import UnitBehaviors
        return UnitBehaviors(self._make_combat())

    def test_turret_fires_in_engaging_state(self):
        """Turret in engaging state should fire at hostiles."""
        behaviors = self._make_behaviors()
        turret = _make_target("t1", "friendly", "turret")
        turret.fsm_state = "engaging"
        turret.weapon_cooldown = 0.0
        turret.last_fired = 0.0

        hostile = _make_target("h1", "hostile", "person", position=(10.0, 0.0), speed=1.5)

        targets = {"t1": turret, "h1": hostile}
        behaviors.tick(0.1, targets)

        # Turret should have fired (last_fired updated)
        assert turret.last_fired > 0

    def test_turret_does_not_fire_in_cooldown(self):
        """Turret in cooldown state should not fire."""
        behaviors = self._make_behaviors()
        turret = _make_target("t1", "friendly", "turret")
        turret.fsm_state = "cooldown"
        turret.weapon_cooldown = 0.0
        turret.last_fired = 0.0

        hostile = _make_target("h1", "hostile", "person", position=(10.0, 0.0), speed=1.5)

        targets = {"t1": turret, "h1": hostile}
        behaviors.tick(0.1, targets)

        # Turret should NOT have fired
        assert turret.last_fired == 0.0

    def test_turret_fires_in_idle(self):
        """Turret in idle state should still fire (always combat-ready)."""
        behaviors = self._make_behaviors()
        turret = _make_target("t1", "friendly", "turret")
        turret.fsm_state = "idle"
        turret.weapon_cooldown = 0.0
        turret.last_fired = 0.0

        hostile = _make_target("h1", "hostile", "person", position=(10.0, 0.0), speed=1.5)

        targets = {"t1": turret, "h1": hostile}
        behaviors.tick(0.1, targets)

        # Turret fires even in idle — always combat-ready
        assert turret.last_fired > 0

    def test_drone_does_not_fire_in_scouting(self):
        """Drone in scouting state should observe but not engage."""
        behaviors = self._make_behaviors()
        drone = _make_target("d1", "friendly", "drone", speed=5.0)
        drone.fsm_state = "scouting"
        drone.weapon_cooldown = 0.0
        drone.last_fired = 0.0

        hostile = _make_target("h1", "hostile", "person", position=(10.0, 0.0), speed=1.5)

        targets = {"d1": drone, "h1": hostile}
        behaviors.tick(0.1, targets)

        # Should NOT have fired in scouting
        assert drone.last_fired == 0.0

    def test_drone_fires_in_engaging(self):
        """Drone in engaging state should fire normally."""
        behaviors = self._make_behaviors()
        drone = _make_target("d1", "friendly", "drone", speed=5.0)
        drone.fsm_state = "engaging"
        drone.weapon_cooldown = 0.0
        drone.last_fired = 0.0

        hostile = _make_target("h1", "hostile", "person", position=(10.0, 0.0), speed=1.5)

        targets = {"d1": drone, "h1": hostile}
        behaviors.tick(0.1, targets)

        assert drone.last_fired > 0

    def test_drone_ignores_hostiles_in_rtb(self):
        """Drone in rtb state should ignore all hostiles."""
        behaviors = self._make_behaviors()
        drone = _make_target("d1", "friendly", "drone", speed=5.0)
        drone.fsm_state = "rtb"
        drone.weapon_cooldown = 0.0
        drone.last_fired = 0.0
        initial_heading = drone.heading

        hostile = _make_target("h1", "hostile", "person", position=(10.0, 0.0), speed=1.5)

        targets = {"d1": drone, "h1": hostile}
        behaviors.tick(0.1, targets)

        # Should not fire OR rotate toward hostile
        assert drone.last_fired == 0.0
        assert drone.heading == initial_heading

    def test_rover_does_not_engage_in_retreating(self):
        """Rover in retreating state should not fire."""
        behaviors = self._make_behaviors()
        rover = _make_target("r1", "friendly", "rover", speed=3.0)
        rover.fsm_state = "retreating"
        rover.weapon_cooldown = 0.0
        rover.last_fired = 0.0
        initial_heading = rover.heading

        hostile = _make_target("h1", "hostile", "person", position=(10.0, 0.0), speed=1.5)

        targets = {"r1": rover, "h1": hostile}
        behaviors.tick(0.1, targets)

        assert rover.last_fired == 0.0
        assert rover.heading == initial_heading

    def test_rover_does_not_engage_in_rtb(self):
        """Rover in rtb state should not fire."""
        behaviors = self._make_behaviors()
        rover = _make_target("r1", "friendly", "rover", speed=3.0)
        rover.fsm_state = "rtb"
        rover.weapon_cooldown = 0.0
        rover.last_fired = 0.0

        hostile = _make_target("h1", "hostile", "person", position=(10.0, 0.0), speed=1.5)

        targets = {"r1": rover, "h1": hostile}
        behaviors.tick(0.1, targets)

        assert rover.last_fired == 0.0

    def test_rover_fires_in_engaging(self):
        """Rover in engaging state should fire normally."""
        behaviors = self._make_behaviors()
        rover = _make_target("r1", "friendly", "rover", speed=3.0)
        rover.fsm_state = "engaging"
        rover.weapon_cooldown = 0.0
        rover.last_fired = 0.0

        hostile = _make_target("h1", "hostile", "person", position=(10.0, 0.0), speed=1.5)

        targets = {"r1": rover, "h1": hostile}
        behaviors.tick(0.1, targets)

        assert rover.last_fired > 0

    def test_no_fsm_state_fires_normally(self):
        """Units with no FSM state (None) should fire normally for backward compat."""
        behaviors = self._make_behaviors()
        turret = _make_target("t1", "friendly", "turret")
        turret.fsm_state = None  # no FSM set
        turret.weapon_cooldown = 0.0
        turret.last_fired = 0.0

        hostile = _make_target("h1", "hostile", "person", position=(10.0, 0.0), speed=1.5)

        targets = {"t1": turret, "h1": hostile}
        behaviors.tick(0.1, targets)

        # Should fire (backward compatible)
        assert turret.last_fired > 0

    def test_drone_orbiting_does_not_fire(self):
        """Drone in orbiting state maintains distance but doesn't fire."""
        behaviors = self._make_behaviors()
        drone = _make_target("d1", "friendly", "drone", speed=5.0)
        drone.fsm_state = "orbiting"
        drone.weapon_cooldown = 0.0
        drone.last_fired = 0.0

        hostile = _make_target("h1", "hostile", "person", position=(10.0, 0.0), speed=1.5)

        targets = {"d1": drone, "h1": hostile}
        behaviors.tick(0.1, targets)

        assert drone.last_fired == 0.0
