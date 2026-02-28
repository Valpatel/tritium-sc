# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for NPC Intelligence Plugin — full-stack behavior."""

import math
import time
import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.target import SimulationTarget
from engine.simulation.npc_intelligence.brain import NPCBrain, NPCPersonality, NPCMemory
from engine.simulation.npc_intelligence.npc_fsm import create_npc_fsm
from engine.simulation.npc_intelligence.event_reactor import EventReactor
from engine.simulation.npc_intelligence.fallback import BehaviorTreeFallback
from engine.simulation.npc_intelligence.crowd import CrowdDynamics
from engine.simulation.npc_intelligence.alliance import AllianceManager
from engine.simulation.npc_intelligence.prompts import build_npc_prompt, parse_npc_response


def _make_target(tid, asset_type="person", alliance="neutral", pos=(0, 0)):
    return SimulationTarget(
        target_id=tid, name=f"NPC {tid}", alliance=alliance,
        asset_type=asset_type, position=pos, speed=1.5, is_combatant=False,
    )


class TestNPCGetsFSM:
    """Integration: NPC targets get FSMs via the intelligence system."""

    def test_pedestrian_gets_fsm_via_create_npc_fsm(self):
        sm = create_npc_fsm("person", "neutral")
        assert sm is not None
        assert sm.current_state == "walking"

    def test_vehicle_gets_fsm(self):
        sm = create_npc_fsm("vehicle", "neutral")
        assert sm is not None
        assert sm.current_state == "driving"

    def test_animal_gets_fsm(self):
        sm = create_npc_fsm("animal", "neutral")
        assert sm is not None
        assert sm.current_state == "wandering"

    def test_brain_fsm_state_matches(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        assert brain.fsm_state == "walking"


class TestNPCFleeFromCombat:
    """Integration: NPCs flee when combat events occur nearby."""

    def test_pedestrian_flees_on_weapon_fired(self):
        bus = EventBus()
        reactor = EventReactor(bus)

        brain = NPCBrain("npc-1", "person", "neutral")
        bwp = [(brain, (10.0, 0.0))]

        event = {"type": "weapon_fired", "data": {"position": [0.0, 0.0]}}
        reactor.process_event(event, bwp)

        # Now tick the brain — it should flee
        brain.tick(0.1)
        assert brain.fsm_state == "fleeing"

    def test_multiple_events_increase_danger(self):
        bus = EventBus()
        reactor = EventReactor(bus)

        brain = NPCBrain("npc-1", "person", "neutral")
        bwp = [(brain, (15.0, 0.0))]

        for _ in range(3):
            event = {"type": "target_eliminated", "data": {"position": [0.0, 0.0]}}
            reactor.process_event(event, bwp)

        assert brain.memory.danger_level() > 0.0
        assert len(brain.memory.events) == 3


class TestVehicleEvades:
    """Integration: Vehicles evade on danger."""

    def test_vehicle_evades_on_explosion(self):
        bus = EventBus()
        reactor = EventReactor(bus)

        brain = NPCBrain("npc-1", "vehicle", "neutral")
        bwp = [(brain, (20.0, 0.0))]

        event = {"type": "weapon_fired", "data": {"position": [0.0, 0.0]}}
        reactor.process_event(event, bwp)

        brain.tick(0.1)
        assert brain.fsm_state == "evading"


class TestAnimalStartles:
    """Integration: Animals startle on loud noise (danger events)."""

    def test_animal_startles_on_nearby_combat(self):
        brain = NPCBrain("npc-1", "animal", "neutral")
        brain.set_danger(distance=5.0)
        brain.tick(0.1)
        assert brain.fsm_state == "startled"


class TestCrowdContagion:
    """Integration: Panic and curiosity spread between NPCs."""

    def test_panic_spreads_from_fleeing_to_nearby(self):
        crowd = CrowdDynamics()

        fleeing = NPCBrain("npc-1", "person", "neutral")
        fleeing.set_danger(distance=5.0)
        fleeing.tick(0.1)
        assert fleeing.fsm_state == "fleeing"

        bystander = NPCBrain("npc-2", "person", "neutral")

        bwp = [(fleeing, (0.0, 0.0)), (bystander, (10.0, 0.0))]
        crowd.update(bwp)

        # Bystander should now have danger set
        bystander.tick(0.1)
        assert bystander.fsm_state == "fleeing"


class TestRadicalization:
    """Integration: NPC can radicalize under extreme conditions."""

    def test_full_radicalization_flow(self):
        bus = EventBus()
        q = bus.subscribe()  # monitor for events

        alliance_mgr = AllianceManager(event_bus=bus)

        brain = NPCBrain("npc-1", "person", "neutral",
                         personality=NPCPersonality(curiosity=0.1, caution=0.1,
                                                     sociability=0.1, aggression=0.9))
        target = _make_target("npc-1", pos=(50.0, 50.0))

        # Add 3 elimination events
        for _ in range(3):
            brain.memory.add_event("target_eliminated", {"distance": 15.0})

        result = alliance_mgr.check_radicalization(
            brain, target, escalation_level="red", friendly_positions=[]
        )

        assert result == "npc-1"
        assert target.alliance == "hostile"
        assert target.is_combatant is True
        assert target.fsm_state == "spawning"

    def test_low_aggression_blocks_radicalization(self):
        bus = EventBus()
        alliance_mgr = AllianceManager(event_bus=bus)

        brain = NPCBrain("npc-1", "person", "neutral",
                         personality=NPCPersonality(curiosity=0.5, caution=0.5,
                                                     sociability=0.5, aggression=0.3))
        target = _make_target("npc-1")

        for _ in range(5):
            brain.memory.add_event("target_eliminated", {"distance": 10.0})

        result = alliance_mgr.check_radicalization(
            brain, target, escalation_level="red", friendly_positions=[]
        )
        assert result is None
        assert target.alliance == "neutral"


class TestFallbackDecisions:
    """Integration: Fallback produces valid actions that the brain can apply."""

    def test_fallback_flee_applied_to_brain(self):
        fallback = BehaviorTreeFallback()
        brain = NPCBrain("npc-1", "person", "neutral",
                         personality=NPCPersonality(curiosity=0.1, caution=0.9,
                                                     sociability=0.5, aggression=0.0))
        action = fallback.decide(brain, danger_level=0.8, interest_level=0.0)
        assert action in ("FLEE", "HIDE")
        brain.apply_action(action)
        assert brain.fsm_state in ("fleeing", "hiding")

    def test_fallback_normal_walk(self):
        fallback = BehaviorTreeFallback()
        brain = NPCBrain("npc-1", "person", "neutral")
        action = fallback.decide(brain, danger_level=0.0, interest_level=0.0)
        assert action in ("WALK", "PAUSE")


class TestPromptRoundtrip:
    """Integration: Prompt building and response parsing work end-to-end."""

    def test_build_prompt_and_parse_response(self):
        brain = NPCBrain("npc-1", "person", "neutral")
        brain.memory.add_event("weapon_fired", {"distance": 10.0})

        prompt = build_npc_prompt(brain, nearby_entities=[
            {"name": "Hostile Alpha", "alliance": "hostile", "asset_type": "person",
             "position": {"x": 5.0, "y": 0.0}},
        ])

        assert "npc-1" in prompt
        assert "weapon_fired" in prompt
        assert "Hostile Alpha" in prompt

        # Parse various response formats
        assert parse_npc_response("FLEE") == "FLEE"
        assert parse_npc_response("I should run away!") == "FLEE"
        assert parse_npc_response("") == "WALK"


class TestPerformanceBudget:
    """Integration: 70 NPCs must tick within 5ms."""

    def test_70_npcs_tick_under_5ms(self):
        brains = []
        for i in range(70):
            asset_type = ["person", "vehicle", "animal"][i % 3]
            brain = NPCBrain(f"npc-{i}", asset_type, "neutral")
            brains.append(brain)

        # Warm up
        for b in brains:
            b.tick(0.1)

        # Measure
        start = time.perf_counter()
        for _ in range(10):  # 10 ticks
            for b in brains:
                b.tick(0.1)
        elapsed = time.perf_counter() - start

        per_tick = elapsed / 10.0
        assert per_tick < 0.005, f"70 NPCs tick took {per_tick*1000:.1f}ms (budget: 5ms)"

    def test_crowd_dynamics_70_npcs_under_5ms(self):
        crowd = CrowdDynamics()
        bwp = []
        for i in range(70):
            asset_type = ["person", "vehicle", "animal"][i % 3]
            brain = NPCBrain(f"npc-{i}", asset_type, "neutral")
            # Spread NPCs around a 60x60 map
            x = (i % 10) * 6.0 - 30.0
            y = (i // 10) * 6.0 - 30.0
            bwp.append((brain, (x, y)))

        # Set a few as fleeing to trigger panic spreading
        bwp[0][0].set_danger(5.0)
        bwp[0][0].tick(0.1)
        bwp[5][0].set_danger(5.0)
        bwp[5][0].tick(0.1)

        # Warm up
        crowd.update(bwp)

        # Measure
        start = time.perf_counter()
        for _ in range(10):
            crowd.update(bwp)
        elapsed = time.perf_counter() - start

        per_update = elapsed / 10.0
        assert per_update < 0.005, f"Crowd update took {per_update*1000:.1f}ms (budget: 5ms)"

    def test_event_reactor_70_npcs_under_5ms(self):
        bus = EventBus()
        reactor = EventReactor(bus)

        bwp = []
        for i in range(70):
            brain = NPCBrain(f"npc-{i}", "person", "neutral")
            x = (i % 10) * 6.0 - 30.0
            y = (i // 10) * 6.0 - 30.0
            bwp.append((brain, (x, y)))

        event = {"type": "weapon_fired", "data": {"position": [0.0, 0.0]}}

        # Warm up
        reactor.process_event(event, bwp)

        # Measure
        start = time.perf_counter()
        for _ in range(10):
            reactor.process_event(event, bwp)
        elapsed = time.perf_counter() - start

        per_event = elapsed / 10.0
        assert per_event < 0.005, f"Event processing took {per_event*1000:.1f}ms (budget: 5ms)"
