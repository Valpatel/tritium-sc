# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests verifying HazardManager is wired into SimulationEngine.

TDD: written BEFORE implementation. All tests should fail until the wiring
is complete, then pass after.

Covers:
  - Engine creates HazardManager on __init__
  - Engine ticks HazardManager during _do_tick()
  - reset_game() calls hazard_manager.reset() / clear()
  - game_mode._start_wave() triggers hazard_manager.spawn_random() for waves 3+
"""

from __future__ import annotations

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.hazards import HazardManager
from engine.simulation.engine import SimulationEngine
from engine.simulation.target import SimulationTarget


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def engine(bus: EventBus) -> SimulationEngine:
    return SimulationEngine(bus, map_bounds=200.0)


# ---------------------------------------------------------------------------
# 1. Engine initialization
# ---------------------------------------------------------------------------

class TestEngineInitialization:
    def test_engine_has_hazard_manager_attribute(self, engine: SimulationEngine):
        """Engine must expose hazard_manager after construction."""
        assert hasattr(engine, 'hazard_manager'), (
            "SimulationEngine is missing 'hazard_manager' attribute. "
            "Add self.hazard_manager = HazardManager(self._event_bus) in __init__."
        )

    def test_hazard_manager_is_correct_type(self, engine: SimulationEngine):
        """hazard_manager must be a HazardManager instance."""
        assert isinstance(engine.hazard_manager, HazardManager), (
            f"engine.hazard_manager is {type(engine.hazard_manager)}, expected HazardManager"
        )

    def test_hazard_manager_starts_empty(self, engine: SimulationEngine):
        """A freshly created engine should have no active hazards."""
        assert len(engine.hazard_manager.active_hazards) == 0


# ---------------------------------------------------------------------------
# 2. Tick integration
# ---------------------------------------------------------------------------

class TestHazardManagerTick:
    def test_tick_advances_hazard_elapsed(self, engine: SimulationEngine):
        """After _do_tick(), hazard elapsed time should increase."""
        engine.hazard_manager.spawn_hazard("fire", (10.0, 10.0), 5.0, duration=60.0)
        assert engine.hazard_manager.active_hazards[0].elapsed == 0.0

        engine._do_tick(0.1)

        assert engine.hazard_manager.active_hazards[0].elapsed == pytest.approx(0.1)

    def test_tick_expires_short_lived_hazard(self, engine: SimulationEngine):
        """A hazard with duration=0.05s should expire after one 0.1s tick."""
        engine.hazard_manager.spawn_hazard("flood", (0.0, 0.0), 3.0, duration=0.05)
        assert len(engine.hazard_manager.active_hazards) == 1

        engine._do_tick(0.1)

        assert len(engine.hazard_manager.active_hazards) == 0

    def test_tick_does_not_expire_long_lived_hazard(self, engine: SimulationEngine):
        """A hazard with duration=30s should still be active after one tick."""
        engine.hazard_manager.spawn_hazard("roadblock", (5.0, 5.0), 8.0, duration=30.0)

        engine._do_tick(0.1)

        assert len(engine.hazard_manager.active_hazards) == 1

    def test_multiple_ticks_expire_hazard(self, engine: SimulationEngine):
        """Hazard with duration=1.0s should expire after 11 ticks of dt=0.1s."""
        engine.hazard_manager.spawn_hazard("fire", (0.0, 0.0), 5.0, duration=1.0)

        for _ in range(11):
            engine._do_tick(0.1)

        assert len(engine.hazard_manager.active_hazards) == 0


# ---------------------------------------------------------------------------
# 3. Reset integration
# ---------------------------------------------------------------------------

class TestHazardManagerReset:
    def test_reset_game_clears_hazards(self, engine: SimulationEngine):
        """reset_game() must clear all active hazards from hazard_manager."""
        engine.hazard_manager.spawn_hazard("fire", (10.0, 10.0), 5.0, 30.0)
        engine.hazard_manager.spawn_hazard("flood", (20.0, 20.0), 8.0, 60.0)
        assert len(engine.hazard_manager.active_hazards) == 2

        engine.reset_game()

        assert len(engine.hazard_manager.active_hazards) == 0, (
            "reset_game() must call hazard_manager.clear() to remove all hazards"
        )

    def test_reset_game_hazard_manager_still_functional(self, engine: SimulationEngine):
        """After reset_game(), hazard_manager should still accept new hazards."""
        engine.hazard_manager.spawn_hazard("roadblock", (0.0, 0.0), 5.0, 30.0)
        engine.reset_game()

        # Should not raise
        engine.hazard_manager.spawn_hazard("fire", (1.0, 1.0), 3.0, 20.0)
        assert len(engine.hazard_manager.active_hazards) == 1


# ---------------------------------------------------------------------------
# 4. Wave start integration (waves 3+)
# ---------------------------------------------------------------------------

class TestWaveHazardSpawning:
    def test_wave_1_does_not_spawn_hazards(self, engine: SimulationEngine):
        """Wave 1 should NOT trigger hazard spawning."""
        # Simulate wave 1 start
        engine.game_mode._start_wave(1)
        # Wait for spawn thread if it exists
        if engine.game_mode._spawn_thread is not None:
            engine.game_mode._spawn_thread.join(timeout=2.0)
        assert len(engine.hazard_manager.active_hazards) == 0, (
            "Wave 1 must not spawn environmental hazards"
        )

    def test_wave_2_does_not_spawn_hazards(self, engine: SimulationEngine):
        """Wave 2 should NOT trigger hazard spawning."""
        engine.game_mode._start_wave(2)
        if engine.game_mode._spawn_thread is not None:
            engine.game_mode._spawn_thread.join(timeout=2.0)
        assert len(engine.hazard_manager.active_hazards) == 0, (
            "Wave 2 must not spawn environmental hazards"
        )

    def test_wave_3_spawns_hazards(self, engine: SimulationEngine):
        """Wave 3 SHOULD trigger hazard spawning (waves 3+ add environmental pressure)."""
        engine.game_mode._start_wave(3)
        if engine.game_mode._spawn_thread is not None:
            engine.game_mode._spawn_thread.join(timeout=2.0)
        assert len(engine.hazard_manager.active_hazards) > 0, (
            "Wave 3 must spawn at least one environmental hazard. "
            "Add hazard_manager.spawn_random() call in game_mode._start_wave() for waves >= 3."
        )

    def test_wave_5_spawns_hazards(self, engine: SimulationEngine):
        """Wave 5 should also trigger hazard spawning."""
        engine.game_mode._start_wave(5)
        if engine.game_mode._spawn_thread is not None:
            engine.game_mode._spawn_thread.join(timeout=2.0)
        assert len(engine.hazard_manager.active_hazards) > 0

    def test_wave_10_spawns_hazards(self, engine: SimulationEngine):
        """Final wave should trigger hazard spawning."""
        engine.game_mode._start_wave(10)
        if engine.game_mode._spawn_thread is not None:
            engine.game_mode._spawn_thread.join(timeout=2.0)
        assert len(engine.hazard_manager.active_hazards) > 0

    def test_hazards_are_within_map_bounds(self, engine: SimulationEngine):
        """Hazards spawned during wave start must be within the engine's map bounds."""
        engine.game_mode._start_wave(3)
        if engine.game_mode._spawn_thread is not None:
            engine.game_mode._spawn_thread.join(timeout=2.0)

        for hazard in engine.hazard_manager.active_hazards:
            x, y = hazard.position
            assert abs(x) <= engine._map_bounds, (
                f"Hazard at x={x} is outside map bounds ±{engine._map_bounds}"
            )
            assert abs(y) <= engine._map_bounds, (
                f"Hazard at y={y} is outside map bounds ±{engine._map_bounds}"
            )
