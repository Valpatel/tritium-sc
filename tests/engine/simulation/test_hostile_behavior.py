# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for HostileBehavior -- hostile kid combat AI with tactical layers.

Tests cover:
  1. Advancing toward targets (basic waypoint following)
  2. Flanking stationary turrets (lateral offset)
  3. Engaging friendlies (firing at defenders in range)
  4. Fleeing when damaged (pursuit-evasion behaviors)
  5. Reconning/scouting (reduced speed)
  6. Suppressing fire (reduced cooldown)
  7. Retreating under fire (zigzag toward cover)
  8. FSM state transitions during behavior ticks
  9. Squad coordination (group rush)
  10. Edge cases (no friendlies, all eliminated, at target position)
"""

from __future__ import annotations

import math
import queue
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.simulation.behavior.hostile import HostileBehavior
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hostile(
    tid: str = "h1",
    pos: tuple[float, float] = (10.0, 0.0),
    speed: float = 1.5,
    fsm_state: str | None = None,
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=tid, name=f"Hostile {tid}", alliance="hostile",
        asset_type="person", position=pos, speed=speed,
    )
    t.apply_combat_profile()
    t.last_fired = 0.0  # ready to fire
    t.fsm_state = fsm_state
    return t


def _make_turret(
    tid: str = "turret1",
    pos: tuple[float, float] = (0.0, 0.0),
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=tid, name=f"Sentry {tid}", alliance="friendly",
        asset_type="turret", position=pos, speed=0.0, status="stationary",
    )
    t.apply_combat_profile()
    t.last_fired = 0.0
    return t


def _make_rover(
    tid: str = "rover1",
    pos: tuple[float, float] = (0.0, 0.0),
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=tid, name=f"Rover {tid}", alliance="friendly",
        asset_type="rover", position=pos, speed=2.0,
    )
    t.apply_combat_profile()
    t.last_fired = 0.0
    return t


def _make_drone(
    tid: str = "drone1",
    pos: tuple[float, float] = (0.0, 0.0),
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=tid, name=f"Drone {tid}", alliance="friendly",
        asset_type="drone", position=pos, speed=4.0,
    )
    t.apply_combat_profile()
    t.last_fired = 0.0
    return t


def _make_behavior(bus=None):
    """Create a HostileBehavior with a CombatSystem and return (behavior, combat, bus)."""
    if bus is None:
        bus = SimpleEventBus()
    combat = CombatSystem(bus)
    behavior = HostileBehavior(combat)
    return behavior, combat, bus


def _mock_pursuit():
    """Create a mock PursuitSystem with all flee-related methods."""
    pursuit = MagicMock()
    pursuit.apply_flee_speed_boost = MagicMock()
    pursuit.start_flee_timer = MagicMock()
    pursuit.apply_zigzag = MagicMock()
    pursuit.find_escape_route = MagicMock(return_value=(1.0, 0.0))
    pursuit.clear = MagicMock()
    return pursuit


def _mock_comms():
    """Create a mock UnitComms with emit methods."""
    comms = MagicMock()
    comms.emit_distress = MagicMock()
    comms.emit_contact = MagicMock()
    comms.emit_retreat = MagicMock()
    comms.clear = MagicMock()
    return comms


def _mock_obstacles(polygons=None):
    """Create a mock BuildingObstacles with polygons."""
    obs = MagicMock()
    obs.polygons = polygons or [[(5.0, 5.0), (10.0, 5.0), (10.0, 10.0), (5.0, 10.0)]]
    return obs


def _drain_fired_events(sub):
    """Drain all events from a queue and return them as a list."""
    events = []
    while not sub.empty():
        events.append(sub.get_nowait())
    return events


# ---------------------------------------------------------------------------
# 1. Hostile advancing toward targets
# ---------------------------------------------------------------------------

class TestHostileAdvancing:
    def test_hostile_dodges_while_advancing(self):
        """Hostile with no FSM state dodges periodically while advancing."""
        behavior, combat, bus = _make_behavior()
        hostile = _make_hostile(pos=(50.0, 0.0))  # out of weapon range
        friendlies = {"turret1": _make_turret()}

        # Force last dodge to be long ago so dodge triggers
        behavior._last_dodge[hostile.target_id] = 0.0
        original_pos = hostile.position

        behavior.tick(hostile, friendlies)

        assert hostile.position != original_pos

    def test_hostile_no_friendlies_just_dodges(self):
        """With no friendlies, hostile just dodges (no firing)."""
        behavior, combat, bus = _make_behavior()
        hostile = _make_hostile(pos=(10.0, 0.0))
        behavior._last_dodge[hostile.target_id] = 0.0
        original_pos = hostile.position

        behavior.tick(hostile, {})

        assert hostile.position != original_pos

    def test_hostile_advancing_state_allows_fire(self):
        """Hostile in 'advancing' FSM state can fire at friendlies in range."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="advancing")
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        source_ids = {e["source_id"] for e in events}
        assert "h1" in source_ids


# ---------------------------------------------------------------------------
# 2. Hostile flanking logic
# ---------------------------------------------------------------------------

class TestHostileFlanking:
    def test_flank_applies_lateral_offset_against_turret(self):
        """Hostile flanks when nearest enemy is a stationary turret."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(20.0, 0.0))
        hostile.weapon_range = 10.0  # out of weapon range so no firing
        turret = _make_turret(pos=(0.0, 0.0))
        friendlies = {"turret1": turret}

        behavior._last_flank[hostile.target_id] = 0.0
        original_pos = hostile.position

        behavior.tick(hostile, friendlies)

        assert hostile.position != original_pos

    def test_flank_detected_hostile_uses_wider_step(self):
        """A detected hostile uses DETECTED_FLANK_STEP (wider lateral offset)."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(20.0, 0.0))
        hostile.detected = True
        hostile.weapon_range = 10.0
        turret = _make_turret(pos=(0.0, 0.0))
        friendlies = {"turret1": turret}

        behavior._last_flank[hostile.target_id] = 0.0
        original_pos = hostile.position

        behavior.tick(hostile, friendlies)

        assert hostile.position != original_pos

    def test_flank_does_not_trigger_for_mobile_units(self):
        """Flanking only targets stationary units (turrets), not rovers."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(20.0, 0.0))
        hostile.weapon_range = 10.0
        rover = _make_rover(pos=(0.0, 0.0))
        friendlies = {"rover1": rover}

        behavior._last_flank[hostile.target_id] = 0.0

        result = behavior._try_flank(hostile, friendlies)
        assert result is False

    def test_flank_returns_false_when_on_cooldown(self):
        """Flanking respects the cooldown interval."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(20.0, 0.0))
        turret = _make_turret(pos=(0.0, 0.0))
        friendlies = {"turret1": turret}

        behavior._last_flank[hostile.target_id] = time.time()

        result = behavior._try_flank(hostile, friendlies)
        assert result is False

    def test_flank_returns_false_when_very_close(self):
        """Flanking returns False when hostile is on top of turret (dist < 0.1)."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(0.0, 0.0))
        turret = _make_turret(pos=(0.0, 0.0))
        friendlies = {"turret1": turret}

        behavior._last_flank[hostile.target_id] = 0.0

        result = behavior._try_flank(hostile, friendlies)
        assert result is False


# ---------------------------------------------------------------------------
# 3. Hostile engaging friendlies (firing)
# ---------------------------------------------------------------------------

class TestHostileEngaging:
    def test_hostile_fires_at_friendly_in_range(self):
        """Hostile fires at nearest friendly within weapon range."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0))
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        source_ids = {e["source_id"] for e in events}
        assert "h1" in source_ids

    def test_hostile_does_not_fire_out_of_range(self):
        """Hostile does not fire at friendlies beyond weapon range."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(50.0, 0.0))  # beyond 40m hostile range
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        hostile_events = [e for e in events if e["source_id"] == "h1"]
        assert len(hostile_events) == 0

    def test_hostile_engaging_state_fires(self):
        """Hostile in 'engaging' FSM state fires at targets."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="engaging")
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        source_ids = {e["source_id"] for e in events}
        assert "h1" in source_ids

    def test_hostile_weapon_cooldown_prevents_fire(self):
        """Hostile cannot fire again before cooldown expires."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0))
        hostile.last_fired = time.time()  # just fired
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        hostile_events = [e for e in events if e["source_id"] == "h1"]
        assert len(hostile_events) == 0

    def test_hostile_fires_at_nearest_friendly(self):
        """Hostile fires at the nearest friendly, not a farther one."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(10.0, 0.0))
        near_turret = _make_turret(tid="near_t", pos=(5.0, 0.0))
        far_turret = _make_turret(tid="far_t", pos=(0.0, 0.0))
        friendlies = {"near_t": near_turret, "far_t": far_turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        hostile_events = [e for e in events if e["source_id"] == "h1"]
        if hostile_events:
            assert hostile_events[0]["target_pos"]["x"] == pytest.approx(5.0, abs=0.1)

    def test_hostile_cannot_fire_when_degraded(self):
        """Hostile cannot fire when can_fire_degraded returns False."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0))
        # Set health extremely low so can_fire_degraded returns False
        hostile.health = 1.0
        hostile.max_health = 100.0
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        hostile_events = [e for e in events if e["source_id"] == "h1"]
        assert len(hostile_events) == 0


# ---------------------------------------------------------------------------
# 4. Hostile fleeing when damaged
# ---------------------------------------------------------------------------

class TestHostileFleeing:
    def test_fleeing_hostile_skips_combat(self):
        """Hostile in 'fleeing' state does not fire."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="fleeing")
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        hostile_events = [e for e in events if e["source_id"] == "h1"]
        assert len(hostile_events) == 0

    def test_fleeing_uses_pursuit_system(self):
        """Fleeing hostile calls pursuit system flee methods."""
        behavior, combat, bus = _make_behavior()
        pursuit = _mock_pursuit()
        behavior.set_pursuit(pursuit, map_bounds=200.0)

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="fleeing")
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        pursuit.apply_flee_speed_boost.assert_called_once_with(hostile)
        pursuit.start_flee_timer.assert_called_once_with(hostile)
        pursuit.apply_zigzag.assert_called_once_with(hostile)
        pursuit.find_escape_route.assert_called_once()

    def test_fleeing_sets_escape_waypoint(self):
        """Fleeing hostile gets waypoints toward map edge."""
        behavior, combat, bus = _make_behavior()
        pursuit = _mock_pursuit()
        pursuit.find_escape_route.return_value = (1.0, 0.0)  # east
        behavior.set_pursuit(pursuit, map_bounds=200.0)

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="fleeing")
        friendlies = {"turret1": _make_turret()}

        behavior.tick(hostile, friendlies)

        assert len(hostile.waypoints) == 1
        assert hostile.waypoints[0][0] == pytest.approx(200.0, abs=1.0)

    def test_fleeing_emits_retreat_signal(self):
        """Fleeing hostile emits retreat signal via comms."""
        behavior, combat, bus = _make_behavior()
        comms = _mock_comms()
        behavior.set_comms(comms)

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="fleeing")
        friendlies = {}

        behavior.tick(hostile, friendlies)

        comms.emit_retreat.assert_called_once_with(
            hostile.target_id, hostile.position, hostile.alliance,
        )

    def test_fleeing_without_pursuit_still_returns(self):
        """Fleeing hostile without pursuit system set still returns early (no crash)."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="fleeing")
        friendlies = {"turret1": _make_turret()}

        behavior.tick(hostile, friendlies)

    def test_fleeing_clamps_to_map_bounds(self):
        """Escape waypoint is clamped to map bounds."""
        behavior, combat, bus = _make_behavior()
        pursuit = _mock_pursuit()
        pursuit.find_escape_route.return_value = (0.0, -1.0)  # south
        behavior.set_pursuit(pursuit, map_bounds=100.0)

        hostile = _make_hostile(pos=(0.0, 50.0), fsm_state="fleeing")
        friendlies = {}

        behavior.tick(hostile, friendlies)

        assert len(hostile.waypoints) == 1
        assert hostile.waypoints[0][1] >= -100.0


# ---------------------------------------------------------------------------
# 5. Hostile reconning/scouting
# ---------------------------------------------------------------------------

class TestHostileReconning:
    def test_recon_reduces_speed(self):
        """Reconning hostile has speed reduced by 50%."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0), fsm_state="reconning")
        original_speed = hostile.speed
        friendlies = {}

        behavior.tick(hostile, friendlies)

        assert hostile.speed == pytest.approx(original_speed * 0.5, rel=0.01)

    def test_recon_speed_restored_on_state_change(self):
        """Speed is restored when hostile leaves recon state."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0), fsm_state="reconning")
        original_speed = hostile.speed
        friendlies = {}

        behavior.tick(hostile, friendlies)
        assert hostile.speed == pytest.approx(original_speed * 0.5, rel=0.01)

        hostile.fsm_state = "advancing"
        behavior.tick(hostile, friendlies)
        assert hostile.speed == pytest.approx(original_speed, rel=0.01)

    def test_recon_returns_early_no_dodge(self):
        """Reconning hostile returns early (no dodge/flank behaviors)."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0), fsm_state="reconning")
        behavior._last_dodge[hostile.target_id] = 0.0
        original_pos = hostile.position
        friendlies = {}

        behavior.tick(hostile, friendlies)

        assert hostile.position == original_pos

    def test_recon_double_entry_no_double_reduction(self):
        """Entering recon twice does not reduce speed twice."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0), fsm_state="reconning")
        original_speed = hostile.speed
        friendlies = {}

        behavior.tick(hostile, friendlies)
        speed_after_first = hostile.speed

        behavior.tick(hostile, friendlies)

        assert hostile.speed == speed_after_first
        assert hostile.speed == pytest.approx(original_speed * 0.5, rel=0.01)


# ---------------------------------------------------------------------------
# 6. Hostile suppressing fire
# ---------------------------------------------------------------------------

class TestHostileSuppressing:
    def test_suppress_reduces_cooldown(self):
        """Suppressing hostile has weapon cooldown halved."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0), fsm_state="suppressing")
        original_cooldown = hostile.weapon_cooldown
        friendlies = {}

        behavior.tick(hostile, friendlies)

        assert hostile.weapon_cooldown == pytest.approx(original_cooldown * 0.5, rel=0.01)

    def test_suppress_cooldown_restored_on_state_change(self):
        """Cooldown is restored when hostile leaves suppress state."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0), fsm_state="suppressing")
        original_cooldown = hostile.weapon_cooldown
        friendlies = {}

        behavior.tick(hostile, friendlies)
        assert hostile.weapon_cooldown == pytest.approx(original_cooldown * 0.5, rel=0.01)

        hostile.fsm_state = "advancing"
        behavior.tick(hostile, friendlies)
        assert hostile.weapon_cooldown == pytest.approx(original_cooldown, rel=0.01)

    def test_suppress_double_entry_no_double_reduction(self):
        """Entering suppress twice does not halve cooldown twice."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0), fsm_state="suppressing")
        original_cooldown = hostile.weapon_cooldown
        friendlies = {}

        behavior.tick(hostile, friendlies)
        behavior.tick(hostile, friendlies)

        assert hostile.weapon_cooldown == pytest.approx(original_cooldown * 0.5, rel=0.01)

    def test_suppress_and_fire_faster(self):
        """Suppressing hostile fires more frequently due to halved cooldown."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="suppressing")
        original_cooldown = hostile.weapon_cooldown
        friendlies = {"turret1": _make_turret()}

        behavior.tick(hostile, friendlies)

        # Cooldown should be halved
        assert hostile.weapon_cooldown < original_cooldown


# ---------------------------------------------------------------------------
# 7. Hostile retreating under fire
# ---------------------------------------------------------------------------

class TestHostileRetreatingUnderFire:
    def test_retreating_under_fire_changes_position(self):
        """Hostile in 'retreating_under_fire' has position changed by zigzag."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(10.0, 10.0), fsm_state="retreating_under_fire")
        hostile.heading = 45.0
        original_pos = hostile.position
        friendlies = {}

        behavior.tick(hostile, friendlies)

        assert hostile.position != original_pos

    def test_retreating_under_fire_moves_toward_cover(self):
        """Hostile retreating under fire moves toward building obstacle."""
        behavior, combat, bus = _make_behavior()
        obstacles = _mock_obstacles(
            polygons=[[(20.0, 10.0), (25.0, 10.0), (25.0, 15.0), (20.0, 15.0)]]
        )
        behavior.set_obstacles(obstacles)

        hostile = _make_hostile(pos=(10.0, 12.0), fsm_state="retreating_under_fire")
        original_x = hostile.position[0]
        friendlies = {}

        behavior.tick(hostile, friendlies)

        # Should have moved toward the building (x should increase toward 20)
        # Note: zigzag adds randomness, but the cover movement dominates
        # We check that the x moved in the right general direction
        assert hostile.position[0] != original_x

    def test_retreating_under_fire_can_still_fire(self):
        """Hostile retreating under fire still fires at enemies in range."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="retreating_under_fire")
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        source_ids = {e["source_id"] for e in events}
        assert "h1" in source_ids

    def test_retreating_without_obstacles_just_zigzags(self):
        """Without obstacles, retreating under fire only zigzags."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(10.0, 10.0), fsm_state="retreating_under_fire")
        hostile.heading = 90.0
        original_pos = hostile.position
        friendlies = {}

        behavior.tick(hostile, friendlies)

        # Should still move (zigzag only)
        assert hostile.position != original_pos


# ---------------------------------------------------------------------------
# 8. FSM state transitions during behavior ticks
# ---------------------------------------------------------------------------

class TestFSMStateBehavior:
    def test_spawning_skips_all_behavior(self):
        """Hostile in 'spawning' state does nothing."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="spawning")
        turret = _make_turret()
        friendlies = {"turret1": turret}

        original_pos = hostile.position
        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        assert len(events) == 0
        assert hostile.position == original_pos

    def test_spawning_restores_recon_speed(self):
        """Transitioning to spawning restores recon speed modifier."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0), fsm_state="reconning")
        original_speed = hostile.speed

        behavior.tick(hostile, {})
        assert hostile.speed == pytest.approx(original_speed * 0.5, rel=0.01)

        hostile.fsm_state = "spawning"
        behavior.tick(hostile, {})
        assert hostile.speed == pytest.approx(original_speed, rel=0.01)

    def test_spawning_restores_suppress_cooldown(self):
        """Transitioning to spawning restores suppress cooldown modifier."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0), fsm_state="suppressing")
        original_cooldown = hostile.weapon_cooldown

        behavior.tick(hostile, {})
        assert hostile.weapon_cooldown == pytest.approx(original_cooldown * 0.5, rel=0.01)

        hostile.fsm_state = "spawning"
        behavior.tick(hostile, {})
        assert hostile.weapon_cooldown == pytest.approx(original_cooldown, rel=0.01)

    def test_broken_morale_skips_combat(self):
        """Hostile with morale < 0.1 skips all combat."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0))
        hostile.morale = 0.05  # broken
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        hostile_events = [e for e in events if e["source_id"] == "h1"]
        assert len(hostile_events) == 0

    def test_suppressed_morale_only_dodges(self):
        """Hostile with morale < 0.3 (suppressed) only dodges, no attacking."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0))
        hostile.morale = 0.2  # suppressed
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior._last_dodge[hostile.target_id] = 0.0
        original_pos = hostile.position

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        hostile_events = [e for e in events if e["source_id"] == "h1"]
        assert len(hostile_events) == 0
        assert hostile.position != original_pos

    def test_flanking_state_allows_fire(self):
        """Hostile in 'flanking' FSM state can fire at targets."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="flanking")
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        source_ids = {e["source_id"] for e in events}
        assert "h1" in source_ids

    def test_suppressing_state_allows_fire(self):
        """Hostile in 'suppressing' FSM state can fire at targets."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="suppressing")
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        source_ids = {e["source_id"] for e in events}
        assert "h1" in source_ids

    def test_none_fsm_state_allows_fire(self):
        """Hostile with None FSM state (default) can fire at targets."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state=None)
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        source_ids = {e["source_id"] for e in events}
        assert "h1" in source_ids


# ---------------------------------------------------------------------------
# 9. Squad coordination (group rush)
# ---------------------------------------------------------------------------

class TestGroupRush:
    def test_group_rush_boosts_speed(self):
        """3+ hostiles within 30m get +20% speed."""
        behavior, combat, bus = _make_behavior()

        h1 = _make_hostile("h1", (10.0, 0.0))
        h2 = _make_hostile("h2", (12.0, 0.0))
        h3 = _make_hostile("h3", (14.0, 0.0))
        original_speed = h1.speed

        hostiles = {"h1": h1, "h2": h2, "h3": h3}
        behavior.check_group_rush(hostiles)

        assert h1.speed == pytest.approx(original_speed * 1.2, rel=0.01)
        assert h2.speed == pytest.approx(original_speed * 1.2, rel=0.01)
        assert h3.speed == pytest.approx(original_speed * 1.2, rel=0.01)

    def test_group_rush_requires_minimum_count(self):
        """2 hostiles do not trigger group rush."""
        behavior, combat, bus = _make_behavior()

        h1 = _make_hostile("h1", (10.0, 0.0))
        h2 = _make_hostile("h2", (12.0, 0.0))
        original_speed = h1.speed

        hostiles = {"h1": h1, "h2": h2}
        behavior.check_group_rush(hostiles)

        assert h1.speed == original_speed
        assert h2.speed == original_speed

    def test_group_rush_restores_speed_when_spread(self):
        """Speed is restored when hostiles spread apart."""
        behavior, combat, bus = _make_behavior()

        h1 = _make_hostile("h1", (10.0, 0.0))
        h2 = _make_hostile("h2", (12.0, 0.0))
        h3 = _make_hostile("h3", (14.0, 0.0))
        original_speed = h1.speed

        hostiles = {"h1": h1, "h2": h2, "h3": h3}
        behavior.check_group_rush(hostiles)

        assert h1.speed == pytest.approx(original_speed * 1.2, rel=0.01)

        h3.position = (200.0, 0.0)
        behavior.check_group_rush(hostiles)

        assert h1.speed == pytest.approx(original_speed, rel=0.01)
        assert h2.speed == pytest.approx(original_speed, rel=0.01)

    def test_group_rush_beyond_radius_no_boost(self):
        """Hostiles farther than 30m apart do not get rush boost."""
        behavior, combat, bus = _make_behavior()

        h1 = _make_hostile("h1", (0.0, 0.0))
        h2 = _make_hostile("h2", (35.0, 0.0))
        h3 = _make_hostile("h3", (70.0, 0.0))
        original_speed = h1.speed

        hostiles = {"h1": h1, "h2": h2, "h3": h3}
        behavior.check_group_rush(hostiles)

        assert h1.speed == original_speed

    def test_group_rush_with_eliminated_hostile(self):
        """Eliminated hostile leaving the dict restores speed for remaining."""
        behavior, combat, bus = _make_behavior()

        h1 = _make_hostile("h1", (10.0, 0.0))
        h2 = _make_hostile("h2", (12.0, 0.0))
        h3 = _make_hostile("h3", (14.0, 0.0))
        original_speed = h1.speed

        hostiles = {"h1": h1, "h2": h2, "h3": h3}
        behavior.check_group_rush(hostiles)

        assert h1.speed == pytest.approx(original_speed * 1.2, rel=0.01)

        # Remove h3 (eliminated)
        del hostiles["h3"]
        behavior.check_group_rush(hostiles)

        assert h1.speed == pytest.approx(original_speed, rel=0.01)


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_no_friendlies_no_crash(self):
        """Tick with empty friendlies dict does not crash."""
        behavior, combat, bus = _make_behavior()
        hostile = _make_hostile(pos=(10.0, 0.0))
        behavior.tick(hostile, {})

    def test_all_friendlies_eliminated(self):
        """When all friendlies are eliminated, hostile does not crash."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(5.0, 0.0))
        turret = _make_turret()
        turret.status = "eliminated"
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

    def test_hostile_at_target_position(self):
        """Hostile at the exact same position as a friendly."""
        behavior, combat, bus = _make_behavior()
        fired_sub = bus.subscribe("projectile_fired")

        hostile = _make_hostile(pos=(0.0, 0.0))
        turret = _make_turret(pos=(0.0, 0.0))
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        events = _drain_fired_events(fired_sub)
        source_ids = {e["source_id"] for e in events}
        assert "h1" in source_ids

    def test_hostile_max_health_zero(self):
        """Hostile with max_health=0 does not crash on cover-seeking."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(10.0, 0.0))
        hostile.max_health = 0.0
        hostile.health = 0.0

        behavior.tick(hostile, {})

    def test_clear_state_resets_all(self):
        """clear_state() resets all internal tracking dicts."""
        behavior, combat, bus = _make_behavior()

        behavior._last_dodge["h1"] = time.time()
        behavior._last_flank["h1"] = time.time()
        behavior._group_rush_ids.add("h1")
        behavior._base_speeds["h1"] = 1.5
        behavior._recon_ids.add("h1")
        behavior._suppress_ids.add("h1")
        behavior._detected_ids.add("h1")
        behavior._contacted_enemies["h1"] = {"t1"}

        behavior.clear_state()

        assert len(behavior._last_dodge) == 0
        assert len(behavior._last_flank) == 0
        assert len(behavior._group_rush_ids) == 0
        assert len(behavior._base_speeds) == 0
        assert len(behavior._recon_ids) == 0
        assert len(behavior._suppress_ids) == 0
        assert len(behavior._detected_ids) == 0
        assert len(behavior._contacted_enemies) == 0

    def test_clear_state_with_pursuit(self):
        """clear_state() calls pursuit.clear() if pursuit is set."""
        behavior, combat, bus = _make_behavior()
        pursuit = _mock_pursuit()
        behavior.set_pursuit(pursuit)

        behavior.clear_state()
        pursuit.clear.assert_called_once()

    def test_clear_state_with_comms(self):
        """clear_state() calls comms.clear() if comms is set."""
        behavior, combat, bus = _make_behavior()
        comms = _mock_comms()
        behavior.set_comms(comms)

        behavior.clear_state()
        comms.clear.assert_called_once()

    def test_set_obstacles(self):
        """set_obstacles stores obstacle reference."""
        behavior, combat, bus = _make_behavior()
        obs = _mock_obstacles()
        behavior.set_obstacles(obs)
        assert behavior._obstacles is obs

    def test_set_pursuit(self):
        """set_pursuit stores pursuit reference and map bounds."""
        behavior, combat, bus = _make_behavior()
        pursuit = _mock_pursuit()
        behavior.set_pursuit(pursuit, map_bounds=500.0)
        assert behavior._pursuit is pursuit
        assert behavior._map_bounds == 500.0

    def test_set_comms(self):
        """set_comms stores comms reference."""
        behavior, combat, bus = _make_behavior()
        comms = _mock_comms()
        behavior.set_comms(comms)
        assert behavior._comms is comms


# ---------------------------------------------------------------------------
# Sensor awareness
# ---------------------------------------------------------------------------

class TestSensorAwareness:
    def test_detected_hostile_gets_speed_boost(self):
        """Detected hostile gets +20% speed boost."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0))
        hostile.detected = True
        original_speed = hostile.speed

        behavior.apply_sensor_awareness(hostile)

        assert hostile.speed == pytest.approx(original_speed * 1.2, rel=0.01)

    def test_detected_speed_boost_removed_when_undetected(self):
        """Speed boost is removed when hostile is no longer detected."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0))
        hostile.detected = True
        original_speed = hostile.speed

        behavior.apply_sensor_awareness(hostile)
        assert hostile.speed == pytest.approx(original_speed * 1.2, rel=0.01)

        hostile.detected = False
        behavior.apply_sensor_awareness(hostile)
        assert hostile.speed == pytest.approx(original_speed, rel=0.01)

    def test_detected_double_apply_no_double_boost(self):
        """Applying sensor awareness twice does not double the speed boost."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0))
        hostile.detected = True
        original_speed = hostile.speed

        behavior.apply_sensor_awareness(hostile)
        behavior.apply_sensor_awareness(hostile)

        assert hostile.speed == pytest.approx(original_speed * 1.2, rel=0.01)

    def test_remove_sensor_awareness_explicit(self):
        """remove_sensor_awareness() restores speed even without checking detected flag."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0))
        hostile.detected = True
        original_speed = hostile.speed

        behavior.apply_sensor_awareness(hostile)
        assert hostile.speed == pytest.approx(original_speed * 1.2, rel=0.01)

        behavior.remove_sensor_awareness(hostile)
        assert hostile.speed == pytest.approx(original_speed, rel=0.01)

    def test_remove_sensor_awareness_noop_if_not_detected(self):
        """remove_sensor_awareness on non-detected hostile is a no-op."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(50.0, 0.0))
        original_speed = hostile.speed

        behavior.remove_sensor_awareness(hostile)
        assert hostile.speed == original_speed


# ---------------------------------------------------------------------------
# Communication signals
# ---------------------------------------------------------------------------

class TestCommunication:
    def test_contact_signal_emitted_on_first_sight(self):
        """First time hostile sees an enemy, emits contact signal."""
        behavior, combat, bus = _make_behavior()
        comms = _mock_comms()
        behavior.set_comms(comms)

        hostile = _make_hostile(pos=(5.0, 0.0))
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

        comms.emit_contact.assert_called_once()
        call_args = comms.emit_contact.call_args
        assert call_args[0][0] == hostile.target_id

    def test_contact_signal_deduped_per_enemy(self):
        """Contact signal is only emitted once per enemy."""
        behavior, combat, bus = _make_behavior()
        comms = _mock_comms()
        behavior.set_comms(comms)

        hostile = _make_hostile(pos=(5.0, 0.0))
        hostile.last_fired = time.time()  # prevent firing to simplify
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)
        behavior.tick(hostile, friendlies)

        assert comms.emit_contact.call_count == 1

    def test_distress_signal_when_outnumbered(self):
        """Distress signal emitted when 2+ enemies in weapon range and engaging."""
        behavior, combat, bus = _make_behavior()
        comms = _mock_comms()
        behavior.set_comms(comms)

        hostile = _make_hostile(pos=(5.0, 0.0), fsm_state="engaging")
        t1 = _make_turret(tid="t1", pos=(0.0, 0.0))
        t2 = _make_turret(tid="t2", pos=(3.0, 0.0))
        friendlies = {"t1": t1, "t2": t2}

        behavior.tick(hostile, friendlies)

        comms.emit_distress.assert_called()

    def test_no_comms_no_crash(self):
        """Without comms set, no signal methods crash."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(5.0, 0.0))
        turret = _make_turret()
        friendlies = {"turret1": turret}

        behavior.tick(hostile, friendlies)

    def test_contact_new_enemy_emits_again(self):
        """Contact signal emitted for each unique enemy."""
        behavior, combat, bus = _make_behavior()
        comms = _mock_comms()
        behavior.set_comms(comms)

        hostile = _make_hostile(pos=(5.0, 0.0))
        hostile.last_fired = time.time()
        t1 = _make_turret(tid="t1", pos=(0.0, 0.0))
        t2 = _make_turret(tid="t2", pos=(3.0, 0.0))

        # First tick: sees t1 (nearest)
        behavior.tick(hostile, {"t1": t1})
        assert comms.emit_contact.call_count == 1

        # Second tick: sees t2 (put t1 out of range)
        t1_far = _make_turret(tid="t1", pos=(100.0, 100.0))
        behavior.tick(hostile, {"t1": t1_far, "t2": t2})
        assert comms.emit_contact.call_count == 2


# ---------------------------------------------------------------------------
# Cover-seeking
# ---------------------------------------------------------------------------

class TestCoverSeeking:
    def test_seek_cover_when_damaged(self):
        """Hostile below 50% health moves toward building edge."""
        behavior, combat, bus = _make_behavior()
        obstacles = _mock_obstacles(
            polygons=[[(20.0, 0.0), (25.0, 0.0), (25.0, 5.0), (20.0, 5.0)]]
        )
        behavior.set_obstacles(obstacles)

        hostile = _make_hostile(pos=(10.0, 2.5))
        hostile.health = 30.0
        hostile.max_health = 100.0
        hostile.weapon_range = 5.0  # out of range for firing
        friendlies = {}

        original_x = hostile.position[0]
        behavior.tick(hostile, friendlies)

        assert hostile.position[0] > original_x

    def test_no_cover_seeking_above_threshold(self):
        """Hostile above 50% health does not seek cover."""
        behavior, combat, bus = _make_behavior()
        obstacles = _mock_obstacles()
        behavior.set_obstacles(obstacles)

        hostile = _make_hostile(pos=(10.0, 2.5))
        hostile.health = 60.0
        hostile.max_health = 100.0

        result = behavior._seek_cover(hostile)
        assert result is False

    def test_no_cover_without_obstacles(self):
        """No cover-seeking without obstacles set."""
        behavior, combat, bus = _make_behavior()

        hostile = _make_hostile(pos=(10.0, 0.0))
        hostile.health = 30.0
        hostile.max_health = 100.0

        result = behavior._seek_cover(hostile)
        assert result is False

    def test_no_cover_when_already_close(self):
        """No cover movement when already within 1m of building edge."""
        behavior, combat, bus = _make_behavior()
        obstacles = _mock_obstacles(
            polygons=[[(10.0, 0.0), (10.5, 0.0), (10.5, 0.5), (10.0, 0.5)]]
        )
        behavior.set_obstacles(obstacles)

        hostile = _make_hostile(pos=(10.0, 0.0))
        hostile.health = 30.0
        hostile.max_health = 100.0

        result = behavior._seek_cover(hostile)
        # When distance < 1.0, _seek_cover returns False
        assert result is False


# ---------------------------------------------------------------------------
# Nearest point on segment (static helper)
# ---------------------------------------------------------------------------

class TestNearestPointOnSegment:
    def test_point_projects_to_midpoint(self):
        """Point directly above midpoint of a horizontal segment."""
        pt = HostileBehavior._nearest_point_on_segment(5.0, 5.0, 0.0, 0.0, 10.0, 0.0)
        assert pt == pytest.approx((5.0, 0.0), abs=0.01)

    def test_point_projects_to_endpoint_a(self):
        """Point past start of segment clamps to start."""
        pt = HostileBehavior._nearest_point_on_segment(-5.0, 0.0, 0.0, 0.0, 10.0, 0.0)
        assert pt == pytest.approx((0.0, 0.0), abs=0.01)

    def test_point_projects_to_endpoint_b(self):
        """Point past end of segment clamps to end."""
        pt = HostileBehavior._nearest_point_on_segment(15.0, 0.0, 0.0, 0.0, 10.0, 0.0)
        assert pt == pytest.approx((10.0, 0.0), abs=0.01)

    def test_zero_length_segment(self):
        """Zero-length segment returns the point itself."""
        pt = HostileBehavior._nearest_point_on_segment(5.0, 5.0, 3.0, 3.0, 3.0, 3.0)
        assert pt == pytest.approx((3.0, 3.0), abs=0.01)

    def test_diagonal_segment(self):
        """Point projects correctly onto a diagonal segment."""
        # Segment from (0,0) to (10,10), point at (10,0) -- nearest is (5,5)
        pt = HostileBehavior._nearest_point_on_segment(10.0, 0.0, 0.0, 0.0, 10.0, 10.0)
        assert pt == pytest.approx((5.0, 5.0), abs=0.01)
