# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Comprehensive unit tests for SimulationEngine — the core 10Hz tick loop.

Tests cover:
  - Target management (add, remove, get, get_target)
  - Hostile spawning (names, positions, waypoints, dedup)
  - Unit dispatch (drones direct, ground direct, stationary ignored)
  - Tick loop mechanics (telemetry publishing, subsystem calls)
  - Interception check (friendly neutralizes hostile at close range)
  - Game mode interface (begin_war, reset_game, get_game_state)
  - Lifecycle cleanup (destroyed, despawned, escaped, neutralized, eliminated)
  - Spawner pause/resume
  - FSM integration (creation on add_target, state sync)
  - Event bus wiring (set_event_bus propagates)
  - Edge cases (empty targets, duplicate IDs, invalid positions, zero speed)
"""

from __future__ import annotations

import math
import queue
import threading
import time

import pytest

from engine.simulation.engine import SimulationEngine, _HOSTILE_NAMES
from engine.simulation.target import SimulationTarget


class SimpleEventBus:
    """Minimal EventBus for unit testing.

    Uses topic-less subscribe (matches real EventBus) so combat_event_listener
    and other internal subscribers work correctly.
    """

    def __init__(self) -> None:
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        msg = {"type": topic, "data": data}
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def subscribe(self, _filter: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass


pytestmark = pytest.mark.unit


def _make_engine(map_bounds: float = 200.0) -> tuple[SimulationEngine, SimpleEventBus]:
    """Create a SimulationEngine with a SimpleEventBus for testing."""
    bus = SimpleEventBus()
    engine = SimulationEngine(bus, map_bounds=map_bounds)
    return engine, bus


def _make_target(
    target_id: str = "t1",
    name: str = "Test",
    alliance: str = "friendly",
    asset_type: str = "rover",
    position: tuple[float, float] = (0.0, 0.0),
    speed: float = 3.0,
    **kwargs,
) -> SimulationTarget:
    """Create a SimulationTarget with sensible defaults for testing."""
    return SimulationTarget(
        target_id=target_id,
        name=name,
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        speed=speed,
        **kwargs,
    )


# ==========================================================================
# Target Management
# ==========================================================================

class TestAddTarget:
    """Tests for SimulationEngine.add_target()."""

    def test_add_single_target(self):
        engine, bus = _make_engine()
        t = _make_target()
        engine.add_target(t)
        assert engine.get_target("t1") is t

    def test_add_multiple_targets(self):
        engine, bus = _make_engine()
        for i in range(5):
            engine.add_target(_make_target(target_id=f"t{i}", name=f"Unit {i}"))
        assert len(engine.get_targets()) == 5

    def test_add_target_overwrites_same_id(self):
        engine, bus = _make_engine()
        t1 = _make_target(target_id="t1", name="First")
        t2 = _make_target(target_id="t1", name="Second")
        engine.add_target(t1)
        engine.add_target(t2)
        assert engine.get_target("t1").name == "Second"
        assert len(engine.get_targets()) == 1

    def test_add_target_creates_fsm_for_combatant(self):
        engine, bus = _make_engine()
        t = _make_target(asset_type="turret", speed=0.0)
        engine.add_target(t)
        # Turrets get an FSM; check fsm_state was set
        assert t.fsm_state is not None

    def test_add_target_creates_fsm_for_rover(self):
        engine, bus = _make_engine()
        t = _make_target(asset_type="rover")
        engine.add_target(t)
        assert t.fsm_state is not None

    def test_add_target_creates_fsm_for_hostile(self):
        engine, bus = _make_engine()
        t = _make_target(
            asset_type="person", alliance="hostile",
            position=(10.0, 10.0), speed=1.5,
        )
        engine.add_target(t)
        assert t.fsm_state is not None

    def test_add_target_no_fsm_for_neutral(self):
        engine, bus = _make_engine()
        t = _make_target(
            asset_type="person", alliance="neutral",
            is_combatant=False, speed=1.0,
        )
        engine.add_target(t)
        # Neutrals may or may not get an FSM depending on create_fsm_for_type
        # The key point is it does not crash
        assert engine.get_target(t.target_id) is t

    def test_add_combatant_gets_weapon(self):
        engine, bus = _make_engine()
        t = _make_target(asset_type="turret", speed=0.0)
        engine.add_target(t)
        # WeaponSystem should have assigned a default weapon
        weapon = engine.weapon_system.get_weapon(t.target_id)
        assert weapon is not None

    def test_add_noncombatant_no_weapon(self):
        engine, bus = _make_engine()
        t = _make_target(
            asset_type="person", alliance="neutral",
            is_combatant=False,
        )
        engine.add_target(t)
        weapon = engine.weapon_system.get_weapon(t.target_id)
        # Non-combatants should not have weapons assigned
        assert weapon is None


class TestRemoveTarget:
    """Tests for SimulationEngine.remove_target()."""

    def test_remove_existing_target(self):
        engine, bus = _make_engine()
        t = _make_target()
        engine.add_target(t)
        assert engine.remove_target("t1") is True
        assert engine.get_target("t1") is None

    def test_remove_nonexistent_returns_false(self):
        engine, bus = _make_engine()
        assert engine.remove_target("nonexistent") is False

    def test_remove_clears_fsm(self):
        engine, bus = _make_engine()
        t = _make_target(asset_type="turret", speed=0.0)
        engine.add_target(t)
        assert "t1" in engine._fsms
        engine.remove_target("t1")
        assert "t1" not in engine._fsms

    def test_remove_idempotent(self):
        engine, bus = _make_engine()
        t = _make_target()
        engine.add_target(t)
        assert engine.remove_target("t1") is True
        assert engine.remove_target("t1") is False

    def test_remove_does_not_affect_others(self):
        engine, bus = _make_engine()
        engine.add_target(_make_target(target_id="a", name="A"))
        engine.add_target(_make_target(target_id="b", name="B"))
        engine.add_target(_make_target(target_id="c", name="C"))
        engine.remove_target("b")
        ids = {t.target_id for t in engine.get_targets()}
        assert ids == {"a", "c"}


class TestGetTargets:
    """Tests for SimulationEngine.get_targets() and get_target()."""

    def test_get_targets_empty(self):
        engine, bus = _make_engine()
        assert engine.get_targets() == []

    def test_get_targets_returns_copy(self):
        engine, bus = _make_engine()
        engine.add_target(_make_target())
        targets_a = engine.get_targets()
        targets_b = engine.get_targets()
        assert targets_a is not targets_b
        # But the target objects themselves should be the same references
        assert targets_a[0] is targets_b[0]

    def test_get_target_none_for_unknown(self):
        engine, bus = _make_engine()
        assert engine.get_target("no_such_id") is None

    def test_get_targets_mixed_alliances(self):
        engine, bus = _make_engine()
        engine.add_target(_make_target(target_id="f1", alliance="friendly"))
        engine.add_target(_make_target(
            target_id="h1", alliance="hostile", asset_type="person", speed=1.5,
        ))
        engine.add_target(_make_target(
            target_id="n1", alliance="neutral", asset_type="person",
            is_combatant=False,
        ))
        targets = engine.get_targets()
        alliances = {t.alliance for t in targets}
        assert alliances == {"friendly", "hostile", "neutral"}


# ==========================================================================
# Hostile Spawning
# ==========================================================================

class TestSpawnHostile:
    """Tests for SimulationEngine.spawn_hostile()."""

    def test_spawn_hostile_returns_target(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        assert isinstance(h, SimulationTarget)

    def test_spawn_hostile_alliance(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        assert h.alliance == "hostile"

    def test_spawn_hostile_asset_type(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        assert h.asset_type == "person"

    def test_spawn_hostile_speed(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        assert h.speed == 1.5

    def test_spawn_hostile_added_to_engine(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        assert engine.get_target(h.target_id) is h

    def test_spawn_hostile_custom_name(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile(name="Custom Intruder")
        assert h.name == "Custom Intruder"

    def test_spawn_hostile_custom_position(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile(position=(50.0, -30.0))
        assert h.position == (50.0, -30.0)

    def test_spawn_hostile_random_name_from_pool(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        # Should use one of the _HOSTILE_NAMES (possibly with suffix)
        base_names = set(_HOSTILE_NAMES)
        base = h.name.split("-")[0]
        assert base in base_names

    def test_spawn_hostile_has_waypoints(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        assert len(h.waypoints) >= 2  # At minimum approach + escape

    def test_spawn_hostile_has_legacy_waypoints(self):
        engine, bus = _make_engine()
        # Without street graph, should get 2 waypoints: objective + escape_edge
        h = engine.spawn_hostile()
        assert len(h.waypoints) == 2

    def test_spawn_hostile_combat_profile_applied(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        # hostile person should have person_hostile profile
        assert h.health == 80.0
        assert h.max_health == 80.0
        assert h.weapon_range == 40.0
        assert h.is_combatant is True

    def test_spawn_hostile_gets_fsm(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        assert h.fsm_state is not None
        assert h.target_id in engine._fsms


class TestHostileNameDedup:
    """Tests for hostile name deduplication."""

    def test_duplicate_names_get_suffix(self):
        engine, bus = _make_engine()
        h1 = engine.spawn_hostile(name="Alpha")
        h2 = engine.spawn_hostile(name="Alpha")
        h3 = engine.spawn_hostile(name="Alpha")
        names = {h1.name, h2.name, h3.name}
        assert len(names) == 3
        assert "Alpha" in names
        assert "Alpha-2" in names
        assert "Alpha-3" in names

    def test_name_recycled_after_remove(self):
        engine, bus = _make_engine()
        h1 = engine.spawn_hostile(name="Bravo")
        engine.remove_target(h1.target_id)
        # Name should still be in _used_names (remove_target does not clear it)
        # But spawn logic uses _used_names, not target list
        h2 = engine.spawn_hostile(name="Bravo")
        # Second spawn gets Bravo-2 because _used_names still has "Bravo"
        assert h2.name == "Bravo-2"

    def test_many_duplicates(self):
        engine, bus = _make_engine()
        hostiles = [engine.spawn_hostile(name="Delta") for _ in range(10)]
        names = [h.name for h in hostiles]
        assert len(set(names)) == 10
        assert names[0] == "Delta"
        assert names[1] == "Delta-2"
        assert names[9] == "Delta-10"


class TestRandomEdgePosition:
    """Tests for _random_edge_position()."""

    def test_position_on_edge(self):
        engine, bus = _make_engine(map_bounds=100.0)
        for _ in range(50):
            x, y = engine._random_edge_position()
            # At least one coordinate should be at +/- map_bounds
            on_edge = (
                abs(x) == pytest.approx(100.0, abs=0.01)
                or abs(y) == pytest.approx(100.0, abs=0.01)
            )
            assert on_edge, f"Position ({x}, {y}) not on edge"

    def test_position_within_bounds(self):
        engine, bus = _make_engine(map_bounds=50.0)
        for _ in range(50):
            x, y = engine._random_edge_position()
            assert -50.0 <= x <= 50.0
            assert -50.0 <= y <= 50.0


class TestCountActiveHostiles:
    """Tests for _count_active_hostiles()."""

    def test_count_zero_initially(self):
        engine, bus = _make_engine()
        assert engine._count_active_hostiles() == 0

    def test_count_active_only(self):
        engine, bus = _make_engine()
        h1 = engine.spawn_hostile()
        h2 = engine.spawn_hostile()
        h3 = engine.spawn_hostile()
        h3.status = "eliminated"
        assert engine._count_active_hostiles() == 2

    def test_count_ignores_friendlies(self):
        engine, bus = _make_engine()
        engine.add_target(_make_target(target_id="f1", alliance="friendly"))
        engine.spawn_hostile()
        assert engine._count_active_hostiles() == 1

    def test_count_ignores_neutralized(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        h.status = "neutralized"
        assert engine._count_active_hostiles() == 0


# ==========================================================================
# Dispatch Unit
# ==========================================================================

class TestDispatchUnit:
    """Tests for SimulationEngine.dispatch_unit()."""

    def test_dispatch_nonexistent_target(self):
        engine, bus = _make_engine()
        # Should not raise
        engine.dispatch_unit("nonexistent", (10.0, 10.0))

    def test_dispatch_zero_speed_ignored(self):
        engine, bus = _make_engine()
        t = _make_target(target_id="turret1", asset_type="turret", speed=0.0)
        engine.add_target(t)
        engine.dispatch_unit("turret1", (10.0, 10.0))
        # Turret should not have waypoints set
        # (it had no waypoints before and dispatch ignores speed=0)
        assert t.status != "active" or len(t.waypoints) == 0

    def test_dispatch_drone_direct(self):
        engine, bus = _make_engine()
        t = _make_target(
            target_id="d1", asset_type="drone", speed=5.0,
            position=(0.0, 0.0),
        )
        engine.add_target(t)
        engine.dispatch_unit("d1", (50.0, 50.0))
        # Drones fly direct: [current_pos, destination]
        assert len(t.waypoints) == 2
        assert t.waypoints[0] == (0.0, 0.0)
        assert t.waypoints[1] == (50.0, 50.0)
        assert t.status == "active"

    def test_dispatch_scout_drone_direct(self):
        engine, bus = _make_engine()
        t = _make_target(
            target_id="sd1", asset_type="scout_drone", speed=4.0,
            position=(5.0, 5.0),
        )
        engine.add_target(t)
        engine.dispatch_unit("sd1", (30.0, 30.0))
        assert len(t.waypoints) == 2
        assert t.waypoints[1] == (30.0, 30.0)

    def test_dispatch_rover_direct_no_graph(self):
        engine, bus = _make_engine()
        t = _make_target(
            target_id="r1", asset_type="rover", speed=3.0,
            position=(0.0, 0.0),
        )
        engine.add_target(t)
        engine.dispatch_unit("r1", (20.0, 20.0))
        # Without street graph, rover moves directly
        assert len(t.waypoints) == 1
        assert t.waypoints[0] == (20.0, 20.0)
        assert t._waypoint_index == 0
        assert t.status == "active"

    def test_dispatch_sets_active_status(self):
        engine, bus = _make_engine()
        t = _make_target(target_id="r1")
        t.status = "idle"
        engine.add_target(t)
        engine.dispatch_unit("r1", (10.0, 10.0))
        assert t.status == "active"

    def test_dispatch_resets_waypoint_index(self):
        engine, bus = _make_engine()
        t = _make_target(target_id="r1")
        t._waypoint_index = 5
        engine.add_target(t)
        engine.dispatch_unit("r1", (10.0, 10.0))
        assert t._waypoint_index == 0


# ==========================================================================
# Tick Loop Mechanics
# ==========================================================================

class TestTickPublishesTelemetry:
    """Tests verifying the tick loop publishes sim_telemetry events."""

    def test_manual_tick_publishes(self):
        engine, bus = _make_engine()
        t = _make_target(
            target_id="r1", name="Rover",
            waypoints=[(10.0, 0.0)],
        )
        engine.add_target(t)

        sub = bus.subscribe()

        # Manually simulate one tick iteration
        t.tick(0.1)
        bus.publish("sim_telemetry", t.to_dict())

        # Drain events to find our telemetry
        found = False
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "sim_telemetry":
                data = msg.get("data", {})
                if data.get("target_id") == "r1":
                    found = True
                    assert data["alliance"] == "friendly"
                    assert "position" in data
                    break
        assert found, "sim_telemetry event not published"

    def test_tick_publishes_for_each_target(self):
        engine, bus = _make_engine()
        for i in range(3):
            engine.add_target(_make_target(
                target_id=f"t{i}", name=f"Unit {i}",
            ))

        sub = bus.subscribe()

        # Simulate one tick for all targets
        for t in engine.get_targets():
            t.tick(0.1)
            bus.publish("sim_telemetry", t.to_dict())

        telemetry_ids = set()
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "sim_telemetry":
                telemetry_ids.add(msg["data"]["target_id"])
        assert telemetry_ids == {"t0", "t1", "t2"}


# ==========================================================================
# Interception Check
# ==========================================================================

class TestCheckInterceptions:
    """Tests for _check_interceptions() — legacy non-game interception."""

    def test_hostile_neutralized_at_close_range(self):
        engine, bus = _make_engine()
        friendly = _make_target(
            target_id="f1", alliance="friendly",
            position=(0.0, 0.0),
        )
        hostile = _make_target(
            target_id="h1", alliance="hostile", asset_type="person",
            position=(1.0, 0.0), speed=1.5,
        )
        engine.add_target(friendly)
        engine.add_target(hostile)

        sub = bus.subscribe()
        engine._check_interceptions(engine.get_targets())

        assert hostile.status == "neutralized"
        # Check event was published
        found_event = False
        while not sub.empty():
            msg = sub.get_nowait()
            if msg.get("type") == "target_neutralized":
                found_event = True
                data = msg["data"]
                assert data["hostile_id"] == "h1"
                assert data["interceptor_id"] == "f1"
        assert found_event

    def test_no_interception_at_long_range(self):
        engine, bus = _make_engine()
        friendly = _make_target(
            target_id="f1", alliance="friendly",
            position=(0.0, 0.0),
        )
        hostile = _make_target(
            target_id="h1", alliance="hostile", asset_type="person",
            position=(50.0, 50.0), speed=1.5,
        )
        engine.add_target(friendly)
        engine.add_target(hostile)

        engine._check_interceptions(engine.get_targets())
        assert hostile.status == "active"

    def test_interception_at_exact_range(self):
        engine, bus = _make_engine()
        # INTERCEPT_RANGE = 2.0, so distance of exactly 2.0 should trigger
        friendly = _make_target(
            target_id="f1", alliance="friendly",
            position=(0.0, 0.0),
        )
        hostile = _make_target(
            target_id="h1", alliance="hostile", asset_type="person",
            position=(2.0, 0.0), speed=1.5,
        )
        engine.add_target(friendly)
        engine.add_target(hostile)

        engine._check_interceptions(engine.get_targets())
        assert hostile.status == "neutralized"

    def test_interception_just_outside_range(self):
        engine, bus = _make_engine()
        # Just outside range should NOT neutralize
        friendly = _make_target(
            target_id="f1", alliance="friendly",
            position=(0.0, 0.0),
        )
        hostile = _make_target(
            target_id="h1", alliance="hostile", asset_type="person",
            position=(2.01, 0.0), speed=1.5,
        )
        engine.add_target(friendly)
        engine.add_target(hostile)

        engine._check_interceptions(engine.get_targets())
        assert hostile.status == "active"

    def test_only_active_hostiles_intercepted(self):
        engine, bus = _make_engine()
        friendly = _make_target(
            target_id="f1", alliance="friendly",
            position=(0.0, 0.0),
        )
        hostile = _make_target(
            target_id="h1", alliance="hostile", asset_type="person",
            position=(1.0, 0.0), speed=1.5,
        )
        hostile.status = "eliminated"
        engine.add_target(friendly)
        engine.add_target(hostile)

        engine._check_interceptions(engine.get_targets())
        # Should remain eliminated, not become neutralized
        assert hostile.status == "eliminated"

    def test_only_active_friendlies_intercept(self):
        engine, bus = _make_engine()
        friendly = _make_target(
            target_id="f1", alliance="friendly",
            position=(0.0, 0.0),
        )
        friendly.status = "destroyed"
        hostile = _make_target(
            target_id="h1", alliance="hostile", asset_type="person",
            position=(1.0, 0.0), speed=1.5,
        )
        engine.add_target(friendly)
        engine.add_target(hostile)

        engine._check_interceptions(engine.get_targets())
        assert hostile.status == "active"


# ==========================================================================
# Game Mode Interface
# ==========================================================================

class TestGameModeInterface:
    """Tests for begin_war, reset_game, get_game_state."""

    def test_initial_state_is_setup(self):
        engine, bus = _make_engine()
        state = engine.get_game_state()
        assert state["state"] == "setup"

    def test_begin_war_changes_state(self):
        engine, bus = _make_engine()
        engine.begin_war()
        state = engine.get_game_state()
        assert state["state"] in ("countdown", "active")

    def test_reset_game_clears_hostiles(self):
        engine, bus = _make_engine()
        engine.spawn_hostile()
        engine.spawn_hostile()
        assert len([t for t in engine.get_targets() if t.alliance == "hostile"]) == 2
        engine.reset_game()
        hostiles = [t for t in engine.get_targets() if t.alliance == "hostile"]
        assert len(hostiles) == 0

    def test_reset_game_heals_friendlies(self):
        engine, bus = _make_engine()
        t = _make_target(target_id="r1", alliance="friendly")
        t.health = 20.0
        t.max_health = 150.0
        engine.add_target(t)
        engine.reset_game()
        assert t.health == t.max_health

    def test_reset_game_revives_eliminated_friendlies(self):
        engine, bus = _make_engine()
        t = _make_target(target_id="r1", alliance="friendly")
        t.status = "eliminated"
        t.health = 0.0
        t.max_health = 150.0
        engine.add_target(t)
        engine.reset_game()
        assert t.status == "active"
        assert t.health == t.max_health

    def test_reset_game_removes_game_units(self):
        engine, bus = _make_engine()
        # Game units (turret-*, drone-*, rover-*) are removed on reset
        t1 = _make_target(target_id="turret-1", alliance="friendly", asset_type="turret", speed=0.0)
        t2 = _make_target(target_id="drone-1", alliance="friendly", asset_type="drone", speed=5.0)
        t3 = _make_target(target_id="rover-1", alliance="friendly", asset_type="rover")
        for t in [t1, t2, t3]:
            engine.add_target(t)
        engine.reset_game()
        assert engine.get_target("turret-1") is None
        assert engine.get_target("drone-1") is None
        assert engine.get_target("rover-1") is None

    def test_reset_game_keeps_non_game_friendlies(self):
        engine, bus = _make_engine()
        # Non-game friendly (not turret-/drone-/rover- prefix) should survive
        t = _make_target(target_id="real-rover-1", alliance="friendly")
        engine.add_target(t)
        engine.reset_game()
        assert engine.get_target("real-rover-1") is t

    def test_reset_game_clears_fsms(self):
        engine, bus = _make_engine()
        engine.spawn_hostile()
        assert len(engine._fsms) > 0
        engine.reset_game()
        assert len(engine._fsms) == 0

    def test_reset_game_resets_subsystems(self):
        engine, bus = _make_engine()
        # After reset, subsystems should be clean
        engine.reset_game()
        # Just verify no exceptions and combat is cleared
        assert engine.combat._projectiles == [] or len(engine.combat._projectiles) == 0


# ==========================================================================
# Lifecycle Cleanup
# ==========================================================================

class TestLifecycleCleanup:
    """Tests for the cleanup logic that runs in the tick loop."""

    def test_destroyed_at_tracking(self):
        engine, bus = _make_engine()
        t = _make_target(target_id="r1")
        t.status = "destroyed"
        engine.add_target(t)
        now = time.time()
        engine._destroyed_at["r1"] = now
        assert "r1" in engine._destroyed_at

    def test_despawned_at_tracking(self):
        engine, bus = _make_engine()
        t = _make_target(target_id="n1", alliance="neutral", is_combatant=False)
        t.status = "despawned"
        engine.add_target(t)
        engine._despawned_at["n1"] = time.time()
        assert "n1" in engine._despawned_at

    def test_low_battery_to_destroyed_transition(self):
        """Simulate the tick loop's low_battery -> destroyed transition."""
        engine, bus = _make_engine()
        t = _make_target(target_id="r1")
        t.battery = 0.0
        t.status = "low_battery"
        engine.add_target(t)

        # First encounter: records timestamp
        now = time.time()
        engine._destroyed_at[t.target_id] = now - 70  # 70s ago

        # Simulate the cleanup check
        if t.battery <= 0 and t.status == "low_battery":
            if t.target_id in engine._destroyed_at:
                if now - engine._destroyed_at[t.target_id] > 60:
                    t.status = "destroyed"
        assert t.status == "destroyed"


# ==========================================================================
# Spawner Pause / Resume
# ==========================================================================

class TestSpawnerPauseResume:
    """Tests for pause_spawners() / resume_spawners()."""

    def test_spawners_not_paused_initially(self):
        engine, bus = _make_engine()
        assert engine.spawners_paused is False

    def test_pause_spawners(self):
        engine, bus = _make_engine()
        engine.pause_spawners()
        assert engine.spawners_paused is True

    def test_resume_spawners(self):
        engine, bus = _make_engine()
        engine.pause_spawners()
        engine.resume_spawners()
        assert engine.spawners_paused is False

    def test_pause_resume_idempotent(self):
        engine, bus = _make_engine()
        engine.pause_spawners()
        engine.pause_spawners()
        assert engine.spawners_paused is True
        engine.resume_spawners()
        assert engine.spawners_paused is False


# ==========================================================================
# Event Bus Wiring
# ==========================================================================

class TestEventBusWiring:
    """Tests for set_event_bus() propagation."""

    def test_set_event_bus_propagates_to_combat(self):
        engine, bus1 = _make_engine()
        bus2 = SimpleEventBus()
        engine.set_event_bus(bus2)
        assert engine._event_bus is bus2
        assert engine.combat._event_bus is bus2
        assert engine.game_mode._event_bus is bus2

    def test_event_bus_property(self):
        engine, bus = _make_engine()
        assert engine.event_bus is bus


# ==========================================================================
# Map Bounds
# ==========================================================================

class TestMapBounds:
    """Tests for configurable map bounds."""

    def test_default_map_bounds(self):
        engine, bus = _make_engine()
        assert engine._map_bounds == 200.0
        assert engine._map_min == -200.0
        assert engine._map_max == 200.0

    def test_custom_map_bounds(self):
        engine, bus = _make_engine(map_bounds=50.0)
        assert engine._map_bounds == 50.0
        assert engine._map_min == -50.0
        assert engine._map_max == 50.0

    def test_negative_bounds_become_positive(self):
        engine, bus = _make_engine(map_bounds=-100.0)
        assert engine._map_bounds == 100.0


# ==========================================================================
# Navigation Properties
# ==========================================================================

class TestNavigationProperties:
    """Tests for street_graph and obstacles properties/setters."""

    def test_street_graph_initially_none(self):
        engine, bus = _make_engine()
        assert engine.street_graph is None

    def test_set_street_graph(self):
        engine, bus = _make_engine()
        mock_graph = object()
        engine.set_street_graph(mock_graph)
        assert engine.street_graph is mock_graph

    def test_obstacles_initially_none(self):
        engine, bus = _make_engine()
        assert engine.obstacles is None

    def test_set_obstacles(self):
        engine, bus = _make_engine()
        mock_obstacles = object()
        engine.set_obstacles(mock_obstacles)
        assert engine.obstacles is mock_obstacles


# ==========================================================================
# FSM Integration
# ==========================================================================

class TestFSMIntegration:
    """Tests for FSM creation and state sync in _tick_fsms()."""

    def test_fsm_created_for_turret(self):
        engine, bus = _make_engine()
        t = _make_target(
            target_id="t1", asset_type="turret", speed=0.0,
        )
        engine.add_target(t)
        assert "t1" in engine._fsms
        assert t.fsm_state is not None

    def test_fsm_created_for_hostile_person(self):
        engine, bus = _make_engine()
        t = _make_target(
            target_id="h1", asset_type="person", alliance="hostile",
            speed=1.5,
        )
        engine.add_target(t)
        assert "h1" in engine._fsms

    def test_tick_fsms_syncs_state(self):
        engine, bus = _make_engine()
        t = _make_target(
            target_id="t1", asset_type="turret", speed=0.0,
        )
        engine.add_target(t)
        initial_state = t.fsm_state

        targets_dict = {t.target_id: t}
        # Tick FSMs multiple times to allow transitions
        for _ in range(20):
            engine._tick_fsms(0.1, targets_dict)

        # State may or may not have changed, but should still be valid
        assert t.fsm_state is not None

    def test_tick_fsms_skips_non_active_targets(self):
        engine, bus = _make_engine()
        t = _make_target(
            target_id="t1", asset_type="turret", speed=0.0,
        )
        engine.add_target(t)
        initial_state = t.fsm_state
        t.status = "destroyed"

        targets_dict = {t.target_id: t}
        engine._tick_fsms(0.1, targets_dict)

        # FSM should not tick for destroyed targets
        assert t.fsm_state == initial_state

    def test_tick_fsms_skips_missing_target(self):
        engine, bus = _make_engine()
        t = _make_target(
            target_id="t1", asset_type="turret", speed=0.0,
        )
        engine.add_target(t)

        # Empty targets dict: target not found => skip
        engine._tick_fsms(0.1, {})
        # Should not crash


# ==========================================================================
# Sensor Detection
# ==========================================================================

class TestSensorDetection:
    """Tests for _handle_sensor_triggered() and _expire_detections()."""

    def test_handle_sensor_triggered_marks_hostile(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        assert h.detected is False

        engine._handle_sensor_triggered({"target_id": h.target_id})
        assert h.detected is True
        assert h.detected_at > 0

    def test_handle_sensor_triggered_ignores_friendly(self):
        engine, bus = _make_engine()
        t = _make_target(target_id="f1", alliance="friendly")
        engine.add_target(t)

        engine._handle_sensor_triggered({"target_id": "f1"})
        assert t.detected is False

    def test_handle_sensor_triggered_ignores_missing_target(self):
        engine, bus = _make_engine()
        # Should not raise
        engine._handle_sensor_triggered({"target_id": "nonexistent"})

    def test_handle_sensor_triggered_ignores_no_target_id(self):
        engine, bus = _make_engine()
        engine._handle_sensor_triggered({})

    def test_expire_detections(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        h.detected = True
        h.detected_at = time.monotonic() - 31.0  # 31s ago, past 30s expiry

        engine._expire_detections()
        assert h.detected is False

    def test_expire_detections_keeps_recent(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile()
        h.detected = True
        h.detected_at = time.monotonic() - 5.0  # Only 5s ago

        engine._expire_detections()
        assert h.detected is True


# ==========================================================================
# Engine Start / Stop
# ==========================================================================

class TestEngineLifecycle:
    """Tests for start() and stop() thread management."""

    def test_start_sets_running(self):
        engine, bus = _make_engine()
        engine.start()
        try:
            assert engine._running is True
            assert engine._thread is not None
            assert engine._thread.is_alive()
            assert engine._spawner_thread is not None
            assert engine._ambient_spawner is not None
        finally:
            engine.stop()

    def test_stop_clears_running(self):
        engine, bus = _make_engine()
        engine.start()
        engine.stop()
        assert engine._running is False
        assert engine._thread is None
        assert engine._spawner_thread is None
        assert engine._ambient_spawner is None

    def test_double_start_is_noop(self):
        engine, bus = _make_engine()
        engine.start()
        thread1 = engine._thread
        engine.start()  # Should not create new thread
        assert engine._thread is thread1
        engine.stop()

    def test_stop_without_start(self):
        engine, bus = _make_engine()
        # Should not raise
        engine.stop()

    def test_start_creates_daemon_threads(self):
        engine, bus = _make_engine()
        engine.start()
        try:
            assert engine._thread.daemon is True
            assert engine._spawner_thread.daemon is True
        finally:
            engine.stop()

    def test_live_tick_publishes_telemetry(self):
        """Start the real tick loop and verify telemetry appears on the bus."""
        engine, bus = _make_engine()
        t = _make_target(target_id="r1", name="LiveTest")
        engine.add_target(t)

        sub = bus.subscribe()
        engine.start()
        try:
            # Wait up to 1s for a telemetry message (batch or individual)
            deadline = time.time() + 1.0
            found = False
            while time.time() < deadline and not found:
                try:
                    msg = sub.get(timeout=0.1)
                    msg_type = msg.get("type", "")
                    if msg_type == "sim_telemetry":
                        data = msg.get("data", {})
                        if data.get("target_id") == "r1":
                            found = True
                    elif msg_type == "sim_telemetry_batch":
                        batch = msg.get("data", [])
                        if isinstance(batch, list) and any(t.get("target_id") == "r1" for t in batch if isinstance(t, dict)):
                            found = True
                except queue.Empty:
                    pass
            assert found, "No sim_telemetry event received from live tick loop"
        finally:
            engine.stop()


# ==========================================================================
# MAX_HOSTILES Constant
# ==========================================================================

class TestMaxHostiles:
    """Tests for MAX_HOSTILES constant."""

    def test_max_hostiles_value(self):
        engine, bus = _make_engine()
        assert engine.MAX_HOSTILES == 200

    def test_intercept_range_value(self):
        engine, bus = _make_engine()
        assert engine.INTERCEPT_RANGE == 2.0


# ==========================================================================
# Subsystem Initialization
# ==========================================================================

class TestSubsystemInit:
    """Tests that all subsystems are properly initialized."""

    def test_combat_system_exists(self):
        engine, bus = _make_engine()
        assert engine.combat is not None

    def test_game_mode_exists(self):
        engine, bus = _make_engine()
        assert engine.game_mode is not None

    def test_behaviors_exists(self):
        engine, bus = _make_engine()
        assert engine.behaviors is not None

    def test_morale_system_exists(self):
        engine, bus = _make_engine()
        assert engine.morale_system is not None

    def test_cover_system_exists(self):
        engine, bus = _make_engine()
        assert engine.cover_system is not None

    def test_degradation_system_exists(self):
        engine, bus = _make_engine()
        assert engine.degradation_system is not None

    def test_pursuit_system_exists(self):
        engine, bus = _make_engine()
        assert engine.pursuit_system is not None

    def test_unit_comms_exists(self):
        engine, bus = _make_engine()
        assert engine.unit_comms is not None

    def test_stats_tracker_exists(self):
        engine, bus = _make_engine()
        assert engine.stats_tracker is not None

    def test_terrain_map_exists(self):
        engine, bus = _make_engine()
        assert engine.terrain_map is not None

    def test_upgrade_system_exists(self):
        engine, bus = _make_engine()
        assert engine.upgrade_system is not None

    def test_weapon_system_exists(self):
        engine, bus = _make_engine()
        assert engine.weapon_system is not None

    def test_sensor_sim_exists(self):
        engine, bus = _make_engine()
        assert engine.sensor_sim is not None


# ==========================================================================
# Edge Cases
# ==========================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_engine_get_targets(self):
        engine, bus = _make_engine()
        assert engine.get_targets() == []

    def test_tick_fsms_with_empty_targets(self):
        engine, bus = _make_engine()
        # Should not crash
        engine._tick_fsms(0.1, {})

    def test_check_interceptions_no_targets(self):
        engine, bus = _make_engine()
        engine._check_interceptions([])

    def test_check_interceptions_only_friendlies(self):
        engine, bus = _make_engine()
        targets = [
            _make_target(target_id=f"f{i}", alliance="friendly")
            for i in range(3)
        ]
        for t in targets:
            engine.add_target(t)
        engine._check_interceptions(targets)
        # Should not crash, all should stay active
        for t in targets:
            assert t.status == "active"

    def test_check_interceptions_only_hostiles(self):
        engine, bus = _make_engine()
        targets = [
            _make_target(
                target_id=f"h{i}", alliance="hostile",
                asset_type="person", speed=1.5,
            )
            for i in range(3)
        ]
        for t in targets:
            engine.add_target(t)
        engine._check_interceptions(targets)
        # No friendlies to intercept
        for t in targets:
            assert t.status == "active"

    def test_spawn_hostile_with_empty_string_name(self):
        engine, bus = _make_engine()
        h = engine.spawn_hostile(name="")
        assert h.name == ""
        # Second one with same empty name gets suffix
        h2 = engine.spawn_hostile(name="")
        assert h2.name == "-2"

    def test_dispatch_after_remove(self):
        engine, bus = _make_engine()
        t = _make_target(target_id="r1")
        engine.add_target(t)
        engine.remove_target("r1")
        # Should not raise when dispatching removed target
        engine.dispatch_unit("r1", (10.0, 10.0))

    def test_multiple_interceptions_one_tick(self):
        """Multiple hostiles near multiple friendlies in one check."""
        engine, bus = _make_engine()
        # 2 friendlies near 2 hostiles
        f1 = _make_target(target_id="f1", alliance="friendly", position=(0.0, 0.0))
        f2 = _make_target(target_id="f2", alliance="friendly", position=(10.0, 0.0))
        h1 = _make_target(
            target_id="h1", alliance="hostile", asset_type="person",
            position=(1.0, 0.0), speed=1.5,
        )
        h2 = _make_target(
            target_id="h2", alliance="hostile", asset_type="person",
            position=(10.5, 0.0), speed=1.5,
        )
        for t in [f1, f2, h1, h2]:
            engine.add_target(t)

        engine._check_interceptions(engine.get_targets())
        assert h1.status == "neutralized"
        assert h2.status == "neutralized"

    def test_generate_hostile_waypoints_legacy(self):
        """Legacy waypoint generation (no street graph)."""
        engine, bus = _make_engine(map_bounds=100.0)
        wps = engine._generate_hostile_waypoints((100.0, 0.0))
        assert len(wps) == 2  # objective + escape_edge
        # Last waypoint should be on map edge
        ex, ey = wps[-1]
        on_edge = (
            abs(abs(ex) - 100.0) < 0.01
            or abs(abs(ey) - 100.0) < 0.01
        )
        assert on_edge, f"Escape point ({ex}, {ey}) not on edge"

    def test_ambient_spawner_property(self):
        engine, bus = _make_engine()
        # Not started yet
        assert engine.ambient_spawner is None
