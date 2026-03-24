# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests that reset_game() fully clears all per-game subsystem state.

Ensures no state leaks between games — every subsystem is reset,
mission-type trackers are None'd, and FSMs are cleared.
"""

from __future__ import annotations

import queue
import threading

from unittest.mock import MagicMock

import pytest

from engine.simulation.engine import SimulationEngine
from tritium_lib.sim_engine.core.entity import SimulationTarget

pytestmark = pytest.mark.unit


class SimpleEventBus:
    """Minimal EventBus for testing."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, data: object) -> None:
        with self._lock:
            for q in self._subscribers.get(topic, []):
                q.put({"type": topic, "data": data})

    def subscribe(self, topic: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        if topic:
            with self._lock:
                self._subscribers.setdefault(topic, []).append(q)
        return q


def _make_engine():
    bus = SimpleEventBus()
    return SimulationEngine(bus, map_bounds=100.0)


class TestResetClearsMissionTrackers:
    """reset_game() should None out all mission-type subsystems."""

    def test_instigator_detector_cleared(self):
        engine = _make_engine()
        engine._instigator_detector = object()  # simulate set during start
        engine.reset_game()
        assert engine._instigator_detector is None

    def test_crowd_density_tracker_cleared(self):
        engine = _make_engine()
        engine._crowd_density_tracker = object()
        engine.reset_game()
        assert engine._crowd_density_tracker is None

    def test_swarm_behavior_cleared(self):
        engine = _make_engine()
        engine._swarm_behavior = object()
        engine.reset_game()
        assert engine._swarm_behavior is None

    def test_infrastructure_health_cleared(self):
        engine = _make_engine()
        engine._infrastructure_health = object()
        engine.reset_game()
        assert engine._infrastructure_health is None

    def test_poi_buildings_cleared(self):
        engine = _make_engine()
        engine._poi_buildings = [1, 2, 3]
        engine.reset_game()
        assert engine._poi_buildings == []


class TestResetClearsGameState:
    """reset_game() should reset game mode and FSMs."""

    def test_game_mode_reset(self):
        engine = _make_engine()
        engine.game_mode.wave = 5
        engine.game_mode.state = "active"
        engine.reset_game()
        assert engine.game_mode.wave == 0
        assert engine.game_mode.state == "setup"  # resets to setup, not idle

    def test_fsms_cleared(self):
        engine = _make_engine()
        engine._fsms["test-unit"] = object()
        engine.reset_game()
        assert len(engine._fsms) == 0

    def test_stall_positions_cleared(self):
        engine = _make_engine()
        engine._stall_positions["t1"] = (10.0, 20.0)
        engine._stall_ticks["t1"] = 5
        engine.reset_game()
        assert len(engine._stall_positions) == 0
        assert len(engine._stall_ticks) == 0


class TestResetClearsSubsystems:
    """reset_game() should call reset on all extended subsystems."""

    def test_stats_tracker_reset(self):
        engine = _make_engine()
        engine.stats_tracker._unit_stats["test"] = object()
        engine.reset_game()
        assert len(engine.stats_tracker._unit_stats) == 0

    def test_weapon_system_reset(self):
        engine = _make_engine()
        engine.weapon_system._weapons["test"] = object()
        engine.reset_game()
        assert len(engine.weapon_system._weapons) == 0

    def test_morale_system_reset(self):
        engine = _make_engine()
        engine.morale_system._morale["test"] = 0.5
        engine.reset_game()
        assert len(engine.morale_system._morale) == 0

    def test_upgrade_system_reset(self):
        engine = _make_engine()
        engine.upgrade_system._unit_upgrades["test"] = []
        engine.reset_game()
        assert len(engine.upgrade_system._unit_upgrades) == 0


class TestResetClearsBackstoryGenerator:
    """reset_game() should reset the BackstoryGenerator's per-game state."""

    def test_backstory_generator_queue_cleared(self):
        """Pending backstory queue should be drained on reset."""
        engine = _make_engine()
        from unittest.mock import MagicMock
        gen = MagicMock()
        gen.reset = MagicMock()
        engine._backstory_generator = gen
        engine.reset_game()
        gen.reset.assert_called_once()

    def test_backstory_generator_none_skips(self):
        """If no backstory generator attached, reset_game() should not crash."""
        engine = _make_engine()
        assert engine._backstory_generator is None
        # Should not raise
        engine.reset_game()

    def test_backstory_reset_method_clears_queue(self):
        """BackstoryGenerator.reset() clears _queue."""
        from engine.simulation.backstory import BackstoryGenerator
        from engine.comms.event_bus import EventBus
        from unittest.mock import MagicMock
        bus = EventBus()
        fleet = MagicMock()
        fleet.hosts_with_model.return_value = []
        gen = BackstoryGenerator(fleet=fleet, event_bus=bus)
        # Simulate queued items
        gen._queue.append(object())
        gen._queue.append(object())
        gen.reset()
        assert len(gen._queue) == 0

    def test_backstory_reset_method_clears_pending(self):
        """BackstoryGenerator.reset() clears _pending set."""
        from engine.simulation.backstory import BackstoryGenerator
        from engine.comms.event_bus import EventBus
        from unittest.mock import MagicMock
        bus = EventBus()
        fleet = MagicMock()
        fleet.hosts_with_model.return_value = []
        gen = BackstoryGenerator(fleet=fleet, event_bus=bus)
        gen._pending.add("unit-1")
        gen._pending.add("unit-2")
        gen.reset()
        assert len(gen._pending) == 0

    def test_backstory_reset_method_clears_backstories(self):
        """BackstoryGenerator.reset() clears _backstories dict."""
        from engine.simulation.backstory import BackstoryGenerator
        from engine.comms.event_bus import EventBus
        from unittest.mock import MagicMock
        bus = EventBus()
        fleet = MagicMock()
        fleet.hosts_with_model.return_value = []
        gen = BackstoryGenerator(fleet=fleet, event_bus=bus)
        gen._backstories["t1"] = {"name": "Old Guy"}
        gen.reset()
        assert len(gen._backstories) == 0

    def test_backstory_reset_method_clears_targets(self):
        """BackstoryGenerator.reset() clears _targets dict."""
        from engine.simulation.backstory import BackstoryGenerator
        from engine.comms.event_bus import EventBus
        from unittest.mock import MagicMock
        bus = EventBus()
        fleet = MagicMock()
        fleet.hosts_with_model.return_value = []
        gen = BackstoryGenerator(fleet=fleet, event_bus=bus)
        gen._targets["t1"] = object()
        gen.reset()
        assert len(gen._targets) == 0

    def test_backstory_reset_preserves_cache(self):
        """BackstoryGenerator.reset() preserves _cache (disk cache persists)."""
        from engine.simulation.backstory import BackstoryGenerator
        from engine.comms.event_bus import EventBus
        from unittest.mock import MagicMock
        bus = EventBus()
        fleet = MagicMock()
        fleet.hosts_with_model.return_value = []
        gen = BackstoryGenerator(fleet=fleet, event_bus=bus)
        gen._cache["some_key"] = {"name": "Cached"}
        gen.reset()
        # Cache should survive reset — it's a disk-backed cross-game cache
        assert "some_key" in gen._cache


class TestResetClearsAmbientSpawnerNames:
    """reset_game() should clear AmbientSpawner._used_names."""

    def test_ambient_used_names_cleared(self):
        """Used names should be empty after reset so names recycle."""
        engine = _make_engine()
        engine._ambient_spawner = MagicMock()
        engine._ambient_spawner._used_names = {"Mrs. Henderson", "Old Tom"}
        engine.reset_game()
        # The engine's _used_names is cleared in reset_game already.
        # But AmbientSpawner has its OWN _used_names that's separate.
        # Verify the ambient spawner's names are cleared too.
        assert len(engine._ambient_spawner._used_names) == 0

    def test_ambient_spawner_not_stopped_on_reset(self):
        """AmbientSpawner should keep running after reset (it's ambient noise)."""
        engine = _make_engine()
        from engine.simulation.ambient import AmbientSpawner
        spawner = AmbientSpawner(engine)
        engine._ambient_spawner = spawner
        engine.reset_game()
        # The spawner should still be alive (not stopped)
        assert engine._ambient_spawner is not None


class TestResetClearsNPCManager:
    """reset_game() should clear NPC manager tracking data."""

    def test_npc_manager_missions_cleared(self):
        """Stale NPC missions should not leak across games."""
        engine = _make_engine()
        from tritium_lib.sim_engine.behavior.npc import NPCManager
        mgr = NPCManager(engine)
        mgr._missions["npc-1"] = object()
        mgr._npc_ids.add("npc-1")
        engine._npc_manager = mgr
        engine.reset_game()
        assert len(mgr._missions) == 0
        assert len(mgr._npc_ids) == 0

    def test_npc_manager_used_names_cleared(self):
        """Name pool should recycle between games."""
        engine = _make_engine()
        from tritium_lib.sim_engine.behavior.npc import NPCManager
        mgr = NPCManager(engine)
        mgr._used_names.update({"Alice", "Bob", "Carol"})
        engine._npc_manager = mgr
        engine.reset_game()
        assert len(mgr._used_names) == 0

    def test_npc_manager_none_skips(self):
        """If no NPC manager attached, reset_game() should not crash."""
        engine = _make_engine()
        assert engine._npc_manager is None
        engine.reset_game()
