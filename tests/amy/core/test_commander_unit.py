# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Comprehensive unit tests for Amy Commander — the core orchestrator.

Tests all module-level tactical functions, Commander class methods, mode logic,
event routing, state management, and helper functions in isolation. All external
dependencies (EventBus, SimulationEngine, TargetTracker, etc.) are mocked.

Source: src/amy/commander.py (~2292 lines)
"""

from __future__ import annotations

import queue
import time
import threading
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from amy.brain.sensorium import Sensorium, SceneEvent
from engine.comms.event_bus import EventBus


# ---------------------------------------------------------------------------
# Helpers — lightweight duck-typed commander for testing module-level fns
# ---------------------------------------------------------------------------

class FakeTracker:
    """Minimal TargetTracker stand-in."""

    def __init__(self, hostiles=None, friendlies=None):
        self._hostiles = hostiles or []
        self._friendlies = friendlies or []

    def summary(self):
        return f"{len(self._friendlies)} friendlies, {len(self._hostiles)} hostile"

    def get_hostiles(self):
        return self._hostiles

    def get_friendlies(self):
        return self._friendlies

    def update_from_simulation(self, data):
        pass

    def update_from_detection(self, data):
        pass


class FakeGameMode:
    """Minimal GameMode stand-in."""

    def __init__(self, state="setup", wave=0, score=0, total_eliminations=0):
        self.state = state
        self.wave = wave
        self.score = score
        self.total_eliminations = total_eliminations


class FakeEngine:
    """Minimal SimulationEngine stand-in."""

    def __init__(self, game_mode=None):
        self.game_mode = game_mode or FakeGameMode()
        self._targets = {}

    def get_target(self, tid):
        return self._targets.get(tid)

    def get_targets(self):
        return list(self._targets.values())

    def pause_spawners(self):
        pass

    def resume_spawners(self):
        pass


def _make_cmd(
    game_active=False,
    wave=3,
    score=500,
    total_eliminations=4,
    hostiles=None,
    friendlies=None,
    engine=None,
    sensorium=None,
    event_bus=None,
):
    """Build a minimal Commander-like duck-type with exact attributes
    required by the module-level tactical functions and _process_bridge_message.
    We avoid instantiating the real Commander (needs YOLO, CUDA, etc.).
    """
    bus = event_bus or EventBus()
    sens = sensorium or Sensorium()
    gm_state = "active" if game_active else "setup"
    gm = FakeGameMode(state=gm_state, wave=wave, score=score,
                       total_eliminations=total_eliminations)

    if engine is None:
        engine = FakeEngine(game_mode=gm)
    else:
        engine.game_mode = gm

    class Cmd:
        pass

    cmd = Cmd()
    cmd.event_bus = bus
    cmd.sensorium = sens
    cmd.target_tracker = FakeTracker(hostiles=hostiles, friendlies=friendlies)
    cmd.simulation_engine = engine
    cmd._running = True
    cmd._mode = "sim"
    cmd._sim_sub = bus.subscribe()
    cmd._tactical_summary_interval = 5.0
    cmd._last_tactical_summary = 0.0
    cmd._last_fire_batch = 0.0
    cmd._fire_batch_count = 0
    cmd._fire_batch_window = 2.0
    cmd._health_warning_times = {}
    cmd._health_warning_interval = 10.0
    cmd._recent_combat_events = []
    cmd.auto_dispatcher = None

    def say(text):
        pass
    cmd.say = say

    return cmd


def _drain_events(sensorium, source=None):
    """Collect sensorium events, optionally filtering by source."""
    with sensorium._lock:
        events = list(sensorium._events)
    if source:
        events = [e for e in events if e.source == source]
    return events


def _drain_tactical(sensorium):
    return _drain_events(sensorium, source="tactical")


pytestmark = pytest.mark.unit


# ===========================================================================
# 1. classify_tactical_event
# ===========================================================================

class TestClassifyTacticalEvent:
    """Tests for the classify_tactical_event() module-level function."""

    def test_projectile_fired_is_combat(self):
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("projectile_fired") == "combat"

    def test_projectile_hit_is_combat(self):
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("projectile_hit") == "combat"

    def test_target_eliminated_is_combat(self):
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("target_eliminated") == "combat"

    def test_elimination_streak_is_tactical(self):
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("elimination_streak") == "tactical"

    def test_wave_stats_summary_is_tactical(self):
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("wave_stats_summary") == "tactical"

    def test_combat_stats_update_is_tactical(self):
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("combat_stats_update") == "tactical"

    def test_ammo_low_is_status(self):
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("ammo_low") == "status"

    def test_unknown_event_returns_unknown(self):
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("some_random_thing") == "unknown"

    def test_empty_string_returns_unknown(self):
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("") == "unknown"

    def test_sim_telemetry_is_unknown(self):
        """sim_telemetry is NOT in combat/tactical/status — it's handled separately."""
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("sim_telemetry") == "unknown"


# ===========================================================================
# 2. _handle_combat_event — each event type
# ===========================================================================

class TestHandleCombatEventProjectileFired:
    """Tests for _handle_combat_event with projectile_fired."""

    def test_first_fire_pushes_to_sensorium(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "projectile_fired", {
            "source_name": "Turret-1",
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1
        assert "Turret-1" in events[0].text
        assert "fired" in events[0].text.lower()

    def test_fire_importance_is_03(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "projectile_fired", {"source_name": "T"})
        events = _drain_tactical(cmd.sensorium)
        assert events[0].importance == pytest.approx(0.3)

    def test_rapid_fires_are_batched(self):
        """Multiple fires within the batch window accumulate instead of each pushing."""
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        # First fire goes through immediately
        _handle_combat_event(cmd, "projectile_fired", {"source_name": "T"})
        # Subsequent within 2s window are accumulated
        _handle_combat_event(cmd, "projectile_fired", {"source_name": "T"})
        _handle_combat_event(cmd, "projectile_fired", {"source_name": "T"})
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1  # Only the first one pushed

    def test_batch_count_increments(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "projectile_fired", {"source_name": "T"})
        _handle_combat_event(cmd, "projectile_fired", {"source_name": "T"})
        _handle_combat_event(cmd, "projectile_fired", {"source_name": "T"})
        assert cmd._fire_batch_count == 2

    def test_fire_default_source_name(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "projectile_fired", {})
        events = _drain_tactical(cmd.sensorium)
        assert "unit" in events[0].text.lower()

    def test_fire_suppressed_when_game_inactive(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=False)
        _handle_combat_event(cmd, "projectile_fired", {"source_name": "T"})
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 0


class TestHandleCombatEventProjectileHit:
    """Tests for _handle_combat_event with projectile_hit."""

    def test_hit_pushes_to_sensorium(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "projectile_hit", {
            "target_name": "Intruder Alpha",
            "damage": 25.0,
            "remaining_health": 55.0,
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1
        assert "Intruder Alpha" in events[0].text
        assert "25" in events[0].text

    def test_hit_importance_is_05(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "projectile_hit", {
            "target_name": "X", "damage": 10.0, "remaining_health": 90.0,
        })
        events = _drain_tactical(cmd.sensorium)
        assert events[0].importance == pytest.approx(0.5)

    def test_hit_includes_remaining_health(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "projectile_hit", {
            "target_name": "X", "damage": 10.0, "remaining_health": 42.0,
        })
        events = _drain_tactical(cmd.sensorium)
        assert "42" in events[0].text


class TestHandleCombatEventTargetEliminated:
    """Tests for _handle_combat_event with target_eliminated."""

    def test_elimination_pushes_to_sensorium(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "target_eliminated", {
            "target_name": "Intruder Bravo",
            "interceptor_name": "Rover-1",
            "position": {"x": 10.0, "y": 20.0},
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1
        assert "Intruder Bravo" in events[0].text
        assert "Rover-1" in events[0].text

    def test_elimination_importance_is_07(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "target_eliminated", {
            "target_name": "X", "interceptor_name": "Y",
            "position": {"x": 0, "y": 0},
        })
        events = _drain_tactical(cmd.sensorium)
        assert events[0].importance == pytest.approx(0.7)

    def test_elimination_includes_coordinates(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "target_eliminated", {
            "target_name": "X", "interceptor_name": "Y",
            "position": {"x": 15.0, "y": 30.0},
        })
        events = _drain_tactical(cmd.sensorium)
        assert "15" in events[0].text
        assert "30" in events[0].text


class TestHandleCombatEventEliminationStreak:
    """Tests for _handle_combat_event with elimination_streak."""

    def test_streak_pushes_to_sensorium(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "elimination_streak", {
            "interceptor_name": "Turret-Alpha",
            "streak": 5,
            "streak_name": "RAMPAGE",
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1
        assert "RAMPAGE" in events[0].text or "5" in events[0].text

    def test_streak_importance_is_06(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "elimination_streak", {
            "interceptor_name": "T", "streak": 3, "streak_name": "X",
        })
        events = _drain_tactical(cmd.sensorium)
        assert events[0].importance == pytest.approx(0.6)


class TestHandleCombatEventAmmoLow:
    """Tests for _handle_combat_event with ammo_low."""

    def test_ammo_low_pushes_to_sensorium(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "ammo_low", {
            "unit_name": "Turret-Alpha",
            "ammo_remaining": 3,
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1
        assert "ammo" in events[0].text.lower()

    def test_ammo_low_importance_is_08(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "ammo_low", {
            "unit_name": "T", "ammo_remaining": 2,
        })
        events = _drain_tactical(cmd.sensorium)
        assert events[0].importance == pytest.approx(0.8)


class TestHandleCombatEventWaveStats:
    """Tests for _handle_combat_event with wave_stats_summary."""

    def test_wave_stats_pushes_to_sensorium(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "wave_stats_summary", {
            "wave": 3, "eliminations": 7, "accuracy": 0.65, "time_elapsed": 45.0,
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1
        assert "Wave 3" in events[0].text

    def test_wave_stats_importance_is_06(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "wave_stats_summary", {
            "wave": 1, "eliminations": 2, "accuracy": 0.5, "time_elapsed": 10.0,
        })
        events = _drain_tactical(cmd.sensorium)
        assert events[0].importance == pytest.approx(0.6)

    def test_wave_stats_includes_accuracy(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "wave_stats_summary", {
            "wave": 1, "eliminations": 2, "accuracy": 0.75, "time_elapsed": 10.0,
        })
        events = _drain_tactical(cmd.sensorium)
        assert "75%" in events[0].text


class TestHandleCombatEventCombatStatsUpdate:
    """Tests for _handle_combat_event with combat_stats_update."""

    def test_combat_stats_pushes_to_sensorium(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "combat_stats_update", {
            "top_unit": "Turret-Alpha", "kills": 5, "accuracy": 0.72,
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1
        assert "Turret-Alpha" in events[0].text

    def test_combat_stats_importance_is_04(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "combat_stats_update", {
            "top_unit": "T", "kills": 1, "accuracy": 0.5,
        })
        events = _drain_tactical(cmd.sensorium)
        assert events[0].importance == pytest.approx(0.4)


class TestHandleCombatEventSuppression:
    """Combat events are suppressed when game is not active."""

    def test_no_engine_suppresses(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        cmd.simulation_engine = None
        _handle_combat_event(cmd, "projectile_hit", {
            "target_name": "X", "damage": 10, "remaining_health": 90,
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 0

    def test_no_game_mode_suppresses(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=True)
        cmd.simulation_engine.game_mode = None
        _handle_combat_event(cmd, "projectile_hit", {
            "target_name": "X", "damage": 10, "remaining_health": 90,
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 0

    def test_setup_state_suppresses(self):
        from amy.commander import _handle_combat_event
        cmd = _make_cmd(game_active=False)
        _handle_combat_event(cmd, "target_eliminated", {
            "target_name": "X", "interceptor_name": "Y",
            "position": {"x": 0, "y": 0},
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 0


# ===========================================================================
# 3. _record_combat_event
# ===========================================================================

class TestRecordCombatEvent:
    """Tests for _record_combat_event buffer management."""

    def test_event_added_to_buffer(self):
        from amy.commander import _record_combat_event
        cmd = _make_cmd(game_active=True)
        _record_combat_event(cmd, "projectile_hit", "Hit on target")
        assert len(cmd._recent_combat_events) == 1
        assert cmd._recent_combat_events[0]["type"] == "projectile_hit"
        assert cmd._recent_combat_events[0]["text"] == "Hit on target"

    def test_buffer_has_time_field(self):
        from amy.commander import _record_combat_event
        cmd = _make_cmd(game_active=True)
        before = time.monotonic()
        _record_combat_event(cmd, "test", "text")
        after = time.monotonic()
        t = cmd._recent_combat_events[0]["time"]
        assert before <= t <= after

    def test_buffer_capped_at_20(self):
        from amy.commander import _record_combat_event
        cmd = _make_cmd(game_active=True)
        for i in range(25):
            _record_combat_event(cmd, "test", f"Event {i}")
        assert len(cmd._recent_combat_events) == 20

    def test_buffer_keeps_most_recent(self):
        from amy.commander import _record_combat_event
        cmd = _make_cmd(game_active=True)
        for i in range(25):
            _record_combat_event(cmd, "test", f"Event {i}")
        assert cmd._recent_combat_events[-1]["text"] == "Event 24"
        assert cmd._recent_combat_events[0]["text"] == "Event 5"


# ===========================================================================
# 4. _check_unit_health
# ===========================================================================

class TestCheckUnitHealth:
    """Tests for the _check_unit_health function."""

    def test_low_health_generates_warning(self):
        from amy.commander import _check_unit_health
        cmd = _make_cmd(game_active=True)
        _check_unit_health(cmd, {
            "target_id": "turret-1",
            "name": "Turret-Alpha",
            "alliance": "friendly",
            "health": 30.0,
            "max_health": 200.0,
            "status": "active",
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1
        assert "Turret-Alpha" in events[0].text
        assert "critical" in events[0].text.lower() or "health" in events[0].text.lower()

    def test_warning_importance_is_06(self):
        from amy.commander import _check_unit_health
        cmd = _make_cmd(game_active=True)
        _check_unit_health(cmd, {
            "target_id": "t1", "name": "T", "alliance": "friendly",
            "health": 10.0, "max_health": 100.0, "status": "active",
        })
        events = _drain_tactical(cmd.sensorium)
        assert events[0].importance == pytest.approx(0.6)

    def test_healthy_unit_no_warning(self):
        from amy.commander import _check_unit_health
        cmd = _make_cmd(game_active=True)
        _check_unit_health(cmd, {
            "target_id": "t1", "name": "T", "alliance": "friendly",
            "health": 180.0, "max_health": 200.0, "status": "active",
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 0

    def test_exactly_50_percent_no_warning(self):
        from amy.commander import _check_unit_health
        cmd = _make_cmd(game_active=True)
        _check_unit_health(cmd, {
            "target_id": "t1", "name": "T", "alliance": "friendly",
            "health": 100.0, "max_health": 200.0, "status": "active",
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 0

    def test_hostile_ignored(self):
        from amy.commander import _check_unit_health
        cmd = _make_cmd(game_active=True)
        _check_unit_health(cmd, {
            "target_id": "h1", "name": "Hostile", "alliance": "hostile",
            "health": 5.0, "max_health": 80.0, "status": "active",
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 0

    def test_eliminated_unit_ignored(self):
        from amy.commander import _check_unit_health
        cmd = _make_cmd(game_active=True)
        _check_unit_health(cmd, {
            "target_id": "t1", "name": "T", "alliance": "friendly",
            "health": 0.0, "max_health": 200.0, "status": "eliminated",
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 0

    def test_zero_max_health_no_crash(self):
        from amy.commander import _check_unit_health
        cmd = _make_cmd(game_active=True)
        _check_unit_health(cmd, {
            "target_id": "t1", "name": "T", "alliance": "friendly",
            "health": 0.0, "max_health": 0.0, "status": "active",
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 0

    def test_health_warning_throttled_per_unit(self):
        from amy.commander import _check_unit_health
        cmd = _make_cmd(game_active=True)
        data = {
            "target_id": "turret-1", "name": "Turret-Alpha",
            "alliance": "friendly", "health": 20.0, "max_health": 200.0,
            "status": "active",
        }
        _check_unit_health(cmd, data)
        first_count = len(_drain_tactical(cmd.sensorium))
        _check_unit_health(cmd, data)
        second_count = len(_drain_tactical(cmd.sensorium))
        # Second call within interval should not add more
        assert second_count == first_count

    def test_different_units_not_throttled(self):
        from amy.commander import _check_unit_health
        cmd = _make_cmd(game_active=True)
        _check_unit_health(cmd, {
            "target_id": "t1", "name": "Turret-1", "alliance": "friendly",
            "health": 20.0, "max_health": 200.0, "status": "active",
        })
        _check_unit_health(cmd, {
            "target_id": "t2", "name": "Turret-2", "alliance": "friendly",
            "health": 15.0, "max_health": 200.0, "status": "active",
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 2

    def test_health_warning_includes_percentage(self):
        from amy.commander import _check_unit_health
        cmd = _make_cmd(game_active=True)
        _check_unit_health(cmd, {
            "target_id": "t1", "name": "T", "alliance": "friendly",
            "health": 40.0, "max_health": 200.0, "status": "active",
        })
        events = _drain_tactical(cmd.sensorium)
        assert "20%" in events[0].text

    def test_suppressed_when_game_inactive(self):
        from amy.commander import _check_unit_health
        cmd = _make_cmd(game_active=False)
        _check_unit_health(cmd, {
            "target_id": "t1", "name": "T", "alliance": "friendly",
            "health": 10.0, "max_health": 200.0, "status": "active",
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 0


# ===========================================================================
# 5. _generate_tactical_summary
# ===========================================================================

class TestGenerateTacticalSummary:
    """Tests for _generate_tactical_summary."""

    def test_returns_string_when_active(self):
        from amy.commander import _generate_tactical_summary
        cmd = _make_cmd(game_active=True, wave=5, score=1200)
        result = _generate_tactical_summary(cmd)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_wave_number(self):
        from amy.commander import _generate_tactical_summary
        cmd = _make_cmd(game_active=True, wave=7, score=800)
        result = _generate_tactical_summary(cmd)
        assert "Wave 7" in result

    def test_includes_score(self):
        from amy.commander import _generate_tactical_summary
        cmd = _make_cmd(game_active=True, wave=3, score=1500)
        result = _generate_tactical_summary(cmd)
        assert "1500" in result

    def test_empty_when_no_engine(self):
        from amy.commander import _generate_tactical_summary
        cmd = _make_cmd(game_active=True)
        cmd.simulation_engine = None
        assert _generate_tactical_summary(cmd) == ""

    def test_empty_when_no_game_mode(self):
        from amy.commander import _generate_tactical_summary
        cmd = _make_cmd(game_active=True)
        cmd.simulation_engine.game_mode = None
        assert _generate_tactical_summary(cmd) == ""

    def test_empty_when_game_idle(self):
        from amy.commander import _generate_tactical_summary
        cmd = _make_cmd(game_active=False)
        assert _generate_tactical_summary(cmd) == ""

    def test_includes_hostile_count(self):
        from amy.commander import _generate_tactical_summary
        cmd = _make_cmd(game_active=True, hostiles=["h1", "h2", "h3"])
        result = _generate_tactical_summary(cmd)
        assert "3 hostiles" in result

    def test_includes_friendly_count(self):
        from amy.commander import _generate_tactical_summary
        cmd = _make_cmd(game_active=True, friendlies=["f1", "f2"])
        result = _generate_tactical_summary(cmd)
        assert "2 friendlies" in result


# ===========================================================================
# 6. _maybe_generate_tactical_summary
# ===========================================================================

class TestMaybeGenerateTacticalSummary:
    """Tests for _maybe_generate_tactical_summary throttle logic."""

    def test_first_call_succeeds(self):
        from amy.commander import _maybe_generate_tactical_summary
        cmd = _make_cmd(game_active=True)
        assert _maybe_generate_tactical_summary(cmd) is True

    def test_immediate_repeat_is_throttled(self):
        from amy.commander import _maybe_generate_tactical_summary
        cmd = _make_cmd(game_active=True)
        _maybe_generate_tactical_summary(cmd)
        assert _maybe_generate_tactical_summary(cmd) is False

    def test_pushes_to_sensorium(self):
        from amy.commander import _maybe_generate_tactical_summary
        cmd = _make_cmd(game_active=True)
        _maybe_generate_tactical_summary(cmd)
        events = _drain_tactical(cmd.sensorium)
        assert len(events) >= 1

    def test_returns_false_when_idle(self):
        from amy.commander import _maybe_generate_tactical_summary
        cmd = _make_cmd(game_active=False)
        assert _maybe_generate_tactical_summary(cmd) is False


# ===========================================================================
# 7. build_tactical_context
# ===========================================================================

class TestBuildTacticalContext:
    """Tests for build_tactical_context."""

    def test_includes_header_when_active(self):
        from amy.commander import build_tactical_context
        cmd = _make_cmd(game_active=True)
        result = build_tactical_context(cmd)
        assert "TACTICAL SITUATION" in result

    def test_empty_when_idle(self):
        from amy.commander import build_tactical_context
        cmd = _make_cmd(game_active=False)
        assert build_tactical_context(cmd) == ""

    def test_empty_when_no_engine(self):
        from amy.commander import build_tactical_context
        cmd = _make_cmd(game_active=True)
        cmd.simulation_engine = None
        assert build_tactical_context(cmd) == ""

    def test_includes_wave_info(self):
        from amy.commander import build_tactical_context
        cmd = _make_cmd(game_active=True, wave=5)
        result = build_tactical_context(cmd)
        assert "Wave 5" in result

    def test_includes_recent_combat_events(self):
        from amy.commander import build_tactical_context, _handle_combat_event
        cmd = _make_cmd(game_active=True)
        _handle_combat_event(cmd, "target_eliminated", {
            "target_name": "Intruder Alpha",
            "interceptor_name": "Turret-1",
            "position": {"x": 5, "y": 10},
        })
        result = build_tactical_context(cmd)
        assert "Recent" in result
        assert "Intruder Alpha" in result

    def test_limits_recent_events_to_5(self):
        from amy.commander import build_tactical_context, _record_combat_event
        cmd = _make_cmd(game_active=True)
        for i in range(10):
            _record_combat_event(cmd, "test", f"Event {i}")
        result = build_tactical_context(cmd)
        # Should only show last 5 events
        assert "Event 9" in result
        assert "Event 5" in result
        assert "Event 4" not in result

    def test_no_recent_events_section_when_empty(self):
        from amy.commander import build_tactical_context
        cmd = _make_cmd(game_active=True)
        result = build_tactical_context(cmd)
        assert "Recent" not in result


# ===========================================================================
# 8. _clear_combat_state
# ===========================================================================

class TestClearCombatState:
    """Tests for _clear_combat_state."""

    def test_clears_recent_events(self):
        from amy.commander import _clear_combat_state, _record_combat_event
        cmd = _make_cmd(game_active=True)
        _record_combat_event(cmd, "test", "text")
        assert len(cmd._recent_combat_events) > 0
        _clear_combat_state(cmd)
        assert len(cmd._recent_combat_events) == 0

    def test_clears_fire_batch_count(self):
        from amy.commander import _clear_combat_state
        cmd = _make_cmd(game_active=True)
        cmd._fire_batch_count = 5
        _clear_combat_state(cmd)
        assert cmd._fire_batch_count == 0

    def test_clears_last_fire_batch(self):
        from amy.commander import _clear_combat_state
        cmd = _make_cmd(game_active=True)
        cmd._last_fire_batch = 100.0
        _clear_combat_state(cmd)
        assert cmd._last_fire_batch == 0.0

    def test_clears_last_tactical_summary(self):
        from amy.commander import _clear_combat_state
        cmd = _make_cmd(game_active=True)
        cmd._last_tactical_summary = 50.0
        _clear_combat_state(cmd)
        assert cmd._last_tactical_summary == 0.0

    def test_clears_health_warning_times(self):
        from amy.commander import _clear_combat_state
        cmd = _make_cmd(game_active=True)
        cmd._health_warning_times = {"t1": 100.0, "t2": 200.0}
        _clear_combat_state(cmd)
        assert cmd._health_warning_times == {}


# ===========================================================================
# 9. _process_bridge_message
# ===========================================================================

class TestProcessBridgeMessage:
    """Tests for _process_bridge_message routing logic."""

    def test_routes_combat_event(self):
        from amy.commander import _process_bridge_message
        cmd = _make_cmd(game_active=True)
        _process_bridge_message(cmd, {
            "type": "projectile_hit",
            "data": {"target_name": "X", "damage": 10, "remaining_health": 90},
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1

    def test_routes_tactical_event(self):
        from amy.commander import _process_bridge_message
        cmd = _make_cmd(game_active=True)
        _process_bridge_message(cmd, {
            "type": "elimination_streak",
            "data": {"interceptor_name": "T", "streak": 3, "streak_name": "X"},
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1

    def test_routes_status_event(self):
        from amy.commander import _process_bridge_message
        cmd = _make_cmd(game_active=True)
        _process_bridge_message(cmd, {
            "type": "ammo_low",
            "data": {"unit_name": "T", "ammo_remaining": 2},
        })
        events = _drain_tactical(cmd.sensorium)
        assert len(events) == 1

    def test_sim_telemetry_calls_tracker(self):
        from amy.commander import _process_bridge_message
        cmd = _make_cmd(game_active=True)
        cmd.target_tracker = MagicMock()
        _process_bridge_message(cmd, {
            "type": "sim_telemetry",
            "data": {"targets": []},
        })
        cmd.target_tracker.update_from_simulation.assert_called_once()

    def test_sim_telemetry_checks_unit_health(self):
        from amy.commander import _process_bridge_message
        cmd = _make_cmd(game_active=True)
        _process_bridge_message(cmd, {
            "type": "sim_telemetry",
            "data": {
                "targets": [{
                    "target_id": "t1", "name": "T", "alliance": "friendly",
                    "health": 20.0, "max_health": 200.0, "status": "active",
                    "is_combatant": True,
                }],
            },
        })
        events = _drain_tactical(cmd.sensorium)
        health_events = [e for e in events if "health" in e.text.lower()]
        assert len(health_events) >= 1

    def test_sim_telemetry_checks_top_level_combatant(self):
        from amy.commander import _process_bridge_message
        cmd = _make_cmd(game_active=True)
        _process_bridge_message(cmd, {
            "type": "sim_telemetry",
            "data": {
                "target_id": "t1", "name": "T", "alliance": "friendly",
                "health": 20.0, "max_health": 200.0, "status": "active",
                "is_combatant": True,
            },
        })
        events = _drain_tactical(cmd.sensorium)
        health_events = [e for e in events if "health" in e.text.lower()]
        assert len(health_events) >= 1

    def test_game_state_change_setup_clears_combat(self):
        from amy.commander import _process_bridge_message, _record_combat_event
        cmd = _make_cmd(game_active=True)
        _record_combat_event(cmd, "test", "text")
        assert len(cmd._recent_combat_events) > 0
        _process_bridge_message(cmd, {
            "type": "game_state_change",
            "data": {"state": "setup"},
        })
        assert len(cmd._recent_combat_events) == 0

    def test_unknown_event_no_crash(self):
        from amy.commander import _process_bridge_message
        cmd = _make_cmd(game_active=True)
        _process_bridge_message(cmd, {
            "type": "completely_unknown_event",
            "data": {},
        })
        # Should not raise

    def test_empty_type_no_crash(self):
        from amy.commander import _process_bridge_message
        cmd = _make_cmd(game_active=True)
        _process_bridge_message(cmd, {"data": {}})
        # Should not raise


# ===========================================================================
# 10. _time_of_day
# ===========================================================================

class TestTimeOfDay:
    """Tests for _time_of_day helper."""

    def test_returns_string(self):
        from amy.commander import _time_of_day
        result = _time_of_day()
        assert isinstance(result, str)
        assert result in ("late night", "morning", "afternoon", "evening", "night")

    @patch("amy.commander.datetime")
    def test_late_night(self, mock_dt):
        mock_dt.now.return_value.hour = 3
        from amy.commander import _time_of_day
        assert _time_of_day() == "late night"

    @patch("amy.commander.datetime")
    def test_morning(self, mock_dt):
        mock_dt.now.return_value.hour = 9
        from amy.commander import _time_of_day
        assert _time_of_day() == "morning"

    @patch("amy.commander.datetime")
    def test_afternoon(self, mock_dt):
        mock_dt.now.return_value.hour = 14
        from amy.commander import _time_of_day
        assert _time_of_day() == "afternoon"

    @patch("amy.commander.datetime")
    def test_evening(self, mock_dt):
        mock_dt.now.return_value.hour = 19
        from amy.commander import _time_of_day
        assert _time_of_day() == "evening"

    @patch("amy.commander.datetime")
    def test_night(self, mock_dt):
        mock_dt.now.return_value.hour = 22
        from amy.commander import _time_of_day
        assert _time_of_day() == "night"


# ===========================================================================
# 11. EventType enum
# ===========================================================================

class TestEventTypeEnum:
    """Tests for the EventType enum values."""

    def test_speech_detected(self):
        from amy.commander import EventType
        assert EventType.SPEECH_DETECTED.value == "speech_detected"

    def test_transcript_ready(self):
        from amy.commander import EventType
        assert EventType.TRANSCRIPT_READY.value == "transcript_ready"

    def test_silence(self):
        from amy.commander import EventType
        assert EventType.SILENCE.value == "silence"

    def test_curiosity_tick(self):
        from amy.commander import EventType
        assert EventType.CURIOSITY_TICK.value == "curiosity_tick"

    def test_motor_done(self):
        from amy.commander import EventType
        assert EventType.MOTOR_DONE.value == "motor_done"

    def test_person_arrived(self):
        from amy.commander import EventType
        assert EventType.PERSON_ARRIVED.value == "person_arrived"

    def test_person_left(self):
        from amy.commander import EventType
        assert EventType.PERSON_LEFT.value == "person_left"

    def test_motion_detected(self):
        from amy.commander import EventType
        assert EventType.MOTION_DETECTED.value == "motion_detected"

    def test_shutdown(self):
        from amy.commander import EventType
        assert EventType.SHUTDOWN.value == "shutdown"


# ===========================================================================
# 12. CreatureState enum
# ===========================================================================

class TestCreatureStateEnum:
    """Tests for the CreatureState enum values."""

    def test_idle(self):
        from amy.commander import CreatureState
        assert CreatureState.IDLE.value == "IDLE"

    def test_listening(self):
        from amy.commander import CreatureState
        assert CreatureState.LISTENING.value == "LISTENING"

    def test_thinking(self):
        from amy.commander import CreatureState
        assert CreatureState.THINKING.value == "THINKING"

    def test_speaking(self):
        from amy.commander import CreatureState
        assert CreatureState.SPEAKING.value == "SPEAKING"


# ===========================================================================
# 13. Event class
# ===========================================================================

class TestEventClass:
    """Tests for the Event data class."""

    def test_event_creation(self):
        from amy.commander import Event, EventType
        e = Event(EventType.SPEECH_DETECTED)
        assert e.type == EventType.SPEECH_DETECTED
        assert e.data is None

    def test_event_with_data(self):
        from amy.commander import Event, EventType
        e = Event(EventType.TRANSCRIPT_READY, data="Hello world")
        assert e.type == EventType.TRANSCRIPT_READY
        assert e.data == "Hello world"

    def test_event_slots(self):
        from amy.commander import Event, EventType
        e = Event(EventType.SHUTDOWN)
        assert hasattr(e, "__slots__")
        assert "type" in e.__slots__
        assert "data" in e.__slots__


# ===========================================================================
# 14. Commander mode selection (set_mode)
# ===========================================================================

class TestCommanderMode:
    """Tests for Commander.set_mode logic."""

    def test_default_mode_is_sim(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        assert cmd.mode == "sim"

    def test_set_mode_to_live(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        result = cmd.set_mode("live")
        assert result == "live"
        assert cmd.mode == "live"

    def test_set_mode_to_sim(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        cmd.set_mode("live")
        result = cmd.set_mode("sim")
        assert result == "sim"
        assert cmd.mode == "sim"

    def test_set_mode_invalid_raises(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        with pytest.raises(ValueError, match="Invalid mode"):
            cmd.set_mode("invalid")

    def test_set_mode_normalizes_case(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        result = cmd.set_mode("LIVE")
        assert result == "live"

    def test_set_mode_strips_whitespace(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        result = cmd.set_mode("  live  ")
        assert result == "live"

    def test_set_mode_publishes_event(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        sub = cmd.event_bus.subscribe()
        cmd.set_mode("live")
        msg = sub.get_nowait()
        assert msg["type"] == "mode_change"
        assert msg["data"]["mode"] == "live"
        assert msg["data"]["previous"] == "sim"

    def test_set_mode_pushes_to_sensorium_on_change(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        cmd.set_mode("live")
        events = _drain_tactical(cmd.sensorium)
        assert len(events) >= 1
        assert "LIVE SENSORS" in events[0].text

    def test_set_mode_pauses_spawners_in_live(self):
        from amy.commander import Commander
        mock_engine = MagicMock()
        cmd = Commander(nodes={}, simulation_engine=mock_engine)
        cmd.set_mode("live")
        mock_engine.pause_spawners.assert_called_once()

    def test_set_mode_resumes_spawners_in_sim(self):
        from amy.commander import Commander
        mock_engine = MagicMock()
        cmd = Commander(nodes={}, simulation_engine=mock_engine)
        cmd.set_mode("live")
        cmd.set_mode("sim")
        mock_engine.resume_spawners.assert_called_once()


# ===========================================================================
# 15. Commander primary node properties
# ===========================================================================

class TestCommanderPrimaryNodes:
    """Tests for primary_camera, primary_ptz, primary_mic, primary_speaker."""

    def test_primary_mic_returns_mic_node(self):
        from tests.amy.conftest import MockSensorNode
        from amy.commander import Commander
        node = MockSensorNode(camera=False, ptz=False, mic=True, speaker=False)
        cmd = Commander(nodes={"mic": node})
        assert cmd.primary_mic is node

    def test_primary_mic_none_when_no_mic(self):
        from tests.amy.conftest import MockSensorNode
        from amy.commander import Commander
        node = MockSensorNode(camera=True, ptz=False, mic=False, speaker=False)
        cmd = Commander(nodes={"cam": node})
        assert cmd.primary_mic is None

    def test_primary_speaker_returns_speaker_node(self):
        from tests.amy.conftest import MockSensorNode
        from amy.commander import Commander
        node = MockSensorNode(camera=False, ptz=False, mic=False, speaker=True)
        cmd = Commander(nodes={"spk": node})
        assert cmd.primary_speaker is node

    def test_primary_speaker_none_when_no_speaker(self):
        from tests.amy.conftest import MockSensorNode
        from amy.commander import Commander
        node = MockSensorNode(camera=True, ptz=False, mic=False, speaker=False)
        cmd = Commander(nodes={"cam": node})
        assert cmd.primary_speaker is None

    def test_no_nodes_all_none(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        assert cmd.primary_camera is None
        assert cmd.primary_ptz is None
        assert cmd.primary_mic is None
        assert cmd.primary_speaker is None


# ===========================================================================
# 16. Commander._set_state
# ===========================================================================

class TestCommanderSetState:
    """Tests for _set_state publishing state_change events."""

    def test_set_state_changes_internal_state(self):
        from amy.commander import Commander, CreatureState
        cmd = Commander(nodes={})
        cmd._set_state(CreatureState.THINKING)
        assert cmd._state == CreatureState.THINKING

    def test_set_state_publishes_event(self):
        from amy.commander import Commander, CreatureState
        cmd = Commander(nodes={})
        sub = cmd.event_bus.subscribe()
        cmd._set_state(CreatureState.LISTENING)
        msg = sub.get_nowait()
        assert msg["type"] == "state_change"
        assert msg["data"]["state"] == "LISTENING"


# ===========================================================================
# 17. Commander._clean_speech (static method)
# ===========================================================================

class TestCleanSpeech:
    """Tests for Commander._clean_speech."""

    def test_removes_long_parenthetical(self):
        from amy.commander import Commander
        result = Commander._clean_speech("(Turns camera to face you) Hello!")
        assert "Turns camera" not in result
        assert "Hello!" in result

    def test_removes_long_asterisk_action(self):
        from amy.commander import Commander
        result = Commander._clean_speech("*A whirring sound fills the room* Good morning!")
        assert "whirring" not in result
        assert "Good morning!" in result

    def test_preserves_short_parens(self):
        from amy.commander import Commander
        result = Commander._clean_speech("Hello (hi) there")
        assert "(hi)" in result

    def test_replaces_smart_quotes(self):
        from amy.commander import Commander
        result = Commander._clean_speech("\u201cHello\u201d")
        assert "\u201c" not in result
        assert "\u201d" not in result

    def test_unwraps_full_quote(self):
        from amy.commander import Commander
        result = Commander._clean_speech('"Welcome to the command center."')
        assert result == "Welcome to the command center."

    def test_collapses_spaces(self):
        from amy.commander import Commander
        result = Commander._clean_speech("Hello   world")
        assert "   " not in result

    def test_fallback_on_empty_result(self):
        from amy.commander import Commander
        raw = "(An extremely long stage direction that removes everything)"
        result = Commander._clean_speech(raw)
        assert result == raw


# ===========================================================================
# 18. Commander._check_wake_word
# ===========================================================================

class TestCheckWakeWord:
    """Tests for Commander._check_wake_word."""

    def test_wake_word_with_query_extracts_query(self):
        from amy.commander import Commander
        cmd = Commander(nodes={}, wake_word="amy")
        result = cmd._check_wake_word("hey amy what time is it")
        assert result == "what time is it"

    def test_wake_word_alone_sets_awake(self):
        from amy.commander import Commander
        cmd = Commander(nodes={}, wake_word="amy")
        result = cmd._check_wake_word("hey amy")
        assert result is None
        assert cmd._awake is True

    def test_no_match_returns_none(self):
        from amy.commander import Commander
        cmd = Commander(nodes={}, wake_word="amy")
        result = cmd._check_wake_word("hello world")
        assert result is None

    def test_follow_up_when_awake(self):
        from amy.commander import Commander
        cmd = Commander(nodes={}, wake_word="amy")
        cmd._awake = True
        result = cmd._check_wake_word("what is the weather")
        assert result == "what is the weather"

    def test_wake_word_none_passes_through(self):
        from amy.commander import Commander
        cmd = Commander(nodes={}, wake_word=None)
        result = cmd._check_wake_word("anything at all")
        assert result == "anything at all"


# ===========================================================================
# 19. Commander._recall_interceptor
# ===========================================================================

class TestRecallInterceptor:
    """Tests for Commander._recall_interceptor."""

    def test_recall_sets_idle_and_clears_waypoints(self):
        from amy.commander import Commander
        mock_engine = MagicMock()
        target = MagicMock()
        target.name = "Rover-1"
        target.waypoints = [(10, 20), (30, 40)]
        target.status = "engaging"
        mock_engine.get_target.return_value = target
        cmd = Commander(nodes={}, simulation_engine=mock_engine)
        cmd._recall_interceptor("rover-1")
        assert target.waypoints == []
        assert target.status == "idle"

    def test_recall_no_engine_does_nothing(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        cmd.simulation_engine = None
        cmd._recall_interceptor("rover-1")  # Should not raise

    def test_recall_empty_id_does_nothing(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        cmd._recall_interceptor("")  # Should not raise

    def test_recall_unknown_target_does_nothing(self):
        from amy.commander import Commander
        mock_engine = MagicMock()
        mock_engine.get_target.return_value = None
        cmd = Commander(nodes={}, simulation_engine=mock_engine)
        cmd._recall_interceptor("nonexistent")  # Should not raise

    def test_recall_pushes_sensorium_message(self):
        from amy.commander import Commander
        mock_engine = MagicMock()
        target = MagicMock()
        target.name = "Drone-2"
        mock_engine.get_target.return_value = target
        cmd = Commander(nodes={}, simulation_engine=mock_engine)
        cmd._recall_interceptor("drone-2")
        events = _drain_tactical(cmd.sensorium)
        assert len(events) >= 1
        assert "Drone-2" in events[0].text
        assert "standby" in events[0].text.lower()


# ===========================================================================
# 20. Commander init defaults
# ===========================================================================

class TestCommanderInitDefaults:
    """Tests for Commander.__init__ default attribute values."""

    def test_default_mode_is_sim(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        assert cmd._mode == "sim"

    def test_default_state_is_idle(self):
        from amy.commander import Commander, CreatureState
        cmd = Commander(nodes={})
        assert cmd._state == CreatureState.IDLE

    def test_event_bus_created(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        assert isinstance(cmd.event_bus, EventBus)

    def test_sensorium_created(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        assert isinstance(cmd.sensorium, Sensorium)

    def test_target_tracker_created(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        assert cmd.target_tracker is not None

    def test_combat_state_initialized(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        assert cmd._recent_combat_events == []
        assert cmd._fire_batch_count == 0
        assert cmd._last_fire_batch == 0.0
        assert cmd._fire_batch_window == 2.0
        assert cmd._health_warning_times == {}
        assert cmd._health_warning_interval == 10.0

    def test_wake_word_lowercased(self):
        from amy.commander import Commander
        cmd = Commander(nodes={}, wake_word="AMY")
        assert cmd.wake_word == "amy"

    def test_wake_word_stripped(self):
        from amy.commander import Commander
        cmd = Commander(nodes={}, wake_word="  amy  ")
        assert cmd.wake_word == "amy"

    def test_running_initially_false(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        assert cmd._running is False

    def test_shutdown_initially_false(self):
        from amy.commander import Commander
        cmd = Commander(nodes={})
        assert cmd._shutdown_called is False


# ===========================================================================
# 21. CuriosityTimer
# ===========================================================================

class TestCuriosityTimer:
    """Tests for CuriosityTimer basic behavior."""

    def test_creates_with_defaults(self):
        from amy.commander import CuriosityTimer
        q = queue.Queue()
        ct = CuriosityTimer(q)
        assert ct.min_interval == 45.0
        assert ct.max_interval == 90.0

    def test_creates_with_custom_intervals(self):
        from amy.commander import CuriosityTimer
        q = queue.Queue()
        ct = CuriosityTimer(q, min_interval=10.0, max_interval=20.0)
        assert ct.min_interval == 10.0
        assert ct.max_interval == 20.0

    def test_stop_without_start(self):
        from amy.commander import CuriosityTimer
        q = queue.Queue()
        ct = CuriosityTimer(q)
        ct.stop()  # Should not raise


# ===========================================================================
# 22. AudioThread
# ===========================================================================

class TestAudioThread:
    """Tests for AudioThread constants."""

    def test_silence_timeout_chunks(self):
        from amy.commander import AudioThread
        assert AudioThread.SILENCE_TIMEOUT_CHUNKS == 22

    def test_max_speech_chunks(self):
        from amy.commander import AudioThread
        assert AudioThread.MAX_SPEECH_CHUNKS == 940

    def test_min_speech_chunks(self):
        from amy.commander import AudioThread
        assert AudioThread.MIN_SPEECH_CHUNKS == 10
