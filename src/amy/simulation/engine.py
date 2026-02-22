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
     Disabled during game mode (wave controller handles spawning instead).

  3. ambient-spawner — delegated to AmbientSpawner (separate class) for
     neutral neighborhood activity.  Continues during game mode for
     atmosphere and "don't shoot civilians" tension.

Combat integration:
  When game_mode.state == "active", the tick loop also runs:
    - game_mode.tick(dt) — state transitions, wave management
    - combat.tick(dt, targets) — projectile flight + damage
    - behaviors.tick(dt, targets) — unit AI decisions

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
from .behaviors import UnitBehaviors
from .combat import CombatSystem
from .game_mode import GameMode
from .target import SimulationTarget

if TYPE_CHECKING:
    from amy.comms.event_bus import EventBus
    from amy.tactical.obstacles import BuildingObstacles
    from amy.tactical.street_graph import StreetGraph

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

    def __init__(self, event_bus: EventBus, map_bounds: float | None = None) -> None:
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

        # Configurable map bounds (half-extent in meters)
        if map_bounds is not None:
            self._map_bounds = abs(map_bounds)
        else:
            try:
                from app.config import settings
                self._map_bounds = settings.simulation_bounds
            except Exception:
                self._map_bounds = 200.0
        self._map_min = -self._map_bounds
        self._map_max = self._map_bounds

        # Combat subsystems
        self.combat = CombatSystem(event_bus)
        self.game_mode = GameMode(event_bus, self, self.combat)
        self.behaviors = UnitBehaviors(self.combat)

        # Street graph and building obstacles for road-aware pathfinding
        self._street_graph: StreetGraph | None = None
        self._obstacles: BuildingObstacles | None = None

        # Wire target_eliminated events back to game mode for scoring
        self._combat_sub_thread: threading.Thread | None = None

    @property
    def event_bus(self) -> EventBus:
        """Public read access to the engine's EventBus."""
        return self._event_bus

    def set_event_bus(self, event_bus: EventBus) -> None:
        """Replace the EventBus on this engine AND all child subsystems.

        Called by app/main.py after Amy is created so GameMode, CombatSystem,
        and the engine itself all publish to the same bus that the WebSocket
        bridge subscribes to.
        """
        self._event_bus = event_bus
        self.combat._event_bus = event_bus
        self.game_mode._event_bus = event_bus

    # -- Pathfinding integration ---------------------------------------------

    def set_street_graph(self, street_graph: StreetGraph) -> None:
        """Set the street graph for road-aware pathfinding."""
        self._street_graph = street_graph

    def set_obstacles(self, obstacles: BuildingObstacles) -> None:
        """Set building obstacles for collision-aware pathfinding."""
        self._obstacles = obstacles

    def dispatch_unit(
        self, target_id: str, destination: tuple[float, float]
    ) -> None:
        """Dispatch a unit to *destination* using pathfinding.

        Sets waypoints on the target based on its unit type and the
        available street graph.  If the target doesn't exist, this is a
        no-op (no crash).
        """
        target = self.get_target(target_id)
        if target is None:
            return

        from .pathfinding import plan_path

        path = plan_path(
            target.position,
            destination,
            target.asset_type,
            self._street_graph,
            self._obstacles,
            alliance=target.alliance,
        )
        if path is not None:
            target.waypoints = path
            target._waypoint_index = 0
            target.status = "active"
            target.loop_waypoints = False

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

    # -- Game mode interface ------------------------------------------------

    def begin_war(self) -> None:
        """Start a new game (delegates to GameMode)."""
        self.game_mode.begin_war()

    def reset_game(self) -> None:
        """Reset game state. Clear all hostiles, heal friendlies, reset combat."""
        self.game_mode.reset()
        self.combat.clear()
        self.combat.reset_streaks()
        self.behaviors.clear_dodge_state()
        with self._lock:
            # Remove all hostile targets
            to_remove = [
                tid for tid, t in self._targets.items()
                if t.alliance == "hostile"
            ]
            for tid in to_remove:
                removed = self._targets.pop(tid, None)
                if removed is not None:
                    self._used_names.discard(removed.name)
            # Also remove placed game units (turrets/drones from previous game)
            game_units = [
                tid for tid, t in self._targets.items()
                if tid.startswith(("turret-", "drone-", "rover-"))
                and t.alliance == "friendly"
            ]
            for tid in game_units:
                removed = self._targets.pop(tid, None)
                if removed is not None:
                    self._used_names.discard(removed.name)
            # Heal surviving friendly units back to full
            for t in self._targets.values():
                if t.alliance == "friendly" and t.is_combatant:
                    t.health = t.max_health
                    if t.status == "eliminated":
                        t.status = "active"

    def get_game_state(self) -> dict:
        """Return current game state dict."""
        return self.game_mode.get_state()

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

        # Start combat event listener
        self._combat_sub_thread = threading.Thread(
            target=self._combat_event_listener, name="combat-events", daemon=True
        )
        self._combat_sub_thread.start()

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
        if self._combat_sub_thread is not None:
            self._combat_sub_thread.join(timeout=2.0)
            self._combat_sub_thread = None

    # Engagement range — a friendly within this distance of a hostile
    # neutralizes the hostile on the next tick.
    INTERCEPT_RANGE = 2.0

    # -- Tick loop ----------------------------------------------------------

    def _tick_loop(self) -> None:
        while self._running:
            time.sleep(0.1)
            with self._lock:
                targets = list(self._targets.values())
                targets_dict = dict(self._targets)
            for target in targets:
                target.tick(0.1)
                self._event_bus.publish("sim_telemetry", target.to_dict())

            # Game mode active — run combat subsystems
            game_active = self.game_mode.state == "active"
            if self.game_mode.state in ("countdown", "active", "wave_complete"):
                self.game_mode.tick(0.1)
            if game_active:
                self.combat.tick(0.1, targets_dict)
                self.behaviors.tick(0.1, targets_dict)
            else:
                # Legacy interception check (non-game-mode)
                if self.game_mode.state == "setup":
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
                # Eliminated targets — remove after 30s
                if target.status == "eliminated":
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

    def _combat_event_listener(self) -> None:
        """Listen for target_eliminated events and forward to game mode."""
        sub = self._event_bus.subscribe()
        while self._running:
            try:
                msg = sub.get(timeout=0.5)
                if msg.get("type") == "target_eliminated":
                    data = msg.get("data", {})
                    target_id = data.get("target_id")
                    if target_id:
                        self.game_mode.on_target_eliminated(target_id)
            except Exception:
                pass  # timeout or shutdown

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

        # Generate waypoints: use pathfinder if available, else legacy jitter
        b = self._map_bounds
        obj_range = b * 0.04  # ~8m at 200m bounds
        objective = (random.uniform(-obj_range, obj_range), random.uniform(-obj_range, obj_range))

        if self._street_graph is not None and self._street_graph.graph is not None:
            # Road-aware path: edge -> roads -> last 30m direct -> objective
            from .pathfinding import plan_path
            road_path = plan_path(
                position, objective, "person",
                self._street_graph, self._obstacles,
                alliance="hostile",
            )
            if road_path is not None and len(road_path) >= 2:
                # Add loiter and escape after the road path
                loiter_jitter = b * 0.015
                loiter = (
                    objective[0] + random.uniform(-loiter_jitter, loiter_jitter),
                    objective[1] + random.uniform(-loiter_jitter, loiter_jitter),
                )
                escape_edge = self._random_edge_position()
                waypoints = road_path[1:] + [loiter, escape_edge]
            else:
                waypoints = self._legacy_hostile_waypoints(position, objective)
        else:
            waypoints = self._legacy_hostile_waypoints(position, objective)

        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=name,
            alliance="hostile",
            asset_type="person",
            position=position,
            speed=1.5,
            waypoints=waypoints,
        )
        # Apply combat profile for hostile person
        target.apply_combat_profile()
        self.add_target(target)
        return target

    def _random_edge_position(self) -> tuple[float, float]:
        """Return a random position on one of the four map edges."""
        edge = random.randint(0, 3)
        coord = random.uniform(self._map_min, self._map_max)
        if edge == 0:  # north
            return (coord, self._map_max)
        elif edge == 1:  # south
            return (coord, self._map_min)
        elif edge == 2:  # east
            return (self._map_max, coord)
        else:  # west
            return (self._map_min, coord)

    def _legacy_hostile_waypoints(
        self,
        position: tuple[float, float],
        objective: tuple[float, float],
    ) -> list[tuple[float, float]]:
        """Generate legacy hostile waypoints without street graph."""
        b = self._map_bounds
        jitter = b * 0.025
        loiter_jitter = b * 0.015
        approach = (
            position[0] * 0.5 + random.uniform(-jitter, jitter),
            position[1] * 0.5 + random.uniform(-jitter, jitter),
        )
        loiter = (
            objective[0] + random.uniform(-loiter_jitter, loiter_jitter),
            objective[1] + random.uniform(-loiter_jitter, loiter_jitter),
        )
        escape_edge = self._random_edge_position()
        return [approach, objective, loiter, escape_edge]

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
        Disabled during game mode (wave controller handles spawning).
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
                # Skip auto-spawning during game mode (wave controller spawns)
                if self.game_mode.state != "setup":
                    continue
                if self._count_active_hostiles() < self.MAX_HOSTILES:
                    self.spawn_hostile()
