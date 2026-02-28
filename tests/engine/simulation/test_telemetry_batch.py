# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for engine-side telemetry batching and idle throttling."""

from __future__ import annotations

import queue
import threading
import time

import pytest

from engine.simulation.target import SimulationTarget
from engine.simulation.engine import SimulationEngine


pytestmark = pytest.mark.unit


class CollectingEventBus:
    """EventBus that collects all published events for inspection."""

    def __init__(self) -> None:
        self._events: list[dict] = []
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object = None) -> None:
        msg = {"type": topic}
        if data is not None:
            msg["data"] = data
        with self._lock:
            self._events.append(msg)
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

    def get_events(self, event_type: str | None = None) -> list[dict]:
        with self._lock:
            if event_type is None:
                return list(self._events)
            return [e for e in self._events if e["type"] == event_type]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def _make_target(tid: str, x: float, y: float, alliance: str = "hostile",
                 asset_type: str = "person", speed: float = 0.0) -> SimulationTarget:
    return SimulationTarget(
        target_id=tid, name=f"T-{tid}", alliance=alliance,
        asset_type=asset_type, position=(x, y), speed=speed,
        is_combatant=False,
    )


class TestBatchTelemetry:
    """Engine should publish one sim_telemetry_batch per tick, not N individual events."""

    def test_batch_event_published_per_tick(self):
        bus = CollectingEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)

        t1 = _make_target("a", 10.0, 10.0)
        t2 = _make_target("b", 20.0, 20.0)
        t3 = _make_target("c", 30.0, 30.0)
        engine.add_target(t1)
        engine.add_target(t2)
        engine.add_target(t3)

        bus.clear()
        engine._do_tick(0.1)

        batch_events = bus.get_events("sim_telemetry_batch")
        individual_events = bus.get_events("sim_telemetry")
        assert len(batch_events) == 1, "Should publish exactly one batch event per tick"
        assert individual_events == [], "Should NOT publish individual sim_telemetry events"

    def test_batch_contains_all_targets(self):
        bus = CollectingEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)

        for i in range(5):
            engine.add_target(_make_target(str(i), float(i * 10), float(i * 10)))

        bus.clear()
        engine._do_tick(0.1)

        batch_events = bus.get_events("sim_telemetry_batch")
        assert len(batch_events) == 1
        batch_data = batch_events[0]["data"]
        assert len(batch_data) == 5

    def test_batch_target_has_expected_fields(self):
        bus = CollectingEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)
        engine.add_target(_make_target("x", 5.0, 5.0))

        bus.clear()
        engine._do_tick(0.1)

        batch_data = bus.get_events("sim_telemetry_batch")[0]["data"]
        entry = batch_data[0]
        assert "target_id" in entry
        assert "position" in entry
        assert "status" in entry

    def test_empty_engine_publishes_empty_batch(self):
        bus = CollectingEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)

        bus.clear()
        engine._do_tick(0.1)

        batch_events = bus.get_events("sim_telemetry_batch")
        assert len(batch_events) == 1
        assert batch_events[0]["data"] == []


class TestIdleThrottling:
    """Idle units (no state change for 5 ticks) should be sent at 2Hz (every 5th tick)."""

    def test_idle_unit_throttled(self):
        """An idle unit should appear in fewer batches than an active one over 10 ticks."""
        bus = CollectingEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)

        # Stationary turret (speed=0, no waypoints) — will be idle
        idle = _make_target("idle", 10.0, 10.0, alliance="friendly", asset_type="turret")
        engine.add_target(idle)

        # Moving hostile — will remain active
        active = _make_target("active", -100.0, -100.0, alliance="hostile",
                              asset_type="person", speed=1.5)
        active.waypoints = [(0.0, 0.0)]
        active.is_combatant = True
        engine.add_target(active)

        # Run 10 ticks
        active_count = 0
        idle_count = 0
        for i in range(10):
            bus.clear()
            engine._do_tick(0.1)
            batch_data = bus.get_events("sim_telemetry_batch")[0]["data"]
            ids_in_batch = {e["target_id"] for e in batch_data}
            if "active" in ids_in_batch:
                active_count += 1
            if "idle" in ids_in_batch:
                idle_count += 1

        # Active unit should appear in all 10 ticks
        assert active_count == 10
        # Idle unit: appears in first 5 ticks (building idle state), then throttled
        # Should appear fewer times than the active unit
        assert idle_count < active_count

    def test_idle_unit_resumes_full_rate_on_change(self):
        """If an idle unit's state changes, it should resume full-rate telemetry."""
        bus = CollectingEventBus()
        engine = SimulationEngine(bus, map_bounds=200.0)

        t = _make_target("t", 10.0, 10.0, alliance="friendly", asset_type="turret")
        engine.add_target(t)

        # Build up idle state (10 ticks with no change)
        for _ in range(10):
            engine._do_tick(0.1)

        # Now change the target's state
        t.health -= 10.0  # health changed
        bus.clear()
        engine._do_tick(0.1)

        batch_data = bus.get_events("sim_telemetry_batch")[0]["data"]
        ids_in_batch = {e["target_id"] for e in batch_data}
        assert "t" in ids_in_batch, "Changed unit must appear in next batch"
