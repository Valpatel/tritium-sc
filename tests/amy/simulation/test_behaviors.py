"""Unit tests for UnitBehaviors — per-unit-type combat AI."""

from __future__ import annotations

import math
import queue
import threading
import time

import pytest

from amy.simulation.behaviors import UnitBehaviors
from amy.simulation.combat import CombatSystem
from amy.simulation.target import SimulationTarget


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
        hostile = _make_hostile("h1", (25.0, 0.0))  # beyond 20 range
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
        hostile = _make_hostile("h1", (15.0, 0.0))  # beyond 12 range
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
        hostile = _make_hostile("h1", (15.0, 0.0))  # beyond 10 range
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
        hostile = _make_hostile("h1", (20.0, 0.0))  # beyond 8 range
        targets = {"turret1": turret, "h1": hostile}

        behaviors.tick(0.1, targets)

        # Turret should fire (range 20), hostile should not (range 8)
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
        unit = _make_turret()
        result = UnitBehaviors._nearest_in_range(unit, {})
        assert result is None

    def test_returns_nearest(self):
        unit = _make_turret((0.0, 0.0))
        far = _make_hostile("far", (18.0, 0.0))
        near = _make_hostile("near", (5.0, 0.0))
        result = UnitBehaviors._nearest_in_range(unit, {"far": far, "near": near})
        assert result is near

    def test_respects_range_limit(self):
        unit = _make_turret((0.0, 0.0))
        unit.weapon_range = 10.0
        far = _make_hostile("far", (15.0, 0.0))
        result = UnitBehaviors._nearest_in_range(unit, {"far": far})
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
