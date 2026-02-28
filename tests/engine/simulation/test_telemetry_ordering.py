# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for telemetry batch ordering relative to combat.

Verifies that:
1. Telemetry batch reflects combat results from the SAME tick (not 1 tick late)
2. Health changes applied mid-tick appear in the batch
3. Idle throttling does not hide status changes

Bug: _do_tick() publishes sim_telemetry_batch BEFORE running combat.tick(),
so the batch shows pre-combat state. Eliminations are delayed by 1 tick.

Run: .venv/bin/python3 -m pytest tests/engine/simulation/test_telemetry_ordering.py -v
"""

from __future__ import annotations

import time as _time
from unittest.mock import patch

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.engine import SimulationEngine
from engine.simulation.target import SimulationTarget


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def engine(bus):
    eng = SimulationEngine(bus, map_bounds=100.0, max_hostiles=50)
    yield eng
    eng.stop()


def _collect_batch(sub, timeout=1.0):
    """Collect the first sim_telemetry_batch event."""
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        try:
            msg = sub.get(timeout=0.1)
            if msg.get("type") == "sim_telemetry_batch":
                return msg.get("data", [])
        except Exception:
            continue
    return None


@pytest.mark.unit
class TestTelemetryBatchOrdering:
    """Verify batch telemetry reflects all state changes from the same tick."""

    def test_combat_damage_reflected_in_batch(self, engine, bus):
        """If combat.tick() damages a target, the SAME tick's batch should
        show the reduced health, not the pre-combat value.

        This test patches combat.tick() to apply known damage, then checks
        whether the published batch includes that damage."""
        hostile = SimulationTarget(
            target_id="h-order-1",
            name="TestHostile",
            alliance="hostile",
            asset_type="person",
            position=(50.0, 50.0),
            speed=0.0,
            waypoints=[],
            status="active",
        )
        hostile.apply_combat_profile()
        hostile.health = 80.0
        hostile.max_health = 80.0
        engine.add_target(hostile)

        # Enable game mode
        engine.game_mode.state = "active"

        sub = bus.subscribe()
        engine._tick_counter = 0
        engine._idle_ticks.clear()
        engine._last_snapshot.clear()

        # Patch combat.tick to apply known damage
        original_combat_tick = engine.combat.tick

        def damaging_combat_tick(dt, targets_dict, **kwargs):
            # Apply 30 damage to our hostile
            t = targets_dict.get("h-order-1")
            if t and t.health > 50:
                t.apply_damage(30.0)
            original_combat_tick(dt, targets_dict, **kwargs)

        with patch.object(engine.combat, 'tick', side_effect=damaging_combat_tick):
            engine._do_tick(0.1)

        batch = _collect_batch(sub)
        assert batch is not None, "Should receive telemetry batch"

        # Find our hostile in the batch
        h_data = None
        for item in batch:
            if item["target_id"] == "h-order-1":
                h_data = item
                break

        assert h_data is not None, "Hostile should appear in batch"
        # The batch should show health=50 (80-30), not 80 (pre-combat)
        assert h_data["health"] == 50.0, (
            f"Batch should show post-combat health 50.0, got {h_data['health']} "
            f"(if 80.0, batch was published BEFORE combat)"
        )

    def test_elimination_reflected_in_batch(self, engine, bus):
        """If combat.tick() eliminates a target, the SAME tick's batch
        should show status='eliminated'."""
        hostile = SimulationTarget(
            target_id="h-elim-1",
            name="Doomed",
            alliance="hostile",
            asset_type="person",
            position=(50.0, 50.0),
            speed=0.0,
            waypoints=[],
            status="active",
        )
        hostile.apply_combat_profile()
        hostile.health = 10.0
        engine.add_target(hostile)

        engine.game_mode.state = "active"

        sub = bus.subscribe()
        engine._tick_counter = 0
        engine._idle_ticks.clear()
        engine._last_snapshot.clear()

        original_combat_tick = engine.combat.tick

        def eliminating_combat_tick(dt, targets_dict, **kwargs):
            t = targets_dict.get("h-elim-1")
            if t and t.status not in ("eliminated", "destroyed"):
                t.apply_damage(100.0)  # Overkill
            original_combat_tick(dt, targets_dict, **kwargs)

        with patch.object(engine.combat, 'tick', side_effect=eliminating_combat_tick):
            engine._do_tick(0.1)

        batch = _collect_batch(sub)
        assert batch is not None

        h_data = None
        for item in batch:
            if item["target_id"] == "h-elim-1":
                h_data = item
                break

        assert h_data is not None, "Eliminated target should appear in batch"
        assert h_data["status"] == "eliminated", (
            f"Should be 'eliminated', got '{h_data['status']}' "
            f"(if 'active', batch was published BEFORE combat)"
        )

    def test_idle_throttling_does_not_hide_status_changes(self, engine, bus):
        """If a target has been idle for 5+ ticks, a status change should
        NOT be hidden by idle throttling."""
        target = SimulationTarget(
            target_id="idle-victim",
            name="IdleGuy",
            alliance="hostile",
            asset_type="person",
            position=(50.0, 50.0),
            speed=0.0,
            waypoints=[],
            status="active",
        )
        target.apply_combat_profile()
        engine.add_target(target)

        sub = bus.subscribe()
        engine._tick_counter = 0
        engine._idle_ticks.clear()
        engine._last_snapshot.clear()

        # Run 6 ticks to build up idle count
        for _ in range(6):
            engine._do_tick(0.1)

        idle_count = engine._idle_ticks.get("idle-victim", 0)
        assert idle_count >= 5, f"Should have idle count >= 5, got {idle_count}"

        # Manually eliminate the target
        target.health = 0.0
        target.status = "eliminated"

        # Drain old events
        while True:
            try:
                sub.get(timeout=0.01)
            except Exception:
                break

        # Run one more tick
        engine._do_tick(0.1)

        batch = _collect_batch(sub)
        assert batch is not None, "Should get a telemetry batch"

        found = False
        for item in batch:
            if item["target_id"] == "idle-victim":
                found = True
                assert item["status"] == "eliminated", (
                    f"Should show 'eliminated', got '{item['status']}'"
                )
                break

        assert found, "Eliminated target should appear in batch despite idle throttling"
