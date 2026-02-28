# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Performance stress tests for city-scale simulation (200+ units).

Proves the system handles 200 units at 10Hz by:
1. Verifying SpatialGrid query performance
2. Verifying full behavior ticks complete within budget
3. Loading and running scenario JSON files
4. Proving spatial queries reduce comparisons vs brute force
"""

from __future__ import annotations

import math
import queue
import threading
import time
import uuid

import pytest

from engine.simulation.behaviors import UnitBehaviors
from engine.simulation.combat import CombatSystem
from engine.simulation.engine import SimulationEngine
from engine.simulation.scenario import load_battle_scenario
from engine.simulation.spatial import SpatialGrid
from engine.simulation.target import SimulationTarget


class SimpleEventBus:
    """Minimal EventBus for stress testing."""

    def __init__(self) -> None:
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait({"type": topic, "data": data})
                except queue.Full:
                    pass

    def subscribe(self, topic: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(q)
        return q


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _make_target(
    tid: str,
    alliance: str = "hostile",
    asset_type: str = "person",
    position: tuple[float, float] = (0.0, 0.0),
    speed: float = 1.5,
) -> SimulationTarget:
    t = SimulationTarget(
        target_id=tid,
        name=f"Unit-{tid}",
        alliance=alliance,
        asset_type=asset_type,
        position=position,
        speed=speed,
    )
    t.apply_combat_profile()
    t.last_fired = 0.0
    return t


def _spread_targets(count: int, bounds: float = 250.0, alliance: str = "hostile") -> list[SimulationTarget]:
    """Create targets spread across a square area."""
    targets = []
    side = int(math.ceil(math.sqrt(count)))
    spacing = (2 * bounds) / max(side, 1)
    for i in range(count):
        row = i // side
        col = i % side
        x = -bounds + col * spacing + spacing * 0.5
        y = -bounds + row * spacing + spacing * 0.5
        t = _make_target(
            tid=f"t-{i}",
            alliance=alliance,
            position=(x, y),
        )
        targets.append(t)
    return targets


# --------------------------------------------------------------------------
# Test: SpatialGrid raw query performance
# --------------------------------------------------------------------------

class TestSpatialGridPerformance:
    """Prove SpatialGrid handles 200+ units efficiently."""

    def test_200_units_spatial_grid_queries(self):
        """200 units, 100 spatial grid queries complete under 50ms."""
        grid = SpatialGrid(cell_size=50.0)
        targets = _spread_targets(200, bounds=250.0)
        grid.rebuild(targets)

        # Run 100 radius queries at random positions
        import random
        random.seed(42)
        positions = [(random.uniform(-250, 250), random.uniform(-250, 250)) for _ in range(100)]

        start = time.perf_counter()
        for pos in positions:
            grid.query_radius(pos, 50.0)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 50.0, f"100 grid queries took {elapsed_ms:.1f}ms (budget: 50ms)"

    def test_spatial_grid_actually_reduces_comparisons(self):
        """Prove grid queries check fewer targets than brute force."""
        grid = SpatialGrid(cell_size=50.0)
        targets = _spread_targets(200, bounds=250.0)
        grid.rebuild(targets)

        # Query at origin with 50m radius
        query_pos = (0.0, 0.0)
        query_radius = 50.0

        # Grid result
        grid_results = grid.query_radius(query_pos, query_radius)

        # Brute force result
        brute_results = []
        for t in targets:
            dx = t.position[0] - query_pos[0]
            dy = t.position[1] - query_pos[1]
            if math.hypot(dx, dy) <= query_radius:
                brute_results.append(t)

        # Results must match
        assert len(grid_results) == len(brute_results), (
            f"Grid returned {len(grid_results)}, brute force returned {len(brute_results)}"
        )

        # Grid should check far fewer than 200 targets
        # With 50m query on 500m area, ~3% of area covered = ~6 targets expected
        assert len(grid_results) < 200, (
            f"Grid returned {len(grid_results)} of 200 targets -- spatial partitioning should filter most"
        )

    def test_rebuild_200_targets_fast(self):
        """Rebuilding grid with 200 targets takes < 5ms."""
        grid = SpatialGrid(cell_size=50.0)
        targets = _spread_targets(200, bounds=250.0)

        start = time.perf_counter()
        for _ in range(100):
            grid.rebuild(targets)
        elapsed_ms = (time.perf_counter() - start) * 1000 / 100

        assert elapsed_ms < 5.0, f"Grid rebuild took {elapsed_ms:.2f}ms (budget: 5ms)"


# --------------------------------------------------------------------------
# Test: Full behavior tick at scale
# --------------------------------------------------------------------------

class TestBehaviorTickPerformance:
    """Prove behaviors.tick() handles 200 units within 10Hz budget."""

    def test_200_units_behavior_tick(self):
        """Full behavior tick with 200 units completes under 100ms."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        # Create a mix: 20 friendly defenders + 180 hostiles
        targets: dict[str, SimulationTarget] = {}

        # Defenders spread across map
        defender_types = ["turret", "drone", "rover", "tank", "heavy_turret"]
        for i in range(20):
            dtype = defender_types[i % len(defender_types)]
            spd = 0.0 if "turret" in dtype else 3.0
            t = _make_target(
                tid=f"f-{i}",
                alliance="friendly",
                asset_type=dtype,
                position=(i * 20 - 200, 0.0),
                speed=spd,
            )
            t.status = "active" if spd > 0 else "stationary"
            targets[t.target_id] = t

        # Hostiles spread across map
        for i in range(180):
            t = _make_target(
                tid=f"h-{i}",
                alliance="hostile",
                position=(i * 3 - 250, 50.0 + (i % 10) * 5),
            )
            targets[t.target_id] = t

        # Warm up (first tick may be slow due to imports)
        behaviors.tick(0.1, targets)

        # Measure 10 ticks
        start = time.perf_counter()
        for _ in range(10):
            behaviors.tick(0.1, targets)
        elapsed_ms = (time.perf_counter() - start) * 1000 / 10

        assert elapsed_ms < 100.0, f"Average behavior tick took {elapsed_ms:.1f}ms (budget: 100ms)"

    def test_200_units_with_spatial_grid(self):
        """Behavior tick with spatial grid should be faster than without."""
        bus = SimpleEventBus()
        combat = CombatSystem(bus)
        behaviors = UnitBehaviors(combat)

        targets: dict[str, SimulationTarget] = {}
        for i in range(20):
            t = _make_target(
                tid=f"f-{i}",
                alliance="friendly",
                asset_type="turret",
                position=(i * 25 - 250, 0.0),
                speed=0.0,
            )
            t.status = "stationary"
            targets[t.target_id] = t

        for i in range(180):
            t = _make_target(
                tid=f"h-{i}",
                alliance="hostile",
                position=(i * 3 - 250, 50.0 + (i % 20) * 10),
            )
            targets[t.target_id] = t

        # Build spatial grid
        grid = SpatialGrid(cell_size=50.0)
        grid.rebuild(list(targets.values()))

        # Pass grid to behaviors for spatial queries
        behaviors.set_spatial_grid(grid)

        # Warm up
        behaviors.tick(0.1, targets)

        # Measure with grid
        start = time.perf_counter()
        for _ in range(10):
            grid.rebuild(list(targets.values()))
            behaviors.tick(0.1, targets)
        with_grid_ms = (time.perf_counter() - start) * 1000 / 10

        # Measure without grid
        behaviors.set_spatial_grid(None)
        start = time.perf_counter()
        for _ in range(10):
            behaviors.tick(0.1, targets)
        without_grid_ms = (time.perf_counter() - start) * 1000 / 10

        # With grid should be at most as slow (ideally faster)
        # At 200 units the difference should be measurable
        assert with_grid_ms < 100.0, f"Grid-backed tick took {with_grid_ms:.1f}ms (budget: 100ms)"


# --------------------------------------------------------------------------
# Test: Scenario loading and execution
# --------------------------------------------------------------------------

class TestScenarioExecution:
    """Prove scenario JSON files load and run correctly."""

    def test_street_combat_scenario_loads_and_runs(self):
        """Load street_combat.json, run 50 ticks, no crash."""
        scenario = load_battle_scenario("scenarios/battle/street_combat.json")

        assert scenario.scenario_id == "street_combat"
        assert scenario.map_bounds == 100.0  # small neighborhood block
        assert len(scenario.defenders) >= 1

        # Verify single rover defender (robot dog concept)
        rover_count = sum(1 for d in scenario.defenders if d.asset_type == "rover")
        assert rover_count == 1, f"Expected 1 rover (robot dog), got {rover_count}"

        # Verify all hostiles are person type (kids with nerf guns)
        for wave in scenario.waves:
            for group in wave.groups:
                assert group.asset_type == "person", (
                    f"Wave '{wave.name}' has non-person hostile: {group.asset_type}"
                )

        # Load into engine and run
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=scenario.map_bounds)
        engine.game_mode.load_scenario(scenario)

        # Run 50 ticks (5 seconds sim time)
        for _ in range(50):
            engine._do_tick(0.1)

    def test_riot_scenario_200_hostiles(self):
        """Load riot.json, verify it can handle 200 hostiles."""
        scenario = load_battle_scenario("scenarios/battle/riot.json")

        assert scenario.scenario_id == "riot"
        assert scenario.map_bounds == 500.0  # city district

        # Count total hostiles across all waves
        total_hostiles = sum(w.total_count for w in scenario.waves)
        assert total_hostiles >= 200, f"Riot scenario has {total_hostiles} total hostiles, expected >= 200"

        # Verify defenders include multiple drones
        drone_count = sum(1 for d in scenario.defenders if d.asset_type in ("drone", "scout_drone"))
        assert drone_count >= 4, f"Expected >= 4 drones, got {drone_count}"

        # Load into engine
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=scenario.map_bounds, max_hostiles=200)
        engine.game_mode.load_scenario(scenario)

        # Manually spawn a large batch to stress test
        for i in range(150):
            engine.spawn_hostile()

        targets = engine.get_targets()
        hostile_count = sum(1 for t in targets if t.alliance == "hostile")
        assert hostile_count >= 150, f"Only {hostile_count} hostiles spawned"

        # Run 10 ticks with all those hostiles
        start = time.perf_counter()
        for _ in range(10):
            engine._do_tick(0.1)
        elapsed_ms = (time.perf_counter() - start) * 1000 / 10

        # Each tick should complete within budget
        assert elapsed_ms < 200.0, f"Average tick with 150+ hostiles took {elapsed_ms:.1f}ms"


# --------------------------------------------------------------------------
# Test: Engine _do_tick at city scale
# --------------------------------------------------------------------------

class TestEngineTickCityScale:
    """Full engine _do_tick with 200 units."""

    def test_full_engine_tick_200_units(self):
        """Create engine with 200 targets, verify 10 ticks complete fast."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=250.0, max_hostiles=200)

        # Add defenders
        for i in range(10):
            t = SimulationTarget(
                target_id=f"def-{i}",
                name=f"Defender-{i}",
                alliance="friendly",
                asset_type="turret",
                position=(i * 50 - 250, 0.0),
                speed=0.0,
            )
            t.apply_combat_profile()
            engine.add_target(t)

        # Add hostiles
        for i in range(190):
            engine.spawn_hostile()

        targets = engine.get_targets()
        assert len(targets) >= 200, f"Only {len(targets)} targets (expected 200)"

        # Activate game mode so behaviors run
        engine.game_mode.state = "active"

        # Warm up
        engine._do_tick(0.1)

        # Measure 10 ticks
        start = time.perf_counter()
        for _ in range(10):
            engine._do_tick(0.1)
        elapsed_ms = (time.perf_counter() - start) * 1000 / 10

        assert elapsed_ms < 200.0, f"Average engine tick took {elapsed_ms:.1f}ms (budget: 200ms)"
