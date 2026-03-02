# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for UnitBehaviors — per-unit-type combat AI."""

from __future__ import annotations

import math
import queue
import threading
import time

import pytest

from engine.simulation.behaviors import UnitBehaviors
from engine.simulation.combat import CombatSystem
from engine.simulation.target import SimulationTarget


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)

    def subscribe(self, topic: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(topic, []).append(q)
        return q


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Helper to create test units
# --------------------------------------------------------------------------

def _make_turret(pos: tuple[float, float] = (0.0, 0.0)) -> SimulationTarget:
    t = SimulationTarget(
        target_id="turret1", name="Sentry Turret", alliance="friendly",
        asset_type="turret", position=pos, speed=0.0, status="stationary",
    )
    t.apply_combat_profile()
    t.last_fired = 0.0  # ready to fire
    return t


def _make_drone(pos: tuple[float, float] = (0.0, 0.0)) -> SimulationTarget:
    t = SimulationTarget(
        target_id="drone1", name="Recon Drone", alliance="friendly",
        asset_type="drone", position=pos, speed=4.0,
    )
    t.apply_combat_profile()
    t.last_fired = 0.0
    return t


def _make_rover(pos: tuple[float, float] = (0.0, 0.0)) -> SimulationTarget:
    t = SimulationTarget(
        target_id="rover1", name="Patrol Rover", alliance="friendly",
        asset_type="rover", position=pos, speed=2.0,
    )
    t.apply_combat_profile()
    t.last_fired = 0.0
    return t


def _make_hostile(
    tid: str = "h1",
    pos: tuple[float, float] = (5.0, 0.0),
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=tid, name=f"Intruder {tid}", alliance="hostile",
        asset_type="person", position=pos, speed=1.5,
    )
    t.apply_combat_profile()
    t.last_fired = 0.0
    return t


# --------------------------------------------------------------------------
# Turret behavior
# --------------------------------------------------------------------------

class TestTurretBehavior:
    def test_turret_fires_at_hostile_in_range(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        fired_sub = bus.subscribe("projectile_fired")

        turret = _make_turret((0.0, 0.0))
        hostile = _make_hostile("h1", (10.0, 0.0))  # within 20 range
        targets = {"turret1": turret, "h1": hostile}

        behaviors.tick(0.1, targets)

        # Should have fired
        event = fired_sub.get(timeout=1.0)
        assert event["source_id"] == "turret1"

    def test_turret_does_not_fire_out_of_range(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        turret = _make_turret((0.0, 0.0))
        hostile = _make_hostile("h1", (85.0, 0.0))  # beyond 80 range
        targets = {"turret1": turret, "h1": hostile}

        behaviors.tick(0.1, targets)
        assert combat.projectile_count == 0

    def test_turret_rotates_toward_hostile(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        turret = _make_turret((0.0, 0.0))
        turret.heading = 0.0
        hostile = _make_hostile("h1", (10.0, 0.0))  # east
        targets = {"turret1": turret, "h1": hostile}

        behaviors.tick(0.1, targets)

        # Heading should now point toward hostile (east = ~90 degrees)
        expected = math.degrees(math.atan2(10.0, 0.0))
        assert abs(turret.heading - expected) < 1.0

    def test_turret_ignores_non_combatants(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        turret = _make_turret((0.0, 0.0))
        civilian = SimulationTarget(
            target_id="c1", name="Neighbor", alliance="hostile",
            asset_type="person", position=(5.0, 0.0),
            is_combatant=False,
        )
        targets = {"turret1": turret, "c1": civilian}

        behaviors.tick(0.1, targets)
        assert combat.projectile_count == 0

    def test_turret_picks_nearest_hostile(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        fired_sub = bus.subscribe("projectile_fired")

        turret = _make_turret((0.0, 0.0))
        far_hostile = _make_hostile("h_far", (15.0, 0.0))
        near_hostile = _make_hostile("h_near", (5.0, 0.0))
        targets = {
            "turret1": turret,
            "h_far": far_hostile,
            "h_near": near_hostile,
        }

        behaviors.tick(0.1, targets)

        event = fired_sub.get(timeout=1.0)
        # Projectile target should be the near hostile's position
        assert event["target_pos"]["x"] == 5.0


# --------------------------------------------------------------------------
# Drone behavior
# --------------------------------------------------------------------------

class TestDroneBehavior:
    def test_drone_fires_at_hostile_in_range(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        fired_sub = bus.subscribe("projectile_fired")

        drone = _make_drone((0.0, 0.0))
        hostile = _make_hostile("h1", (8.0, 0.0))  # within 12 range
        targets = {"drone1": drone, "h1": hostile}

        behaviors.tick(0.1, targets)
        event = fired_sub.get(timeout=1.0)
        assert event["source_id"] == "drone1"

    def test_drone_does_not_fire_out_of_range(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        drone = _make_drone((0.0, 0.0))
        hostile = _make_hostile("h1", (55.0, 0.0))  # beyond 50 range
        targets = {"drone1": drone, "h1": hostile}

        behaviors.tick(0.1, targets)
        assert combat.projectile_count == 0

    def test_drone_updates_heading(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        drone = _make_drone((0.0, 0.0))
        drone.heading = 0.0
        hostile = _make_hostile("h1", (0.0, 10.0))  # north
        targets = {"drone1": drone, "h1": hostile}

        behaviors.tick(0.1, targets)
        # Should face north (0 degrees)
        expected = math.degrees(math.atan2(0.0, 10.0))
        assert abs(drone.heading - expected) < 1.0


# --------------------------------------------------------------------------
# Rover behavior
# --------------------------------------------------------------------------

class TestRoverBehavior:
    def test_rover_fires_at_hostile_in_range(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        fired_sub = bus.subscribe("projectile_fired")

        rover = _make_rover((0.0, 0.0))
        hostile = _make_hostile("h1", (5.0, 0.0))  # within 10 range
        targets = {"rover1": rover, "h1": hostile}

        behaviors.tick(0.1, targets)
        event = fired_sub.get(timeout=1.0)
        assert event["source_id"] == "rover1"

    def test_rover_does_not_fire_out_of_range(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        rover = _make_rover((0.0, 0.0))
        hostile = _make_hostile("h1", (65.0, 0.0))  # beyond 60 range
        targets = {"rover1": rover, "h1": hostile}

        behaviors.tick(0.1, targets)
        assert combat.projectile_count == 0


# --------------------------------------------------------------------------
# Hostile kid behavior
# --------------------------------------------------------------------------

class TestHostileKidBehavior:
    def test_hostile_fires_at_friendly_in_range(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        fired_sub = bus.subscribe("projectile_fired")

        turret = _make_turret((0.0, 0.0))
        hostile = _make_hostile("h1", (5.0, 0.0))
        targets = {"turret1": turret, "h1": hostile}

        behaviors.tick(0.1, targets)

        # Both should fire (turret at hostile, hostile at turret)
        events = []
        while not fired_sub.empty():
            events.append(fired_sub.get_nowait())
        source_ids = {e["source_id"] for e in events}
        assert "h1" in source_ids  # hostile fired at turret

    def test_hostile_does_not_fire_out_of_range(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        fired_sub = bus.subscribe("projectile_fired")

        turret = _make_turret((0.0, 0.0))
        hostile = _make_hostile("h1", (50.0, 0.0))  # beyond hostile 40 range, within turret 80
        targets = {"turret1": turret, "h1": hostile}

        behaviors.tick(0.1, targets)

        # Turret should fire (range 80), hostile should not (range 40)
        events = []
        while not fired_sub.empty():
            events.append(fired_sub.get_nowait())
        source_ids = {e["source_id"] for e in events}
        assert "turret1" in source_ids
        assert "h1" not in source_ids

    def test_hostile_dodge_changes_position(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile("h1", (10.0, 0.0))
        hostile.heading = 90.0
        # Set last dodge to long ago to trigger dodge
        behaviors._last_dodge["h1"] = 0.0
        targets = {"h1": hostile}

        original_pos = hostile.position
        behaviors.tick(0.1, targets)

        # Position should have changed due to dodge
        assert hostile.position != original_pos


# --------------------------------------------------------------------------
# UnitBehaviors filtering
# --------------------------------------------------------------------------

class TestBehaviorFiltering:
    def test_ignores_eliminated_friendlies(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        turret = _make_turret((0.0, 0.0))
        turret.status = "eliminated"
        hostile = _make_hostile("h1", (5.0, 0.0))
        targets = {"turret1": turret, "h1": hostile}

        behaviors.tick(0.1, targets)
        # Eliminated turret should not fire
        assert combat.projectile_count == 0

    def test_ignores_eliminated_hostiles(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        turret = _make_turret((0.0, 0.0))
        hostile = _make_hostile("h1", (5.0, 0.0))
        hostile.status = "eliminated"
        targets = {"turret1": turret, "h1": hostile}

        behaviors.tick(0.1, targets)
        # No valid targets, should not fire
        assert combat.projectile_count == 0

    def test_ignores_neutral_targets(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        turret = _make_turret((0.0, 0.0))
        civilian = SimulationTarget(
            target_id="c1", name="Neighbor", alliance="neutral",
            asset_type="person", position=(5.0, 0.0),
            is_combatant=False,
        )
        targets = {"turret1": turret, "c1": civilian}

        behaviors.tick(0.1, targets)
        assert combat.projectile_count == 0


class TestNearestInRange:
    def test_returns_none_no_enemies(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        unit = _make_turret()
        result = behaviors._nearest_in_range(unit, {})
        assert result is None

    def test_returns_nearest(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        unit = _make_turret((0.0, 0.0))
        far = _make_hostile("far", (18.0, 0.0))
        near = _make_hostile("near", (5.0, 0.0))
        result = behaviors._nearest_in_range(unit, {"far": far, "near": near})
        assert result is near

    def test_respects_range_limit(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        unit = _make_turret((0.0, 0.0))
        unit.weapon_range = 10.0
        far = _make_hostile("far", (15.0, 0.0))
        result = behaviors._nearest_in_range(unit, {"far": far})
        assert result is None


class TestClearDodgeState:
    def test_clear_dodge_state(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        behaviors._last_dodge["h1"] = time.time()
        behaviors._last_dodge["h2"] = time.time()
        behaviors.clear_dodge_state()
        assert len(behaviors._last_dodge) == 0


# --------------------------------------------------------------------------
# Weapon type dispatch per unit type
# --------------------------------------------------------------------------

class TestWeaponTypeDispatch:
    """Verify each unit type fires the correct projectile type via _WEAPON_TYPES."""

    def test_turret_fires_nerf_turret_gun(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        fired_sub = bus.subscribe("projectile_fired")

        turret = _make_turret((0.0, 0.0))
        hostile = _make_hostile("h1", (5.0, 0.0))
        targets = {"turret1": turret, "h1": hostile}
        behaviors.tick(0.1, targets)

        event = fired_sub.get(timeout=1.0)
        assert event["projectile_type"] == "nerf_turret_gun"

    def test_drone_fires_nerf_dart_gun(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        fired_sub = bus.subscribe("projectile_fired")

        drone = _make_drone((0.0, 0.0))
        hostile = _make_hostile("h1", (8.0, 0.0))
        targets = {"drone1": drone, "h1": hostile}
        behaviors.tick(0.1, targets)

        event = fired_sub.get(timeout=1.0)
        assert event["projectile_type"] == "nerf_dart_gun"

    def test_rover_fires_nerf_cannon(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        fired_sub = bus.subscribe("projectile_fired")

        rover = _make_rover((0.0, 0.0))
        hostile = _make_hostile("h1", (5.0, 0.0))
        targets = {"rover1": rover, "h1": hostile}
        behaviors.tick(0.1, targets)

        event = fired_sub.get(timeout=1.0)
        assert event["projectile_type"] == "nerf_cannon"

    def test_hostile_person_fires_nerf_pistol(self):
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)
        fired_sub = bus.subscribe("projectile_fired")

        turret = _make_turret((0.0, 0.0))
        hostile = _make_hostile("h1", (5.0, 0.0))
        targets = {"turret1": turret, "h1": hostile}
        behaviors.tick(0.1, targets)

        events = []
        while not fired_sub.empty():
            events.append(fired_sub.get_nowait())
        hostile_events = [e for e in events if e["source_id"] == "h1"]
        assert len(hostile_events) > 0
        assert hostile_events[0]["projectile_type"] == "nerf_pistol"

    def test_weapon_types_map_completeness(self):
        """Verify _WEAPON_TYPES covers all combatant unit types."""
        from engine.simulation.behaviors import _WEAPON_TYPES
        expected_types = {
            "turret", "heavy_turret", "missile_turret",
            "drone", "scout_drone", "rover", "tank", "apc",
            "person", "hostile_person", "hostile_leader", "hostile_vehicle",
        }
        for t in expected_types:
            assert t in _WEAPON_TYPES, f"Missing weapon type for {t}"

    def test_weapon_types_values_non_empty(self):
        """All weapon type values should be non-empty strings or None for non-firing units."""
        from engine.simulation.behaviors import _WEAPON_TYPES
        # Units that intentionally cannot fire (None weapon type)
        no_weapon_types = {"scout_swarm", "bomber_swarm"}
        for unit_type, weapon in _WEAPON_TYPES.items():
            if unit_type in no_weapon_types:
                assert weapon is None, \
                    f"Non-firing unit {unit_type} should have None weapon, got: {weapon!r}"
            else:
                assert isinstance(weapon, str) and len(weapon) > 0, \
                    f"Weapon type for {unit_type} is invalid: {weapon!r}"


# --------------------------------------------------------------------------
# Reconning speed modifier (BUG FIX: must not compound per tick)
# --------------------------------------------------------------------------

class TestReconningSpeedModifier:
    """Verify reconning speed modifier applies once, not exponentially per tick."""

    def test_reconning_speed_applied_once(self):
        """Speed should be 0.6x base after entering reconning, not compounding."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile("h1", (50.0, 0.0))  # out of turret range
        base_speed = hostile.speed
        hostile.fsm_state = "reconning"
        targets = {"h1": hostile}

        # Tick 10 times (1 second at 10Hz)
        for _ in range(10):
            behaviors.tick(0.1, targets)

        # Speed should be exactly 0.6x base, NOT 0.6^10 * base
        expected = base_speed * 0.6
        assert abs(hostile.speed - expected) < 0.001, \
            f"Speed {hostile.speed:.6f} should be {expected:.6f} (0.6x base), " \
            f"not {base_speed * (0.6 ** 10):.6f} (exponential decay)"

    def test_reconning_speed_stable_over_many_ticks(self):
        """Speed must remain constant over 100 ticks in reconning state."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile("h1", (50.0, 0.0))
        base_speed = hostile.speed
        hostile.fsm_state = "reconning"
        targets = {"h1": hostile}

        # Tick 100 times (10 seconds at 10Hz)
        for _ in range(100):
            behaviors.tick(0.1, targets)

        expected = base_speed * 0.6
        assert abs(hostile.speed - expected) < 0.001, \
            f"Speed drifted to {hostile.speed:.6f} after 100 ticks, expected {expected:.6f}"

    def test_reconning_speed_restored_on_exit(self):
        """Speed should restore to base when leaving reconning state."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile("h1", (50.0, 0.0))
        base_speed = hostile.speed
        hostile.fsm_state = "reconning"
        targets = {"h1": hostile}

        # Enter reconning for a few ticks
        for _ in range(5):
            behaviors.tick(0.1, targets)
        assert abs(hostile.speed - base_speed * 0.6) < 0.001

        # Exit reconning
        hostile.fsm_state = "advancing"
        behaviors.tick(0.1, targets)

        assert abs(hostile.speed - base_speed) < 0.001, \
            f"Speed {hostile.speed:.6f} should be restored to {base_speed:.6f}"

    def test_reconning_reentry_applies_modifier_again(self):
        """Re-entering reconning after leaving should apply 0.6x again."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile("h1", (50.0, 0.0))
        base_speed = hostile.speed
        hostile.fsm_state = "reconning"
        targets = {"h1": hostile}

        # Enter reconning
        behaviors.tick(0.1, targets)
        assert abs(hostile.speed - base_speed * 0.6) < 0.001

        # Exit reconning
        hostile.fsm_state = "advancing"
        behaviors.tick(0.1, targets)
        assert abs(hostile.speed - base_speed) < 0.001

        # Re-enter reconning
        hostile.fsm_state = "reconning"
        behaviors.tick(0.1, targets)
        assert abs(hostile.speed - base_speed * 0.6) < 0.001


# --------------------------------------------------------------------------
# Suppressing cooldown modifier (BUG FIX: must not compound per tick)
# --------------------------------------------------------------------------

class TestSuppressingCooldownModifier:
    """Verify suppressing cooldown modifier applies once, not exponentially per tick."""

    def test_suppressing_cooldown_applied_once(self):
        """Cooldown should be 0.5x base after entering suppressing, not compounding."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile("h1", (50.0, 0.0))  # out of turret range
        base_cooldown = hostile.weapon_cooldown
        hostile.fsm_state = "suppressing"
        targets = {"h1": hostile}

        # Tick 10 times (1 second at 10Hz)
        for _ in range(10):
            behaviors.tick(0.1, targets)

        # Cooldown should be exactly 0.5x base, NOT 0.5^10 * base
        expected = base_cooldown * 0.5
        assert abs(hostile.weapon_cooldown - expected) < 0.001, \
            f"Cooldown {hostile.weapon_cooldown:.6f} should be {expected:.6f} (0.5x base), " \
            f"not {base_cooldown * (0.5 ** 10):.6f} (exponential decay)"

    def test_suppressing_cooldown_stable_over_many_ticks(self):
        """Cooldown must remain constant over 100 ticks in suppressing state."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile("h1", (50.0, 0.0))
        base_cooldown = hostile.weapon_cooldown
        hostile.fsm_state = "suppressing"
        targets = {"h1": hostile}

        # Tick 100 times (10 seconds at 10Hz)
        for _ in range(100):
            behaviors.tick(0.1, targets)

        expected = base_cooldown * 0.5
        assert abs(hostile.weapon_cooldown - expected) < 0.001, \
            f"Cooldown drifted to {hostile.weapon_cooldown:.6f} after 100 ticks, expected {expected:.6f}"

    def test_suppressing_cooldown_restored_on_exit(self):
        """Cooldown should restore to base when leaving suppressing state."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile("h1", (50.0, 0.0))
        base_cooldown = hostile.weapon_cooldown
        hostile.fsm_state = "suppressing"
        targets = {"h1": hostile}

        # Enter suppressing for a few ticks
        for _ in range(5):
            behaviors.tick(0.1, targets)
        assert abs(hostile.weapon_cooldown - base_cooldown * 0.5) < 0.001

        # Exit suppressing
        hostile.fsm_state = "advancing"
        behaviors.tick(0.1, targets)

        assert abs(hostile.weapon_cooldown - base_cooldown) < 0.001, \
            f"Cooldown {hostile.weapon_cooldown:.6f} should be restored to {base_cooldown:.6f}"

    def test_suppressing_reentry_applies_modifier_again(self):
        """Re-entering suppressing after leaving should apply 0.5x again."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        hostile = _make_hostile("h1", (50.0, 0.0))
        base_cooldown = hostile.weapon_cooldown
        hostile.fsm_state = "suppressing"
        targets = {"h1": hostile}

        # Enter suppressing
        behaviors.tick(0.1, targets)
        assert abs(hostile.weapon_cooldown - base_cooldown * 0.5) < 0.001

        # Exit suppressing
        hostile.fsm_state = "advancing"
        behaviors.tick(0.1, targets)
        assert abs(hostile.weapon_cooldown - base_cooldown) < 0.001

        # Re-enter suppressing
        hostile.fsm_state = "suppressing"
        behaviors.tick(0.1, targets)
        assert abs(hostile.weapon_cooldown - base_cooldown * 0.5) < 0.001
