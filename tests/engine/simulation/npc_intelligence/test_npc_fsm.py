# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for NPC FSM factories — civilian pedestrian, vehicle, animal."""

import pytest
from engine.simulation.npc_intelligence.npc_fsm import (
    create_civilian_pedestrian_fsm,
    create_civilian_vehicle_fsm,
    create_animal_fsm,
    create_npc_fsm,
)
from engine.simulation.state_machine import StateMachine


# ============================================================================
# Civilian Pedestrian FSM
# ============================================================================

class TestCivilianPedestrianFSM:
    """Tests for the 7-state civilian pedestrian FSM."""

    def test_initial_state_is_walking(self):
        sm = create_civilian_pedestrian_fsm()
        assert sm.current_state == "walking"

    def test_has_all_seven_states(self):
        sm = create_civilian_pedestrian_fsm()
        expected = {"walking", "pausing", "observing", "fleeing", "hiding", "curious", "panicking"}
        assert expected.issubset(set(sm.state_names))

    def test_returns_state_machine(self):
        sm = create_civilian_pedestrian_fsm()
        assert isinstance(sm, StateMachine)

    def test_danger_triggers_fleeing(self):
        sm = create_civilian_pedestrian_fsm()
        sm.tick(0.1, {"danger_nearby": True, "danger_distance": 10.0})
        assert sm.current_state == "fleeing"

    def test_danger_from_any_state(self):
        """Danger override should work from any non-flee state."""
        sm = create_civilian_pedestrian_fsm()
        # First get to pausing
        sm.tick(0.1, {"danger_nearby": False})
        # Force to pausing
        sm.force_state("pausing")
        assert sm.current_state == "pausing"
        # Now trigger danger
        sm.tick(0.1, {"danger_nearby": True, "danger_distance": 10.0})
        assert sm.current_state == "fleeing"

    def test_fleeing_to_hiding_with_cover(self):
        sm = create_civilian_pedestrian_fsm()
        sm.tick(0.1, {"danger_nearby": True, "danger_distance": 10.0})
        assert sm.current_state == "fleeing"
        sm.tick(0.1, {"danger_nearby": True, "danger_distance": 10.0, "cover_available": True})
        assert sm.current_state == "hiding"

    def test_fleeing_to_panicking_no_cover_close_danger(self):
        sm = create_civilian_pedestrian_fsm()
        sm.tick(0.1, {"danger_nearby": True, "danger_distance": 5.0})
        assert sm.current_state == "fleeing"
        # Close danger, no cover
        sm.tick(0.1, {"danger_nearby": True, "danger_distance": 5.0, "cover_available": False})
        assert sm.current_state == "panicking"

    def test_interest_triggers_curious(self):
        sm = create_civilian_pedestrian_fsm()
        sm.tick(0.1, {"danger_nearby": False})
        sm.tick(0.1, {"danger_nearby": False, "interest_nearby": True, "curiosity": 0.8})
        assert sm.current_state == "curious"

    def test_curious_to_observing(self):
        sm = create_civilian_pedestrian_fsm()
        sm.force_state("curious")
        sm.tick(0.1, {"danger_nearby": False, "interest_nearby": True, "interest_distance": 5.0})
        assert sm.current_state == "observing"

    def test_pausing_returns_to_walking(self):
        sm = create_civilian_pedestrian_fsm()
        sm.force_state("pausing")
        # Tick past max_duration
        for _ in range(200):
            sm.tick(0.1, {"danger_nearby": False})
        assert sm.current_state == "walking"

    def test_observing_returns_to_walking(self):
        sm = create_civilian_pedestrian_fsm()
        sm.force_state("observing")
        for _ in range(150):
            sm.tick(0.1, {"danger_nearby": False})
        assert sm.current_state == "walking"

    def test_hiding_returns_to_walking_when_safe(self):
        sm = create_civilian_pedestrian_fsm()
        sm.force_state("hiding")
        for _ in range(400):
            sm.tick(0.1, {"danger_nearby": False})
        assert sm.current_state == "walking"

    def test_panicking_to_fleeing(self):
        sm = create_civilian_pedestrian_fsm()
        sm.force_state("panicking")
        for _ in range(200):
            sm.tick(0.1, {"danger_nearby": True, "danger_distance": 20.0})
        assert sm.current_state == "fleeing"

    def test_walking_no_events_stays_walking(self):
        sm = create_civilian_pedestrian_fsm()
        sm.tick(0.1, {"danger_nearby": False})
        assert sm.current_state == "walking"


# ============================================================================
# Civilian Vehicle FSM
# ============================================================================

class TestCivilianVehicleFSM:
    """Tests for the 5-state civilian vehicle FSM."""

    def test_initial_state_is_driving(self):
        sm = create_civilian_vehicle_fsm()
        assert sm.current_state == "driving"

    def test_has_all_five_states(self):
        sm = create_civilian_vehicle_fsm()
        expected = {"driving", "stopped", "yielding", "evading", "parked"}
        assert expected.issubset(set(sm.state_names))

    def test_returns_state_machine(self):
        sm = create_civilian_vehicle_fsm()
        assert isinstance(sm, StateMachine)

    def test_danger_triggers_evading(self):
        sm = create_civilian_vehicle_fsm()
        sm.tick(0.1, {"danger_nearby": True, "danger_distance": 10.0})
        assert sm.current_state == "evading"

    def test_evading_from_any_state(self):
        sm = create_civilian_vehicle_fsm()
        sm.force_state("stopped")
        sm.tick(0.1, {"danger_nearby": True, "danger_distance": 10.0})
        assert sm.current_state == "evading"

    def test_driving_to_stopped(self):
        sm = create_civilian_vehicle_fsm()
        sm.tick(0.1, {"danger_nearby": False, "obstacle_ahead": True})
        assert sm.current_state == "stopped"

    def test_driving_to_yielding(self):
        sm = create_civilian_vehicle_fsm()
        sm.tick(0.1, {"danger_nearby": False, "emergency_nearby": True})
        assert sm.current_state == "yielding"

    def test_stopped_returns_to_driving(self):
        sm = create_civilian_vehicle_fsm()
        sm.force_state("stopped")
        for _ in range(100):
            sm.tick(0.1, {"danger_nearby": False})
        assert sm.current_state == "driving"

    def test_yielding_returns_to_driving(self):
        sm = create_civilian_vehicle_fsm()
        sm.force_state("yielding")
        for _ in range(120):
            sm.tick(0.1, {"danger_nearby": False})
        assert sm.current_state == "driving"

    def test_parked_returns_to_driving(self):
        sm = create_civilian_vehicle_fsm()
        sm.force_state("parked")
        for _ in range(350):
            sm.tick(0.1, {"danger_nearby": False})
        assert sm.current_state == "driving"


# ============================================================================
# Animal FSM
# ============================================================================

class TestAnimalFSM:
    """Tests for the 5-state animal FSM."""

    def test_initial_state_is_wandering(self):
        sm = create_animal_fsm()
        assert sm.current_state == "wandering"

    def test_has_all_five_states(self):
        sm = create_animal_fsm()
        expected = {"wandering", "resting", "startled", "fleeing", "following"}
        assert expected.issubset(set(sm.state_names))

    def test_returns_state_machine(self):
        sm = create_animal_fsm()
        assert isinstance(sm, StateMachine)

    def test_loud_noise_triggers_startled(self):
        sm = create_animal_fsm()
        sm.tick(0.1, {"loud_noise": True})
        assert sm.current_state == "startled"

    def test_startled_auto_transitions_to_fleeing(self):
        sm = create_animal_fsm()
        sm.force_state("startled")
        for _ in range(40):
            sm.tick(0.1, {})
        assert sm.current_state == "fleeing"

    def test_dog_follows_nearby_person(self):
        sm = create_animal_fsm()
        sm.tick(0.1, {"loud_noise": False, "is_dog": True, "person_nearby": True})
        assert sm.current_state == "following"

    def test_fleeing_returns_to_wandering_when_safe(self):
        sm = create_animal_fsm()
        sm.force_state("fleeing")
        for _ in range(200):
            sm.tick(0.1, {"loud_noise": False})
        assert sm.current_state == "wandering"

    def test_wandering_no_events_stays(self):
        sm = create_animal_fsm()
        sm.tick(0.1, {"loud_noise": False})
        assert sm.current_state == "wandering"


# ============================================================================
# Factory Router
# ============================================================================

class TestCreateNPCFsm:
    """Tests for the NPC FSM factory router."""

    def test_person_neutral_gets_pedestrian_fsm(self):
        sm = create_npc_fsm("person", "neutral")
        assert sm is not None
        assert sm.current_state == "walking"

    def test_vehicle_neutral_gets_vehicle_fsm(self):
        sm = create_npc_fsm("vehicle", "neutral")
        assert sm is not None
        assert sm.current_state == "driving"

    def test_animal_neutral_gets_animal_fsm(self):
        sm = create_npc_fsm("animal", "neutral")
        assert sm is not None
        assert sm.current_state == "wandering"

    def test_unknown_type_returns_none(self):
        sm = create_npc_fsm("turret", "friendly")
        assert sm is None

    def test_hostile_person_returns_none(self):
        """Hostile persons use create_hostile_fsm, not NPC FSM."""
        sm = create_npc_fsm("person", "hostile")
        assert sm is None
