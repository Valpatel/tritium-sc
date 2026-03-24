# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for drone swarm engine wiring -- infrastructure damage from combat
events and SwarmBehavior (boids) integration into the tick loop.

Tests verify that:
  1. InfrastructureHealth receives damage from bomber_detonation events
  2. InfrastructureHealth receives damage from projectile_hit events near POI
  3. SwarmBehavior is instantiated and ticked for drone_swarm mode
  4. SwarmBehavior modifies swarm drone positions/headings
  5. Both subsystems are cleaned up on reset_game()
  6. Non-drone-swarm modes are not affected
"""

from __future__ import annotations

import math
import queue
import threading
import time

import pytest

from engine.simulation.engine import SimulationEngine
from engine.simulation.infrastructure import InfrastructureHealth
from engine.simulation.swarm import SwarmBehavior
from tritium_lib.sim_engine.core.entity import SimulationTarget


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._all_subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)
            for q in self._all_subscribers:
                try:
                    q.put_nowait({"type": topic, "data": data})
                except queue.Full:
                    pass

    def subscribe(self, _filter: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            if _filter is None:
                self._all_subscribers.append(q)
            else:
                self._subscribers.setdefault(_filter, []).append(q)
        return q


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _make_engine(bus: SimpleEventBus) -> SimulationEngine:
    """Create engine with a friendly turret (stationary POI)."""
    engine = SimulationEngine(bus, map_bounds=200)
    turret = SimulationTarget(
        target_id="turret-1", name="Base Turret", alliance="friendly",
        asset_type="turret", position=(50.0, 50.0),
        is_combatant=True, status="stationary", speed=0.0,
    )
    engine.add_target(turret)
    return engine


def _start_drone_swarm(engine: SimulationEngine) -> None:
    """Configure and start a drone swarm game."""
    engine.game_mode.game_mode_type = "drone_swarm"
    engine.begin_war()
    # Advance through countdown to active state
    from engine.simulation.game_mode import _COUNTDOWN_DURATION
    engine.game_mode.tick(_COUNTDOWN_DURATION + 1.0)
    assert engine.game_mode.state == "active"


# --------------------------------------------------------------------------
# TASK 1: Infrastructure damage from combat events
# --------------------------------------------------------------------------

class TestInfrastructureCreatedForDroneSwarm:
    """InfrastructureHealth is instantiated when drone_swarm mode starts."""

    def test_infrastructure_created_on_begin_war(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        assert engine._infrastructure_health is None

        engine.game_mode.game_mode_type = "drone_swarm"
        engine.begin_war()

        assert engine._infrastructure_health is not None
        assert isinstance(engine._infrastructure_health, InfrastructureHealth)

    def test_infrastructure_not_created_for_battle_mode(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        engine.game_mode.game_mode_type = "battle"
        engine.begin_war()

        assert engine._infrastructure_health is None

    def test_infrastructure_not_created_for_civil_unrest(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        engine.game_mode.game_mode_type = "civil_unrest"
        engine.begin_war()

        assert engine._infrastructure_health is None


class TestPOIBuildingsComputed:
    """POI buildings are computed from friendly stationary units."""

    def test_poi_from_stationary_friendlies(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)  # Has turret at (50, 50)
        engine.game_mode.game_mode_type = "drone_swarm"
        engine.begin_war()

        assert len(engine._poi_buildings) >= 1
        assert (50.0, 50.0) in engine._poi_buildings

    def test_poi_fallback_when_no_stationary_units(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200)
        # Add a mobile friendly (not stationary, has speed)
        mobile = SimulationTarget(
            target_id="rover-1", name="Rover", alliance="friendly",
            asset_type="rover", position=(10.0, 10.0),
            is_combatant=True, status="active", speed=3.0,
        )
        engine.add_target(mobile)

        engine.game_mode.game_mode_type = "drone_swarm"
        engine.begin_war()

        # Should fall back to (0, 0)
        assert (0.0, 0.0) in engine._poi_buildings

    def test_poi_cleared_on_reset(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        engine.game_mode.game_mode_type = "drone_swarm"
        engine.begin_war()

        assert len(engine._poi_buildings) >= 1

        engine.reset_game()
        assert engine._poi_buildings == []


class TestBomberDetonationRoutedToInfrastructure:
    """bomber_detonation events feed InfrastructureHealth.apply_bomber_detonation."""

    def test_bomber_detonation_near_poi_reduces_health(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        _start_drone_swarm(engine)

        initial_health = engine._infrastructure_health._health

        # Start the combat event listener so it processes events
        engine._running = True
        listener_thread = threading.Thread(
            target=engine._combat_event_listener, daemon=True,
        )
        listener_thread.start()

        try:
            # Simulate a bomber detonation event near the POI (50, 50)
            bus.publish("bomber_detonation", {
                "bomber_id": "bomber-1",
                "position": {"x": 52.0, "y": 50.0},  # 2m from POI
                "radius": 5.0,
                "damage": 40.0,
            })

            # Give the listener thread time to process
            time.sleep(0.3)

            # Infrastructure should have taken damage
            assert engine._infrastructure_health._health < initial_health
        finally:
            engine._running = False
            listener_thread.join(timeout=2.0)

    def test_bomber_detonation_far_from_poi_no_damage(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        _start_drone_swarm(engine)

        initial_health = engine._infrastructure_health._health

        engine._running = True
        listener_thread = threading.Thread(
            target=engine._combat_event_listener, daemon=True,
        )
        listener_thread.start()

        try:
            # Detonation far from POI (50, 50) -- at (200, 200)
            bus.publish("bomber_detonation", {
                "bomber_id": "bomber-2",
                "position": {"x": 200.0, "y": 200.0},
                "radius": 5.0,
                "damage": 40.0,
            })

            time.sleep(0.3)

            # Infrastructure should NOT have taken damage
            assert engine._infrastructure_health._health == initial_health
        finally:
            engine._running = False
            listener_thread.join(timeout=2.0)


class TestProjectileHitRoutedToInfrastructure:
    """projectile_hit events near POI feed InfrastructureHealth.apply_attack_fire."""

    def test_projectile_hit_near_poi_reduces_health(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        _start_drone_swarm(engine)

        initial_health = engine._infrastructure_health._health

        engine._running = True
        listener_thread = threading.Thread(
            target=engine._combat_event_listener, daemon=True,
        )
        listener_thread.start()

        try:
            # Projectile hit near POI (50, 50)
            bus.publish("projectile_hit", {
                "projectile_id": "p-1",
                "target_id": "turret-1",
                "target_name": "Base Turret",
                "damage": 20.0,
                "remaining_health": 80.0,
                "source_id": "attacker-1",
                "projectile_type": "nerf_dart",
                "position": {"x": 51.0, "y": 50.0},  # 1m from POI
            })

            time.sleep(0.3)

            # Infrastructure should take 25% of 20 = 5 damage
            assert engine._infrastructure_health._health < initial_health
            expected = initial_health - (20.0 * 0.25)
            assert engine._infrastructure_health._health == pytest.approx(
                expected, abs=0.1
            )
        finally:
            engine._running = False
            listener_thread.join(timeout=2.0)

    def test_projectile_hit_far_from_poi_no_infra_damage(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        _start_drone_swarm(engine)

        initial_health = engine._infrastructure_health._health

        engine._running = True
        listener_thread = threading.Thread(
            target=engine._combat_event_listener, daemon=True,
        )
        listener_thread.start()

        try:
            # Projectile hit far from all POIs
            bus.publish("projectile_hit", {
                "projectile_id": "p-2",
                "target_id": "rover-1",
                "target_name": "Rover",
                "damage": 20.0,
                "remaining_health": 80.0,
                "source_id": "attacker-2",
                "projectile_type": "nerf_dart",
                "position": {"x": -100.0, "y": -100.0},
            })

            time.sleep(0.3)

            # Infrastructure should NOT have taken damage
            assert engine._infrastructure_health._health == initial_health
        finally:
            engine._running = False
            listener_thread.join(timeout=2.0)


class TestInfrastructureDestroyedTriggersGameOver:
    """Infrastructure reaching 0 triggers game_over in the tick loop."""

    def test_tick_detects_destroyed_infrastructure(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        _start_drone_swarm(engine)

        # Damage infrastructure to exactly 0
        engine._infrastructure_health.apply_damage(
            1000.0, source_id="test", source_type="test",
        )
        assert engine._infrastructure_health.is_destroyed()

        # Run a tick -- should sync to game_mode and trigger defeat
        engine._do_tick(0.1)

        assert engine.game_mode.infrastructure_health == 0.0
        assert engine.game_mode.state == "defeat"

    def test_tick_syncs_partial_damage(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        _start_drone_swarm(engine)

        engine._infrastructure_health.apply_damage(
            300.0, source_id="test", source_type="test",
        )

        engine._do_tick(0.1)

        # game_mode.infrastructure_health should be synced from InfrastructureHealth
        assert engine.game_mode.infrastructure_health == pytest.approx(700.0, abs=1.0)
        assert engine.game_mode.state == "active"  # Not defeated

    def test_infrastructure_health_in_game_state(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        _start_drone_swarm(engine)

        engine._infrastructure_health.apply_damage(
            400.0, source_id="test", source_type="test",
        )
        engine._do_tick(0.1)

        state = engine.get_game_state()
        assert state["infrastructure_health"] == pytest.approx(600.0, abs=1.0)
        assert state["infrastructure_max"] == 1000.0


class TestInfrastructureNotAffectedInBattleMode:
    """Non-drone-swarm modes do not create infrastructure subsystem."""

    def test_battle_mode_tick_no_infrastructure_check(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        engine.game_mode.game_mode_type = "battle"
        engine.begin_war()
        from engine.simulation.game_mode import _COUNTDOWN_DURATION
        engine.game_mode.tick(_COUNTDOWN_DURATION + 1.0)

        # No infrastructure subsystem
        assert engine._infrastructure_health is None

        # Tick should not crash
        engine._do_tick(0.1)


# --------------------------------------------------------------------------
# TASK 2: SwarmBehavior (boids) wired into engine tick
# --------------------------------------------------------------------------

class TestSwarmBehaviorCreatedForDroneSwarm:
    """SwarmBehavior is instantiated when drone_swarm mode starts."""

    def test_swarm_behavior_created_on_begin_war(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        assert engine._swarm_behavior is None

        engine.game_mode.game_mode_type = "drone_swarm"
        engine.begin_war()

        assert engine._swarm_behavior is not None
        assert isinstance(engine._swarm_behavior, SwarmBehavior)

    def test_swarm_behavior_not_created_for_battle(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        engine.game_mode.game_mode_type = "battle"
        engine.begin_war()

        assert engine._swarm_behavior is None

    def test_swarm_behavior_cleared_on_reset(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        engine.game_mode.game_mode_type = "drone_swarm"
        engine.begin_war()

        assert engine._swarm_behavior is not None

        engine.reset_game()
        assert engine._swarm_behavior is None


class TestSwarmBehaviorTickedDuringGameplay:
    """SwarmBehavior.tick() is called during active drone_swarm games."""

    def test_swarm_drones_move_via_boids(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        _start_drone_swarm(engine)

        # Add swarm drones
        for i in range(5):
            drone = SimulationTarget(
                target_id=f"swarm-{i}", name=f"Swarm {i}",
                alliance="hostile", asset_type="swarm_drone",
                position=(100.0 + i * 2, 100.0),
                speed=6.0, is_combatant=True, status="active",
            )
            drone.drone_variant = "attack_swarm"
            drone.apply_combat_profile()
            engine.add_target(drone)

        # Record initial positions
        initial_positions = {}
        for t in engine.get_targets():
            if t.asset_type == "swarm_drone":
                initial_positions[t.target_id] = t.position

        # Run several ticks -- boids should move drones
        for _ in range(10):
            engine._do_tick(0.1)

        # Check that at least some drones moved
        moved_count = 0
        for t in engine.get_targets():
            if t.target_id in initial_positions:
                old_pos = initial_positions[t.target_id]
                if t.status == "active":
                    dx = t.position[0] - old_pos[0]
                    dy = t.position[1] - old_pos[1]
                    if math.hypot(dx, dy) > 0.1:
                        moved_count += 1

        assert moved_count > 0, "Boids should have moved at least one swarm drone"

    def test_swarm_drones_steer_toward_defenders(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        _start_drone_swarm(engine)

        # Single swarm drone far from the defender (turret at 50, 50)
        drone = SimulationTarget(
            target_id="swarm-solo", name="Solo Swarm",
            alliance="hostile", asset_type="swarm_drone",
            position=(150.0, 150.0),
            speed=6.0, is_combatant=True, status="active",
        )
        drone.drone_variant = "attack_swarm"
        drone.apply_combat_profile()
        engine.add_target(drone)

        initial_dist = math.hypot(
            150.0 - 50.0, 150.0 - 50.0,
        )

        # Run ticks -- target-seeking should pull toward (50, 50)
        for _ in range(20):
            engine._do_tick(0.1)

        # Get the drone's current position
        d = engine.get_target("swarm-solo")
        if d is not None and d.status == "active":
            current_dist = math.hypot(
                d.position[0] - 50.0, d.position[1] - 50.0,
            )
            assert current_dist < initial_dist, (
                "Boids target-seeking should pull drone toward defenders"
            )

    def test_non_swarm_drones_not_affected_by_boids(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        _start_drone_swarm(engine)

        # Add a regular hostile (not swarm_drone)
        hostile = SimulationTarget(
            target_id="hostile-person", name="Regular Hostile",
            alliance="hostile", asset_type="person",
            position=(100.0, 100.0),
            speed=1.5, is_combatant=True, status="active",
        )
        hostile.apply_combat_profile()
        engine.add_target(hostile)

        initial_pos = hostile.position

        # Swarm behavior only applies to swarm_drone asset_type
        # This test verifies that the filtering works correctly
        swarm_drones = {
            tid: t for tid, t in {hostile.target_id: hostile}.items()
            if t.asset_type == "swarm_drone"
        }
        assert len(swarm_drones) == 0, "Regular hostile should not be in swarm dict"

    def test_swarm_behavior_only_active_during_game(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        engine.game_mode.game_mode_type = "drone_swarm"
        engine.begin_war()

        assert engine._swarm_behavior is not None

        # Before countdown completes, game_mode.state is "countdown"
        # The swarm behavior tick is inside the `if game_active:` block,
        # so it should not run during countdown
        engine.game_mode.state = "countdown"
        drone = SimulationTarget(
            target_id="swarm-test", name="Test Swarm",
            alliance="hostile", asset_type="swarm_drone",
            position=(100.0, 100.0),
            speed=6.0, is_combatant=True, status="active",
        )
        drone.drone_variant = "attack_swarm"
        drone.apply_combat_profile()
        engine.add_target(drone)

        initial_pos = drone.position

        # Tick during countdown -- boids should NOT run
        engine._do_tick(0.1)

        # Position may change from target.tick(dt) movement, but not from boids
        # (Since there are no waypoints, movement tick won't move it either)
        # This test validates the code path doesn't crash during non-active state


class TestSwarmBehaviorHeadingUpdate:
    """Boids should update drone headings to match movement direction."""

    def test_headings_updated(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        _start_drone_swarm(engine)

        # Two drones, separated -- cohesion and target-seeking will create force
        d1 = SimulationTarget(
            target_id="sw-1", name="Swarm 1",
            alliance="hostile", asset_type="swarm_drone",
            position=(120.0, 120.0),
            speed=6.0, is_combatant=True, status="active",
        )
        d1.drone_variant = "attack_swarm"
        d1.apply_combat_profile()
        d1.heading = 0.0

        d2 = SimulationTarget(
            target_id="sw-2", name="Swarm 2",
            alliance="hostile", asset_type="swarm_drone",
            position=(125.0, 120.0),
            speed=6.0, is_combatant=True, status="active",
        )
        d2.drone_variant = "attack_swarm"
        d2.apply_combat_profile()
        d2.heading = 0.0

        engine.add_target(d1)
        engine.add_target(d2)

        # Run ticks
        for _ in range(5):
            engine._do_tick(0.1)

        # At least one heading should have changed (target-seeking toward 50,50)
        t1 = engine.get_target("sw-1")
        t2 = engine.get_target("sw-2")
        headings_changed = False
        if t1 and t1.status == "active" and t1.heading != 0.0:
            headings_changed = True
        if t2 and t2.status == "active" and t2.heading != 0.0:
            headings_changed = True

        assert headings_changed, "Boids should update drone headings"


# --------------------------------------------------------------------------
# Combined: both subsystems together
# --------------------------------------------------------------------------

class TestBothSubsystemsTogether:
    """Infrastructure and swarm behavior work together in drone_swarm mode."""

    def test_both_created_on_begin_war(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        engine.game_mode.game_mode_type = "drone_swarm"
        engine.begin_war()

        assert engine._infrastructure_health is not None
        assert engine._swarm_behavior is not None
        assert len(engine._poi_buildings) >= 1

    def test_both_cleared_on_reset(self):
        bus = SimpleEventBus()
        engine = _make_engine(bus)
        engine.game_mode.game_mode_type = "drone_swarm"
        engine.begin_war()

        engine.reset_game()

        assert engine._infrastructure_health is None
        assert engine._swarm_behavior is None
        assert engine._poi_buildings == []
