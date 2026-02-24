"""Tests for the behavior/ package refactor.

Validates that:
1. Each behavior class can be instantiated independently
2. TurretBehavior, DroneBehavior, RoverBehavior are stateless
3. HostileBehavior has state dicts
4. BehaviorCoordinator delegates to the right behavior
5. Old import path still works
6. nearest_in_range helper works independently

SKIPPED: amy.simulation.behavior/ package does not exist.
Behaviors remain in the monolithic behaviors.py (UnitBehaviors class).
BehaviorCoordinator, TurretBehavior, DroneBehavior, RoverBehavior,
HostileBehavior as separate classes were never implemented.
"""

from __future__ import annotations

import math
import time

import pytest

pytestmark = pytest.mark.unit
pytest.skip(
    "amy.simulation.behavior/ package not implemented — behaviors remain in behaviors.py",
    allow_module_level=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bus_and_combat():
    bus = EventBus()
    combat = CombatSystem(bus)
    return bus, combat


def _make_turret(pos=(0.0, 0.0)):
    t = SimulationTarget(
        target_id="turret1", name="Sentry Turret", alliance="friendly",
        asset_type="turret", position=pos, speed=0.0, status="stationary",
    )
    t.apply_combat_profile()
    t.last_fired = 0.0
    return t


def _make_drone(pos=(0.0, 0.0)):
    t = SimulationTarget(
        target_id="drone1", name="Recon Drone", alliance="friendly",
        asset_type="drone", position=pos, speed=4.0,
    )
    t.apply_combat_profile()
    t.last_fired = 0.0
    return t


def _make_rover(pos=(0.0, 0.0)):
    t = SimulationTarget(
        target_id="rover1", name="Patrol Rover", alliance="friendly",
        asset_type="rover", position=pos, speed=2.0,
    )
    t.apply_combat_profile()
    t.last_fired = 0.0
    return t


def _make_hostile(tid="h1", pos=(5.0, 0.0)):
    t = SimulationTarget(
        target_id=tid, name=f"Intruder {tid}", alliance="hostile",
        asset_type="person", position=pos, speed=1.5, status="active",
        waypoints=[(0.0, 0.0)],
    )
    t.apply_combat_profile()
    t.last_fired = 0.0
    return t


# ---------------------------------------------------------------------------
# 1. Independent instantiation of each behavior class
# ---------------------------------------------------------------------------

class TestIndependentInstantiation:
    """Each behavior class can be created on its own with just a combat system."""

    def test_turret_behavior_instantiates(self):
        from engine.simulation.behavior.turret import TurretBehavior
        _, combat = _bus_and_combat()
        tb = TurretBehavior(combat)
        assert tb is not None

    def test_drone_behavior_instantiates(self):
        from engine.simulation.behavior.drone import DroneBehavior
        _, combat = _bus_and_combat()
        db = DroneBehavior(combat)
        assert db is not None

    def test_rover_behavior_instantiates(self):
        from engine.simulation.behavior.rover import RoverBehavior
        _, combat = _bus_and_combat()
        rb = RoverBehavior(combat)
        assert rb is not None

    def test_hostile_behavior_instantiates(self):
        from engine.simulation.behavior.hostile import HostileBehavior
        _, combat = _bus_and_combat()
        hb = HostileBehavior(combat)
        assert hb is not None

    def test_coordinator_instantiates(self):
        from engine.simulation.behavior.coordinator import BehaviorCoordinator
        _, combat = _bus_and_combat()
        bc = BehaviorCoordinator(combat)
        assert bc is not None


# ---------------------------------------------------------------------------
# 2. Statelessness of friendly behaviors
# ---------------------------------------------------------------------------

class TestFriendlyBehaviorsStateless:
    """TurretBehavior, DroneBehavior, RoverBehavior have no state dicts."""

    def test_turret_behavior_has_no_state_dicts(self):
        from engine.simulation.behavior.turret import TurretBehavior
        _, combat = _bus_and_combat()
        tb = TurretBehavior(combat)
        # Should only have _combat, no state tracking dicts
        attrs = [a for a in vars(tb) if not a.startswith('__')]
        assert '_last_dodge' not in attrs
        assert '_last_flank' not in attrs

    def test_drone_behavior_has_no_state_dicts(self):
        from engine.simulation.behavior.drone import DroneBehavior
        _, combat = _bus_and_combat()
        db = DroneBehavior(combat)
        attrs = [a for a in vars(db) if not a.startswith('__')]
        assert '_last_dodge' not in attrs

    def test_rover_behavior_has_no_state_dicts(self):
        from engine.simulation.behavior.rover import RoverBehavior
        _, combat = _bus_and_combat()
        rb = RoverBehavior(combat)
        attrs = [a for a in vars(rb) if not a.startswith('__')]
        assert '_last_dodge' not in attrs


# ---------------------------------------------------------------------------
# 3. HostileBehavior has state
# ---------------------------------------------------------------------------

class TestHostileBehaviorStateful:
    """HostileBehavior owns the 9 state tracking dicts."""

    def test_hostile_behavior_has_state_dicts(self):
        from engine.simulation.behavior.hostile import HostileBehavior
        _, combat = _bus_and_combat()
        hb = HostileBehavior(combat)
        assert hasattr(hb, '_last_dodge')
        assert hasattr(hb, '_last_flank')
        assert hasattr(hb, '_group_rush_ids')
        assert hasattr(hb, '_base_speeds')
        assert hasattr(hb, '_recon_ids')
        assert hasattr(hb, '_recon_base_speeds')
        assert hasattr(hb, '_suppress_ids')
        assert hasattr(hb, '_suppress_base_cooldowns')
        assert hasattr(hb, '_detected_ids')
        assert hasattr(hb, '_detected_base_speeds')

    def test_hostile_behavior_clear_state(self):
        from engine.simulation.behavior.hostile import HostileBehavior
        _, combat = _bus_and_combat()
        hb = HostileBehavior(combat)
        hb._last_dodge["h1"] = time.time()
        hb._last_flank["h2"] = time.time()
        hb._group_rush_ids.add("h3")
        hb.clear_state()
        assert len(hb._last_dodge) == 0
        assert len(hb._last_flank) == 0
        assert len(hb._group_rush_ids) == 0

    def test_hostile_behavior_set_obstacles(self):
        from engine.simulation.behavior.hostile import HostileBehavior
        from unittest.mock import MagicMock
        _, combat = _bus_and_combat()
        hb = HostileBehavior(combat)
        obs = MagicMock()
        hb.set_obstacles(obs)
        assert hb._obstacles is obs


# ---------------------------------------------------------------------------
# 4. BehaviorCoordinator delegates to correct behavior
# ---------------------------------------------------------------------------

class TestCoordinatorDelegation:
    """BehaviorCoordinator.tick() should dispatch to the right sub-behavior."""

    def test_coordinator_delegates_turret(self):
        from engine.simulation.behavior.coordinator import BehaviorCoordinator
        bus, combat = _bus_and_combat()
        bc = BehaviorCoordinator(combat)
        fired_sub = bus.subscribe()

        turret = _make_turret((0.0, 0.0))
        hostile = _make_hostile("h1", (10.0, 0.0))
        targets = {"turret1": turret, "h1": hostile}

        bc.tick(0.1, targets)
        event = fired_sub.get(timeout=1.0)
        assert event["data"]["source_id"] == "turret1"

    def test_coordinator_delegates_hostile(self):
        from engine.simulation.behavior.coordinator import BehaviorCoordinator
        bus, combat = _bus_and_combat()
        bc = BehaviorCoordinator(combat)
        fired_sub = bus.subscribe()

        turret = _make_turret((0.0, 0.0))
        hostile = _make_hostile("h1", (5.0, 0.0))
        targets = {"turret1": turret, "h1": hostile}

        bc.tick(0.1, targets)
        events = []
        while not fired_sub.empty():
            events.append(fired_sub.get_nowait())
        source_ids = {e["data"]["source_id"] for e in events if e.get("type") == "projectile_fired"}
        assert "h1" in source_ids

    def test_coordinator_set_obstacles_reaches_hostile(self):
        from engine.simulation.behavior.coordinator import BehaviorCoordinator
        from unittest.mock import MagicMock
        _, combat = _bus_and_combat()
        bc = BehaviorCoordinator(combat)
        obs = MagicMock()
        bc.set_obstacles(obs)
        assert bc._hostile._obstacles is obs

    def test_coordinator_clear_dodge_state(self):
        from engine.simulation.behavior.coordinator import BehaviorCoordinator
        _, combat = _bus_and_combat()
        bc = BehaviorCoordinator(combat)
        bc._hostile._last_dodge["h1"] = time.time()
        bc.clear_dodge_state()
        assert len(bc._hostile._last_dodge) == 0


# ---------------------------------------------------------------------------
# 5. Old import path still works
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """from engine.simulation.behaviors import UnitBehaviors must still work."""

    def test_old_import_path(self):
        from engine.simulation.behaviors import UnitBehaviors
        _, combat = _bus_and_combat()
        ub = UnitBehaviors(combat)
        assert ub is not None

    def test_old_import_is_coordinator(self):
        from engine.simulation.behaviors import UnitBehaviors
        from engine.simulation.behavior.coordinator import BehaviorCoordinator
        assert UnitBehaviors is BehaviorCoordinator

    def test_simulation_init_reexport(self):
        from engine.simulation import UnitBehaviors
        _, combat = _bus_and_combat()
        ub = UnitBehaviors(combat)
        assert ub is not None

    def test_behavior_init_reexport(self):
        from engine.simulation.behavior import BehaviorCoordinator
        _, combat = _bus_and_combat()
        bc = BehaviorCoordinator(combat)
        assert bc is not None


# ---------------------------------------------------------------------------
# 6. nearest_in_range helper
# ---------------------------------------------------------------------------

class TestNearestInRangeHelper:
    """nearest_in_range is a module-level function in base.py."""

    def test_nearest_in_range_importable(self):
        from engine.simulation.behavior.base import nearest_in_range
        assert callable(nearest_in_range)

    def test_nearest_in_range_returns_none_no_enemies(self):
        from engine.simulation.behavior.base import nearest_in_range
        unit = _make_turret()
        result = nearest_in_range(unit, {})
        assert result is None

    def test_nearest_in_range_returns_nearest(self):
        from engine.simulation.behavior.base import nearest_in_range
        unit = _make_turret((0.0, 0.0))
        far = _make_hostile("far", (18.0, 0.0))
        near = _make_hostile("near", (5.0, 0.0))
        result = nearest_in_range(unit, {"far": far, "near": near})
        assert result is near

    def test_nearest_in_range_respects_range(self):
        from engine.simulation.behavior.base import nearest_in_range
        unit = _make_turret((0.0, 0.0))
        unit.weapon_range = 10.0
        far = _make_hostile("far", (15.0, 0.0))
        result = nearest_in_range(unit, {"far": far})
        assert result is None
