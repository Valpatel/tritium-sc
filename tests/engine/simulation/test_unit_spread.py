# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Statistical tests verifying units spread across the full city map.

Tests validate:
  - Hostile spawn positions cover all quadrants of the map
  - Combat spawn radius is within 70-95% of bounds
  - Objectives are spread across the map (not all at dead center)
  - Different wave spawn directions produce different spawn patterns
  - Defenders are spread when using the spread_defenders() helper
"""

from __future__ import annotations

import math
import queue
import threading

import pytest

from engine.simulation.engine import SimulationEngine
from engine.simulation.game_mode import GameMode, WaveConfig, WAVE_CONFIGS
from engine.simulation.scenario import (
    BattleScenario,
    DefenderConfig,
    SpawnGroup,
    WaveDefinition,
    spread_defenders,
)
from engine.simulation.target import SimulationTarget


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

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

    def subscribe(self) -> queue.Queue:
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


def _make_engine(map_bounds: float = 200.0) -> tuple[SimulationEngine, SimpleEventBus]:
    bus = SimpleEventBus()
    engine = SimulationEngine(bus, map_bounds=map_bounds)
    return engine, bus


# ---------------------------------------------------------------------------
# Tests: combat spawn radius
# ---------------------------------------------------------------------------


class TestCombatSpawnRadius:
    """Hostile combat spawns should be at 40-65% of map bounds.

    (Previously 70-95%, reduced for faster engagement.)
    """

    def test_combat_spawn_within_40_65_percent(self):
        """Every combat spawn should have distance 40-65% of map_bounds."""
        engine, bus = _make_engine(map_bounds=200.0)
        for _ in range(200):
            x, y = engine._random_edge_position(combat=True)
            dist = math.hypot(x, y)
            frac = dist / 200.0
            assert 0.38 <= frac <= 0.67, (
                f"Combat spawn at ({x:.1f}, {y:.1f}) is at {frac:.2%} of "
                f"bounds, expected 40-65%"
            )

    def test_combat_spawn_never_at_center(self):
        """No combat spawn should be within 20% of center."""
        engine, bus = _make_engine(map_bounds=200.0)
        for _ in range(200):
            x, y = engine._random_edge_position(combat=True)
            dist = math.hypot(x, y)
            assert dist > 40.0, (
                f"Combat spawn at ({x:.1f}, {y:.1f}) is too close to center "
                f"(dist={dist:.1f})"
            )

    def test_combat_spawn_covers_full_perimeter(self):
        """Spawns should cover all 4 quadrants of the circle."""
        engine, bus = _make_engine(map_bounds=200.0)
        quadrants = set()
        for _ in range(200):
            x, y = engine._random_edge_position(combat=True)
            q = (1 if x >= 0 else -1, 1 if y >= 0 else -1)
            quadrants.add(q)
        assert len(quadrants) == 4, (
            f"Only {len(quadrants)} quadrants hit: {quadrants}"
        )

    def test_noncombat_spawn_unchanged(self):
        """Non-combat spawns should still be on the map edge (unchanged)."""
        engine, bus = _make_engine(map_bounds=100.0)
        for _ in range(50):
            x, y = engine._random_edge_position(combat=False)
            on_edge = (
                abs(abs(x) - 100.0) < 0.01
                or abs(abs(y) - 100.0) < 0.01
            )
            assert on_edge, f"Non-combat spawn ({x}, {y}) not on edge"


# ---------------------------------------------------------------------------
# Tests: objective spread
# ---------------------------------------------------------------------------


class TestObjectiveSpread:
    """Hostile waypoint objectives should be spread across the map."""

    def test_objectives_not_all_at_center(self):
        """Objective waypoints should NOT all be within 10% of center."""
        engine, bus = _make_engine(map_bounds=200.0)
        max_dist = 0.0
        for _ in range(100):
            wps = engine._generate_hostile_waypoints((180.0, 0.0))
            # The first waypoint after approach is typically the objective
            if len(wps) >= 1:
                ox, oy = wps[0]
                dist = math.hypot(ox, oy)
                max_dist = max(max_dist, dist)
        # At least some objectives should be far from center
        assert max_dist > 20.0, (
            f"All objectives within {max_dist:.1f}m of center -- "
            f"should be spread to ~50% of bounds"
        )

    def test_objectives_cover_multiple_quadrants(self):
        """Objectives should end up in different areas, not all in one spot.

        _generate_hostile_waypoints routes through the grid pathfinder,
        which snaps to cell centers.  We check all waypoints in the
        approach half of the route for quadrant coverage.
        """
        engine, bus = _make_engine(map_bounds=200.0)
        quadrants = set()
        for _ in range(200):
            wps = engine._generate_hostile_waypoints((180.0, 0.0))
            # Check the midpoint waypoint (approximate objective location)
            mid = len(wps) // 2
            if mid < len(wps):
                ox, oy = wps[mid]
                q = (1 if ox >= 0 else -1, 1 if oy >= 0 else -1)
                quadrants.add(q)
        assert len(quadrants) >= 3, (
            f"Only {len(quadrants)} quadrant(s) hit for objectives"
        )


# ---------------------------------------------------------------------------
# Tests: spawn direction / wave variety
# ---------------------------------------------------------------------------


class TestSpawnDirections:
    """Wave spawn directions should produce different spawn patterns."""

    def test_direction_north_spawns_from_north(self):
        """Spawns with direction='north' should have positive y."""
        engine, bus = _make_engine(map_bounds=200.0)
        for _ in range(50):
            x, y = engine._random_edge_position(
                combat=True, direction="north"
            )
            assert y > 0, f"North spawn at ({x:.1f}, {y:.1f}) has y <= 0"

    def test_direction_south_spawns_from_south(self):
        engine, bus = _make_engine(map_bounds=200.0)
        for _ in range(50):
            x, y = engine._random_edge_position(
                combat=True, direction="south"
            )
            assert y < 0, f"South spawn at ({x:.1f}, {y:.1f}) has y >= 0"

    def test_direction_east_spawns_from_east(self):
        engine, bus = _make_engine(map_bounds=200.0)
        for _ in range(50):
            x, y = engine._random_edge_position(
                combat=True, direction="east"
            )
            assert x > 0, f"East spawn at ({x:.1f}, {y:.1f}) has x <= 0"

    def test_direction_west_spawns_from_west(self):
        engine, bus = _make_engine(map_bounds=200.0)
        for _ in range(50):
            x, y = engine._random_edge_position(
                combat=True, direction="west"
            )
            assert x < 0, f"West spawn at ({x:.1f}, {y:.1f}) has x >= 0"

    def test_direction_pincer_spawns_from_opposite_sides(self):
        """Pincer should produce spawns from two opposite sides."""
        engine, bus = _make_engine(map_bounds=200.0)
        xs = []
        for _ in range(100):
            x, y = engine._random_edge_position(
                combat=True, direction="pincer"
            )
            xs.append(x)
        # Should have both positive and negative x values
        has_pos = any(x > 50 for x in xs)
        has_neg = any(x < -50 for x in xs)
        assert has_pos and has_neg, "Pincer should spawn from both sides"

    def test_direction_surround_covers_all_quadrants(self):
        """Surround should spawn from all 4 quadrants."""
        engine, bus = _make_engine(map_bounds=200.0)
        quadrants = set()
        for _ in range(100):
            x, y = engine._random_edge_position(
                combat=True, direction="surround"
            )
            q = (1 if x >= 0 else -1, 1 if y >= 0 else -1)
            quadrants.add(q)
        assert len(quadrants) == 4, (
            f"Surround only hit {len(quadrants)} quadrants"
        )

    def test_direction_random_is_default(self):
        """direction='random' should behave like no direction specified."""
        engine, bus = _make_engine(map_bounds=200.0)
        quadrants = set()
        for _ in range(100):
            x, y = engine._random_edge_position(
                combat=True, direction="random"
            )
            q = (1 if x >= 0 else -1, 1 if y >= 0 else -1)
            quadrants.add(q)
        assert len(quadrants) >= 3, "Random direction should cover most quadrants"


# ---------------------------------------------------------------------------
# Tests: WaveConfig spawn_direction field
# ---------------------------------------------------------------------------


class TestWaveConfigDirection:
    """WaveConfig should support a spawn_direction field."""

    def test_wave_config_has_spawn_direction(self):
        wc = WaveConfig(
            name="Test",
            count=5,
            speed_mult=1.0,
            health_mult=1.0,
            spawn_direction="north",
        )
        assert wc.spawn_direction == "north"

    def test_wave_config_default_direction_is_random(self):
        wc = WaveConfig(
            name="Test",
            count=5,
            speed_mult=1.0,
            health_mult=1.0,
        )
        assert wc.spawn_direction == "random"

    def test_later_waves_have_tactical_directions(self):
        """Waves 6+ should have non-random spawn directions."""
        tactical_waves = [w for w in WAVE_CONFIGS if w.spawn_direction != "random"]
        assert len(tactical_waves) >= 3, (
            f"Only {len(tactical_waves)} waves have tactical directions, "
            f"expected at least 3 in later waves"
        )


# ---------------------------------------------------------------------------
# Tests: spread_defenders helper
# ---------------------------------------------------------------------------


class TestSpreadDefenders:
    """spread_defenders() should distribute defenders across the map."""

    def test_spread_defenders_returns_correct_count(self):
        configs = spread_defenders(6, map_bounds=200.0)
        assert len(configs) == 6

    def test_spread_defenders_returns_defender_configs(self):
        configs = spread_defenders(4, map_bounds=200.0)
        for cfg in configs:
            assert isinstance(cfg, DefenderConfig)

    def test_spread_defenders_covers_multiple_quadrants(self):
        configs = spread_defenders(8, map_bounds=200.0)
        quadrants = set()
        for cfg in configs:
            x, y = cfg.position
            q = (1 if x >= 0 else -1, 1 if y >= 0 else -1)
            quadrants.add(q)
        assert len(quadrants) >= 3, (
            f"Defenders only in {len(quadrants)} quadrants"
        )

    def test_spread_defenders_not_all_at_center(self):
        configs = spread_defenders(6, map_bounds=200.0)
        dists = [math.hypot(*cfg.position) for cfg in configs]
        max_dist = max(dists)
        assert max_dist > 40.0, (
            f"All defenders within {max_dist:.1f}m of center"
        )

    def test_spread_defenders_within_bounds(self):
        configs = spread_defenders(8, map_bounds=200.0)
        for cfg in configs:
            x, y = cfg.position
            assert abs(x) <= 200.0, f"Defender x={x} out of bounds"
            assert abs(y) <= 200.0, f"Defender y={y} out of bounds"

    def test_spread_defenders_uses_combat_types(self):
        """Defenders should be combat-capable types."""
        valid_types = {"turret", "heavy_turret", "missile_turret",
                       "rover", "drone", "scout_drone", "tank", "apc"}
        configs = spread_defenders(6, map_bounds=200.0)
        for cfg in configs:
            assert cfg.asset_type in valid_types, (
                f"Defender type '{cfg.asset_type}' is not a combat type"
            )

    def test_spread_defenders_single(self):
        """Single defender should be placed at center."""
        configs = spread_defenders(1, map_bounds=200.0)
        assert len(configs) == 1
        x, y = configs[0].position
        assert abs(x) <= 50.0 and abs(y) <= 50.0

    def test_spread_defenders_custom_types(self):
        """Caller can specify which types to use."""
        types = ["turret", "turret", "rover", "rover"]
        configs = spread_defenders(4, map_bounds=200.0, unit_types=types)
        assert len(configs) == 4
        for i, cfg in enumerate(configs):
            assert cfg.asset_type == types[i]


# ---------------------------------------------------------------------------
# Tests: Full integration -- spawn_hostile uses wider radius
# ---------------------------------------------------------------------------


class TestSpawnHostileSpread:
    """spawn_hostile() should use the 40-65% radius during combat."""

    def test_spawned_hostile_position_far_from_center(self):
        engine, bus = _make_engine(map_bounds=200.0)
        # Force game_mode to active state for combat spawning
        engine.game_mode.state = "active"
        dists = []
        for _ in range(50):
            h = engine.spawn_hostile()
            dist = math.hypot(*h.position)
            dists.append(dist)
        avg_dist = sum(dists) / len(dists)
        # Average should be around 105m (52.5% of 200)
        assert avg_dist > 70.0, (
            f"Average hostile spawn distance {avg_dist:.1f}m is too close "
            f"to center (expected >70m for 200m bounds)"
        )

    def test_spawned_hostiles_cover_all_quadrants(self):
        engine, bus = _make_engine(map_bounds=200.0)
        engine.game_mode.state = "active"
        quadrants = set()
        for _ in range(100):
            h = engine.spawn_hostile()
            x, y = h.position
            q = (1 if x >= 0 else -1, 1 if y >= 0 else -1)
            quadrants.add(q)
        assert len(quadrants) == 4

    def test_spawn_hostile_respects_direction_north(self):
        """spawn_hostile(direction='north') should produce y > 0."""
        engine, bus = _make_engine(map_bounds=200.0)
        engine.game_mode.state = "active"
        for _ in range(30):
            h = engine.spawn_hostile(direction="north")
            _, y = h.position
            assert y > 0, f"North-directed spawn at y={y:.1f}"

    def test_spawn_hostile_typed_respects_direction(self):
        """spawn_hostile_typed with direction should spawn from that direction."""
        engine, bus = _make_engine(map_bounds=200.0)
        engine.game_mode.state = "active"
        for _ in range(30):
            h = engine.spawn_hostile_typed("person", direction="west")
            x, _ = h.position
            assert x < 0, f"West-directed typed spawn at x={x:.1f}"


# ---------------------------------------------------------------------------
# Tests: Wave spawn uses WaveConfig.spawn_direction end-to-end
# ---------------------------------------------------------------------------


class TestWaveSpawnDirection:
    """Verify spawn_direction flows from WaveConfig through the wave spawner."""

    def test_wave_spawner_passes_direction(self):
        """_spawn_wave_hostiles should use config.spawn_direction."""
        engine, bus = _make_engine(map_bounds=200.0)
        engine.game_mode.state = "active"

        config = WaveConfig(
            name="North Wave",
            count=10,
            speed_mult=1.0,
            health_mult=1.0,
            spawn_direction="north",
        )
        # Call the spawner directly (normally runs in thread)
        engine.game_mode._spawn_wave_hostiles(config)

        # All spawned hostiles should have y > 0
        hostiles = [
            t for t in engine.get_targets()
            if t.alliance == "hostile"
        ]
        assert len(hostiles) == 10, f"Expected 10, got {len(hostiles)}"
        for h in hostiles:
            _, y = h.position
            assert y > 0, (
                f"Wave hostile '{h.name}' at y={y:.1f} should be > 0 "
                f"for north direction"
            )

    def test_mixed_wave_passes_direction(self):
        """_spawn_mixed_wave should use config.spawn_direction."""
        engine, bus = _make_engine(map_bounds=200.0)
        engine.game_mode.state = "active"

        config = WaveConfig(
            name="South Push",
            count=6,
            speed_mult=1.0,
            health_mult=1.0,
            composition=[("person", 4), ("hostile_vehicle", 2)],
            spawn_direction="south",
        )
        engine.game_mode._spawn_mixed_wave(config)

        hostiles = [
            t for t in engine.get_targets()
            if t.alliance == "hostile"
        ]
        assert len(hostiles) == 6, f"Expected 6, got {len(hostiles)}"
        for h in hostiles:
            _, y = h.position
            assert y < 0, (
                f"Mixed wave hostile '{h.name}' at y={y:.1f} should be < 0 "
                f"for south direction"
            )

    def test_surround_wave_hits_all_quadrants(self):
        """Surround direction should produce spawns in all 4 quadrants."""
        engine, bus = _make_engine(map_bounds=200.0)
        engine.game_mode.state = "active"

        config = WaveConfig(
            name="Surround Wave",
            count=40,
            speed_mult=1.0,
            health_mult=1.0,
            spawn_direction="surround",
        )
        engine.game_mode._spawn_wave_hostiles(config)

        quadrants = set()
        for t in engine.get_targets():
            if t.alliance == "hostile":
                x, y = t.position
                q = (1 if x >= 0 else -1, 1 if y >= 0 else -1)
                quadrants.add(q)
        assert len(quadrants) == 4, (
            f"Surround wave only hit {len(quadrants)} quadrants"
        )

    def test_final_stand_wave_uses_surround(self):
        """WAVE_CONFIGS[9] (FINAL STAND) should use surround direction."""
        final = WAVE_CONFIGS[9]
        assert final.name == "FINAL STAND"
        assert final.spawn_direction == "surround"
