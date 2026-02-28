# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for engine scaling — configurable max hostiles, terrain bounds, spatial grid."""

from __future__ import annotations

import queue
import threading
import time

import pytest

from engine.simulation.target import SimulationTarget
from engine.simulation.engine import SimulationEngine


pytestmark = pytest.mark.unit


class SimpleEventBus:
    """Minimal EventBus for unit testing."""

    def __init__(self) -> None:
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object = None) -> None:
        msg = {"type": topic}
        if data is not None:
            msg["data"] = data
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def subscribe(self, _filter: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass


def _make_target(tid: str, x: float, y: float, alliance: str = "hostile",
                 asset_type: str = "person", speed: float = 1.5) -> SimulationTarget:
    """Helper to create a target."""
    return SimulationTarget(
        target_id=tid,
        name=f"T-{tid}",
        alliance=alliance,
        asset_type=asset_type,
        position=(x, y),
        speed=speed,
    )


class TestMaxHostilesConfigurable:
    """MAX_HOSTILES should be overridable via constructor param."""

    def test_default_max_hostiles_is_200(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        assert engine.MAX_HOSTILES == 200

    def test_max_hostiles_from_constructor(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, max_hostiles=500)
        assert engine.MAX_HOSTILES == 500

    def test_max_hostiles_from_constructor_small(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, max_hostiles=5)
        assert engine.MAX_HOSTILES == 5


class TestTerrainMapUsesBounds:
    """terrain_map should use engine's configured map_bounds."""

    def test_default_terrain_uses_engine_bounds(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=300.0)
        assert engine.terrain_map._bounds == 300.0

    def test_custom_bounds_passed_through(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=1000.0)
        assert engine.terrain_map._bounds == 1000.0


class TestSpatialGridInEngine:
    """Spatial grid should exist on engine and be rebuilt each tick."""

    def test_engine_has_spatial_grid(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus)
        assert hasattr(engine, '_spatial_grid')
        assert engine._spatial_grid is not None

    def test_spatial_grid_rebuilt_each_tick(self):
        """After a manual tick, the spatial grid should contain the engine's targets."""
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)

        t1 = _make_target("a", 10.0, 10.0, alliance="friendly", asset_type="turret", speed=0.0)
        t2 = _make_target("b", 15.0, 15.0, alliance="hostile")
        engine.add_target(t1)
        engine.add_target(t2)

        # Run one tick manually (engine not started — call internal method)
        engine._do_tick(0.1)

        # Grid should contain both targets
        result = engine._spatial_grid.query_radius((10.0, 10.0), 50.0)
        ids = {t.target_id for t in result}
        assert "a" in ids
        assert "b" in ids


class TestEngineScalingPerformance:
    """200 units should tick under 200ms."""

    def test_200_units_tick_under_200ms(self):
        bus = SimpleEventBus()
        engine = SimulationEngine(bus, map_bounds=500.0)

        # Add 100 friendly turrets and 100 hostiles
        for i in range(100):
            t = _make_target(
                f"turret-{i}", float(i * 5), float(i * 5),
                alliance="friendly", asset_type="turret", speed=0.0,
            )
            t.apply_combat_profile()
            engine.add_target(t)

        for i in range(100):
            t = _make_target(
                f"hostile-{i}", float(i * 5 + 2), float(i * 5 + 2),
                alliance="hostile", asset_type="person", speed=1.5,
            )
            t.apply_combat_profile()
            engine.add_target(t)

        # Warm up
        engine._do_tick(0.1)

        # Time 10 ticks
        start = time.perf_counter()
        for _ in range(10):
            engine._do_tick(0.1)
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / 10) * 1000
        assert avg_ms < 200, f"Average tick time {avg_ms:.1f}ms exceeds 200ms limit"


class TestEventBusCapacity:
    """EventBus queue capacity should be 1000."""

    def test_eventbus_queue_capacity(self):
        from engine.comms.event_bus import EventBus
        bus = EventBus()
        q = bus.subscribe()
        assert q.maxsize == 1000
