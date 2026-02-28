# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for StatsTracker — after-action statistics system.

TDD: Write all tests first, run them (all fail), then implement.
Tests cover: UnitStats creation, computed properties, StatsTracker
registration, shot/kill/assist tracking, wave stats, movement,
time tracking, MVP, summary, serialization, and reset.
"""

from __future__ import annotations

import math
import time

import pytest

from engine.simulation.stats import StatsTracker, UnitStats, WaveStats

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker() -> StatsTracker:
    """Create a StatsTracker with no event bus (unit test mode)."""
    return StatsTracker()


def _register_turret(tracker: StatsTracker, tid: str = "t1") -> None:
    tracker.register_unit(tid, "Turret Alpha", "friendly", "turret")


def _register_hostile(tracker: StatsTracker, tid: str = "h1") -> None:
    tracker.register_unit(tid, "Intruder Alpha", "hostile", "person")


# ---------------------------------------------------------------------------
# UnitStats creation and defaults
# ---------------------------------------------------------------------------

class TestUnitStatsCreation:
    def test_default_values(self):
        us = UnitStats(target_id="t1", name="Turret", alliance="friendly", asset_type="turret")
        assert us.shots_fired == 0
        assert us.shots_hit == 0
        assert us.damage_dealt == 0.0
        assert us.damage_taken == 0.0
        assert us.kills == 0
        assert us.deaths == 0
        assert us.assists == 0
        assert us.distance_traveled == 0.0
        assert us.max_speed_reached == 0.0
        assert us.time_alive == 0.0
        assert us.time_in_combat == 0.0
        assert us.health_remaining == 0.0

    def test_fields_present(self):
        us = UnitStats(target_id="r1", name="Rover", alliance="friendly", asset_type="rover")
        assert us.target_id == "r1"
        assert us.name == "Rover"
        assert us.alliance == "friendly"
        assert us.asset_type == "rover"


# ---------------------------------------------------------------------------
# UnitStats computed properties — accuracy
# ---------------------------------------------------------------------------

class TestUnitStatsAccuracy:
    def test_accuracy_zero_shots(self):
        us = UnitStats(target_id="t1", name="T", alliance="friendly", asset_type="turret")
        assert us.accuracy == 0.0

    def test_accuracy_all_hit(self):
        us = UnitStats(target_id="t1", name="T", alliance="friendly", asset_type="turret")
        us.shots_fired = 10
        us.shots_hit = 10
        assert us.accuracy == 1.0

    def test_accuracy_partial(self):
        us = UnitStats(target_id="t1", name="T", alliance="friendly", asset_type="turret")
        us.shots_fired = 4
        us.shots_hit = 3
        assert us.accuracy == pytest.approx(0.75)

    def test_accuracy_no_hits(self):
        us = UnitStats(target_id="t1", name="T", alliance="friendly", asset_type="turret")
        us.shots_fired = 5
        us.shots_hit = 0
        assert us.accuracy == 0.0


# ---------------------------------------------------------------------------
# UnitStats computed properties — KD ratio
# ---------------------------------------------------------------------------

class TestUnitStatsKDRatio:
    def test_kd_zero_deaths(self):
        us = UnitStats(target_id="t1", name="T", alliance="friendly", asset_type="turret")
        us.kills = 5
        us.deaths = 0
        assert us.kd_ratio == 5.0  # float(kills) when 0 deaths

    def test_kd_zero_kills_zero_deaths(self):
        us = UnitStats(target_id="t1", name="T", alliance="friendly", asset_type="turret")
        assert us.kd_ratio == 0.0

    def test_kd_normal(self):
        us = UnitStats(target_id="t1", name="T", alliance="friendly", asset_type="turret")
        us.kills = 6
        us.deaths = 2
        assert us.kd_ratio == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# UnitStats computed properties — damage efficiency
# ---------------------------------------------------------------------------

class TestUnitStatsDamageEfficiency:
    def test_efficiency_no_damage(self):
        us = UnitStats(target_id="t1", name="T", alliance="friendly", asset_type="turret")
        assert us.damage_efficiency == 0.0

    def test_efficiency_dealt_no_taken(self):
        us = UnitStats(target_id="t1", name="T", alliance="friendly", asset_type="turret")
        us.damage_dealt = 100.0
        us.damage_taken = 0.0
        assert us.damage_efficiency == float("inf")

    def test_efficiency_normal(self):
        us = UnitStats(target_id="t1", name="T", alliance="friendly", asset_type="turret")
        us.damage_dealt = 200.0
        us.damage_taken = 50.0
        assert us.damage_efficiency == pytest.approx(4.0)

    def test_efficiency_taken_more(self):
        us = UnitStats(target_id="t1", name="T", alliance="friendly", asset_type="turret")
        us.damage_dealt = 30.0
        us.damage_taken = 60.0
        assert us.damage_efficiency == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# StatsTracker — register
# ---------------------------------------------------------------------------

class TestStatsTrackerRegister:
    def test_register_unit(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        stats = tracker.get_unit_stats("t1")
        assert stats is not None
        assert stats.target_id == "t1"
        assert stats.name == "Turret Alpha"
        assert stats.alliance == "friendly"
        assert stats.asset_type == "turret"

    def test_register_multiple_units(self):
        tracker = _make_tracker()
        _register_turret(tracker, "t1")
        _register_hostile(tracker, "h1")
        assert tracker.get_unit_stats("t1") is not None
        assert tracker.get_unit_stats("h1") is not None

    def test_get_nonexistent_returns_none(self):
        tracker = _make_tracker()
        assert tracker.get_unit_stats("nonexistent") is None

    def test_register_overwrites(self):
        tracker = _make_tracker()
        tracker.register_unit("t1", "Old Name", "friendly", "turret")
        tracker.register_unit("t1", "New Name", "friendly", "turret")
        assert tracker.get_unit_stats("t1").name == "New Name"


# ---------------------------------------------------------------------------
# StatsTracker — shot fired
# ---------------------------------------------------------------------------

class TestShotFired:
    def test_increments_shots_fired(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        tracker.on_shot_fired("t1")
        assert tracker.get_unit_stats("t1").shots_fired == 1

    def test_multiple_shots(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        for _ in range(5):
            tracker.on_shot_fired("t1")
        assert tracker.get_unit_stats("t1").shots_fired == 5

    def test_unregistered_unit_no_crash(self):
        tracker = _make_tracker()
        tracker.on_shot_fired("ghost")  # Should not raise


# ---------------------------------------------------------------------------
# StatsTracker — shot hit
# ---------------------------------------------------------------------------

class TestShotHit:
    def test_increments_shots_hit(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        _register_hostile(tracker)
        tracker.on_shot_hit("t1", "h1", 15.0)
        stats = tracker.get_unit_stats("t1")
        assert stats.shots_hit == 1
        assert stats.damage_dealt == 15.0

    def test_target_receives_damage(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        _register_hostile(tracker)
        tracker.on_shot_hit("t1", "h1", 15.0)
        target_stats = tracker.get_unit_stats("h1")
        assert target_stats.damage_taken == 15.0

    def test_multiple_hits_accumulate(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        _register_hostile(tracker)
        tracker.on_shot_hit("t1", "h1", 10.0)
        tracker.on_shot_hit("t1", "h1", 20.0)
        assert tracker.get_unit_stats("t1").damage_dealt == 30.0
        assert tracker.get_unit_stats("h1").damage_taken == 30.0

    def test_unregistered_shooter_no_crash(self):
        tracker = _make_tracker()
        _register_hostile(tracker)
        tracker.on_shot_hit("ghost", "h1", 10.0)  # Should not raise


# ---------------------------------------------------------------------------
# StatsTracker — kill
# ---------------------------------------------------------------------------

class TestKill:
    def test_kill_increments_killer(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        _register_hostile(tracker)
        tracker.on_kill("t1", "h1")
        assert tracker.get_unit_stats("t1").kills == 1

    def test_kill_sets_death(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        _register_hostile(tracker)
        tracker.on_kill("t1", "h1")
        assert tracker.get_unit_stats("h1").deaths == 1

    def test_multiple_kills(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        tracker.register_unit("h1", "Hostile 1", "hostile", "person")
        tracker.register_unit("h2", "Hostile 2", "hostile", "person")
        tracker.on_kill("t1", "h1")
        tracker.on_kill("t1", "h2")
        assert tracker.get_unit_stats("t1").kills == 2

    def test_unregistered_killer_no_crash(self):
        tracker = _make_tracker()
        _register_hostile(tracker)
        tracker.on_kill("ghost", "h1")  # Should not raise


# ---------------------------------------------------------------------------
# StatsTracker — damage taken
# ---------------------------------------------------------------------------

class TestDamageTaken:
    def test_damage_taken_increments(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        tracker.on_damage_taken("t1", 25.0)
        assert tracker.get_unit_stats("t1").damage_taken == 25.0

    def test_damage_taken_accumulates(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        tracker.on_damage_taken("t1", 10.0)
        tracker.on_damage_taken("t1", 15.0)
        assert tracker.get_unit_stats("t1").damage_taken == 25.0

    def test_unregistered_no_crash(self):
        tracker = _make_tracker()
        tracker.on_damage_taken("ghost", 10.0)  # Should not raise


# ---------------------------------------------------------------------------
# StatsTracker — assist tracking
# ---------------------------------------------------------------------------

class TestAssistTracking:
    def test_assist_within_window(self):
        """If unit A damages target, and unit B kills it within 5s, A gets assist."""
        tracker = _make_tracker()
        tracker.register_unit("a1", "Attacker A", "friendly", "turret")
        tracker.register_unit("b1", "Attacker B", "friendly", "turret")
        _register_hostile(tracker)

        # A hits the target
        tracker.on_shot_hit("a1", "h1", 10.0)
        # B kills the target within the assist window
        tracker.on_kill("b1", "h1")

        assert tracker.get_unit_stats("a1").assists == 1
        assert tracker.get_unit_stats("b1").assists == 0  # Killer doesn't get assist

    def test_multiple_assisters(self):
        """Multiple units that damaged the target get assists."""
        tracker = _make_tracker()
        tracker.register_unit("a1", "A", "friendly", "turret")
        tracker.register_unit("a2", "B", "friendly", "turret")
        tracker.register_unit("killer", "Killer", "friendly", "turret")
        _register_hostile(tracker)

        tracker.on_shot_hit("a1", "h1", 5.0)
        tracker.on_shot_hit("a2", "h1", 5.0)
        tracker.on_kill("killer", "h1")

        assert tracker.get_unit_stats("a1").assists == 1
        assert tracker.get_unit_stats("a2").assists == 1
        assert tracker.get_unit_stats("killer").assists == 0


class TestAssistExpiry:
    def test_no_assist_after_window(self):
        """Damage older than 5 seconds should not grant an assist."""
        tracker = _make_tracker()
        tracker.register_unit("a1", "Attacker A", "friendly", "turret")
        tracker.register_unit("killer", "Killer", "friendly", "turret")
        _register_hostile(tracker)

        # Record damage with a timestamp in the past (beyond 5s window)
        tracker.on_shot_hit("a1", "h1", 10.0, timestamp=time.monotonic() - 6.0)
        tracker.on_kill("killer", "h1")

        assert tracker.get_unit_stats("a1").assists == 0

    def test_mixed_window(self):
        """One assist within window, one outside -- only recent counts."""
        tracker = _make_tracker()
        tracker.register_unit("old", "Old Attacker", "friendly", "turret")
        tracker.register_unit("new", "New Attacker", "friendly", "turret")
        tracker.register_unit("killer", "Killer", "friendly", "turret")
        _register_hostile(tracker)

        now = time.monotonic()
        tracker.on_shot_hit("old", "h1", 10.0, timestamp=now - 6.0)  # expired
        tracker.on_shot_hit("new", "h1", 10.0, timestamp=now - 1.0)  # recent
        tracker.on_kill("killer", "h1")

        assert tracker.get_unit_stats("old").assists == 0
        assert tracker.get_unit_stats("new").assists == 1


# ---------------------------------------------------------------------------
# StatsTracker — wave stats
# ---------------------------------------------------------------------------

class TestWaveStats:
    def test_wave_start(self):
        tracker = _make_tracker()
        tracker.on_wave_start(1, "Scout Party", 3)
        waves = tracker.get_wave_stats()
        assert len(waves) == 1
        assert waves[0].wave_number == 1
        assert waves[0].wave_name == "Scout Party"
        assert waves[0].hostiles_spawned == 3

    def test_wave_complete(self):
        tracker = _make_tracker()
        tracker.on_wave_start(1, "Scout Party", 3)
        tracker.on_wave_complete(score=500)
        waves = tracker.get_wave_stats()
        assert waves[0].score_earned == 500


class TestWaveStatsAggregates:
    def test_wave_tracks_shots_and_damage(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        _register_hostile(tracker)

        tracker.on_wave_start(1, "Scout Party", 3)
        tracker.on_shot_fired("t1")
        tracker.on_shot_fired("t1")
        tracker.on_shot_hit("t1", "h1", 15.0)
        tracker.on_wave_complete(score=300)

        wave = tracker.get_wave_stats()[0]
        assert wave.total_shots_fired == 2
        assert wave.total_shots_hit == 1
        assert wave.total_damage_dealt == 15.0

    def test_wave_tracks_eliminations(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        _register_hostile(tracker)

        tracker.on_wave_start(1, "Scout Party", 3)
        tracker.on_kill("t1", "h1")
        tracker.on_wave_complete(score=300)

        wave = tracker.get_wave_stats()[0]
        assert wave.hostiles_eliminated == 1


class TestMultipleWaves:
    def test_two_waves(self):
        tracker = _make_tracker()
        _register_turret(tracker)

        # Wave 1
        tracker.register_unit("h1", "H1", "hostile", "person")
        tracker.on_wave_start(1, "Scout Party", 3)
        tracker.on_shot_fired("t1")
        tracker.on_kill("t1", "h1")
        tracker.on_wave_complete(score=300)

        # Wave 2
        tracker.register_unit("h2", "H2", "hostile", "person")
        tracker.on_wave_start(2, "Raiding Party", 5)
        tracker.on_shot_fired("t1")
        tracker.on_shot_fired("t1")
        tracker.on_kill("t1", "h2")
        tracker.on_wave_complete(score=600)

        waves = tracker.get_wave_stats()
        assert len(waves) == 2
        assert waves[0].wave_number == 1
        assert waves[1].wave_number == 2
        assert waves[1].total_shots_fired == 2

    def test_stats_persist_across_waves(self):
        """Unit stats accumulate across waves (not reset per wave)."""
        tracker = _make_tracker()
        _register_turret(tracker)
        tracker.register_unit("h1", "H1", "hostile", "person")
        tracker.register_unit("h2", "H2", "hostile", "person")

        tracker.on_wave_start(1, "W1", 1)
        tracker.on_kill("t1", "h1")
        tracker.on_wave_complete(score=100)

        tracker.on_wave_start(2, "W2", 1)
        tracker.on_kill("t1", "h2")
        tracker.on_wave_complete(score=200)

        assert tracker.get_unit_stats("t1").kills == 2


# ---------------------------------------------------------------------------
# StatsTracker — distance traveled
# ---------------------------------------------------------------------------

class TestDistanceTraveled:
    def test_movement_tracking(self):
        """Distance traveled should accumulate from position changes per tick."""
        tracker = _make_tracker()
        _register_turret(tracker, "r1")

        class FakeTargetStart:
            target_id = "r1"
            position = (0.0, 0.0)
            status = "active"
            speed = 2.0
            weapon_range = 15.0
            alliance = "friendly"

        class FakeTargetMoved:
            target_id = "r1"
            position = (3.0, 4.0)
            status = "active"
            speed = 2.0
            weapon_range = 15.0
            alliance = "friendly"

        # First tick initializes position
        tracker.tick(0.1, {"r1": FakeTargetStart()})
        # Second tick: moved from (0,0) to (3,4) — distance = 5.0
        tracker.tick(0.1, {"r1": FakeTargetMoved()})

        stats = tracker.get_unit_stats("r1")
        assert stats.distance_traveled == pytest.approx(5.0)

    def test_stationary_no_distance(self):
        """No distance for targets that don't move."""
        tracker = _make_tracker()
        _register_turret(tracker, "t1")

        class FakeTarget:
            target_id = "t1"
            position = (0.0, 0.0)
            status = "active"
            speed = 0.0
            weapon_range = 15.0
            alliance = "friendly"

        targets = {"t1": FakeTarget()}
        # Set initial position to match
        tracker._last_positions["t1"] = (0.0, 0.0)
        tracker.tick(0.1, targets)

        stats = tracker.get_unit_stats("t1")
        assert stats.distance_traveled == 0.0


# ---------------------------------------------------------------------------
# StatsTracker — time alive
# ---------------------------------------------------------------------------

class TestTimeAlive:
    def test_time_alive_accumulates(self):
        tracker = _make_tracker()
        _register_turret(tracker, "r1")

        class FakeTarget:
            target_id = "r1"
            position = (0.0, 0.0)
            status = "active"
            speed = 0.0
            weapon_range = 15.0
            alliance = "friendly"

        targets = {"r1": FakeTarget()}
        tracker.tick(0.1, targets)
        tracker.tick(0.1, targets)
        tracker.tick(0.1, targets)

        assert tracker.get_unit_stats("r1").time_alive == pytest.approx(0.3)

    def test_eliminated_stops_time(self):
        tracker = _make_tracker()
        _register_turret(tracker, "r1")

        class FakeTargetAlive:
            target_id = "r1"
            position = (0.0, 0.0)
            status = "active"
            speed = 0.0
            weapon_range = 15.0
            alliance = "friendly"

        class FakeTargetDead:
            target_id = "r1"
            position = (0.0, 0.0)
            status = "eliminated"
            speed = 0.0
            weapon_range = 15.0
            alliance = "friendly"

        tracker.tick(0.1, {"r1": FakeTargetAlive()})
        tracker.tick(0.1, {"r1": FakeTargetDead()})

        assert tracker.get_unit_stats("r1").time_alive == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# StatsTracker — time in combat
# ---------------------------------------------------------------------------

class TestTimeInCombat:
    def test_in_combat_with_enemy_in_range(self):
        tracker = _make_tracker()
        tracker.register_unit("t1", "Turret", "friendly", "turret")
        tracker.register_unit("h1", "Hostile", "hostile", "person")

        class FakeFriendly:
            target_id = "t1"
            position = (0.0, 0.0)
            status = "active"
            speed = 0.0
            weapon_range = 15.0
            alliance = "friendly"

        class FakeHostile:
            target_id = "h1"
            position = (10.0, 0.0)  # Within weapon_range of 15
            status = "active"
            speed = 3.0
            weapon_range = 10.0
            alliance = "hostile"

        targets = {"t1": FakeFriendly(), "h1": FakeHostile()}
        tracker.tick(0.1, targets)

        assert tracker.get_unit_stats("t1").time_in_combat == pytest.approx(0.1)

    def test_not_in_combat_no_enemies(self):
        tracker = _make_tracker()
        tracker.register_unit("t1", "Turret", "friendly", "turret")

        class FakeFriendly:
            target_id = "t1"
            position = (0.0, 0.0)
            status = "active"
            speed = 0.0
            weapon_range = 15.0
            alliance = "friendly"

        targets = {"t1": FakeFriendly()}
        tracker.tick(0.1, targets)

        assert tracker.get_unit_stats("t1").time_in_combat == 0.0

    def test_enemy_out_of_range_no_combat(self):
        tracker = _make_tracker()
        tracker.register_unit("t1", "Turret", "friendly", "turret")
        tracker.register_unit("h1", "Hostile", "hostile", "person")

        class FakeFriendly:
            target_id = "t1"
            position = (0.0, 0.0)
            status = "active"
            speed = 0.0
            weapon_range = 15.0
            alliance = "friendly"

        class FakeHostile:
            target_id = "h1"
            position = (50.0, 0.0)  # Way out of range
            status = "active"
            speed = 3.0
            weapon_range = 10.0
            alliance = "hostile"

        targets = {"t1": FakeFriendly(), "h1": FakeHostile()}
        tracker.tick(0.1, targets)

        assert tracker.get_unit_stats("t1").time_in_combat == 0.0


# ---------------------------------------------------------------------------
# StatsTracker — max speed
# ---------------------------------------------------------------------------

class TestMaxSpeed:
    def test_max_speed_recorded(self):
        tracker = _make_tracker()
        tracker.register_unit("r1", "Rover", "friendly", "rover")
        tracker._last_positions["r1"] = (0.0, 0.0)

        class FakeTarget:
            target_id = "r1"
            position = (5.0, 0.0)  # Moved 5 units in 0.1s = 50 u/s
            status = "active"
            speed = 5.0
            weapon_range = 10.0
            alliance = "friendly"

        targets = {"r1": FakeTarget()}
        tracker.tick(0.1, targets)

        assert tracker.get_unit_stats("r1").max_speed_reached == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# StatsTracker — MVP
# ---------------------------------------------------------------------------

class TestMVP:
    def test_mvp_most_kills(self):
        tracker = _make_tracker()
        tracker.register_unit("t1", "Turret A", "friendly", "turret")
        tracker.register_unit("t2", "Turret B", "friendly", "turret")
        tracker.register_unit("h1", "H1", "hostile", "person")
        tracker.register_unit("h2", "H2", "hostile", "person")
        tracker.register_unit("h3", "H3", "hostile", "person")

        tracker.on_kill("t1", "h1")
        tracker.on_kill("t2", "h2")
        tracker.on_kill("t2", "h3")

        mvp = tracker.get_mvp()
        assert mvp is not None
        assert mvp.target_id == "t2"
        assert mvp.kills == 2

    def test_mvp_no_kills(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        mvp = tracker.get_mvp()
        # When no kills, return the unit with the best stats (or None if no units)
        # With one unit and 0 kills, it should still return that unit
        assert mvp is not None
        assert mvp.kills == 0

    def test_mvp_empty(self):
        tracker = _make_tracker()
        assert tracker.get_mvp() is None


class TestMVPTiebreaker:
    def test_kills_tie_accuracy_wins(self):
        tracker = _make_tracker()
        tracker.register_unit("a", "Unit A", "friendly", "turret")
        tracker.register_unit("b", "Unit B", "friendly", "turret")
        tracker.register_unit("h1", "H1", "hostile", "person")
        tracker.register_unit("h2", "H2", "hostile", "person")

        # Both get 1 kill, but A has better accuracy
        tracker.on_shot_fired("a")
        tracker.on_shot_hit("a", "h1", 10.0)
        tracker.on_kill("a", "h1")  # A: 1 shot, 1 hit, accuracy = 1.0

        tracker.on_shot_fired("b")
        tracker.on_shot_fired("b")
        tracker.on_shot_hit("b", "h2", 10.0)
        tracker.on_kill("b", "h2")  # B: 2 shots, 1 hit, accuracy = 0.5

        mvp = tracker.get_mvp()
        assert mvp is not None
        assert mvp.target_id == "a"


# ---------------------------------------------------------------------------
# StatsTracker — get_summary
# ---------------------------------------------------------------------------

class TestGetSummary:
    def test_summary_dict_format(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        _register_hostile(tracker)

        tracker.on_wave_start(1, "Scout Party", 3)
        tracker.on_shot_fired("t1")
        tracker.on_shot_hit("t1", "h1", 15.0)
        tracker.on_kill("t1", "h1")
        tracker.on_wave_complete(score=300)

        summary = tracker.get_summary()
        assert "total_kills" in summary
        assert "total_deaths" in summary
        assert "total_shots_fired" in summary
        assert "total_shots_hit" in summary
        assert "overall_accuracy" in summary
        assert "total_damage_dealt" in summary
        assert "total_damage_taken" in summary
        assert "waves_completed" in summary
        assert "mvp" in summary
        assert "unit_count" in summary

    def test_summary_values(self):
        tracker = _make_tracker()
        tracker.register_unit("t1", "Turret", "friendly", "turret")
        tracker.register_unit("h1", "H1", "hostile", "person")

        tracker.on_shot_fired("t1")
        tracker.on_shot_fired("t1")
        tracker.on_shot_hit("t1", "h1", 20.0)
        tracker.on_kill("t1", "h1")

        summary = tracker.get_summary()
        assert summary["total_kills"] == 1
        assert summary["total_deaths"] == 1  # h1 died
        assert summary["total_shots_fired"] == 2
        assert summary["total_shots_hit"] == 1
        assert summary["overall_accuracy"] == pytest.approx(0.5)
        assert summary["total_damage_dealt"] == 20.0


# ---------------------------------------------------------------------------
# StatsTracker — reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_all(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        _register_hostile(tracker)
        tracker.on_shot_fired("t1")
        tracker.on_kill("t1", "h1")
        tracker.on_wave_start(1, "W1", 3)
        tracker.on_wave_complete(score=100)

        tracker.reset()

        assert tracker.get_unit_stats("t1") is None
        assert tracker.get_all_unit_stats() == []
        assert tracker.get_wave_stats() == []
        assert tracker.get_mvp() is None


# ---------------------------------------------------------------------------
# StatsTracker — to_dict serialization
# ---------------------------------------------------------------------------

class TestToDict:
    def test_serializable(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        _register_hostile(tracker)
        tracker.on_wave_start(1, "Scout Party", 3)
        tracker.on_shot_fired("t1")
        tracker.on_shot_hit("t1", "h1", 15.0)
        tracker.on_kill("t1", "h1")
        tracker.on_wave_complete(score=300)

        d = tracker.to_dict()
        assert "units" in d
        assert "waves" in d
        assert "summary" in d
        assert isinstance(d["units"], list)
        assert isinstance(d["waves"], list)
        assert isinstance(d["summary"], dict)

    def test_unit_dict_fields(self):
        tracker = _make_tracker()
        _register_turret(tracker)
        tracker.on_shot_fired("t1")

        d = tracker.to_dict()
        unit = d["units"][0]
        assert unit["target_id"] == "t1"
        assert unit["shots_fired"] == 1
        assert "accuracy" in unit
        assert "kd_ratio" in unit
        assert "damage_efficiency" in unit


# ---------------------------------------------------------------------------
# StatsTracker — get_all_unit_stats sorted
# ---------------------------------------------------------------------------

class TestGetAllSorted:
    def test_sorted_by_kills_desc(self):
        tracker = _make_tracker()
        tracker.register_unit("a", "A", "friendly", "turret")
        tracker.register_unit("b", "B", "friendly", "turret")
        tracker.register_unit("c", "C", "friendly", "turret")
        tracker.register_unit("h1", "H1", "hostile", "person")
        tracker.register_unit("h2", "H2", "hostile", "person")
        tracker.register_unit("h3", "H3", "hostile", "person")

        tracker.on_kill("a", "h1")  # A: 1 kill
        tracker.on_kill("c", "h2")
        tracker.on_kill("c", "h3")  # C: 2 kills

        all_stats = tracker.get_all_unit_stats()
        # C (2 kills) should be first, A (1 kill) second
        kills_list = [s.kills for s in all_stats]
        assert kills_list == sorted(kills_list, reverse=True)


# ---------------------------------------------------------------------------
# StatsTracker — no stats / graceful handling
# ---------------------------------------------------------------------------

class TestNoStats:
    def test_shot_fired_unregistered(self):
        tracker = _make_tracker()
        tracker.on_shot_fired("ghost")
        assert tracker.get_unit_stats("ghost") is None

    def test_shot_hit_unregistered(self):
        tracker = _make_tracker()
        tracker.on_shot_hit("ghost_shooter", "ghost_target", 10.0)
        assert tracker.get_unit_stats("ghost_shooter") is None

    def test_kill_unregistered(self):
        tracker = _make_tracker()
        tracker.on_kill("ghost_killer", "ghost_victim")
        # No crash expected

    def test_damage_taken_unregistered(self):
        tracker = _make_tracker()
        tracker.on_damage_taken("ghost", 25.0)
        # No crash expected

    def test_tick_with_unregistered_target(self):
        tracker = _make_tracker()

        class FakeTarget:
            target_id = "unknown"
            position = (5.0, 5.0)
            status = "active"
            speed = 2.0
            weapon_range = 15.0
            alliance = "friendly"

        targets = {"unknown": FakeTarget()}
        tracker.tick(0.1, targets)  # No crash expected


# ---------------------------------------------------------------------------
# StatsTracker — health remaining
# ---------------------------------------------------------------------------

class TestHealthRemaining:
    def test_health_updated_on_tick(self):
        tracker = _make_tracker()
        tracker.register_unit("t1", "Turret", "friendly", "turret")

        class FakeTarget:
            target_id = "t1"
            position = (0.0, 0.0)
            status = "active"
            speed = 0.0
            weapon_range = 15.0
            alliance = "friendly"
            health = 75.0
            max_health = 100.0

        targets = {"t1": FakeTarget()}
        tracker.tick(0.1, targets)

        assert tracker.get_unit_stats("t1").health_remaining == 75.0


# ---------------------------------------------------------------------------
# StatsTracker — wave escaped and friendly losses
# ---------------------------------------------------------------------------

class TestWaveEscapedAndLosses:
    def test_hostile_escaped_tracked(self):
        tracker = _make_tracker()
        tracker.on_wave_start(1, "W1", 3)
        tracker.on_hostile_escaped()
        tracker.on_wave_complete(score=100)

        wave = tracker.get_wave_stats()[0]
        assert wave.hostiles_escaped == 1

    def test_friendly_loss_tracked(self):
        tracker = _make_tracker()
        tracker.on_wave_start(1, "W1", 3)
        tracker.on_friendly_loss()
        tracker.on_wave_complete(score=100)

        wave = tracker.get_wave_stats()[0]
        assert wave.friendly_losses == 1


# ---------------------------------------------------------------------------
# StatsTracker — wave duration
# ---------------------------------------------------------------------------

class TestWaveDuration:
    def test_wave_duration_recorded(self):
        tracker = _make_tracker()
        tracker.on_wave_start(1, "W1", 3)
        # Simulate some elapsed time
        if tracker._current_wave is not None:
            tracker._wave_start_time = time.monotonic() - 10.0
        tracker.on_wave_complete(score=100)

        wave = tracker.get_wave_stats()[0]
        assert wave.duration >= 9.5  # At least ~10s, allow small variance
