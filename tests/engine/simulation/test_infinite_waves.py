"""Unit tests for InfiniteWaveMode — procedurally scaling endless survival.

TDD: these tests were written FIRST, before the implementation existed.
InfiniteWaveMode is now implemented in game_mode.py.
"""

from __future__ import annotations

import math
import queue
import threading
import time

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Minimal EventBus for unit testing (same pattern as test_game_mode.py)
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


class _MockEngine:
    """Minimal engine mock for GameMode tests."""

    def __init__(self, event_bus: SimpleEventBus) -> None:
        self._event_bus = event_bus
        self._targets: list = []
        self._map_bounds = 200.0

    class _MockHazardManager:
        def spawn_random(self, count: int, map_bounds: float) -> None:
            pass

    hazard_manager = _MockHazardManager()

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


def _make_game_mode(infinite: bool = False):
    """Create a GameMode with optional infinite mode enabled."""
    from engine.simulation.combat import CombatSystem
    from engine.simulation.game_mode import GameMode

    bus = SimpleEventBus()
    engine = _MockEngine(bus)
    combat = CombatSystem(bus)
    gm = GameMode(bus, engine, combat, infinite=infinite)
    return gm, bus, engine


def _add_friendly(engine: _MockEngine) -> None:
    """Add a friendly combatant to the engine so defeat doesn't trigger."""
    from engine.simulation.target import SimulationTarget
    friendly = SimulationTarget(
        target_id="friendly-1",
        name="Turret Alpha",
        alliance="friendly",
        asset_type="turret",
        position=(0.0, 0.0),
        is_combatant=True,
        status="stationary",
    )
    engine._targets.append(friendly)


# ---------------------------------------------------------------------------
# InfiniteWaveMode — wave config generation
# ---------------------------------------------------------------------------


class TestInfiniteWaveConfigGeneration:
    """get_wave_config() generates procedural configs for any wave number."""

    def test_wave_11_config_generated(self):
        """Wave 11 does not raise an error -- it generates a config."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(11)
        assert config is not None
        assert config.count > 0
        assert config.speed_mult > 0
        assert config.health_mult > 0

    def test_wave_50_config_generated(self):
        """Arbitrary high wave numbers work."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(50)
        assert config is not None
        assert config.count > 0

    def test_wave_1_uses_base_values(self):
        """Wave 1 should use base count (3) with minimal scaling."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(1)
        # base_count=3, scale = 3 * 1.08^1 ~ 3.24 -> rounds to 3
        assert config.count >= 3

    def test_config_name_includes_wave_number(self):
        """Generated wave names include the wave number for identification."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(15)
        assert "15" in config.name


# ---------------------------------------------------------------------------
# Hostile count scaling
# ---------------------------------------------------------------------------


class TestInfiniteHostileCountScaling:
    """Hostile count scales as base * (1.08 ^ wave_num)."""

    def test_count_increases_with_wave_number(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        count_5 = iwm.get_wave_config(5).count
        count_15 = iwm.get_wave_config(15).count
        assert count_15 > count_5

    def test_count_formula_matches_spec(self):
        """count = round(base * 1.08^wave_num), base=3."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        # Wave 10: 3 * 1.08^10 = 3 * 2.1589 = 6.477 -> 6
        config = iwm.get_wave_config(10)
        expected = round(3 * (1.08 ** 10))
        assert config.count == expected

    def test_count_at_wave_20(self):
        """Wave 20 should have significantly more hostiles."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(20)
        expected = round(3 * (1.08 ** 20))
        assert config.count == expected

    def test_count_never_zero(self):
        """Even wave 0 (edge case) produces at least 1 hostile."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(0)
        assert config.count >= 1


# ---------------------------------------------------------------------------
# Speed scaling
# ---------------------------------------------------------------------------


class TestInfiniteSpeedScaling:
    """Speed multiplier = 1.0 + 0.03 * wave_num."""

    def test_speed_increases_gradually(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        speed_1 = iwm.get_wave_config(1).speed_mult
        speed_10 = iwm.get_wave_config(10).speed_mult
        assert speed_10 > speed_1

    def test_speed_formula_wave_10(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(10)
        expected = 1.0 + 0.03 * 10  # 1.3
        assert config.speed_mult == pytest.approx(expected)

    def test_speed_formula_wave_1(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(1)
        expected = 1.0 + 0.03 * 1  # 1.03
        assert config.speed_mult == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Health scaling (every 5 waves)
# ---------------------------------------------------------------------------


class TestInfiniteHealthScaling:
    """Health multiplier increases every 5 waves."""

    def test_health_increases_at_wave_5(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        health_1 = iwm.get_wave_config(1).health_mult
        health_5 = iwm.get_wave_config(5).health_mult
        assert health_5 > health_1

    def test_health_increases_at_wave_10(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        health_5 = iwm.get_wave_config(5).health_mult
        health_10 = iwm.get_wave_config(10).health_mult
        assert health_10 > health_5

    def test_health_same_within_bracket(self):
        """Waves 1-4 share the same health bracket, 5-9 share another."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        # Waves 6,7,8,9 should be in the same bracket (floor(wave/5) = 1)
        h6 = iwm.get_wave_config(6).health_mult
        h9 = iwm.get_wave_config(9).health_mult
        assert h6 == pytest.approx(h9)

    def test_health_bracket_formula(self):
        """health_mult = 1.0 + 0.2 * floor(wave_num / 5)."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        # Wave 15: 1.0 + 0.2 * 3 = 1.6
        config = iwm.get_wave_config(15)
        expected = 1.0 + 0.2 * (15 // 5)
        assert config.health_mult == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Elite hostiles (after wave 10)
# ---------------------------------------------------------------------------


class TestInfiniteEliteHostiles:
    """After wave 10, elite hostiles appear (2x health, faster)."""

    def test_no_elites_before_wave_11(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(10)
        assert not config.has_elites

    def test_elites_after_wave_10(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(11)
        assert config.has_elites
        assert config.elite_count >= 1

    def test_elite_count_increases_with_wave(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        elites_15 = iwm.get_wave_config(15).elite_count
        elites_25 = iwm.get_wave_config(25).elite_count
        assert elites_25 > elites_15

    def test_elite_health_multiplier(self):
        """Elites have 2x the base health multiplier."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(15)
        assert config.elite_health_mult == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Boss hostiles (after wave 20)
# ---------------------------------------------------------------------------


class TestInfiniteBossHostiles:
    """After wave 20, boss hostiles appear (5x health, spawns alone)."""

    def test_no_boss_before_wave_21(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(20)
        assert not config.has_boss

    def test_boss_after_wave_20(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(21)
        assert config.has_boss

    def test_boss_health_multiplier(self):
        """Boss has 5x the base health multiplier."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(25)
        assert config.boss_health_mult == pytest.approx(5.0)

    def test_boss_every_5_waves_after_20(self):
        """Boss appears on waves 21, 26, 31, etc. (every 5th wave after 20)."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        assert iwm.get_wave_config(21).has_boss
        assert not iwm.get_wave_config(22).has_boss
        assert iwm.get_wave_config(26).has_boss
        assert iwm.get_wave_config(31).has_boss


# ---------------------------------------------------------------------------
# Score multiplier
# ---------------------------------------------------------------------------


class TestInfiniteScoreMultiplier:
    """Score multiplier increases with wave number."""

    def test_score_multiplier_wave_1(self):
        """Wave 1 = 0.1x base points (score_mult = wave_num / 10)."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(1)
        assert config.score_mult == pytest.approx(0.1)

    def test_score_multiplier_wave_15(self):
        """Wave 15 = 1.5x base points."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(15)
        assert config.score_mult == pytest.approx(1.5)

    def test_score_multiplier_wave_30(self):
        """Wave 30 = 3.0x base points."""
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        config = iwm.get_wave_config(30)
        assert config.score_mult == pytest.approx(3.0)

    def test_score_multiplier_increases(self):
        from engine.simulation.game_mode import InfiniteWaveMode
        iwm = InfiniteWaveMode()
        sm_5 = iwm.get_wave_config(5).score_mult
        sm_20 = iwm.get_wave_config(20).score_mult
        assert sm_20 > sm_5


# ---------------------------------------------------------------------------
# GameMode infinite integration
# ---------------------------------------------------------------------------


class TestGameModeInfiniteParameter:
    """GameMode accepts infinite=True parameter."""

    def test_default_is_not_infinite(self):
        gm, _, _ = _make_game_mode(infinite=False)
        assert gm.infinite is False

    def test_infinite_parameter_stored(self):
        gm, _, _ = _make_game_mode(infinite=True)
        assert gm.infinite is True

    def test_get_state_includes_infinite(self):
        gm, _, _ = _make_game_mode(infinite=True)
        state = gm.get_state()
        assert "infinite" in state
        assert state["infinite"] is True


class TestGameModeInfiniteNeverEndsAtWave10:
    """In infinite mode, wave 10 completion does not trigger victory."""

    def test_no_victory_after_wave_10_infinite(self):
        from engine.simulation.game_mode import _COUNTDOWN_DURATION, _WAVE_ADVANCE_DELAY
        gm, bus, engine = _make_game_mode(infinite=True)
        _add_friendly(engine)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)

        # Simulate clearing waves 1-10
        for wave_num in range(1, 11):
            gm._spawn_thread = None
            gm._wave_hostile_ids.clear()
            gm.tick(0.1)
            assert gm.state == "wave_complete", f"Expected wave_complete after wave {wave_num}"
            gm._wave_complete_time = time.time() - _WAVE_ADVANCE_DELAY - 1
            gm.tick(0.1)

        # After wave 10 in infinite mode, should NOT be victory
        assert gm.state != "victory"
        assert gm.wave == 11
        assert gm.state == "active"


class TestGameModeInfiniteDefeat:
    """Game ends when ALL friendly units are eliminated (same as finite)."""

    def test_defeat_when_all_friendlies_eliminated(self):
        from engine.simulation.game_mode import _COUNTDOWN_DURATION
        gm, bus, engine = _make_game_mode(infinite=True)
        game_over_sub = bus.subscribe("game_over")

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)
        assert gm.state == "active"

        # No friendly combatants — should defeat
        gm._spawn_thread = None
        gm.tick(0.1)
        assert gm.state == "defeat"

        event = game_over_sub.get(timeout=1.0)
        assert event["result"] == "defeat"


class TestGameModeInfiniteAutoStart:
    """In infinite mode, wave auto-starts after 5s countdown."""

    def test_auto_advance_to_wave_11(self):
        from engine.simulation.game_mode import _COUNTDOWN_DURATION, _WAVE_ADVANCE_DELAY
        gm, bus, engine = _make_game_mode(infinite=True)
        _add_friendly(engine)
        wave_start_sub = bus.subscribe("wave_start")

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)

        # Clear 10 waves
        for wave_num in range(1, 11):
            gm._spawn_thread = None
            gm._wave_hostile_ids.clear()
            gm.tick(0.1)
            gm._wave_complete_time = time.time() - _WAVE_ADVANCE_DELAY - 1
            gm.tick(0.1)

        # Should now be on wave 11 in active state
        assert gm.wave == 11
        assert gm.state == "active"


class TestGameModeInfiniteReset:
    """Reset clears infinite state."""

    def test_reset_clears_infinite_wave_state(self):
        from engine.simulation.game_mode import _COUNTDOWN_DURATION, _WAVE_ADVANCE_DELAY
        gm, bus, engine = _make_game_mode(infinite=True)
        _add_friendly(engine)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)

        # Advance a few waves
        for _ in range(3):
            gm._spawn_thread = None
            gm._wave_hostile_ids.clear()
            gm.tick(0.1)
            gm._wave_complete_time = time.time() - _WAVE_ADVANCE_DELAY - 1
            gm.tick(0.1)

        gm.reset()
        assert gm.state == "setup"
        assert gm.wave == 0
        assert gm.score == 0


class TestGameModeInfiniteDifficultyIntegration:
    """Infinite mode uses DifficultyScaler for adaptive scaling."""

    def test_difficulty_scaler_active_in_infinite(self):
        gm, _, _ = _make_game_mode(infinite=True)
        assert gm.difficulty is not None
        assert gm.difficulty.get_multiplier() == 1.0

    def test_infinite_wave_config_uses_difficulty(self):
        """InfiniteWaveMode accepts a DifficultyScaler for adjustments."""
        from engine.simulation.difficulty import DifficultyScaler
        from engine.simulation.game_mode import InfiniteWaveMode

        scaler = DifficultyScaler()
        # Push multiplier up
        scaler._multiplier = 1.5
        iwm = InfiniteWaveMode(difficulty=scaler)
        config = iwm.get_wave_config(10)
        # The config should exist and be valid
        assert config.count > 0


class TestGameModeInfiniteGetState:
    """get_state() reports infinite mode and wave correctly past wave 10."""

    def test_get_state_wave_11(self):
        from engine.simulation.game_mode import _COUNTDOWN_DURATION, _WAVE_ADVANCE_DELAY
        gm, bus, engine = _make_game_mode(infinite=True)
        _add_friendly(engine)

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)

        # Clear 10 waves
        for _ in range(10):
            gm._spawn_thread = None
            gm._wave_hostile_ids.clear()
            gm.tick(0.1)
            gm._wave_complete_time = time.time() - _WAVE_ADVANCE_DELAY - 1
            gm.tick(0.1)

        state = gm.get_state()
        assert state["wave"] == 11
        assert state["infinite"] is True
        # In infinite mode, total_waves should indicate no fixed limit
        assert state["total_waves"] == -1 or state["total_waves"] > 10


class TestGameModeFiniteUnchanged:
    """Finite mode (infinite=False) still works exactly as before."""

    def test_victory_after_wave_10_finite(self):
        from engine.simulation.game_mode import _COUNTDOWN_DURATION, _WAVE_ADVANCE_DELAY
        gm, bus, engine = _make_game_mode(infinite=False)
        _add_friendly(engine)
        game_over_sub = bus.subscribe("game_over")

        gm.begin_war()
        gm.tick(_COUNTDOWN_DURATION + 1.0)

        # Clear all 10 waves
        for wave_num in range(1, 11):
            gm._spawn_thread = None
            gm._wave_hostile_ids.clear()
            gm.tick(0.1)
            if gm.state == "wave_complete":
                gm._wave_complete_time = time.time() - _WAVE_ADVANCE_DELAY - 1
                gm.tick(0.1)

        assert gm.state == "victory"
        event = game_over_sub.get(timeout=1.0)
        assert event["result"] == "victory"
