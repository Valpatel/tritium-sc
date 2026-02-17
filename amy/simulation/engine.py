"""SimulationEngine — 10 Hz tick loop driving all SimulationTargets.

Architecture
------------
The engine is the authoritative owner of all SimulationTarget instances.
It runs three daemon threads:

  1. sim-tick (10 Hz) — calls target.tick(0.1) for every target, then
     publishes each target's state as a ``sim_telemetry`` event on the
     EventBus.  Also handles garbage collection: despawned neutrals are
     removed after 5s, destroyed targets after 300s.

  2. sim-spawner — hostile auto-spawner with adaptive timing.  Spawn rate
     slows as hostile count increases (back-pressure) and hard-caps at
     MAX_HOSTILES=10.  This is part of the engine (not a separate spawner
     class) because hostile pressure is the engine's core tactical output.

  3. ambient-spawner — delegated to AmbientSpawner (separate class) for
     neutral neighborhood activity.

Data flow:
  Engine --(sim_telemetry)--> EventBus --(bridge loop)--> TargetTracker
  The bridge loop in Commander._sim_bridge_loop subscribes to EventBus
  and copies state into TargetTracker.  This is intentional double-tracking:
  the engine owns *simulation* state (waypoints, tick physics), while the
  tracker provides Amy with a *unified view* of sim + YOLO targets.

  When Amy dispatches a unit (dispatch/patrol Lua actions), the action
  handler in thinking.py modifies the SimulationTarget directly (setting
  waypoints).  The next tick publishes updated telemetry, and the bridge
  loop propagates it to the tracker.  The one-tick latency (~100ms) is
  acceptable for turn-based tactical decisions.

Tick rate (10 Hz / fixed 0.1s step):
  At max vehicle speed (8.0 units/s), movement per tick is 0.8 units.
  This is adequate for map-scale rendering (60x60 unit map); sub-unit
  jitter is invisible at the tactical zoom level.  Variable-rate ticking
  was considered but adds complexity (accumulator, spiral-of-death
  protection) with no visual benefit at this scale.
"""

from __future__ import annotations

import math
import random
import threading
import time
import uuid
from typing import TYPE_CHECKING

from .ambient import AmbientSpawner
from .target import SimulationTarget

if TYPE_CHECKING:
    from amy.commander import EventBus

# Map bounds for random spawns
_MAP_MIN = -30.0
_MAP_MAX = 30.0

_HOSTILE_NAMES = [
    "Intruder Alpha",
    "Intruder Bravo",
    "Intruder Charlie",
    "Intruder Delta",
    "Intruder Echo",
    "Intruder Foxtrot",
    "Intruder Golf",
    "Intruder Hotel",
]


class SimulationEngine:
    """Drives simulated targets at 10 Hz and publishes telemetry events."""

    MAX_HOSTILES = 10

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._targets: dict[str, SimulationTarget] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._spawner_thread: threading.Thread | None = None
        self._used_names: set[str] = set()
        self._destroyed_at: dict[str, float] = {}
        self._despawned_at: dict[str, float] = {}
        self._ambient_spawner: AmbientSpawner | None = None
        self._spawners_paused = threading.Event()  # clear = running, set = paused

    # -- Target management --------------------------------------------------

    def add_target(self, target: SimulationTarget) -> None:
        with self._lock:
            self._targets[target.target_id] = target

    def remove_target(self, target_id: str) -> bool:
        with self._lock:
            return self._targets.pop(target_id, None) is not None

    def get_targets(self) -> list[SimulationTarget]:
        with self._lock:
            return list(self._targets.values())

    def get_target(self, target_id: str) -> SimulationTarget | None:
        with self._lock:
            return self._targets.get(target_id)

    @property
    def ambient_spawner(self) -> AmbientSpawner | None:
        return self._ambient_spawner

    @property
    def spawners_paused(self) -> bool:
        return self._spawners_paused.is_set()

    def pause_spawners(self) -> None:
        """Pause hostile and ambient spawners (tick loop continues)."""
        self._spawners_paused.set()

    def resume_spawners(self) -> None:
        """Resume hostile and ambient spawners."""
        self._spawners_paused.clear()

    # -- Lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._tick_loop, name="sim-tick", daemon=True
        )
        self._thread.start()
        self._spawner_thread = threading.Thread(
            target=self._random_hostile_spawner, name="sim-spawner", daemon=True
        )
        self._spawner_thread.start()
        self._ambient_spawner = AmbientSpawner(self)
        self._ambient_spawner.start()

    def stop(self) -> None:
        self._running = False
        if self._ambient_spawner is not None:
            self._ambient_spawner.stop()
            self._ambient_spawner = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._spawner_thread is not None:
            self._spawner_thread.join(timeout=2.0)
            self._spawner_thread = None

    # Engagement range — a friendly within this distance of a hostile
    # neutralizes the hostile on the next tick.
    INTERCEPT_RANGE = 2.0

    # -- Tick loop ----------------------------------------------------------

    def _tick_loop(self) -> None:
        while self._running:
            time.sleep(0.1)
            with self._lock:
                targets = list(self._targets.values())
            for target in targets:
                target.tick(0.1)
                self._event_bus.publish("sim_telemetry", target.to_dict())

            # Interception check — friendly within range neutralizes hostile
            self._check_interceptions(targets)

            # Lifecycle cleanup
            now = time.time()
            to_remove: list[str] = []
            for target in targets:
                if target.battery <= 0 and target.status == "low_battery":
                    if target.target_id not in self._destroyed_at:
                        self._destroyed_at[target.target_id] = now
                    elif now - self._destroyed_at[target.target_id] > 60:
                        target.status = "destroyed"
                if target.status == "destroyed":
                    if target.target_id not in self._destroyed_at:
                        self._destroyed_at[target.target_id] = now
                    elif now - self._destroyed_at[target.target_id] > 300:
                        to_remove.append(target.target_id)
                # Despawned neutrals — remove after 5s
                if target.status == "despawned":
                    if target.target_id not in self._despawned_at:
                        self._despawned_at[target.target_id] = now
                    elif now - self._despawned_at[target.target_id] > 5:
                        to_remove.append(target.target_id)
                # Escaped hostiles — remove after 10s (they left the map)
                if target.status == "escaped":
                    if target.target_id not in self._despawned_at:
                        self._despawned_at[target.target_id] = now
                    elif now - self._despawned_at[target.target_id] > 10:
                        to_remove.append(target.target_id)
                # Neutralized targets — remove after 30s (visible on map briefly)
                if target.status == "neutralized":
                    if target.target_id not in self._despawned_at:
                        self._despawned_at[target.target_id] = now
                    elif now - self._despawned_at[target.target_id] > 30:
                        to_remove.append(target.target_id)

            for tid in to_remove:
                with self._lock:
                    removed = self._targets.pop(tid, None)
                self._destroyed_at.pop(tid, None)
                self._despawned_at.pop(tid, None)
                if removed is not None:
                    self._used_names.discard(removed.name)
                    if self._ambient_spawner is not None:
                        self._ambient_spawner.release_name(removed.name)

    def _check_interceptions(self, targets: list[SimulationTarget]) -> None:
        """Check if any friendly unit is close enough to neutralize a hostile."""
        friendlies = [t for t in targets if t.alliance == "friendly" and t.status == "active"]
        hostiles = [t for t in targets if t.alliance == "hostile" and t.status == "active"]
        r2 = self.INTERCEPT_RANGE ** 2
        for hostile in hostiles:
            for friendly in friendlies:
                dx = hostile.position[0] - friendly.position[0]
                dy = hostile.position[1] - friendly.position[1]
                if (dx * dx + dy * dy) <= r2:
                    hostile.status = "neutralized"
                    self._event_bus.publish("target_neutralized", {
                        "hostile_id": hostile.target_id,
                        "hostile_name": hostile.name,
                        "interceptor_id": friendly.target_id,
                        "interceptor_name": friendly.name,
                        "position": {"x": hostile.position[0], "y": hostile.position[1]},
                    })
                    break

    # -- Hostile spawning ---------------------------------------------------

    def spawn_hostile(
        self,
        name: str | None = None,
        position: tuple[float, float] | None = None,
    ) -> SimulationTarget:
        """Create a hostile person target, optionally at a specific position."""
        if position is None:
            position = self._random_edge_position()

        if name is None:
            base_name = random.choice(_HOSTILE_NAMES)
        else:
            base_name = name
        name = base_name
        suffix = 2
        while name in self._used_names:
            name = f"{base_name}-{suffix}"
            suffix += 1
        self._used_names.add(name)

        # Multi-waypoint path: edge -> approach -> objective -> loiter -> escape
        approach = (
            position[0] * 0.5 + random.uniform(-5, 5),
            position[1] * 0.5 + random.uniform(-5, 5),
        )
        objective = (random.uniform(-8, 8), random.uniform(-8, 8))
        loiter = (
            objective[0] + random.uniform(-3, 3),
            objective[1] + random.uniform(-3, 3),
        )
        escape_edge = self._random_edge_position()
        waypoints = [approach, objective, loiter, escape_edge]

        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=name,
            alliance="hostile",
            asset_type="person",
            position=position,
            speed=1.5,
            waypoints=waypoints,
        )
        self.add_target(target)
        return target

    def _random_edge_position(self) -> tuple[float, float]:
        """Return a random position on one of the four map edges."""
        edge = random.randint(0, 3)
        coord = random.uniform(_MAP_MIN, _MAP_MAX)
        if edge == 0:  # north
            return (coord, _MAP_MAX)
        elif edge == 1:  # south
            return (coord, _MAP_MIN)
        elif edge == 2:  # east
            return (_MAP_MAX, coord)
        else:  # west
            return (_MAP_MIN, coord)

    def _count_active_hostiles(self) -> int:
        """Count hostiles that are still a threat (active, not neutralized/escaped/destroyed)."""
        with self._lock:
            return sum(
                1 for t in self._targets.values()
                if t.alliance == "hostile" and t.status == "active"
            )

    def _random_hostile_spawner(self) -> None:
        """Periodically spawn hostile intruders with adaptive rate and cap.

        Hostile spawn rate is modulated by time of day: more intrusions at
        night, fewer during daylight hours.  See ambient._hour_activity().
        Respects _spawners_paused — when set, skips spawning entirely.
        """
        from .ambient import _hour_activity

        while self._running:
            # Adaptive delay based on current active hostile count
            hostile_count = self._count_active_hostiles()
            if hostile_count >= self.MAX_HOSTILES:
                delay = 10.0  # Check again in 10s
            elif hostile_count > 5:
                delay = random.uniform(60.0, 120.0)  # Slower when many
            else:
                delay = random.uniform(30.0, 60.0)  # Normal rate

            # Scale by time of day — shorter delays at night (more pressure)
            _, hostile_mult = _hour_activity()
            delay = delay / max(hostile_mult, 0.1)

            # Sleep in small increments so we can stop quickly
            elapsed = 0.0
            while elapsed < delay and self._running:
                time.sleep(0.5)
                elapsed += 0.5

            if self._running and not self._spawners_paused.is_set():
                if self._count_active_hostiles() < self.MAX_HOSTILES:
                    self.spawn_hostile()
