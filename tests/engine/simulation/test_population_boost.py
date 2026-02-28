# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for boosted non-combatant population.

Verifies:
- AmbientSpawner MAX_NEUTRALS increased to 80
- NPCManager has auto-spawn loop
- NPCManager default caps increased (150 vehicles, 200 pedestrians)
- Time-of-day density scaling works for NPC auto-spawning
"""

import pytest
import time
from unittest.mock import MagicMock, patch


def _make_engine(map_bounds=200):
    """Create a minimal mock engine."""
    from engine.comms.event_bus import EventBus
    bus = EventBus()
    engine = MagicMock()
    engine._map_bounds = map_bounds
    engine.spawners_paused = False
    engine.get_targets.return_value = []
    engine.add_target = MagicMock()
    engine._street_graph = None
    engine._obstacles = None
    return engine


class TestAmbientSpawnerBoost:
    """Test increased ambient spawner capacity."""

    def test_max_neutrals_increased(self):
        from engine.simulation.ambient import AmbientSpawner
        assert AmbientSpawner.MAX_NEUTRALS >= 80

    def test_spawn_interval_reduced(self):
        """Spawn interval should be shorter to fill faster."""
        from engine.simulation.ambient import AmbientSpawner
        assert AmbientSpawner.SPAWN_MIN <= 8.0
        assert AmbientSpawner.SPAWN_MAX <= 20.0


class TestNPCManagerAutoSpawn:
    """Test that NPCManager auto-spawns when started."""

    def test_npc_manager_has_start_method(self):
        from engine.simulation.npc import NPCManager
        engine = _make_engine()
        mgr = NPCManager(engine)
        assert hasattr(mgr, "start")

    def test_npc_manager_has_stop_method(self):
        from engine.simulation.npc import NPCManager
        engine = _make_engine()
        mgr = NPCManager(engine)
        assert hasattr(mgr, "stop")

    def test_default_caps_increased(self):
        from engine.simulation.npc import NPCManager
        engine = _make_engine()
        mgr = NPCManager(engine)
        assert mgr.max_vehicles >= 150
        assert mgr.max_pedestrians >= 200

    def test_auto_spawn_creates_vehicles(self):
        """After calling _auto_spawn_tick, should create vehicles."""
        from engine.simulation.npc import NPCManager
        engine = _make_engine()
        mgr = NPCManager(engine)

        # Manually trigger a spawn tick
        mgr._auto_spawn_tick()
        # Should have called add_target at least once
        assert engine.add_target.call_count > 0

    def test_auto_spawn_respects_vehicle_cap(self):
        """Should not exceed vehicle capacity."""
        from engine.simulation.npc import NPCManager
        engine = _make_engine()
        mgr = NPCManager(engine, max_vehicles=5, max_pedestrians=5)

        # Simulate existing vehicles
        for _ in range(5):
            mgr.spawn_vehicle()

        # Now try auto-spawn — should not add more vehicles
        initial = len(mgr._npc_ids)
        mgr._auto_spawn_tick()
        # May add pedestrians but not vehicles beyond cap
        vehicle_count = sum(1 for tid in mgr._npc_ids if tid in mgr._vehicle_types)
        assert vehicle_count <= 5

    def test_auto_spawn_batch_size(self):
        """Auto-spawn should create multiple entities per tick for fast fill."""
        from engine.simulation.npc import NPCManager
        engine = _make_engine()
        mgr = NPCManager(engine, max_vehicles=100, max_pedestrians=100)

        mgr._auto_spawn_tick()
        # Should spawn a batch, not just 1
        assert len(mgr._npc_ids) >= 3

    def test_spawn_loop_can_start_and_stop(self):
        """Start and stop the auto-spawn thread without hanging."""
        from engine.simulation.npc import NPCManager
        engine = _make_engine()
        mgr = NPCManager(engine, max_vehicles=5, max_pedestrians=5)
        mgr.start()
        assert mgr._running
        time.sleep(0.1)
        mgr.stop()
        assert not mgr._running


class TestNPCManagerDefaultsInEngine:
    """Test that engine creates NPCManager with boosted defaults."""

    def test_engine_npc_defaults(self):
        """Engine should create NPCManager with higher caps."""
        from engine.comms.event_bus import EventBus
        from engine.simulation.engine import SimulationEngine

        bus = EventBus()
        engine = SimulationEngine(bus, map_bounds=200)
        # Don't start threads — just check the config would pass through
        # The actual caps come from settings or defaults
        assert hasattr(engine, '_npc_manager')


class TestTrafficDensityScaling:
    """Test time-of-day traffic density for auto-spawning."""

    def test_rush_hour_high(self):
        from engine.simulation.npc import traffic_density
        assert traffic_density(8) >= 0.7
        assert traffic_density(17) >= 0.7

    def test_night_low(self):
        from engine.simulation.npc import traffic_density
        assert traffic_density(3) <= 0.1

    def test_midday_moderate(self):
        from engine.simulation.npc import traffic_density
        d = traffic_density(12)
        assert 0.3 <= d <= 0.8
