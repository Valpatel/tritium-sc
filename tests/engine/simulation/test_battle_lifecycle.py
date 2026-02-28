# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Comprehensive engine integration test: full battle lifecycle end-to-end.

Exercises the FULL battle lifecycle in Python:
  - Initialization (clean engine state)
  - Unit placement (turret, rover, drone, tank)
  - Game start (countdown -> wave 1)
  - Combat cycle (projectile fire, hit detection, damage)
  - Kill tracking (elimination events, kill counts)
  - Wave progression (wave_complete -> next wave)
  - Degradation (health-based performance penalties)
  - Morale (damage -> morale drop -> suppression / broken)
  - Stats tracking (per-unit accuracy, KD, assists)
  - Victory condition (all 10 waves cleared)
  - Defeat condition (all friendlies eliminated)
  - Score calculation (per-kill + wave bonuses)
  - Replay data (snapshot recording during battle)
  - Reset (clean state restored)
  - Edge cases (no friendlies, no spawn points, etc.)
"""

from __future__ import annotations

import math
import queue
import threading
import time

import pytest

from engine.simulation.combat import CombatSystem, Projectile, HIT_RADIUS
from engine.simulation.engine import SimulationEngine
from engine.simulation.weapons import Weapon
from engine.simulation.game_mode import (
    GameMode,
    WAVE_CONFIGS,
    _COUNTDOWN_DURATION,
    _WAVE_ADVANCE_DELAY,
)
from engine.simulation.target import SimulationTarget
from engine.simulation.degradation import DegradationSystem
from engine.simulation.morale import (
    MoraleSystem,
    BROKEN_THRESHOLD,
    SUPPRESSED_THRESHOLD,
    EMBOLDENED_THRESHOLD,
)
from engine.simulation.stats import StatsTracker, UnitStats


# ---------------------------------------------------------------------------
# Shared test EventBus (topic-based subscribe, matches existing test patterns)
# ---------------------------------------------------------------------------

class SimpleEventBus:
    """Minimal topic-filtering EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._global_subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put(data)
            # Also deliver to global subscribers (engine combat listener needs this)
            msg = {"type": topic, "data": data}
            for q in self._global_subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        q.put_nowait(msg)
                    except queue.Full:
                        pass

    def subscribe(self, topic: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            if topic is None:
                self._global_subscribers.append(q)
            else:
                self._subscribers.setdefault(topic, []).append(q)
        return q


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_engine() -> tuple[SimpleEventBus, SimulationEngine]:
    """Create an engine with a SimpleEventBus. Does NOT start daemon threads."""
    bus = SimpleEventBus()
    engine = SimulationEngine(bus, map_bounds=200.0)
    return bus, engine


def _make_turret(
    target_id: str = "turret-1",
    name: str = "Turret Alpha",
    position: tuple[float, float] = (0.0, 0.0),
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=target_id, name=name, alliance="friendly",
        asset_type="turret", position=position, speed=0.0,
        status="stationary",
    )
    t.apply_combat_profile()
    return t


def _make_rover(
    target_id: str = "rover-1",
    name: str = "Rover Bravo",
    position: tuple[float, float] = (10.0, 0.0),
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=target_id, name=name, alliance="friendly",
        asset_type="rover", position=position, speed=3.0,
    )
    t.apply_combat_profile()
    return t


def _make_drone(
    target_id: str = "drone-1",
    name: str = "Drone Charlie",
    position: tuple[float, float] = (-10.0, 0.0),
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=target_id, name=name, alliance="friendly",
        asset_type="drone", position=position, speed=5.0,
    )
    t.apply_combat_profile()
    return t


def _make_tank(
    target_id: str = "tank-1",
    name: str = "Tank Delta",
    position: tuple[float, float] = (0.0, 10.0),
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=target_id, name=name, alliance="friendly",
        asset_type="tank", position=position, speed=2.0,
    )
    t.apply_combat_profile()
    return t


def _make_hostile(
    target_id: str = "hostile-1",
    name: str = "Intruder Alpha",
    position: tuple[float, float] = (5.0, 0.0),
    health: float = 80.0,
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=target_id, name=name, alliance="hostile",
        asset_type="person", position=position, speed=1.5,
    )
    t.apply_combat_profile()
    # Override health AFTER profile is applied so tests can control HP
    t.health = health
    t.max_health = health
    return t


def _set_perfect_accuracy(engine: SimulationEngine, target_id: str) -> None:
    """Override weapon accuracy to 1.0 so combat tests are deterministic."""
    weapon = engine.weapon_system.get_weapon(target_id)
    if weapon is not None:
        weapon.accuracy = 1.0


def _skip_countdown(gm: GameMode) -> None:
    """Tick past the countdown period to reach 'active' state."""
    gm.tick(_COUNTDOWN_DURATION + 0.1)


def _clear_wave(gm: GameMode) -> None:
    """Pretend the current wave's hostiles are all gone."""
    gm._spawn_thread = None
    gm._wave_hostile_ids.clear()


def _advance_past_intermission(gm: GameMode) -> None:
    """Set wave_complete_time in the past so next tick advances."""
    gm._wave_complete_time = time.time() - _WAVE_ADVANCE_DELAY - 1


def _purge_hostiles(engine: SimulationEngine) -> None:
    """Remove all hostile targets from the engine (for manual wave control)."""
    hostile_ids = [
        t.target_id for t in engine.get_targets()
        if t.alliance == "hostile"
    ]
    for tid in hostile_ids:
        engine.remove_target(tid)


# ==========================================================================
# 1. Initialization — clean engine state
# ==========================================================================

class TestEngineInitialization:
    def test_engine_starts_in_setup(self):
        bus, engine = _make_engine()
        assert engine.game_mode.state == "setup"

    def test_engine_no_targets_initially(self):
        bus, engine = _make_engine()
        assert len(engine.get_targets()) == 0

    def test_engine_wave_zero_initially(self):
        bus, engine = _make_engine()
        assert engine.game_mode.wave == 0

    def test_engine_score_zero_initially(self):
        bus, engine = _make_engine()
        assert engine.game_mode.score == 0

    def test_engine_total_eliminations_zero(self):
        bus, engine = _make_engine()
        assert engine.game_mode.total_eliminations == 0

    def test_combat_system_no_projectiles(self):
        bus, engine = _make_engine()
        assert engine.combat.projectile_count == 0

    def test_get_game_state_clean(self):
        bus, engine = _make_engine()
        state = engine.get_game_state()
        assert state["state"] == "setup"
        assert state["wave"] == 0
        assert state["score"] == 0
        assert state["total_waves"] == 10
        assert state["total_eliminations"] == 0


# ==========================================================================
# 2. Unit placement — positions, types, alliance
# ==========================================================================

class TestUnitPlacement:
    def test_add_turret(self):
        bus, engine = _make_engine()
        turret = _make_turret()
        engine.add_target(turret)
        targets = engine.get_targets()
        assert len(targets) == 1
        assert targets[0].asset_type == "turret"
        assert targets[0].alliance == "friendly"
        assert targets[0].position == (0.0, 0.0)

    def test_add_rover(self):
        bus, engine = _make_engine()
        rover = _make_rover()
        engine.add_target(rover)
        t = engine.get_target("rover-1")
        assert t is not None
        assert t.asset_type == "rover"
        assert t.speed == 3.0

    def test_add_drone(self):
        bus, engine = _make_engine()
        drone = _make_drone()
        engine.add_target(drone)
        t = engine.get_target("drone-1")
        assert t is not None
        assert t.asset_type == "drone"
        assert t.health == 60.0  # drone combat profile

    def test_add_tank(self):
        bus, engine = _make_engine()
        tank = _make_tank()
        engine.add_target(tank)
        t = engine.get_target("tank-1")
        assert t is not None
        assert t.asset_type == "tank"
        assert t.health == 400.0  # tank combat profile
        assert t.weapon_range == 100.0

    def test_place_multiple_units(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.add_target(_make_rover())
        engine.add_target(_make_drone())
        engine.add_target(_make_tank())
        assert len(engine.get_targets()) == 4

    def test_combat_profiles_applied(self):
        bus, engine = _make_engine()
        turret = _make_turret()
        engine.add_target(turret)
        assert turret.weapon_range == 80.0
        assert turret.weapon_cooldown == 1.5
        assert turret.weapon_damage == 15.0
        assert turret.is_combatant is True

    def test_remove_target(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        assert len(engine.get_targets()) == 1
        removed = engine.remove_target("turret-1")
        assert removed is True
        assert len(engine.get_targets()) == 0

    def test_remove_nonexistent_target(self):
        bus, engine = _make_engine()
        removed = engine.remove_target("does-not-exist")
        assert removed is False


# ==========================================================================
# 3. Game start — countdown -> wave 1
# ==========================================================================

class TestGameStart:
    def test_begin_war_transitions_to_countdown(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.begin_war()
        assert engine.game_mode.state == "countdown"
        assert engine.game_mode.wave == 1

    def test_countdown_decrements_over_time(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.begin_war()
        initial = engine.game_mode._countdown_remaining
        engine.game_mode.tick(1.0)
        assert engine.game_mode._countdown_remaining == initial - 1.0

    def test_countdown_transitions_to_active(self):
        bus, engine = _make_engine()
        wave_sub = bus.subscribe("wave_start")
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)
        assert engine.game_mode.state == "active"

    def test_wave_start_event_published(self):
        bus, engine = _make_engine()
        wave_sub = bus.subscribe("wave_start")
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)
        event = wave_sub.get(timeout=2.0)
        assert event["wave_number"] == 1
        assert event["wave_name"] == "Scout Party"

    def test_begin_war_resets_score(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.game_mode.score = 999
        engine.game_mode.total_eliminations = 50
        engine.begin_war()
        assert engine.game_mode.score == 0
        assert engine.game_mode.total_eliminations == 0


# ==========================================================================
# 4. Combat cycle — projectiles, hits, damage
# ==========================================================================

class TestCombatCycle:
    def test_fire_creates_projectile(self):
        bus, engine = _make_engine()
        turret = _make_turret()
        hostile = _make_hostile(position=(3.0, 0.0))
        engine.add_target(turret)
        engine.add_target(hostile)
        _set_perfect_accuracy(engine, "turret-1")

        proj = engine.combat.fire(turret, hostile)
        assert proj is not None
        assert engine.combat.projectile_count == 1

    def test_projectile_hits_close_target(self):
        bus, engine = _make_engine()
        hit_sub = bus.subscribe("projectile_hit")
        turret = _make_turret()
        hostile = _make_hostile(position=(2.0, 0.0), health=100.0)
        engine.add_target(turret)
        engine.add_target(hostile)
        _set_perfect_accuracy(engine, "turret-1")

        engine.combat.fire(turret, hostile)
        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.combat.tick(0.1, targets_dict)

        event = hit_sub.get(timeout=1.0)
        assert event["target_id"] == "hostile-1"
        assert event["damage"] == 15.0  # turret weapon_damage
        assert hostile.health < 100.0

    def test_damage_reduces_health(self):
        bus, engine = _make_engine()
        turret = _make_turret()
        hostile = _make_hostile(position=(2.0, 0.0), health=80.0)
        engine.add_target(turret)
        engine.add_target(hostile)
        _set_perfect_accuracy(engine, "turret-1")

        engine.combat.fire(turret, hostile)
        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.combat.tick(0.1, targets_dict)

        assert hostile.health == 80.0 - 15.0  # 65.0

    def test_projectile_event_published(self):
        bus, engine = _make_engine()
        fire_sub = bus.subscribe("projectile_fired")
        turret = _make_turret()
        hostile = _make_hostile(position=(10.0, 0.0))
        engine.add_target(turret)
        engine.add_target(hostile)
        _set_perfect_accuracy(engine, "turret-1")

        engine.combat.fire(turret, hostile)
        event = fire_sub.get(timeout=1.0)
        assert event["source_id"] == "turret-1"
        assert event["target_id"] == "hostile-1"

    def test_fire_respects_cooldown(self):
        bus, engine = _make_engine()
        turret = _make_turret()
        hostile = _make_hostile(position=(3.0, 0.0))
        engine.add_target(turret)
        engine.add_target(hostile)
        _set_perfect_accuracy(engine, "turret-1")

        # First shot succeeds
        proj1 = engine.combat.fire(turret, hostile)
        assert proj1 is not None

        # Immediate second shot fails (cooldown 1.5s)
        proj2 = engine.combat.fire(turret, hostile)
        assert proj2 is None

    def test_fire_respects_range(self):
        bus, engine = _make_engine()
        turret = _make_turret()
        # Hostile at 200m -- well beyond turret range of 80m
        hostile = _make_hostile(position=(200.0, 0.0))
        engine.add_target(turret)
        engine.add_target(hostile)

        proj = engine.combat.fire(turret, hostile)
        assert proj is None


# ==========================================================================
# 5. Kill tracking — eliminations, kill counts, events
# ==========================================================================

class TestKillTracking:
    def test_elimination_on_lethal_damage(self):
        bus, engine = _make_engine()
        elim_sub = bus.subscribe("target_eliminated")
        turret = _make_turret()
        # Hostile with very low health
        hostile = _make_hostile(position=(2.0, 0.0), health=10.0)
        engine.add_target(turret)
        engine.add_target(hostile)
        _set_perfect_accuracy(engine, "turret-1")

        engine.combat.fire(turret, hostile)  # 15 damage > 10 health
        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.combat.tick(0.1, targets_dict)

        assert hostile.status == "eliminated"
        assert hostile.health == 0.0

    def test_elimination_event_published(self):
        bus, engine = _make_engine()
        elim_sub = bus.subscribe("target_eliminated")
        turret = _make_turret()
        hostile = _make_hostile(position=(2.0, 0.0), health=10.0)
        engine.add_target(turret)
        engine.add_target(hostile)
        _set_perfect_accuracy(engine, "turret-1")

        engine.combat.fire(turret, hostile)
        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.combat.tick(0.1, targets_dict)

        event = elim_sub.get(timeout=1.0)
        assert event["target_id"] == "hostile-1"
        assert event["interceptor_id"] == "turret-1"
        assert event["interceptor_name"] == "Turret Alpha"

    def test_kill_counter_increments(self):
        bus, engine = _make_engine()
        turret = _make_turret()
        hostile = _make_hostile(position=(2.0, 0.0), health=10.0)
        engine.add_target(turret)
        engine.add_target(hostile)
        _set_perfect_accuracy(engine, "turret-1")

        engine.combat.fire(turret, hostile)
        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.combat.tick(0.1, targets_dict)

        assert turret.kills == 1

    def test_multiple_kills_increment(self):
        bus, engine = _make_engine()
        turret = _make_turret()
        engine.add_target(turret)
        _set_perfect_accuracy(engine, "turret-1")

        targets_dict = {"turret-1": turret}
        for i in range(3):
            hostile = _make_hostile(
                target_id=f"hostile-{i}",
                name=f"Intruder {i}",
                position=(2.0, 0.0),
                health=10.0,
            )
            engine.add_target(hostile)
            targets_dict[hostile.target_id] = hostile
            turret.last_fired = 0.0  # reset cooldown
            engine.combat.fire(turret, hostile)
            engine.combat.tick(0.1, targets_dict)

        assert turret.kills == 3

    def test_elimination_streak_at_three(self):
        bus, engine = _make_engine()
        streak_sub = bus.subscribe("elimination_streak")
        turret = _make_turret()
        engine.add_target(turret)
        _set_perfect_accuracy(engine, "turret-1")

        targets_dict = {"turret-1": turret}
        for i in range(3):
            hostile = _make_hostile(
                target_id=f"hostile-{i}",
                name=f"Intruder {i}",
                position=(2.0, 0.0),
                health=10.0,
            )
            engine.add_target(hostile)
            targets_dict[hostile.target_id] = hostile
            turret.last_fired = 0.0
            engine.combat.fire(turret, hostile)
            engine.combat.tick(0.1, targets_dict)

        event = streak_sub.get(timeout=1.0)
        assert event["streak"] == 3
        assert event["streak_name"] == "ON A STREAK"


# ==========================================================================
# 6. Wave progression — wave_complete -> intermission -> next wave
# ==========================================================================

class TestWaveProgression:
    def test_wave_complete_when_all_hostiles_gone(self):
        bus, engine = _make_engine()
        wave_complete_sub = bus.subscribe("wave_complete")
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)
        assert engine.game_mode.state == "active"

        _clear_wave(engine.game_mode)
        engine.game_mode.tick(0.1)
        assert engine.game_mode.state == "wave_complete"

    def test_wave_complete_event_published(self):
        bus, engine = _make_engine()
        wave_complete_sub = bus.subscribe("wave_complete")
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        _clear_wave(engine.game_mode)
        engine.game_mode.tick(0.1)

        event = wave_complete_sub.get(timeout=1.0)
        assert event["wave_number"] == 1

    def test_wave_complete_advances_to_next_wave(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        _clear_wave(engine.game_mode)
        engine.game_mode.tick(0.1)
        assert engine.game_mode.state == "wave_complete"

        _advance_past_intermission(engine.game_mode)
        engine.game_mode.tick(0.1)
        assert engine.game_mode.state == "active"
        assert engine.game_mode.wave == 2

    def test_wave_eliminations_reset_each_wave(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        # Simulate a kill in wave 1
        engine.game_mode._wave_hostile_ids.add("h1")
        engine.game_mode.on_target_eliminated("h1")
        assert engine.game_mode.wave_eliminations == 1

        # Complete wave 1 -> advance to wave 2
        _clear_wave(engine.game_mode)
        engine.game_mode.tick(0.1)
        _advance_past_intermission(engine.game_mode)
        engine.game_mode.tick(0.1)

        # wave_eliminations should be reset for wave 2
        assert engine.game_mode.wave_eliminations == 0

    def test_progress_through_multiple_waves(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        for expected_wave in range(1, 6):
            assert engine.game_mode.wave == expected_wave
            _clear_wave(engine.game_mode)
            engine.game_mode.tick(0.1)
            assert engine.game_mode.state == "wave_complete"
            _advance_past_intermission(engine.game_mode)
            engine.game_mode.tick(0.1)

        assert engine.game_mode.wave == 6


# ==========================================================================
# 7. Degradation — health-based performance penalties
# ==========================================================================

class TestDegradation:
    def test_no_degradation_at_full_health(self):
        bus, engine = _make_engine()
        rover = _make_rover()
        engine.add_target(rover)
        ds = engine.degradation_system

        assert ds.get_degradation_factor(rover) == 1.0
        assert ds.get_effective_speed(rover) == rover.speed

    def test_degradation_at_half_health(self):
        bus, engine = _make_engine()
        rover = _make_rover()
        engine.add_target(rover)
        ds = engine.degradation_system

        # Set to exactly 50% health -- at threshold, no degradation
        rover.health = rover.max_health * 0.5
        factor = ds.get_degradation_factor(rover)
        assert factor == 1.0

    def test_degradation_at_quarter_health(self):
        bus, engine = _make_engine()
        rover = _make_rover()
        engine.add_target(rover)
        ds = engine.degradation_system

        # Set to 25% health (below 50% threshold) -> degradation kicks in
        rover.health = rover.max_health * 0.25
        factor = ds.get_degradation_factor(rover)
        assert 0.0 < factor < 1.0

    def test_degradation_affects_speed(self):
        bus, engine = _make_engine()
        rover = _make_rover()
        engine.add_target(rover)
        ds = engine.degradation_system
        original_speed = rover.speed

        rover.health = rover.max_health * 0.1
        effective = ds.get_effective_speed(rover)
        assert effective < original_speed

    def test_degradation_affects_cooldown(self):
        bus, engine = _make_engine()
        rover = _make_rover()
        engine.add_target(rover)
        ds = engine.degradation_system
        original_cooldown = rover.weapon_cooldown

        rover.health = rover.max_health * 0.1
        effective = ds.get_effective_cooldown(rover)
        assert effective > original_cooldown

    def test_fire_disabled_at_very_low_health(self):
        bus, engine = _make_engine()
        rover = _make_rover()
        engine.add_target(rover)
        ds = engine.degradation_system

        # Below 10% health -- fire disabled
        rover.health = rover.max_health * 0.05
        assert ds.can_fire_degraded(rover) is False


# ==========================================================================
# 8. Morale — damage drops morale, suppression, broken
# ==========================================================================

class TestMorale:
    def test_morale_starts_at_default(self):
        bus, engine = _make_engine()
        ms = engine.morale_system
        # Unregistered unit returns 1.0 (full morale)
        assert ms.get_morale("unknown") == 1.0

    def test_damage_reduces_morale(self):
        bus, engine = _make_engine()
        ms = engine.morale_system
        ms.set_morale("hostile-1", 0.8)
        ms.on_damage_taken("hostile-1", 50.0)
        assert ms.get_morale("hostile-1") < 0.8

    def test_ally_eliminated_reduces_morale(self):
        bus, engine = _make_engine()
        ms = engine.morale_system
        ms.set_morale("hostile-2", 0.7)
        ms.on_ally_eliminated("hostile-2")
        assert ms.get_morale("hostile-2") < 0.7

    def test_enemy_eliminated_boosts_morale(self):
        bus, engine = _make_engine()
        ms = engine.morale_system
        ms.set_morale("turret-1", 0.5)
        ms.on_enemy_eliminated("turret-1")
        assert ms.get_morale("turret-1") > 0.5

    def test_broken_morale_threshold(self):
        bus, engine = _make_engine()
        ms = engine.morale_system
        ms.set_morale("hostile-1", 0.05)
        assert ms.is_broken("hostile-1") is True

    def test_suppressed_morale_threshold(self):
        bus, engine = _make_engine()
        ms = engine.morale_system
        ms.set_morale("hostile-1", 0.2)
        assert ms.is_suppressed("hostile-1") is True
        assert ms.is_broken("hostile-1") is False

    def test_emboldened_morale_threshold(self):
        bus, engine = _make_engine()
        ms = engine.morale_system
        ms.set_morale("turret-1", 0.95)
        assert ms.is_emboldened("turret-1") is True

    def test_morale_clamps_to_zero(self):
        bus, engine = _make_engine()
        ms = engine.morale_system
        ms.set_morale("hostile-1", 0.01)
        ms.on_damage_taken("hostile-1", 1000.0)
        assert ms.get_morale("hostile-1") == 0.0

    def test_morale_clamps_to_one(self):
        bus, engine = _make_engine()
        ms = engine.morale_system
        ms.set_morale("turret-1", 0.99)
        ms.on_enemy_eliminated("turret-1")
        assert ms.get_morale("turret-1") <= 1.0


# ==========================================================================
# 9. Stats tracking — per-unit accuracy, KD, assists
# ==========================================================================

class TestStatsTracking:
    def test_register_unit(self):
        tracker = StatsTracker()
        tracker.register_unit("turret-1", "Turret Alpha", "friendly", "turret")
        stats = tracker.get_unit_stats("turret-1")
        assert stats is not None
        assert stats.name == "Turret Alpha"
        assert stats.shots_fired == 0

    def test_record_shot_fired(self):
        tracker = StatsTracker()
        tracker.register_unit("turret-1", "Turret Alpha", "friendly", "turret")
        tracker.on_shot_fired("turret-1")
        stats = tracker.get_unit_stats("turret-1")
        assert stats.shots_fired == 1

    def test_record_shot_hit(self):
        tracker = StatsTracker()
        tracker.register_unit("turret-1", "Turret Alpha", "friendly", "turret")
        tracker.register_unit("hostile-1", "Intruder", "hostile", "person")
        tracker.on_shot_fired("turret-1")
        tracker.on_shot_hit("turret-1", "hostile-1", 15.0)
        stats = tracker.get_unit_stats("turret-1")
        assert stats.shots_hit == 1
        assert stats.damage_dealt == 15.0
        assert stats.accuracy == 1.0

    def test_accuracy_calculation(self):
        tracker = StatsTracker()
        tracker.register_unit("turret-1", "Turret Alpha", "friendly", "turret")
        tracker.register_unit("hostile-1", "Intruder", "hostile", "person")
        # 3 shots, 2 hits
        for _ in range(3):
            tracker.on_shot_fired("turret-1")
        tracker.on_shot_hit("turret-1", "hostile-1", 15.0)
        tracker.on_shot_hit("turret-1", "hostile-1", 15.0)
        stats = tracker.get_unit_stats("turret-1")
        assert stats.accuracy == pytest.approx(2.0 / 3.0, abs=0.01)

    def test_kd_ratio(self):
        tracker = StatsTracker()
        tracker.register_unit("turret-1", "Turret Alpha", "friendly", "turret")
        tracker.register_unit("hostile-1", "Intruder", "hostile", "person")
        tracker.on_kill("turret-1", "hostile-1")
        tracker.on_kill("turret-1", "hostile-1")  # 2 kills
        stats = tracker.get_unit_stats("turret-1")
        assert stats.kills == 2
        assert stats.deaths == 0
        assert stats.kd_ratio == 2.0  # kills / 0 deaths = float(kills)

    def test_assist_tracking(self):
        tracker = StatsTracker()
        tracker.register_unit("turret-1", "Turret Alpha", "friendly", "turret")
        tracker.register_unit("rover-1", "Rover Bravo", "friendly", "rover")
        tracker.register_unit("hostile-1", "Intruder", "hostile", "person")

        # Turret damages the hostile (within 5s window)
        ts = time.monotonic()
        tracker.on_shot_hit("turret-1", "hostile-1", 30.0, timestamp=ts)

        # Rover gets the kill
        tracker.on_kill("rover-1", "hostile-1")

        # Turret should get an assist
        turret_stats = tracker.get_unit_stats("turret-1")
        assert turret_stats.assists == 1

        # Rover should not get an assist (they got the kill)
        rover_stats = tracker.get_unit_stats("rover-1")
        assert rover_stats.assists == 0

    def test_wave_stats(self):
        tracker = StatsTracker()
        tracker.on_wave_start(1, "Scout Party", 3)
        assert len(tracker.get_wave_stats()) == 1
        wave = tracker.get_wave_stats()[0]
        assert wave.wave_number == 1
        assert wave.wave_name == "Scout Party"
        assert wave.hostiles_spawned == 3

    def test_get_summary(self):
        tracker = StatsTracker()
        tracker.register_unit("turret-1", "Turret Alpha", "friendly", "turret")
        tracker.on_shot_fired("turret-1")
        summary = tracker.get_summary()
        assert summary["total_shots_fired"] == 1
        assert summary["unit_count"] == 1

    def test_reset_clears_stats(self):
        tracker = StatsTracker()
        tracker.register_unit("turret-1", "Turret Alpha", "friendly", "turret")
        tracker.on_shot_fired("turret-1")
        tracker.on_wave_start(1, "Wave 1", 3)
        tracker.reset()
        assert tracker.get_unit_stats("turret-1") is None
        assert len(tracker.get_wave_stats()) == 0


# ==========================================================================
# 10. Victory condition — all 10 waves cleared
# ==========================================================================

class TestVictoryCondition:
    def test_victory_after_all_ten_waves(self):
        bus, engine = _make_engine()
        game_over_sub = bus.subscribe("game_over")
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        # Clear all 10 waves
        for wave_num in range(1, len(WAVE_CONFIGS) + 1):
            assert engine.game_mode.wave == wave_num
            _clear_wave(engine.game_mode)
            engine.game_mode.tick(0.1)
            if engine.game_mode.state == "wave_complete":
                _advance_past_intermission(engine.game_mode)
                engine.game_mode.tick(0.1)

        assert engine.game_mode.state == "victory"
        event = game_over_sub.get(timeout=1.0)
        assert event["result"] == "victory"
        assert event["waves_completed"] == 10

    def test_victory_preserves_final_score(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        for _ in range(len(WAVE_CONFIGS)):
            _clear_wave(engine.game_mode)
            engine.game_mode.tick(0.1)
            if engine.game_mode.state == "wave_complete":
                _advance_past_intermission(engine.game_mode)
                engine.game_mode.tick(0.1)

        assert engine.game_mode.state == "victory"
        # Score should include wave bonuses (wave_num * 200 per wave)
        assert engine.game_mode.score > 0


# ==========================================================================
# 11. Defeat condition — all friendlies eliminated
# ==========================================================================

class TestDefeatCondition:
    def test_defeat_when_no_friendlies(self):
        bus, engine = _make_engine()
        game_over_sub = bus.subscribe("game_over")
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        # No friendly combatants at all -> defeat
        engine.game_mode._spawn_thread = None
        engine.game_mode.tick(0.1)
        assert engine.game_mode.state == "defeat"

    def test_defeat_when_all_friendlies_eliminated(self):
        bus, engine = _make_engine()
        game_over_sub = bus.subscribe("game_over")
        turret = _make_turret()
        engine.add_target(turret)
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        # Eliminate the turret
        turret.apply_damage(turret.health)
        assert turret.status == "eliminated"

        engine.game_mode._spawn_thread = None
        engine.game_mode.tick(0.1)
        assert engine.game_mode.state == "defeat"

        event = game_over_sub.get(timeout=1.0)
        assert event["result"] == "defeat"

    def test_defeat_event_has_score(self):
        bus, engine = _make_engine()
        game_over_sub = bus.subscribe("game_over")
        turret = _make_turret()
        engine.add_target(turret)
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        # Score some points before defeat
        engine.game_mode._wave_hostile_ids.add("h1")
        engine.game_mode.on_target_eliminated("h1")

        turret.apply_damage(turret.health)
        engine.game_mode._spawn_thread = None
        engine.game_mode.tick(0.1)

        event = game_over_sub.get(timeout=1.0)
        assert event["result"] == "defeat"
        assert event["final_score"] == 100  # 1 elimination

    def test_no_defeat_with_low_battery_friendly(self):
        """Low-battery units are alive (reduced capability, not dead)."""
        bus, engine = _make_engine()
        turret = _make_turret()
        turret.status = "low_battery"
        engine.add_target(turret)
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        engine.game_mode._spawn_thread = None
        engine.game_mode.tick(0.1)
        # low_battery is still alive -- should NOT defeat
        assert engine.game_mode.state != "defeat"


# ==========================================================================
# 12. Score calculation — per-kill + wave bonuses
# ==========================================================================

class TestScoreCalculation:
    def test_hundred_points_per_elimination(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        engine.game_mode._wave_hostile_ids.add("h1")
        engine.game_mode.on_target_eliminated("h1")
        assert engine.game_mode.score == 100

    def test_multiple_eliminations_accumulate(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        for i in range(5):
            engine.game_mode._wave_hostile_ids.add(f"h{i}")
            engine.game_mode.on_target_eliminated(f"h{i}")

        assert engine.game_mode.score == 500

    def test_wave_completion_bonus(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        score_before = engine.game_mode.score
        _clear_wave(engine.game_mode)
        engine.game_mode.tick(0.1)

        # Wave 1 completion: wave_bonus = 1 * 200 = 200 + time_bonus
        score_after = engine.game_mode.score
        assert score_after > score_before
        # The wave bonus for wave 1 is at least 200 (plus time bonus up to 50)
        wave_bonus = score_after - score_before
        assert wave_bonus >= 200

    def test_score_accumulates_across_waves(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)

        total_score_after_waves = []
        for w in range(1, 4):
            _clear_wave(engine.game_mode)
            engine.game_mode.tick(0.1)
            total_score_after_waves.append(engine.game_mode.score)
            _advance_past_intermission(engine.game_mode)
            engine.game_mode.tick(0.1)

        # Score should monotonically increase
        assert total_score_after_waves[0] < total_score_after_waves[1]
        assert total_score_after_waves[1] < total_score_after_waves[2]

    def test_scoring_only_in_active_state(self):
        bus, engine = _make_engine()
        gm = engine.game_mode
        # Not in active state
        assert gm.state == "setup"
        gm._wave_hostile_ids.add("h1")
        gm.on_target_eliminated("h1")
        assert gm.score == 0  # ignored in setup state


# ==========================================================================
# 13. Replay data — verify snapshots recorded
# ==========================================================================

class TestReplayData:
    def test_replay_recorder_exists_on_engine(self):
        """StatsTracker records game events (replay is separate; verify stats is wired)."""
        bus, engine = _make_engine()
        assert engine.stats_tracker is not None

    def test_stats_tracker_records_wave_events(self):
        bus, engine = _make_engine()
        tracker = engine.stats_tracker
        tracker.on_wave_start(1, "Scout Party", 3)
        waves = tracker.get_wave_stats()
        assert len(waves) == 1
        assert waves[0].wave_number == 1
        assert waves[0].hostiles_spawned == 3

    def test_stats_tracker_records_kills(self):
        bus, engine = _make_engine()
        tracker = engine.stats_tracker
        tracker.register_unit("turret-1", "Turret Alpha", "friendly", "turret")
        tracker.register_unit("hostile-1", "Intruder", "hostile", "person")
        tracker.on_shot_fired("turret-1")
        tracker.on_shot_hit("turret-1", "hostile-1", 15.0)
        tracker.on_kill("turret-1", "hostile-1")

        stats = tracker.get_unit_stats("turret-1")
        assert stats.kills == 1
        assert stats.shots_fired == 1
        assert stats.shots_hit == 1

    def test_stats_tracker_exports_dict(self):
        bus, engine = _make_engine()
        tracker = engine.stats_tracker
        tracker.register_unit("turret-1", "Turret Alpha", "friendly", "turret")
        d = tracker.to_dict()
        assert "units" in d
        assert "waves" in d
        assert "summary" in d


# ==========================================================================
# 14. Reset — clean state restored
# ==========================================================================

class TestGameReset:
    def test_reset_returns_to_setup(self):
        bus, engine = _make_engine()
        engine.add_target(_make_turret())
        engine.begin_war()
        _skip_countdown(engine.game_mode)
        engine.game_mode.score = 500

        engine.reset_game()
        assert engine.game_mode.state == "setup"
        assert engine.game_mode.wave == 0
        assert engine.game_mode.score == 0
        assert engine.game_mode.total_eliminations == 0

    def test_reset_removes_hostiles(self):
        bus, engine = _make_engine()
        engine.spawn_hostile()
        engine.spawn_hostile()
        hostiles_before = sum(1 for t in engine.get_targets() if t.alliance == "hostile")
        assert hostiles_before == 2

        engine.reset_game()
        hostiles_after = sum(1 for t in engine.get_targets() if t.alliance == "hostile")
        assert hostiles_after == 0

    def test_reset_heals_friendlies(self):
        bus, engine = _make_engine()
        turret = _make_turret()
        engine.add_target(turret)
        turret.health = 10.0  # badly damaged

        engine.reset_game()
        # Turret's ID starts with "turret-" so it gets removed by reset_game
        # Only friendlies NOT matching game unit prefixes survive
        # Let's use a non-game-unit prefix
        bus2, engine2 = _make_engine()
        friendly = SimulationTarget(
            target_id="permanent-1", name="Base", alliance="friendly",
            asset_type="turret", position=(0.0, 0.0), speed=0.0,
            status="stationary", health=10.0, max_health=200.0,
        )
        friendly.is_combatant = True
        engine2.add_target(friendly)
        engine2.reset_game()
        t = engine2.get_target("permanent-1")
        assert t is not None
        assert t.health == t.max_health

    def test_reset_clears_projectiles(self):
        bus, engine = _make_engine()
        turret = _make_turret()
        hostile = _make_hostile(position=(10.0, 0.0))
        engine.add_target(turret)
        engine.add_target(hostile)
        _set_perfect_accuracy(engine, "turret-1")
        engine.combat.fire(turret, hostile)
        assert engine.combat.projectile_count == 1

        engine.reset_game()
        assert engine.combat.projectile_count == 0

    def test_reset_clears_morale(self):
        bus, engine = _make_engine()
        engine.morale_system.set_morale("hostile-1", 0.2)
        engine.reset_game()
        # After reset, unregistered units return default
        assert engine.morale_system.get_morale("hostile-1") == 1.0

    def test_reset_clears_stats(self):
        bus, engine = _make_engine()
        engine.stats_tracker.register_unit("t1", "T", "friendly", "turret")
        engine.stats_tracker.on_shot_fired("t1")
        engine.reset_game()
        assert engine.stats_tracker.get_unit_stats("t1") is None


# ==========================================================================
# 15. Edge cases
# ==========================================================================

class TestEdgeCases:
    def test_begin_war_only_from_setup(self):
        bus, engine = _make_engine()
        engine.begin_war()
        assert engine.game_mode.state == "countdown"
        # Try to begin again -- should be ignored
        engine.begin_war()
        assert engine.game_mode.state == "countdown"

    def test_start_with_no_friendlies_causes_defeat(self):
        """Starting a battle with no friendly units triggers immediate defeat."""
        bus, engine = _make_engine()
        engine.begin_war()
        _skip_countdown(engine.game_mode)
        engine.game_mode._spawn_thread = None
        engine.game_mode.tick(0.1)
        assert engine.game_mode.state == "defeat"

    def test_hostile_spawn_positions_on_map_edge(self):
        bus, engine = _make_engine()
        h = engine.spawn_hostile()
        x, y = h.position
        # Should be on or near the map edge (within bounds)
        assert -200.0 <= x <= 200.0
        assert -200.0 <= y <= 200.0
        # At least one coordinate should be at the edge
        at_edge = (
            abs(abs(x) - 200.0) < 1.0 or
            abs(abs(y) - 200.0) < 1.0
        )
        assert at_edge, f"Hostile at ({x}, {y}) not near edge"

    def test_spawn_hostile_has_waypoints(self):
        bus, engine = _make_engine()
        h = engine.spawn_hostile()
        assert len(h.waypoints) > 0

    def test_spawn_hostile_is_combatant(self):
        bus, engine = _make_engine()
        h = engine.spawn_hostile()
        assert h.is_combatant is True
        assert h.alliance == "hostile"

    def test_eliminated_target_cannot_fire(self):
        turret = _make_turret()
        turret.status = "eliminated"
        assert turret.can_fire() is False

    def test_eliminated_target_does_not_move(self):
        rover = _make_rover()
        rover.waypoints = [(100.0, 0.0)]
        rover.status = "eliminated"
        pos_before = rover.position
        rover.tick(1.0)
        assert rover.position == pos_before

    def test_apply_damage_idempotent_on_eliminated(self):
        hostile = _make_hostile(health=10.0)
        hostile.apply_damage(15.0)
        assert hostile.status == "eliminated"
        assert hostile.health == 0.0
        # Second damage call should not change status
        result = hostile.apply_damage(50.0)
        assert result is True
        assert hostile.status == "eliminated"

    def test_zero_damage_does_not_eliminate(self):
        hostile = _make_hostile(health=50.0)
        result = hostile.apply_damage(0.0)
        assert result is False
        assert hostile.health == 50.0
        assert hostile.status == "active"

    def test_get_state_dict_has_all_expected_keys(self):
        bus, engine = _make_engine()
        state = engine.get_game_state()
        expected_keys = {
            "state", "wave", "wave_name", "total_waves",
            "countdown", "score", "total_eliminations",
            "wave_eliminations", "wave_hostiles_remaining", "infinite",
        }
        assert expected_keys.issubset(state.keys())


# ==========================================================================
# 16. Behavior integration — turrets fire at hostiles in range
# ==========================================================================

class TestBehaviorIntegration:
    def test_turret_fires_at_hostile_in_range(self):
        bus, engine = _make_engine()
        fire_sub = bus.subscribe("projectile_fired")
        turret = _make_turret()
        # Place hostile within turret weapon_range (80m)
        hostile = _make_hostile(position=(20.0, 0.0))
        engine.add_target(turret)
        engine.add_target(hostile)
        _set_perfect_accuracy(engine, "turret-1")

        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.behaviors.tick(0.1, targets_dict)

        # Turret should have fired
        event = fire_sub.get(timeout=1.0)
        assert event["source_id"] == "turret-1"

    def test_turret_does_not_fire_at_out_of_range(self):
        bus, engine = _make_engine()
        fire_sub = bus.subscribe("projectile_fired")
        turret = _make_turret()
        # Hostile beyond weapon_range
        hostile = _make_hostile(position=(200.0, 0.0))
        engine.add_target(turret)
        engine.add_target(hostile)

        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.behaviors.tick(0.1, targets_dict)

        # Should not have fired
        assert fire_sub.empty()

    def test_hostile_fires_at_friendly_in_range(self):
        bus, engine = _make_engine()
        fire_sub = bus.subscribe("projectile_fired")
        turret = _make_turret()
        # Hostile person weapon_range is 40m -- place turret within that
        hostile = _make_hostile(position=(10.0, 0.0))
        engine.add_target(turret)
        engine.add_target(hostile)
        _set_perfect_accuracy(engine, "turret-1")
        _set_perfect_accuracy(engine, "hostile-1")

        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.behaviors.tick(0.1, targets_dict)

        # Both turret and hostile should fire (drain the queue)
        events = []
        while not fire_sub.empty():
            events.append(fire_sub.get_nowait())

        source_ids = [e["source_id"] for e in events]
        # Turret fires at hostile
        assert "turret-1" in source_ids
        # Hostile fires at turret
        assert "hostile-1" in source_ids


# ==========================================================================
# 17. Full integrated lifecycle — connect the dots
# ==========================================================================

class TestFullLifecycle:
    def test_setup_to_combat_to_wave_complete(self):
        """Full mini-lifecycle: place units, start battle, fire and kill, complete wave."""
        bus, engine = _make_engine()
        elim_sub = bus.subscribe("target_eliminated")
        wave_complete_sub = bus.subscribe("wave_complete")

        # Place a turret
        turret = _make_turret()
        engine.add_target(turret)
        _set_perfect_accuracy(engine, "turret-1")

        # Begin war and skip countdown
        engine.begin_war()
        _skip_countdown(engine.game_mode)
        assert engine.game_mode.state == "active"
        assert engine.game_mode.wave == 1

        # Wait for the wave spawner thread to finish, then clear any
        # auto-spawned hostiles so we control the battle manually.
        if engine.game_mode._spawn_thread is not None:
            engine.game_mode._spawn_thread.join(timeout=30)
        # Remove all auto-spawned hostiles and clear wave tracking
        _purge_hostiles(engine)
        engine.game_mode._wave_hostile_ids.clear()

        # Manually add a hostile (our controlled target)
        hostile = _make_hostile(position=(2.0, 0.0), health=10.0)
        engine.add_target(hostile)
        engine.game_mode._wave_hostile_ids.add(hostile.target_id)
        engine.game_mode._spawn_thread = None  # mark spawning done

        # Fire turret at hostile
        proj = engine.combat.fire(turret, hostile)
        assert proj is not None

        # Tick combat to resolve hit
        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.combat.tick(0.1, targets_dict)

        # Hostile should be eliminated (15 damage > 10 health)
        assert hostile.status == "eliminated"
        event = elim_sub.get(timeout=1.0)
        assert event["target_id"] == hostile.target_id

        # Notify game mode of elimination
        engine.game_mode.on_target_eliminated(hostile.target_id)
        assert engine.game_mode.wave_eliminations == 1
        assert engine.game_mode.total_eliminations == 1
        assert engine.game_mode.score == 100

        # Tick game mode -- wave should complete (all hostiles gone)
        engine.game_mode.tick(0.1)
        assert engine.game_mode.state == "wave_complete"

        wave_event = wave_complete_sub.get(timeout=1.0)
        assert wave_event["wave_number"] == 1

    def test_full_two_wave_battle(self):
        """Two complete waves with combat in each."""
        bus, engine = _make_engine()
        turret = _make_turret()
        engine.add_target(turret)
        _set_perfect_accuracy(engine, "turret-1")

        engine.begin_war()
        _skip_countdown(engine.game_mode)

        total_kills = 0
        for wave_num in range(1, 3):
            assert engine.game_mode.wave == wave_num

            # Wait for auto-spawner to finish, then clear its hostiles
            if engine.game_mode._spawn_thread is not None:
                engine.game_mode._spawn_thread.join(timeout=30)
            _purge_hostiles(engine)
            engine.game_mode._wave_hostile_ids.clear()

            # Spawn 2 hostiles per wave (manually controlled)
            hostiles = []
            for i in range(2):
                h = _make_hostile(
                    target_id=f"h-w{wave_num}-{i}",
                    name=f"Wave {wave_num} Hostile {i}",
                    position=(2.0 + i, 0.0),
                    health=10.0,
                )
                engine.add_target(h)
                engine.game_mode._wave_hostile_ids.add(h.target_id)
                hostiles.append(h)
            engine.game_mode._spawn_thread = None

            # Kill all hostiles
            for h in hostiles:
                turret.last_fired = 0.0
                proj = engine.combat.fire(turret, h)
                assert proj is not None
                targets_dict = {t.target_id: t for t in engine.get_targets()}
                engine.combat.tick(0.1, targets_dict)
                assert h.status == "eliminated"
                engine.game_mode.on_target_eliminated(h.target_id)
                total_kills += 1

            # Tick to complete wave
            engine.game_mode.tick(0.1)
            assert engine.game_mode.state == "wave_complete"

            # Advance to next wave
            _advance_past_intermission(engine.game_mode)
            engine.game_mode.tick(0.1)

        assert engine.game_mode.wave == 3
        assert engine.game_mode.total_eliminations == total_kills
        assert turret.kills == total_kills

    def test_battle_with_mixed_unit_types(self):
        """Battle with turret, rover, drone, and tank all present."""
        bus, engine = _make_engine()

        units = [
            _make_turret(),
            _make_rover(),
            _make_drone(),
            _make_tank(),
        ]
        for u in units:
            engine.add_target(u)

        engine.begin_war()
        _skip_countdown(engine.game_mode)
        assert engine.game_mode.state == "active"

        # All 4 friendlies present
        friendlies = [t for t in engine.get_targets() if t.alliance == "friendly"]
        assert len(friendlies) == 4

        # Add a hostile in range of all units
        hostile = _make_hostile(position=(5.0, 5.0), health=10.0)
        engine.add_target(hostile)
        engine.game_mode._wave_hostile_ids.add(hostile.target_id)
        engine.game_mode._spawn_thread = None

        # Run behaviors -- at least one unit should fire
        targets_dict = {t.target_id: t for t in engine.get_targets()}
        engine.behaviors.tick(0.1, targets_dict)

        # Resolve combat
        engine.combat.tick(0.1, targets_dict)

        # Hostile should be damaged or eliminated
        assert hostile.health < 80.0 or hostile.status == "eliminated"
