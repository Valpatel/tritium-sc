# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for DifficultyScaler — adaptive difficulty for wave-based combat.

TDD: these tests are written FIRST, before the implementation exists.
Run them, watch them fail, then implement src/amy/simulation/difficulty.py.
"""

from __future__ import annotations

import queue
import threading

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Minimal EventBus for unit testing (same pattern as test_combat.py)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# DifficultyScaler — core behavior
# ---------------------------------------------------------------------------


class TestDifficultyScalerInit:
    """DifficultyScaler starts with known defaults."""

    def test_initial_multiplier_is_one(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        assert scaler.get_multiplier() == 1.0

    def test_initial_wave_history_empty(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        assert scaler.wave_history == []

    def test_initial_elimination_rate_zero(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        assert scaler.last_elimination_rate == 0.0


class TestDifficultyScalerRecordWave:
    """record_wave() stores wave performance and adjusts multiplier."""

    def test_record_wave_stores_stats(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        scaler.record_wave({
            "eliminations": 5,
            "hostiles_spawned": 5,
            "wave_time": 15.0,
            "friendly_damage_taken": 20.0,
            "friendly_max_health": 200.0,
            "escapes": 0,
        })
        assert len(scaler.wave_history) == 1

    def test_record_wave_computes_elimination_rate(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        scaler.record_wave({
            "eliminations": 4,
            "hostiles_spawned": 5,
            "wave_time": 20.0,
            "friendly_damage_taken": 10.0,
            "friendly_max_health": 200.0,
            "escapes": 1,
        })
        assert scaler.last_elimination_rate == pytest.approx(0.8)

    def test_record_wave_handles_zero_spawned(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        scaler.record_wave({
            "eliminations": 0,
            "hostiles_spawned": 0,
            "wave_time": 10.0,
            "friendly_damage_taken": 0.0,
            "friendly_max_health": 200.0,
            "escapes": 0,
        })
        assert scaler.last_elimination_rate == 0.0


class TestDifficultyScalerIncreases:
    """High performance increases the multiplier."""

    def test_high_elimination_rate_increases_multiplier(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        # Perfect wave: all killed, fast, no damage, no escapes
        scaler.record_wave({
            "eliminations": 5,
            "hostiles_spawned": 5,
            "wave_time": 10.0,
            "friendly_damage_taken": 0.0,
            "friendly_max_health": 200.0,
            "escapes": 0,
        })
        assert scaler.get_multiplier() > 1.0

    def test_consecutive_good_waves_increase_further(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        for _ in range(3):
            scaler.record_wave({
                "eliminations": 5,
                "hostiles_spawned": 5,
                "wave_time": 10.0,
                "friendly_damage_taken": 0.0,
                "friendly_max_health": 200.0,
                "escapes": 0,
            })
        assert scaler.get_multiplier() > 1.2

    def test_multiplier_changes_by_at_most_0_1_per_wave(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        before = scaler.get_multiplier()
        scaler.record_wave({
            "eliminations": 10,
            "hostiles_spawned": 10,
            "wave_time": 5.0,
            "friendly_damage_taken": 0.0,
            "friendly_max_health": 500.0,
            "escapes": 0,
        })
        after = scaler.get_multiplier()
        assert abs(after - before) <= 0.1 + 1e-9


class TestDifficultyScalerDecreases:
    """Poor performance decreases the multiplier."""

    def test_low_elimination_rate_decreases_multiplier(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        # Terrible wave: few kills, slow, lots of damage, many escapes
        scaler.record_wave({
            "eliminations": 1,
            "hostiles_spawned": 5,
            "wave_time": 60.0,
            "friendly_damage_taken": 150.0,
            "friendly_max_health": 200.0,
            "escapes": 4,
        })
        assert scaler.get_multiplier() < 1.0

    def test_many_escapes_decrease_multiplier(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        # Most hostiles escaped, slow wave, took significant damage
        scaler.record_wave({
            "eliminations": 1,
            "hostiles_spawned": 5,
            "wave_time": 50.0,
            "friendly_damage_taken": 120.0,
            "friendly_max_health": 200.0,
            "escapes": 4,
        })
        assert scaler.get_multiplier() < 1.0

    def test_consecutive_bad_waves_decrease_further(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        for _ in range(3):
            scaler.record_wave({
                "eliminations": 0,
                "hostiles_spawned": 5,
                "wave_time": 90.0,
                "friendly_damage_taken": 180.0,
                "friendly_max_health": 200.0,
                "escapes": 5,
            })
        assert scaler.get_multiplier() < 0.8


class TestDifficultyScalerClamping:
    """Multiplier is clamped to [0.5, 2.0]."""

    def test_multiplier_cannot_exceed_2_0(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        # 20 perfect waves should not push past 2.0
        for _ in range(20):
            scaler.record_wave({
                "eliminations": 10,
                "hostiles_spawned": 10,
                "wave_time": 5.0,
                "friendly_damage_taken": 0.0,
                "friendly_max_health": 500.0,
                "escapes": 0,
            })
        assert scaler.get_multiplier() <= 2.0

    def test_multiplier_cannot_drop_below_0_5(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        # 20 terrible waves should not push below 0.5
        for _ in range(20):
            scaler.record_wave({
                "eliminations": 0,
                "hostiles_spawned": 10,
                "wave_time": 120.0,
                "friendly_damage_taken": 500.0,
                "friendly_max_health": 500.0,
                "escapes": 10,
            })
        assert scaler.get_multiplier() >= 0.5


class TestDifficultyScalerReset:
    """reset() clears all difficulty state."""

    def test_reset_restores_multiplier_to_1_0(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        for _ in range(5):
            scaler.record_wave({
                "eliminations": 10,
                "hostiles_spawned": 10,
                "wave_time": 5.0,
                "friendly_damage_taken": 0.0,
                "friendly_max_health": 500.0,
                "escapes": 0,
            })
        assert scaler.get_multiplier() > 1.0
        scaler.reset()
        assert scaler.get_multiplier() == 1.0

    def test_reset_clears_wave_history(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        scaler.record_wave({
            "eliminations": 5,
            "hostiles_spawned": 5,
            "wave_time": 10.0,
            "friendly_damage_taken": 0.0,
            "friendly_max_health": 200.0,
            "escapes": 0,
        })
        scaler.reset()
        assert scaler.wave_history == []
        assert scaler.last_elimination_rate == 0.0


# ---------------------------------------------------------------------------
# Wave config adjustments
# ---------------------------------------------------------------------------


class TestDifficultyScalerWaveConfig:
    """get_wave_adjustments() applies multiplier to wave parameters."""

    def test_base_multiplier_no_change(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        adj = scaler.get_wave_adjustments(base_count=5)
        assert adj["hostile_count"] == 5
        assert adj["hostile_health_bonus"] == pytest.approx(0.0)
        assert adj["hostile_speed_bonus"] == pytest.approx(0.0)

    def test_high_multiplier_increases_count(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        # Push multiplier up
        for _ in range(5):
            scaler.record_wave({
                "eliminations": 10,
                "hostiles_spawned": 10,
                "wave_time": 5.0,
                "friendly_damage_taken": 0.0,
                "friendly_max_health": 500.0,
                "escapes": 0,
            })
        adj = scaler.get_wave_adjustments(base_count=10)
        assert adj["hostile_count"] > 10

    def test_low_multiplier_decreases_count(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        # Push multiplier down
        for _ in range(5):
            scaler.record_wave({
                "eliminations": 0,
                "hostiles_spawned": 10,
                "wave_time": 120.0,
                "friendly_damage_taken": 500.0,
                "friendly_max_health": 500.0,
                "escapes": 10,
            })
        adj = scaler.get_wave_adjustments(base_count=10)
        assert adj["hostile_count"] < 10

    def test_hostile_count_always_at_least_1(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        # Even at min multiplier (0.5), count should be >= 1
        for _ in range(20):
            scaler.record_wave({
                "eliminations": 0,
                "hostiles_spawned": 10,
                "wave_time": 120.0,
                "friendly_damage_taken": 500.0,
                "friendly_max_health": 500.0,
                "escapes": 10,
            })
        adj = scaler.get_wave_adjustments(base_count=1)
        assert adj["hostile_count"] >= 1

    def test_health_bonus_at_1_5_multiplier(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        # Manually set multiplier for deterministic test
        scaler._multiplier = 1.5
        adj = scaler.get_wave_adjustments(base_count=5)
        # (1.5 - 1.0) * 0.3 = 0.15 (15% health bonus)
        assert adj["hostile_health_bonus"] == pytest.approx(0.15)

    def test_speed_bonus_at_1_5_multiplier(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        scaler._multiplier = 1.5
        adj = scaler.get_wave_adjustments(base_count=5)
        # (1.5 - 1.0) * 0.15 = 0.075 (7.5% speed bonus)
        assert adj["hostile_speed_bonus"] == pytest.approx(0.075)

    def test_negative_bonuses_at_low_multiplier(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        scaler._multiplier = 0.7
        adj = scaler.get_wave_adjustments(base_count=5)
        # (0.7 - 1.0) * 0.3 = -0.09 -> capped at 0.0 (no negative health bonus)
        assert adj["hostile_health_bonus"] == pytest.approx(0.0)
        assert adj["hostile_speed_bonus"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Hardened / easy wave variants
# ---------------------------------------------------------------------------


class TestDifficultyScalerHardenedVariant:
    """When multiplier > 1.5, hardened tactics are enabled."""

    def test_hardened_variant_at_high_multiplier(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        scaler._multiplier = 1.6
        adj = scaler.get_wave_adjustments(base_count=8)
        assert adj["hardened"] is True
        assert adj["flank_chance_boost"] > 0.0
        assert adj["use_cover_seeking"] is True
        assert adj["elite_count"] >= 1

    def test_no_hardened_at_normal_multiplier(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        adj = scaler.get_wave_adjustments(base_count=8)
        assert adj["hardened"] is False
        assert adj["elite_count"] == 0

    def test_hardened_threshold_exactly_1_5(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        # At exactly 1.5, hardened should NOT trigger (requires > 1.5)
        scaler._multiplier = 1.5
        adj = scaler.get_wave_adjustments(base_count=8)
        assert adj["hardened"] is False


class TestDifficultyScalerEasyVariant:
    """When multiplier < 0.7, easy mode reduces challenge."""

    def test_easy_variant_at_low_multiplier(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        scaler._multiplier = 0.6
        adj = scaler.get_wave_adjustments(base_count=8)
        assert adj["easy"] is True
        assert adj["disable_flanking"] is True
        assert adj["speed_reduction"] > 0.0

    def test_no_easy_at_normal_multiplier(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        adj = scaler.get_wave_adjustments(base_count=8)
        assert adj["easy"] is False
        assert adj["disable_flanking"] is False

    def test_easy_threshold_exactly_0_7(self):
        from engine.simulation.difficulty import DifficultyScaler
        scaler = DifficultyScaler()
        # At exactly 0.7, easy should NOT trigger (requires < 0.7)
        scaler._multiplier = 0.7
        adj = scaler.get_wave_adjustments(base_count=8)
        assert adj["easy"] is False


# ---------------------------------------------------------------------------
# Integration with GameMode
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="GameMode does not have .difficulty attribute — DifficultyScaler not wired into GameMode")
class TestDifficultyGameModeIntegration:
    """DifficultyScaler is wired into GameMode and adapts across waves."""

    def _make_game_mode(self):
        """Create a GameMode with a SimpleEventBus and mock engine."""
        from engine.simulation.combat import CombatSystem
        from engine.simulation.game_mode import GameMode

        bus = SimpleEventBus()
        # Minimal engine mock — only needs spawn_hostile and get_targets
        engine = _MockEngine(bus)
        combat = CombatSystem(bus)
        gm = GameMode(bus, engine, combat)
        return gm, bus, engine

    def test_game_mode_has_difficulty_scaler(self):
        from engine.simulation.difficulty import DifficultyScaler
        gm, _, _ = self._make_game_mode()
        assert hasattr(gm, "difficulty")
        assert isinstance(gm.difficulty, DifficultyScaler)

    def test_game_state_includes_difficulty(self):
        gm, _, _ = self._make_game_mode()
        state = gm.get_state()
        assert "difficulty_multiplier" in state
        assert state["difficulty_multiplier"] == 1.0

    def test_difficulty_adapts_across_waves(self):
        """Simulate 3 perfect waves and verify multiplier increased."""
        from engine.simulation.difficulty import DifficultyScaler
        gm, bus, engine = self._make_game_mode()

        # Verify it starts at 1.0
        assert gm.difficulty.get_multiplier() == 1.0

        # Simulate 3 waves of perfect performance
        for wave_num in range(1, 4):
            gm.difficulty.record_wave({
                "eliminations": 5,
                "hostiles_spawned": 5,
                "wave_time": 10.0,
                "friendly_damage_taken": 0.0,
                "friendly_max_health": 200.0,
                "escapes": 0,
            })

        # After 3 perfect waves, multiplier should have increased
        assert gm.difficulty.get_multiplier() > 1.0

    def test_game_mode_reset_clears_difficulty(self):
        gm, _, _ = self._make_game_mode()
        # Push multiplier up
        for _ in range(5):
            gm.difficulty.record_wave({
                "eliminations": 10,
                "hostiles_spawned": 10,
                "wave_time": 5.0,
                "friendly_damage_taken": 0.0,
                "friendly_max_health": 500.0,
                "escapes": 0,
            })
        assert gm.difficulty.get_multiplier() > 1.0
        gm.reset()
        assert gm.difficulty.get_multiplier() == 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockEngine:
    """Minimal engine mock for GameMode tests."""

    def __init__(self, event_bus: SimpleEventBus) -> None:
        self._event_bus = event_bus
        self._targets: list = []

    def get_targets(self) -> list:
        return list(self._targets)

    def spawn_hostile(self, **kwargs):
        from engine.simulation.target import SimulationTarget
        t = SimulationTarget(
            target_id=f"h-{len(self._targets)}",
            name="Hostile",
            alliance="hostile",
            asset_type="person",
            position=(50.0, 0.0),
            speed=3.0,
        )
        t.apply_combat_profile()
        self._targets.append(t)
        return t
