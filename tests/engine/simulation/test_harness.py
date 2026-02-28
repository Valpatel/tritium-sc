# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Reusable test harness for simulation combat scenarios.

Provides SimulationTestHarness — a self-contained sandbox that wires
EventBus, CombatSystem, and UnitBehaviors together so tests can place
friendlies, spawn hostiles, run ticks, and assert on combat events
without starting the full SimulationEngine (no threads, no sleeps).
"""

from __future__ import annotations

import time

import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.combat import CombatSystem
from engine.simulation.behaviors import UnitBehaviors
from engine.simulation.target import SimulationTarget


class SimulationTestHarness:
    """Synchronous test harness for combat simulation scenarios.

    Runs CombatSystem + UnitBehaviors in lockstep ticks.  No background
    threads — everything is deterministic and driven by ``run_ticks()``.
    """

    def __init__(self) -> None:
        self.bus = EventBus()
        self.events: list[dict] = []
        self._targets: dict[str, SimulationTarget] = {}
        self._combat = CombatSystem(self.bus)
        self._behaviors = UnitBehaviors(self._combat)
        self._sub = self.bus.subscribe()

    # -- Setup helpers -------------------------------------------------------

    def place_friendly(
        self,
        target_id: str,
        x: float,
        y: float,
        asset_type: str = "turret",
    ) -> SimulationTarget:
        """Place a friendly combatant at (x, y) with its combat profile."""
        t = SimulationTarget(
            target_id=target_id,
            name=f"Friendly {target_id}",
            alliance="friendly",
            asset_type=asset_type,
            position=(x, y),
            speed=0.0 if asset_type == "turret" else 2.0,
        )
        t.apply_combat_profile()
        # Reset last_fired so the unit can fire immediately
        t.last_fired = 0.0
        self._targets[target_id] = t
        return t

    def spawn_hostile(
        self,
        target_id: str,
        x: float,
        y: float,
        speed: float = 1.5,
    ) -> SimulationTarget:
        """Spawn a hostile person at (x, y) heading toward origin."""
        t = SimulationTarget(
            target_id=target_id,
            name=f"Hostile {target_id}",
            alliance="hostile",
            asset_type="person",
            position=(x, y),
            speed=speed,
            waypoints=[(0.0, 0.0)],  # head toward origin
        )
        t.apply_combat_profile()
        t.last_fired = 0.0
        self._targets[target_id] = t
        return t

    # -- Tick ----------------------------------------------------------------

    def run_ticks(self, n: int, dt: float = 0.1) -> None:
        """Run n simulation ticks synchronously.

        Each tick: advance targets, run behaviors, resolve combat,
        then drain the EventBus queue into self.events.

        Weapon cooldowns use ``time.time()`` internally, so we reset
        ``last_fired`` each tick to simulate real-time passage.  Without
        this, a fast test loop would only allow 1-2 shots per second of
        wall-clock time regardless of how many ticks run.
        """
        for _ in range(n):
            # Reset weapon cooldowns so units can fire each tick
            for t in self._targets.values():
                if t.is_combatant and t.status in ("active", "idle", "stationary"):
                    t.last_fired = 0.0

            # Advance target waypoint movement
            for t in self._targets.values():
                t.tick(dt)

            # Unit AI decisions (turret aim, drone strafe, etc.)
            self._behaviors.tick(dt, self._targets)

            # Projectile flight + hit detection + damage
            self._combat.tick(dt, self._targets)

            # Drain event queue
            self._drain_events()

    def _drain_events(self) -> None:
        """Drain all pending events from the bus subscriber queue."""
        while True:
            try:
                msg = self._sub.get_nowait()
                self.events.append(msg)
            except Exception:
                break

    # -- Assertions ----------------------------------------------------------

    def assert_event(self, event_type: str, predicate=None) -> dict:
        """Assert that an event matching event_type was received.

        Returns the last matching event.
        """
        matching = [e for e in self.events if e.get("type") == event_type]
        if predicate:
            matching = [e for e in matching if predicate(e)]
        assert matching, (
            f"Expected event '{event_type}' not found in "
            f"{len(self.events)} events: {[e.get('type') for e in self.events]}"
        )
        return matching[-1]

    def assert_no_event(self, event_type: str) -> None:
        """Assert that no event of the given type was received."""
        matching = [e for e in self.events if e.get("type") == event_type]
        assert not matching, f"Unexpected event '{event_type}' found: {matching}"

    def assert_target_alive(self, target_id: str) -> None:
        """Assert target exists and is in an alive status."""
        t = self._targets.get(target_id)
        assert t is not None, f"Target '{target_id}' not found"
        assert t.status in ("active", "idle", "stationary"), (
            f"Target '{target_id}' status is '{t.status}', expected alive"
        )

    def assert_target_eliminated(self, target_id: str) -> None:
        """Assert target has been eliminated."""
        t = self._targets.get(target_id)
        assert t is not None, f"Target '{target_id}' not found"
        assert t.status == "eliminated", (
            f"Target '{target_id}' status is '{t.status}', expected 'eliminated'"
        )

    def get_target(self, target_id: str) -> SimulationTarget | None:
        """Get a target by ID."""
        return self._targets.get(target_id)

    def event_count(self, event_type: str) -> int:
        """Count events of a given type."""
        return sum(1 for e in self.events if e.get("type") == event_type)


class _EngineStub:
    """Minimal engine interface for GameMode."""

    def __init__(self, targets: dict[str, SimulationTarget]):
        self._targets = targets
        self._hostile_counter = 0

    def get_targets(self) -> list[SimulationTarget]:
        return list(self._targets.values())

    def spawn_hostile(self) -> SimulationTarget:
        """Spawn a hostile at a random edge position."""
        import random
        self._hostile_counter += 1
        tid = f"wave-hostile-{self._hostile_counter}"
        x = random.choice([-20, 20])
        y = random.uniform(-15, 15)
        t = SimulationTarget(
            target_id=tid,
            name=f"Hostile {tid}",
            alliance="hostile",
            asset_type="person",
            position=(x, y),
            speed=1.5,
            waypoints=[(0.0, 0.0)],
        )
        t.apply_combat_profile()
        t.last_fired = 0.0
        self._targets[tid] = t
        return t


class GameTestHarness(SimulationTestHarness):
    """Extends SimulationTestHarness with GameMode for full game lifecycle testing.

    Synchronous: spawning is done inline (no background threads).
    """

    def __init__(self) -> None:
        super().__init__()
        from engine.simulation.game_mode import GameMode
        self._engine_stub = _EngineStub(self._targets)
        self._game_mode = GameMode(self.bus, self._engine_stub, self._combat)
        # Monkey-patch _start_wave to spawn synchronously (no threads)
        self._game_mode._start_wave = self._sync_start_wave

    def _sync_start_wave(self, wave_num: int) -> None:
        """Synchronous wave spawn (replaces threaded version for tests)."""
        from engine.simulation.game_mode import WAVE_CONFIGS
        config = WAVE_CONFIGS[wave_num - 1] if 1 <= wave_num <= len(WAVE_CONFIGS) else None
        if config is None:
            return
        self._game_mode.wave_eliminations = 0
        self._game_mode._wave_start_time = time.time()
        self._game_mode._wave_hostile_ids.clear()
        self.bus.publish("wave_start", {
            "wave_number": wave_num,
            "wave_name": config.name,
            "hostile_count": config.count,
        })
        for i in range(config.count):
            hostile = self._engine_stub.spawn_hostile()
            hostile.speed *= config.speed_mult
            hostile.health = 80.0 * config.health_mult
            hostile.max_health = 80.0 * config.health_mult
            hostile.apply_combat_profile()
            hostile.health = 80.0 * config.health_mult
            hostile.max_health = 80.0 * config.health_mult
            self._game_mode._wave_hostile_ids.add(hostile.target_id)

    def begin_war(self) -> None:
        """Start the game (setup -> countdown)."""
        self._game_mode.begin_war()
        self._drain_events()

    def tick_game(self, n: int = 1, dt: float = 0.1) -> None:
        """Run n ticks of game + combat simulation."""
        for _ in range(n):
            # Reset cooldowns
            for t in self._targets.values():
                if t.is_combatant and t.status in ("active", "idle", "stationary"):
                    t.last_fired = 0.0
            for t in self._targets.values():
                t.tick(dt)
            self._behaviors.tick(dt, self._targets)
            self._combat.tick(dt, self._targets)
            self._game_mode.tick(dt)
            self._drain_events()

    def get_game_state(self) -> dict:
        return self._game_mode.get_state()

    def reset_game(self) -> None:
        self._game_mode.reset()
        self._drain_events()

    def eliminate_all_wave_hostiles(self) -> None:
        """Force-eliminate all current wave hostiles for testing."""
        for tid in list(self._game_mode._wave_hostile_ids):
            t = self._targets.get(tid)
            if t and t.status == "active":
                t.health = 0
                t.status = "eliminated"
                self._game_mode.on_target_eliminated(tid)
        self._drain_events()

    def eliminate_all_friendlies(self) -> None:
        """Force-eliminate all friendly combatants for testing defeat."""
        for t in list(self._targets.values()):
            if t.alliance == "friendly" and t.is_combatant:
                t.health = 0
                t.status = "eliminated"
        self._drain_events()
