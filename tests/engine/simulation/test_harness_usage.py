# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Combat scenario tests using SimulationTestHarness.

Note on combat distances: Projectiles are semi-guided (track target's
current position) with HIT_RADIUS of 5.0 units.  Misses occur after
5 seconds of flight time.  Tests place units within weapon range and
run enough ticks for projectiles to reach targets.
"""

from __future__ import annotations

import pytest

from tests.engine.simulation.test_harness import SimulationTestHarness


pytestmark = pytest.mark.unit


class TestCombatScenarios:
    """End-to-end combat scenarios driven by the test harness."""

    def test_turret_fires_at_hostile_in_range(self):
        """Turret at origin, hostile at (15,0) within weapon range -> projectile_fired."""
        h = SimulationTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.spawn_hostile("hostile-1", 15, 0)
        h.run_ticks(20)
        h.assert_event("projectile_fired")

    def test_turret_no_fire_outside_range(self):
        """Turret at origin range=80, hostile at (85,0) -> no fire."""
        h = SimulationTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.spawn_hostile("hostile-1", 85, 0)
        h.run_ticks(20)
        h.assert_no_event("projectile_fired")

    def test_hostile_eliminated_at_close_range(self):
        """Hostile 2 units from turret -> hit, damage, eliminated."""
        h = SimulationTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        # Place hostile close enough for projectile hits (within MISS_OVERSHOOT)
        h.spawn_hostile("hostile-1", 2, 0)
        h.run_ticks(200)
        h.assert_event("target_eliminated")
        h.assert_target_eliminated("hostile-1")

    def test_projectile_hit_event_close_range(self):
        """Turret fires at close range -> projectile_hit event."""
        h = SimulationTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.spawn_hostile("hostile-1", 2, 0)
        h.run_ticks(50)
        h.assert_event("projectile_hit")

    def test_hostile_walks_into_range_and_is_hit(self):
        """Hostile starts far away, walks toward turret, eventually takes damage."""
        h = SimulationTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        # Hostile starts at (10,0), walks toward (0,0) at 1.5 u/s
        # Reaches close range (~3 units) after ~47 ticks
        hostile = h.spawn_hostile("hostile-1", 10, 0)
        h.run_ticks(150)  # 15 simulated seconds — plenty of time to close distance
        h.assert_event("projectile_hit")

    def test_hostile_damages_friendly_close_range(self):
        """Hostile person walking past turret fires back at it."""
        h = SimulationTestHarness()
        # Hostile walks from (4,0) toward (-30,0), passing turret at origin.
        # While within hostile's weapon_range (8 units), it fires at the turret.
        h.place_friendly("turret-1", 0, 0, "turret")
        hostile = h.spawn_hostile("hostile-1", 4, 0)
        # Give the hostile a far waypoint so it stays active while passing through
        hostile.waypoints = [(-30.0, 0.0)]
        h.run_ticks(200)
        turret = h.get_target("turret-1")
        assert turret.health < turret.max_health, "Turret should have taken damage"

    def test_wave_scenario_multiple_hostiles(self):
        """Two turrets vs three hostiles -> combat events occur."""
        h = SimulationTestHarness()
        h.place_friendly("turret-1", -5, 0, "turret")
        h.place_friendly("turret-2", 5, 0, "turret")
        for i in range(3):
            h.spawn_hostile(f"hostile-{i}", 15, -5 + i * 5)
        h.run_ticks(200)
        h.assert_event("projectile_fired")

    def test_drone_fires_at_hostile(self):
        """Drone combatant fires at hostile in range."""
        h = SimulationTestHarness()
        h.place_friendly("drone-1", 0, 0, "drone")
        h.spawn_hostile("hostile-1", 8, 0)
        h.run_ticks(30)
        h.assert_event("projectile_fired")

    def test_rover_fires_at_hostile(self):
        """Rover combatant fires at hostile in range."""
        h = SimulationTestHarness()
        h.place_friendly("rover-1", 0, 0, "rover")
        h.spawn_hostile("hostile-1", 8, 0)
        h.run_ticks(30)
        h.assert_event("projectile_fired")

    def test_no_friendly_fire(self):
        """Two friendlies near each other should NOT fire at each other."""
        h = SimulationTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.place_friendly("turret-2", 5, 0, "turret")
        h.run_ticks(50)
        h.assert_no_event("projectile_fired")

    def test_eliminated_hostile_not_targeted_again(self):
        """Once eliminated, hostile does not receive further hits."""
        h = SimulationTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.spawn_hostile("hostile-1", 2, 0)
        # Run enough ticks to eliminate the hostile
        h.run_ticks(200)
        h.assert_target_eliminated("hostile-1")
        # Record hit count, run more ticks, verify no new hits on that target
        hits_before = h.event_count("projectile_hit")
        h.run_ticks(50)
        hits_after = h.event_count("projectile_hit")
        assert hits_after == hits_before, "No new hits should land on eliminated target"

    def test_event_count_increases_with_ticks(self):
        """More ticks with a hostile in range -> more fire events."""
        h = SimulationTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.spawn_hostile("hostile-1", 10, 0)
        h.run_ticks(10)
        count_10 = h.event_count("projectile_fired")
        h.run_ticks(30)
        count_40 = h.event_count("projectile_fired")
        assert count_40 >= count_10

    def test_target_health_decreases_close_range(self):
        """Hostile at close range takes damage from turret fire."""
        h = SimulationTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        hostile = h.spawn_hostile("hostile-1", 2, 0)
        initial_health = hostile.health
        h.run_ticks(50)
        assert hostile.health < initial_health, "Hostile should have taken damage"

    def test_elimination_streak_event(self):
        """Turret eliminates 3 hostiles -> elimination_streak event with streak >= 3."""
        h = SimulationTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        # Spawn 3 hostiles staggered: first close, others beyond hostile
        # weapon range (40m) but within turret range (80m).  This prevents
        # the turret from being overwhelmed by return fire.
        # Turret range=80, hostile range=40, projectile speed=80 m/s.
        # The turret fires at the nearest hostile each tick (cooldown reset).
        # ~6 hits each (80hp / 15dmg) plus projectile flight time.
        h.spawn_hostile("hostile-1", 2, 0)
        h.spawn_hostile("hostile-2", 45, 0)
        h.spawn_hostile("hostile-3", 55, 0)
        # 300 ticks = 30s sim time.  Turret kills hostile-1 by tick ~6,
        # hostile-2 by tick ~19, hostile-3 by tick ~31.
        h.run_ticks(300)
        # All 3 hostiles should be eliminated
        h.assert_target_eliminated("hostile-1")
        h.assert_target_eliminated("hostile-2")
        h.assert_target_eliminated("hostile-3")
        # Elimination streak event fires at exactly 3 eliminations (ON A STREAK).
        # EventBus wraps payload under "data", so check e["data"]["streak"].
        evt = h.assert_event(
            "elimination_streak",
            predicate=lambda e: e.get("data", {}).get("streak", 0) >= 3,
        )
        data = evt["data"]
        assert data["interceptor_id"] == "turret-1"
        assert data["streak"] >= 3
        assert data["streak_name"] in ("ON A STREAK", "RAMPAGE", "DOMINATING", "GODLIKE")

    def test_combat_profile_applied(self):
        """Placed units should have correct combat stats from their profile."""
        h = SimulationTestHarness()
        turret = h.place_friendly("t1", 0, 0, "turret")
        assert turret.health == 200.0
        assert turret.weapon_range == 80.0
        assert turret.weapon_damage == 15.0
        assert turret.is_combatant is True

        hostile = h.spawn_hostile("h1", 5, 0)
        assert hostile.health == 80.0  # person_hostile profile
        assert hostile.weapon_range == 40.0
        assert hostile.is_combatant is True


class TestGameLifecycle:
    """Full game lifecycle through the GameTestHarness."""

    def test_setup_to_countdown(self):
        """begin_war transitions from setup to countdown."""
        from tests.engine.simulation.test_harness import GameTestHarness
        h = GameTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        assert h.get_game_state()["state"] == "setup"
        h.begin_war()
        assert h.get_game_state()["state"] == "countdown"

    def test_countdown_to_active(self):
        """Countdown ticks down to active with wave 1."""
        from tests.engine.simulation.test_harness import GameTestHarness
        h = GameTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.begin_war()
        # Tick through 5s countdown (50 ticks at 0.1s each)
        h.tick_game(55)
        state = h.get_game_state()
        assert state["state"] == "active"
        assert state["wave"] == 1

    def test_wave_complete_on_all_hostiles_eliminated(self):
        """Wave completes when all hostiles eliminated."""
        from tests.engine.simulation.test_harness import GameTestHarness
        h = GameTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.begin_war()
        h.tick_game(55)  # past countdown
        assert h.get_game_state()["state"] == "active"
        h.eliminate_all_wave_hostiles()
        h.tick_game(1)  # tick to trigger wave_complete check
        assert h.get_game_state()["state"] == "wave_complete"

    def test_defeat_when_all_friendlies_eliminated(self):
        """Game ends in defeat when all friendly combatants die."""
        from tests.engine.simulation.test_harness import GameTestHarness
        h = GameTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.begin_war()
        h.tick_game(55)  # past countdown, now active
        h.eliminate_all_friendlies()
        h.tick_game(1)  # trigger defeat check
        state = h.get_game_state()
        assert state["state"] == "defeat"

    def test_score_increases_on_kills(self):
        """Score increments for each hostile eliminated."""
        from tests.engine.simulation.test_harness import GameTestHarness
        h = GameTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.begin_war()
        h.tick_game(55)  # past countdown
        initial_score = h.get_game_state()["score"]
        # Eliminate one hostile manually
        for tid in list(h._game_mode._wave_hostile_ids):
            t = h.get_target(tid)
            if t and t.status == "active":
                t.health = 0
                t.status = "eliminated"
                h._game_mode.on_target_eliminated(tid)
                break
        assert h.get_game_state()["score"] > initial_score

    def test_reset_clears_all_state(self):
        """After reset, game returns to setup with zeroed stats."""
        from tests.engine.simulation.test_harness import GameTestHarness
        h = GameTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.begin_war()
        h.tick_game(55)
        h.reset_game()
        state = h.get_game_state()
        assert state["state"] == "setup"
        assert state["wave"] == 0
        assert state["score"] == 0
        assert state["total_eliminations"] == 0

    def test_begin_war_only_from_setup(self):
        """begin_war has no effect if not in setup state."""
        from tests.engine.simulation.test_harness import GameTestHarness
        h = GameTestHarness()
        h.place_friendly("turret-1", 0, 0, "turret")
        h.begin_war()
        assert h.get_game_state()["state"] == "countdown"
        # Try begin_war again -- should be ignored
        h.begin_war()
        assert h.get_game_state()["state"] == "countdown"

    def test_difficulty_scaling(self):
        """Later waves have more hostiles."""
        from engine.simulation.game_mode import WAVE_CONFIGS
        assert WAVE_CONFIGS[0].count < WAVE_CONFIGS[-1].count
        assert WAVE_CONFIGS[-1].speed_mult > WAVE_CONFIGS[0].speed_mult
        assert WAVE_CONFIGS[-1].health_mult > WAVE_CONFIGS[0].health_mult
