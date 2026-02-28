# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Amy's tactical awareness — combat events wired into sensorium.

Validates that the Commander's _sim_bridge_loop correctly:
  - Routes combat events (projectile_fired, projectile_hit, target_eliminated,
    elimination_streak) to sensorium observations with correct importance
  - Generates periodic tactical summaries during active combat
  - Throttles high-frequency events (batches shots, not one per projectile)
  - Produces no tactical observations when game is idle
  - Generates unit status observations from sim_telemetry
  - Provides thinking context with TACTICAL SITUATION section during combat
"""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from amy.brain.sensorium import Sensorium, SceneEvent
from engine.comms.event_bus import EventBus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_commander(
    event_bus: EventBus | None = None,
    sensorium: Sensorium | None = None,
    game_active: bool = False,
):
    """Build a minimal Commander-like object for testing _sim_bridge_loop.

    We don't instantiate the full Commander (needs YOLO, CUDA, etc.) — instead
    we build a duck-type with the exact attributes _sim_bridge_loop reads.
    """
    bus = event_bus or EventBus()
    sens = sensorium or Sensorium()

    class FakeTracker:
        def summary(self):
            return "2 friendlies, 1 hostile"
        def get_hostiles(self):
            return []
        def get_friendlies(self):
            return []

    class FakeGameMode:
        def __init__(self, active):
            self.state = "active" if active else "setup"
            self.wave = 3 if active else 0
            self.score = 500 if active else 0
            self.total_eliminations = 4 if active else 0

    class FakeEngine:
        def __init__(self):
            self.game_mode = FakeGameMode(game_active)
        def get_target(self, tid):
            return None
        def get_targets(self):
            return []

    class FakeCommander:
        def __init__(self):
            self.event_bus = bus
            self.sensorium = sens
            self.target_tracker = FakeTracker()
            self.simulation_engine = FakeEngine()
            self._running = True
            self._mode = "sim"
            self._sim_sub = bus.subscribe()
            self._tactical_summary_interval = 5.0
            self._last_tactical_summary = 0.0
            self._last_fire_batch = 0.0
            self._fire_batch_count = 0
            self._fire_batch_window = 2.0
            self._health_warning_times = {}
            self._health_warning_interval = 10.0
            self._recent_combat_events = []

        def say(self, text):
            pass  # No TTS in tests

    return FakeCommander()


def _drain_events(sensorium: Sensorium, source: str | None = None) -> list[SceneEvent]:
    """Collect sensorium events, optionally filtering by source."""
    with sensorium._lock:
        events = list(sensorium._events)
    if source:
        events = [e for e in events if e.source == source]
    return events


def _drain_tactical(sensorium: Sensorium) -> list[SceneEvent]:
    """Collect all tactical-source events from sensorium."""
    return _drain_events(sensorium, source="tactical")


pytestmark = pytest.mark.unit


# ===========================================================================
# 1. Combat events reach sensorium with correct importance
# ===========================================================================

class TestCombatEventsReachSensorium:
    """Verify each combat event type is routed to sensorium."""

    def test_projectile_fired_reaches_sensorium(self):
        """projectile_fired events produce a sensorium observation."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        # Import and call the handler directly
        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "projectile_fired", {
            "source_name": "Turret-Alpha",
            "target_id": "hostile-1",
            "source_id": "turret-1",
            "projectile_type": "nerf_dart",
        })

        events = _drain_tactical(sens)
        assert len(events) >= 1
        assert any("Turret-Alpha" in e.text and "fire" in e.text.lower() for e in events)

    def test_projectile_fired_importance(self):
        """projectile_fired events have importance 0.3."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "projectile_fired", {
            "source_name": "Turret-Alpha",
            "target_id": "hostile-1",
            "source_id": "turret-1",
            "projectile_type": "nerf_dart",
        })

        events = _drain_tactical(sens)
        fire_events = [e for e in events if "fire" in e.text.lower()]
        assert len(fire_events) >= 1
        assert fire_events[0].importance == pytest.approx(0.3, abs=0.01)

    def test_projectile_hit_reaches_sensorium(self):
        """projectile_hit events produce a sensorium observation."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "projectile_hit", {
            "source_id": "turret-1",
            "target_name": "Intruder Alpha",
            "damage": 15.0,
            "remaining_health": 65.0,
        })

        events = _drain_tactical(sens)
        assert len(events) >= 1
        assert any("hit" in e.text.lower() or "damage" in e.text.lower() for e in events)

    def test_projectile_hit_importance(self):
        """projectile_hit events have importance 0.5."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "projectile_hit", {
            "source_id": "turret-1",
            "target_name": "Intruder Alpha",
            "damage": 15.0,
            "remaining_health": 65.0,
        })

        events = _drain_tactical(sens)
        hit_events = [e for e in events if "hit" in e.text.lower() or "damage" in e.text.lower()]
        assert len(hit_events) >= 1
        assert hit_events[0].importance == pytest.approx(0.5, abs=0.01)

    def test_target_eliminated_reaches_sensorium(self):
        """target_eliminated events produce a sensorium observation."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "target_eliminated", {
            "target_name": "Intruder Bravo",
            "interceptor_name": "Turret-Alpha",
            "target_id": "hostile-2",
            "interceptor_id": "turret-1",
            "position": {"x": 10.0, "y": 20.0},
            "method": "nerf_dart",
        })

        events = _drain_tactical(sens)
        assert len(events) >= 1
        assert any("eliminated" in e.text.lower() or "Intruder Bravo" in e.text for e in events)

    def test_target_eliminated_importance(self):
        """target_eliminated events have importance 0.7."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "target_eliminated", {
            "target_name": "Intruder Bravo",
            "interceptor_name": "Turret-Alpha",
            "target_id": "hostile-2",
            "interceptor_id": "turret-1",
            "position": {"x": 10.0, "y": 20.0},
            "method": "nerf_dart",
        })

        events = _drain_tactical(sens)
        elim_events = [e for e in events if "eliminated" in e.text.lower()]
        assert len(elim_events) >= 1
        assert elim_events[0].importance == pytest.approx(0.7, abs=0.01)

    def test_elimination_streak_reaches_sensorium(self):
        """elimination_streak events produce a sensorium observation."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "elimination_streak", {
            "interceptor_name": "Turret-Alpha",
            "interceptor_id": "turret-1",
            "streak": 3,
            "streak_name": "ON A STREAK",
        })

        events = _drain_tactical(sens)
        assert len(events) >= 1
        assert any("streak" in e.text.lower() or "Turret-Alpha" in e.text for e in events)

    def test_elimination_streak_importance(self):
        """elimination_streak events have importance 0.6."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "elimination_streak", {
            "interceptor_name": "Turret-Alpha",
            "interceptor_id": "turret-1",
            "streak": 3,
            "streak_name": "ON A STREAK",
        })

        events = _drain_tactical(sens)
        streak_events = [e for e in events if "streak" in e.text.lower()]
        assert len(streak_events) >= 1
        assert streak_events[0].importance == pytest.approx(0.6, abs=0.01)

    def test_ammo_low_reaches_sensorium(self):
        """ammo_low events produce a high-importance sensorium observation."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "ammo_low", {
            "unit_name": "Turret-Alpha",
            "unit_id": "turret-1",
            "ammo_remaining": 3,
        })

        events = _drain_tactical(sens)
        assert len(events) >= 1
        assert any("ammo" in e.text.lower() or "ammunition" in e.text.lower() for e in events)

    def test_ammo_low_importance(self):
        """ammo_low events have importance 0.8."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "ammo_low", {
            "unit_name": "Turret-Alpha",
            "unit_id": "turret-1",
            "ammo_remaining": 3,
        })

        events = _drain_tactical(sens)
        ammo_events = [e for e in events if "ammo" in e.text.lower() or "ammunition" in e.text.lower()]
        assert len(ammo_events) >= 1
        assert ammo_events[0].importance == pytest.approx(0.8, abs=0.01)

    def test_wave_stats_summary_reaches_sensorium(self):
        """wave_stats_summary events produce a sensorium observation."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "wave_stats_summary", {
            "wave": 3,
            "eliminations": 7,
            "accuracy": 0.65,
            "time_elapsed": 45.0,
        })

        events = _drain_tactical(sens)
        assert len(events) >= 1

    def test_wave_stats_summary_importance(self):
        """wave_stats_summary events have importance 0.6."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "wave_stats_summary", {
            "wave": 3,
            "eliminations": 7,
            "accuracy": 0.65,
            "time_elapsed": 45.0,
        })

        events = _drain_tactical(sens)
        assert len(events) >= 1
        assert events[0].importance == pytest.approx(0.6, abs=0.01)

    def test_combat_stats_update_reaches_sensorium(self):
        """combat_stats_update events produce a sensorium observation."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "combat_stats_update", {
            "top_unit": "Turret-Alpha",
            "kills": 5,
            "accuracy": 0.72,
        })

        events = _drain_tactical(sens)
        assert len(events) >= 1

    def test_combat_stats_update_importance(self):
        """combat_stats_update events have importance 0.4."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "combat_stats_update", {
            "top_unit": "Turret-Alpha",
            "kills": 5,
            "accuracy": 0.72,
        })

        events = _drain_tactical(sens)
        assert len(events) >= 1
        assert events[0].importance == pytest.approx(0.4, abs=0.01)


# ===========================================================================
# 2. Event text content is correct
# ===========================================================================

class TestCombatEventText:
    """Verify the text content of sensorium observations is meaningful."""

    def test_fire_event_includes_source_name(self):
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "projectile_fired", {
            "source_name": "Drone-Beta",
            "target_id": "hostile-1",
            "source_id": "drone-1",
            "projectile_type": "nerf_dart",
        })

        events = _drain_tactical(sens)
        assert any("Drone-Beta" in e.text for e in events)

    def test_hit_event_includes_target_and_damage(self):
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "projectile_hit", {
            "source_id": "turret-1",
            "target_name": "Intruder Charlie",
            "damage": 25.0,
            "remaining_health": 55.0,
        })

        events = _drain_tactical(sens)
        assert any("Intruder Charlie" in e.text for e in events)
        assert any("25" in e.text for e in events)

    def test_elimination_includes_both_names(self):
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "target_eliminated", {
            "target_name": "Intruder Delta",
            "interceptor_name": "Rover-Charlie",
            "target_id": "hostile-4",
            "interceptor_id": "rover-1",
            "position": {"x": 5.0, "y": 15.0},
            "method": "nerf_dart",
        })

        events = _drain_tactical(sens)
        text = " ".join(e.text for e in events)
        assert "Intruder Delta" in text
        assert "Rover-Charlie" in text

    def test_streak_includes_streak_name(self):
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "elimination_streak", {
            "interceptor_name": "Turret-Alpha",
            "interceptor_id": "turret-1",
            "streak": 5,
            "streak_name": "RAMPAGE",
        })

        events = _drain_tactical(sens)
        text = " ".join(e.text for e in events)
        assert "RAMPAGE" in text or "5" in text


# ===========================================================================
# 3. Throttling / batching of high-frequency events
# ===========================================================================

class TestEventThrottling:
    """High-frequency events (projectile_fired) must be batched, not spammed."""

    def test_rapid_fire_events_are_batched(self):
        """Multiple rapid projectile_fired events should not all appear individually."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event

        # Simulate 10 rapid-fire events
        for i in range(10):
            _handle_combat_event(cmd, "projectile_fired", {
                "source_name": "Turret-Alpha",
                "target_id": f"hostile-{i}",
                "source_id": "turret-1",
                "projectile_type": "nerf_dart",
            })

        events = _drain_tactical(sens)
        # Should NOT have 10 individual observations — batching should reduce this
        assert len(events) < 10

    def test_fire_batch_produces_summary(self):
        """After a batch of fires, the observation should summarize them."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event

        # Fire multiple shots rapidly
        for i in range(5):
            _handle_combat_event(cmd, "projectile_fired", {
                "source_name": "Turret-Alpha",
                "target_id": f"hostile-{i}",
                "source_id": "turret-1",
                "projectile_type": "nerf_dart",
            })

        events = _drain_tactical(sens)
        assert len(events) >= 1
        # At least one event should reference the firing
        assert any("fire" in e.text.lower() or "engag" in e.text.lower() for e in events)

    def test_hits_are_not_throttled(self):
        """Hits are significant enough to not be throttled."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event

        for i in range(3):
            # Small time gap to avoid sensorium dedup
            time.sleep(0.01)
            _handle_combat_event(cmd, "projectile_hit", {
                "source_id": f"turret-{i}",
                "target_name": f"Intruder {i}",
                "damage": 15.0,
                "remaining_health": 65.0 - i * 15,
            })

        events = _drain_tactical(sens)
        # Each hit should appear (hits are important enough)
        hit_events = [e for e in events if "hit" in e.text.lower() or "damage" in e.text.lower()]
        assert len(hit_events) >= 2

    def test_eliminations_are_not_throttled(self):
        """Eliminations are always reported individually."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event

        for i in range(3):
            time.sleep(0.01)
            _handle_combat_event(cmd, "target_eliminated", {
                "target_name": f"Intruder {chr(65 + i)}",
                "interceptor_name": "Turret-Alpha",
                "target_id": f"hostile-{i}",
                "interceptor_id": "turret-1",
                "position": {"x": float(i), "y": float(i)},
                "method": "nerf_dart",
            })

        events = _drain_tactical(sens)
        elim_events = [e for e in events if "eliminated" in e.text.lower()]
        assert len(elim_events) >= 2


# ===========================================================================
# 4. Tactical summary generation
# ===========================================================================

class TestTacticalSummary:
    """_generate_tactical_summary() produces battle overviews."""

    def test_tactical_summary_exists(self):
        """The function exists and returns a string."""
        from amy.commander import _generate_tactical_summary
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)
        result = _generate_tactical_summary(cmd)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_tactical_summary_mentions_wave(self):
        """Summary mentions the current wave number."""
        from amy.commander import _generate_tactical_summary
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)
        result = _generate_tactical_summary(cmd)
        assert "Wave" in result or "wave" in result

    def test_tactical_summary_mentions_score(self):
        """Summary includes the current score."""
        from amy.commander import _generate_tactical_summary
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)
        result = _generate_tactical_summary(cmd)
        assert "500" in result or "score" in result.lower()

    def test_tactical_summary_empty_when_idle(self):
        """No summary when game is not active."""
        from amy.commander import _generate_tactical_summary
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=False)
        result = _generate_tactical_summary(cmd)
        assert result == "" or result is None

    def test_tactical_summary_interval_honored(self):
        """Summary not generated more often than every 5 seconds."""
        from amy.commander import _maybe_generate_tactical_summary
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        # First call should produce summary
        result1 = _maybe_generate_tactical_summary(cmd)
        assert result1 is True

        # Immediate second call should be throttled
        result2 = _maybe_generate_tactical_summary(cmd)
        assert result2 is False

    def test_tactical_summary_pushed_to_sensorium(self):
        """When generated, summary is pushed into sensorium."""
        from amy.commander import _maybe_generate_tactical_summary
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        _maybe_generate_tactical_summary(cmd)

        events = _drain_tactical(sens)
        assert len(events) >= 1

    def test_tactical_summary_importance(self):
        """Summary has importance 0.5."""
        from amy.commander import _maybe_generate_tactical_summary
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        _maybe_generate_tactical_summary(cmd)

        events = _drain_tactical(sens)
        summary_events = [e for e in events if "wave" in e.text.lower() or "Wave" in e.text]
        assert len(summary_events) >= 1
        assert summary_events[0].importance == pytest.approx(0.5, abs=0.01)


# ===========================================================================
# 5. Unit health status from telemetry
# ===========================================================================

class TestUnitHealthStatus:
    """sim_telemetry processing generates health warnings."""

    def test_low_health_unit_generates_warning(self):
        """A unit below 50% health triggers a sensorium warning."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _check_unit_health
        _check_unit_health(cmd, {
            "target_id": "turret-1",
            "name": "Turret-Alpha",
            "alliance": "friendly",
            "health": 30.0,
            "max_health": 200.0,
            "status": "active",
            "is_combatant": True,
        })

        events = _drain_tactical(sens)
        assert len(events) >= 1
        assert any("Turret-Alpha" in e.text for e in events)
        health_events = [e for e in events if "health" in e.text.lower() or "damage" in e.text.lower()]
        assert len(health_events) >= 1
        assert health_events[0].importance >= 0.5

    def test_healthy_unit_no_warning(self):
        """A unit above 50% health triggers no warning."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _check_unit_health
        _check_unit_health(cmd, {
            "target_id": "turret-1",
            "name": "Turret-Alpha",
            "alliance": "friendly",
            "health": 180.0,
            "max_health": 200.0,
            "status": "active",
            "is_combatant": True,
        })

        events = _drain_tactical(sens)
        health_events = [e for e in events if "health" in e.text.lower() or "damage" in e.text.lower()]
        assert len(health_events) == 0

    def test_hostile_health_not_tracked(self):
        """Hostile unit health does not generate friendly health warnings."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _check_unit_health
        _check_unit_health(cmd, {
            "target_id": "hostile-1",
            "name": "Intruder Alpha",
            "alliance": "hostile",
            "health": 10.0,
            "max_health": 80.0,
            "status": "active",
            "is_combatant": True,
        })

        events = _drain_tactical(sens)
        # Should not generate a health warning for hostiles
        health_events = [e for e in events if "health" in e.text.lower() and "Intruder" in e.text]
        assert len(health_events) == 0

    def test_eliminated_unit_no_duplicate_warning(self):
        """Eliminated units don't generate health warnings."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _check_unit_health
        _check_unit_health(cmd, {
            "target_id": "turret-1",
            "name": "Turret-Alpha",
            "alliance": "friendly",
            "health": 0.0,
            "max_health": 200.0,
            "status": "eliminated",
            "is_combatant": True,
        })

        events = _drain_tactical(sens)
        health_events = [e for e in events if "health" in e.text.lower()]
        assert len(health_events) == 0

    def test_health_warning_throttled(self):
        """Health warnings for the same unit are throttled."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _check_unit_health

        # First warning
        _check_unit_health(cmd, {
            "target_id": "turret-1",
            "name": "Turret-Alpha",
            "alliance": "friendly",
            "health": 30.0,
            "max_health": 200.0,
            "status": "active",
            "is_combatant": True,
        })
        count1 = len(_drain_tactical(sens))

        # Immediate second — should be throttled
        _check_unit_health(cmd, {
            "target_id": "turret-1",
            "name": "Turret-Alpha",
            "alliance": "friendly",
            "health": 25.0,
            "max_health": 200.0,
            "status": "active",
            "is_combatant": True,
        })
        count2 = len(_drain_tactical(sens))

        # Should not have doubled
        assert count2 <= count1 + 1


# ===========================================================================
# 6. No observations when game is idle
# ===========================================================================

class TestIdleGameNoObservations:
    """No tactical combat observations during idle game state."""

    def test_no_combat_events_when_idle(self):
        """Combat events do not generate observations when game is setup."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=False)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "projectile_fired", {
            "source_name": "Turret-Alpha",
            "target_id": "hostile-1",
            "source_id": "turret-1",
            "projectile_type": "nerf_dart",
        })

        events = _drain_tactical(sens)
        fire_events = [e for e in events if "fire" in e.text.lower()]
        assert len(fire_events) == 0

    def test_no_tactical_summary_when_idle(self):
        """No tactical summary generated when game is idle."""
        from amy.commander import _maybe_generate_tactical_summary
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=False)

        result = _maybe_generate_tactical_summary(cmd)
        assert result is False

        events = _drain_tactical(sens)
        assert len(events) == 0

    def test_health_warnings_only_during_combat(self):
        """Health warnings suppressed when game is not active."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=False)

        from amy.commander import _check_unit_health
        _check_unit_health(cmd, {
            "target_id": "turret-1",
            "name": "Turret-Alpha",
            "alliance": "friendly",
            "health": 10.0,
            "max_health": 200.0,
            "status": "active",
            "is_combatant": True,
        })

        events = _drain_tactical(sens)
        health_events = [e for e in events if "health" in e.text.lower()]
        assert len(health_events) == 0


# ===========================================================================
# 7. Event type classification
# ===========================================================================

class TestEventClassification:
    """Events are correctly classified as combat vs tactical vs status."""

    def test_combat_events_classified(self):
        """projectile_fired, projectile_hit, target_eliminated are combat events."""
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("projectile_fired") == "combat"
        assert classify_tactical_event("projectile_hit") == "combat"
        assert classify_tactical_event("target_eliminated") == "combat"

    def test_tactical_events_classified(self):
        """wave_stats_summary, elimination_streak are tactical events."""
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("elimination_streak") == "tactical"
        assert classify_tactical_event("wave_stats_summary") == "tactical"
        assert classify_tactical_event("combat_stats_update") == "tactical"

    def test_status_events_classified(self):
        """ammo_low is a status event."""
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("ammo_low") == "status"

    def test_unknown_events_classified(self):
        """Unknown events return 'unknown'."""
        from amy.commander import classify_tactical_event
        assert classify_tactical_event("some_random_event") == "unknown"


# ===========================================================================
# 8. Thinking context includes tactical situation
# ===========================================================================

class TestThinkingTacticalContext:
    """ThinkingThread provides TACTICAL SITUATION when combat is active."""

    def test_build_tactical_context_exists(self):
        """build_tactical_context function exists."""
        from amy.commander import build_tactical_context
        assert callable(build_tactical_context)

    def test_tactical_context_empty_when_idle(self):
        """No tactical context when game is idle."""
        from amy.commander import build_tactical_context
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=False)
        result = build_tactical_context(cmd)
        assert result == ""

    def test_tactical_context_present_when_active(self):
        """Tactical context includes section header when combat active."""
        from amy.commander import build_tactical_context
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)
        result = build_tactical_context(cmd)
        assert "TACTICAL SITUATION" in result

    def test_tactical_context_includes_wave(self):
        """Tactical context includes current wave info."""
        from amy.commander import build_tactical_context
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)
        result = build_tactical_context(cmd)
        assert "Wave" in result or "wave" in result

    def test_tactical_context_includes_score(self):
        """Tactical context includes current score."""
        from amy.commander import build_tactical_context
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)
        result = build_tactical_context(cmd)
        assert "500" in result or "score" in result.lower()

    def test_tactical_context_recent_events_section(self):
        """Tactical context has a section for recent combat events."""
        from amy.commander import build_tactical_context, _handle_combat_event
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        # Inject some combat events first
        _handle_combat_event(cmd, "target_eliminated", {
            "target_name": "Intruder Alpha",
            "interceptor_name": "Turret-Alpha",
            "target_id": "h1",
            "interceptor_id": "t1",
            "position": {"x": 0, "y": 0},
            "method": "nerf_dart",
        })

        result = build_tactical_context(cmd)
        assert "Recent" in result or "recent" in result or "event" in result.lower()


# ===========================================================================
# 9. Integration: bridge loop processes combat events
# ===========================================================================

class TestBridgeLoopIntegration:
    """The _sim_bridge_loop correctly routes new event types."""

    def test_bridge_routes_projectile_hit(self):
        """projectile_hit on the EventBus reaches sensorium via bridge."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        # Publish event to the bus
        bus.publish("projectile_hit", {
            "source_id": "turret-1",
            "target_name": "Intruder Alpha",
            "damage": 15.0,
            "remaining_health": 65.0,
        })

        # Process one event through the bridge
        from amy.commander import _process_bridge_message
        msg = cmd._sim_sub.get(timeout=1.0)
        _process_bridge_message(cmd, msg)

        events = _drain_tactical(sens)
        assert len(events) >= 1

    def test_bridge_routes_target_eliminated(self):
        """target_eliminated on the EventBus reaches sensorium via bridge."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        bus.publish("target_eliminated", {
            "target_name": "Intruder Bravo",
            "interceptor_name": "Turret-Alpha",
            "target_id": "h2",
            "interceptor_id": "t1",
            "position": {"x": 10, "y": 20},
            "method": "nerf_dart",
        })

        from amy.commander import _process_bridge_message
        msg = cmd._sim_sub.get(timeout=1.0)
        _process_bridge_message(cmd, msg)

        events = _drain_tactical(sens)
        assert any("eliminated" in e.text.lower() for e in events)

    def test_bridge_routes_elimination_streak(self):
        """elimination_streak on the EventBus reaches sensorium via bridge."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        bus.publish("elimination_streak", {
            "interceptor_name": "Turret-Alpha",
            "interceptor_id": "t1",
            "streak": 5,
            "streak_name": "RAMPAGE",
        })

        from amy.commander import _process_bridge_message
        msg = cmd._sim_sub.get(timeout=1.0)
        _process_bridge_message(cmd, msg)

        events = _drain_tactical(sens)
        assert any("streak" in e.text.lower() or "RAMPAGE" in e.text for e in events)


# ===========================================================================
# 10. Recent combat events buffer
# ===========================================================================

class TestRecentCombatEventsBuffer:
    """A buffer of recent combat events is maintained for thinking context."""

    def test_recent_events_buffer_exists(self):
        """Commander has a _recent_combat_events list."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)
        assert hasattr(cmd, '_recent_combat_events')
        assert isinstance(cmd._recent_combat_events, list)

    def test_combat_events_added_to_buffer(self):
        """Combat events are tracked in the buffer."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        _handle_combat_event(cmd, "target_eliminated", {
            "target_name": "Intruder Alpha",
            "interceptor_name": "Turret-Alpha",
            "target_id": "h1",
            "interceptor_id": "t1",
            "position": {"x": 0, "y": 0},
            "method": "nerf_dart",
        })

        assert len(cmd._recent_combat_events) >= 1

    def test_buffer_capped_at_20(self):
        """Buffer does not grow beyond 20 entries."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event
        for i in range(30):
            time.sleep(0.01)
            _handle_combat_event(cmd, "projectile_hit", {
                "source_id": f"t-{i}",
                "target_name": f"Intruder {i}",
                "damage": 10.0,
                "remaining_health": 50.0,
            })

        assert len(cmd._recent_combat_events) <= 20

    def test_buffer_cleared_on_game_reset(self):
        """Buffer is cleared when game returns to setup."""
        bus = EventBus()
        sens = Sensorium()
        cmd = _make_commander(bus, sens, game_active=True)

        from amy.commander import _handle_combat_event, _clear_combat_state
        _handle_combat_event(cmd, "target_eliminated", {
            "target_name": "Intruder Alpha",
            "interceptor_name": "Turret-Alpha",
            "target_id": "h1",
            "interceptor_id": "t1",
            "position": {"x": 0, "y": 0},
            "method": "nerf_dart",
        })
        assert len(cmd._recent_combat_events) >= 1

        _clear_combat_state(cmd)
        assert len(cmd._recent_combat_events) == 0
