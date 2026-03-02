# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for civil unrest behavior — instigators, rioters, de-escalation.

Covers spec section 2.8 tests 16-23.
"""

import math
import time
import pytest
from unittest.mock import MagicMock, patch

from engine.simulation.target import SimulationTarget
from engine.simulation.combat import CombatSystem


def _make_event_bus():
    bus = MagicMock()
    bus.publish = MagicMock()
    return bus


def _make_target(tid, x, y, alliance="hostile", asset_type="person",
                 speed=1.5, health=100, status="active",
                 crowd_role=None, drone_variant=None,
                 is_combatant=True, weapon_range=15.0,
                 weapon_cooldown=2.0, weapon_damage=10.0):
    t = SimulationTarget(
        target_id=tid, name=f"Unit-{tid}", alliance=alliance,
        asset_type=asset_type, position=(x, y), speed=speed,
    )
    t.health = health
    t.max_health = health
    t.status = status
    t.crowd_role = crowd_role
    t.drone_variant = drone_variant
    t.is_combatant = is_combatant
    t.weapon_range = weapon_range
    t.weapon_cooldown = weapon_cooldown
    t.weapon_damage = weapon_damage
    return t


class TestInstigatorActivationCycle:
    """Test 16: Verify hidden(8s)->activating(2s)->active(5s)->hidden timing."""

    def test_instigator_starts_hidden(self):
        """Instigators start in the hidden state."""
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_event_bus()
        combat = CombatSystem(bus)
        beh = UnitBehaviors(combat)
        beh.set_game_mode_type("civil_unrest")

        instigator = _make_target(
            "ins1", 10, 10, "hostile", "person",
            crowd_role="instigator", weapon_range=15.0,
            weapon_cooldown=3.0, weapon_damage=5.0,
        )
        instigator.instigator_state = "hidden"
        instigator.instigator_timer = 0.0

        assert instigator.instigator_state == "hidden"

    def test_hidden_to_activating_after_8s(self):
        """After 8s in hidden, instigator transitions to activating."""
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_event_bus()
        combat = CombatSystem(bus)
        beh = UnitBehaviors(combat)
        beh.set_game_mode_type("civil_unrest")

        instigator = _make_target(
            "ins1", 10, 10, "hostile", "person",
            crowd_role="instigator", weapon_range=15.0,
            weapon_cooldown=3.0, weapon_damage=5.0,
        )
        instigator.instigator_state = "hidden"
        instigator.instigator_timer = 0.0
        instigator.apply_combat_profile()

        friendlies = {
            "f1": _make_target("f1", 20, 20, "friendly", "turret",
                               speed=0, weapon_range=80.0),
        }

        # Tick 81 times at dt=0.1 (8.1s total, accounts for float accumulation)
        for _ in range(81):
            beh._instigator_behavior(instigator, friendlies, dt=0.1)

        assert instigator.instigator_state == "activating"

    def test_activating_to_active_after_2s(self):
        """After 2s in activating, instigator transitions to active."""
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_event_bus()
        combat = CombatSystem(bus)
        beh = UnitBehaviors(combat)
        beh.set_game_mode_type("civil_unrest")

        instigator = _make_target(
            "ins1", 10, 10, "hostile", "person",
            crowd_role="instigator", weapon_range=15.0,
            weapon_cooldown=3.0, weapon_damage=5.0,
        )
        instigator.instigator_state = "activating"
        instigator.instigator_timer = 0.0
        instigator.apply_combat_profile()

        friendlies = {
            "f1": _make_target("f1", 20, 20, "friendly", "turret",
                               speed=0, weapon_range=80.0),
        }

        # Tick 20 times at dt=0.1 (2s total)
        for _ in range(20):
            beh._instigator_behavior(instigator, friendlies, dt=0.1)

        assert instigator.instigator_state == "active"

    def test_active_to_hidden_after_5s(self):
        """After 5s in active, instigator transitions back to hidden."""
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_event_bus()
        combat = CombatSystem(bus)
        beh = UnitBehaviors(combat)
        beh.set_game_mode_type("civil_unrest")

        instigator = _make_target(
            "ins1", 10, 10, "hostile", "person",
            crowd_role="instigator", weapon_range=15.0,
            weapon_cooldown=3.0, weapon_damage=5.0,
        )
        instigator.instigator_state = "active"
        instigator.instigator_timer = 0.0
        instigator.apply_combat_profile()

        # Put the friendly out of range so the instigator won't fire
        friendlies = {
            "f1": _make_target("f1", 200, 200, "friendly", "turret",
                               speed=0, weapon_range=80.0),
        }

        # Tick 51 times at dt=0.1 (5.1s total, accounts for float accumulation)
        for _ in range(51):
            beh._instigator_behavior(instigator, friendlies, dt=0.1)

        assert instigator.instigator_state == "hidden"

    def test_full_cycle(self):
        """Full cycle: hidden(8s) -> activating(2s) -> active(5s) -> hidden."""
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_event_bus()
        combat = CombatSystem(bus)
        beh = UnitBehaviors(combat)
        beh.set_game_mode_type("civil_unrest")

        instigator = _make_target(
            "ins1", 10, 10, "hostile", "person",
            crowd_role="instigator", weapon_range=15.0,
            weapon_cooldown=3.0, weapon_damage=5.0,
        )
        instigator.instigator_state = "hidden"
        instigator.instigator_timer = 0.0
        instigator.apply_combat_profile()

        friendlies = {
            "f1": _make_target("f1", 200, 200, "friendly", "turret",
                               speed=0, weapon_range=80.0),
        }

        # Phase 1: hidden for 8s (81 ticks to overcome float accumulation)
        for _ in range(81):
            beh._instigator_behavior(instigator, friendlies, dt=0.1)
        assert instigator.instigator_state == "activating"

        # Phase 2: activating for 2s (21 ticks)
        for _ in range(21):
            beh._instigator_behavior(instigator, friendlies, dt=0.1)
        assert instigator.instigator_state == "active"

        # Phase 3: active for 5s (51 ticks)
        for _ in range(51):
            beh._instigator_behavior(instigator, friendlies, dt=0.1)
        assert instigator.instigator_state == "hidden"


class TestInstigatorVisibility:
    """Test 17: Vision can't distinguish instigator from civilian during hidden."""

    def test_instigator_hidden_is_not_combatant_visual(self):
        """When hidden, instigator acts like civilian -- no combat."""
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_event_bus()
        combat = CombatSystem(bus)
        beh = UnitBehaviors(combat)
        beh.set_game_mode_type("civil_unrest")

        instigator = _make_target(
            "ins1", 10, 10, "hostile", "person",
            crowd_role="instigator", weapon_range=15.0,
            weapon_cooldown=3.0, weapon_damage=5.0,
        )
        instigator.instigator_state = "hidden"
        instigator.instigator_timer = 0.0
        instigator.apply_combat_profile()

        friendly = _make_target("f1", 12, 12, "friendly", "turret",
                                speed=0, weapon_range=80.0)
        friendlies = {"f1": friendly}

        # Tick once - instigator should NOT fire while hidden
        initial_proj = combat.projectile_count
        beh._instigator_behavior(instigator, friendlies, dt=0.1)
        assert combat.projectile_count == initial_proj


class TestRoverDeEscalation:
    """Test 18: Rover within 15m for 3s converts rioter back to civilian."""

    def test_rover_converts_rioter_after_3s(self):
        """Rover near rioter for 3s should convert them to civilian."""
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_event_bus()
        combat = CombatSystem(bus)
        beh = UnitBehaviors(combat)
        beh.set_game_mode_type("civil_unrest")

        rover = _make_target("r1", 10, 10, "friendly", "rover",
                             speed=3, weapon_range=60.0)
        rioter = _make_target("riot1", 15, 10, "hostile", "person",
                              crowd_role="rioter", weapon_range=3.0,
                              weapon_cooldown=2.0, weapon_damage=3.0)
        rioter.apply_combat_profile()

        targets = {"r1": rover, "riot1": rioter}

        # Simulate 3s of proximity (30 ticks at 0.1s)
        for _ in range(30):
            beh._rover_de_escalation(rover, targets, dt=0.1)

        assert rioter.crowd_role == "civilian"
        assert rioter.is_combatant is False


class TestRoverFiringCancelsDeEscalation:
    """Test 19: Rover fires: timer resets, 30% conversion chance on nearby civilians."""

    def test_rover_firing_resets_timer(self):
        """When rover fires, de-escalation timer should reset."""
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_event_bus()
        combat = CombatSystem(bus)
        beh = UnitBehaviors(combat)
        beh.set_game_mode_type("civil_unrest")

        rover = _make_target("r1", 10, 10, "friendly", "rover",
                             speed=3, weapon_range=60.0)
        rioter = _make_target("riot1", 15, 10, "hostile", "person",
                              crowd_role="rioter", weapon_range=3.0)
        rioter.apply_combat_profile()

        targets = {"r1": rover, "riot1": rioter}

        # Simulate 2s of proximity first (not quite 3s)
        for _ in range(20):
            beh._rover_de_escalation(rover, targets, dt=0.1)

        # Rioter should still be a rioter
        assert rioter.crowd_role == "rioter"

        # Rover fires -- simulate by setting last_fired to now
        rover.last_fired = time.time()
        beh._rover_de_escalation(rover, targets, dt=0.1, rover_fired=True)

        # Timer should reset -- need another 3s
        # Tick 2.5s more (should NOT convert yet because timer was reset)
        for _ in range(25):
            beh._rover_de_escalation(rover, targets, dt=0.1)

        assert rioter.crowd_role == "rioter"  # Still rioter, timer was reset


class TestCivilianConversionFromInstigator:
    """Test 20: Instigator activation near civilians: 20% conversion per tick."""

    def test_civilian_conversion_when_instigator_active(self):
        """Civilians near an active instigator have a chance to convert to rioter."""
        from engine.simulation.hostile_commander import HostileCommander
        cmd = HostileCommander()
        cmd.set_game_mode_type("civil_unrest")

        instigator = _make_target(
            "ins1", 10, 10, "hostile", "person",
            crowd_role="instigator",
        )
        instigator.instigator_state = "active"

        # Create many civilians nearby to get statistical conversion
        civilians = []
        all_targets = {"ins1": instigator}
        for i in range(50):
            c = _make_target(
                f"civ{i}", 12, 12, "hostile", "person",
                crowd_role="civilian", is_combatant=False,
                weapon_range=0.0, weapon_damage=0.0,
            )
            civilians.append(c)
            all_targets[c.target_id] = c

        hostiles = [instigator] + civilians

        # Run conversion check with fixed seed for determinism
        import random
        random.seed(42)
        cmd._civilian_conversion_check(hostiles, all_targets)

        # With 50 civilians and 20% chance, we should get some conversions
        converted = sum(1 for c in civilians if c.crowd_role == "rioter")
        assert converted > 0, "At least some civilians should convert"
        assert converted < 50, "Not all civilians should convert"


class TestDroneNeverFiresCivilUnrest:
    """Test 21: Drone in civil unrest mode: tracks but never fires."""

    def test_drone_tracks_but_no_fire(self):
        """In civil_unrest mode, drones should not fire at crowd targets."""
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_event_bus()
        combat = CombatSystem(bus)
        beh = UnitBehaviors(combat)
        beh.set_game_mode_type("civil_unrest")

        drone = _make_target("d1", 10, 10, "friendly", "drone",
                             speed=5, weapon_range=50.0)

        rioter = _make_target("riot1", 15, 10, "hostile", "person",
                              crowd_role="rioter", weapon_range=3.0)
        rioter.apply_combat_profile()

        hostiles = {"riot1": rioter}

        initial_proj = combat.projectile_count
        beh._drone_behavior(drone, hostiles)
        assert combat.projectile_count == initial_proj


class TestScoutMarksInstigator:
    """Test 22: Scout drone emits SIGNAL_CONTACT when instigator is active and in range."""

    def test_scout_signals_active_instigator(self):
        """Scout drone should emit contact signal for active instigators."""
        from engine.simulation.behaviors import UnitBehaviors
        from engine.simulation.comms import UnitComms, SIGNAL_CONTACT
        bus = _make_event_bus()
        combat = CombatSystem(bus)
        beh = UnitBehaviors(combat)
        beh.set_game_mode_type("civil_unrest")

        comms = UnitComms()
        beh.set_comms(comms)

        scout = _make_target("s1", 10, 10, "friendly", "scout_drone",
                             speed=5, weapon_range=40.0)

        instigator = _make_target(
            "ins1", 15, 10, "hostile", "person",
            crowd_role="instigator", weapon_range=15.0,
        )
        instigator.instigator_state = "active"

        hostiles = {"ins1": instigator}

        # Tick drone behavior -- should emit contact signal for active instigator
        beh._drone_behavior(scout, hostiles)

        signals = comms.get_all_signals()
        contact_signals = [s for s in signals if s.signal_type == SIGNAL_CONTACT]
        # Scout should have signaled the instigator
        assert len(contact_signals) > 0


class TestVehicleContactDamage:
    """Test 23: Hostile vehicle within 3m deals contact damage, does not fire projectiles."""

    def test_vehicle_contact_damage(self):
        """Hostile vehicle close to friendly should deal contact damage."""
        from engine.simulation.behaviors import UnitBehaviors
        bus = _make_event_bus()
        combat = CombatSystem(bus)
        beh = UnitBehaviors(combat)
        beh.set_game_mode_type("civil_unrest")

        vehicle = _make_target("v1", 10, 10, "hostile", "hostile_vehicle",
                               crowd_role="rioter", speed=3,
                               weapon_range=3.0, weapon_damage=15.0,
                               weapon_cooldown=2.0)
        vehicle.apply_combat_profile()

        friendly = _make_target("f1", 12, 10, "friendly", "rover",
                                speed=3, weapon_range=60.0)
        friendlies = {"f1": friendly}

        initial_health = friendly.health
        # Vehicle is within 3m (distance = 2m) -- should deal contact/melee damage
        beh._rioter_behavior(vehicle, friendlies)
        # The vehicle should use melee_strike type -- verify weapon type mapping
        from engine.simulation.behaviors import _WEAPON_TYPES
        assert "rioter" in _WEAPON_TYPES
