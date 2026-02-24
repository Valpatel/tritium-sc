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
from .comms import UnitComms
from .cover import CoverSystem
from .degradation import DegradationSystem
from .game_mode import GameMode
from .morale import MoraleSystem
from .pursuit import PursuitSystem
from .sensors import SensorSimulator
from .stats import StatsTracker
from .target import SimulationTarget
from .terrain import TerrainMap
from .unit_states import create_fsm_for_type
from .upgrades import UpgradeSystem
from .weapons import WeaponSystem

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus

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

        # Extended subsystems
        self.morale_system = MoraleSystem()
        self.cover_system = CoverSystem()
        self.degradation_system = DegradationSystem()
        self.pursuit_system = PursuitSystem()
        self.unit_comms = UnitComms()
        self.stats_tracker = StatsTracker()
        self.terrain_map = TerrainMap(map_bounds=200.0)
        self.upgrade_system = UpgradeSystem()
        self.weapon_system = WeaponSystem()

        # FSM per target (target_id -> StateMachine)
        self._fsms: dict[str, object] = {}

        # Wire target_eliminated events back to game mode for scoring
        self._combat_sub_thread: threading.Thread | None = None

        # Optional navigation aids (set after construction)
        self._street_graph = None
        self._obstacles = None

        # Sensor simulation
        self.sensor_sim = SensorSimulator(event_bus)

    @property
    def event_bus(self) -> EventBus:
        """Public read access to the engine's EventBus."""
        return self._event_bus

    @property
    def street_graph(self):
        return self._street_graph

    @property
    def obstacles(self):
        return self._obstacles

    def set_event_bus(self, event_bus: EventBus) -> None:
        """Replace the EventBus on this engine AND all child subsystems.

        Called by app/main.py after Amy is created so GameMode, CombatSystem,
        and the engine itself all publish to the same bus that the WebSocket
        bridge subscribes to.
        """
        self._event_bus = event_bus
        self.combat._event_bus = event_bus
        self.game_mode._event_bus = event_bus

    def set_street_graph(self, street_graph) -> None:
        """Store a street graph for road-aware pathfinding."""
        self._street_graph = street_graph

    def set_obstacles(self, obstacles) -> None:
        """Store obstacle geometry for pathfinding avoidance and cover-seeking."""
        self._obstacles = obstacles
        self.behaviors.set_obstacles(obstacles)

    # -- Target management --------------------------------------------------

    def add_target(self, target: SimulationTarget) -> None:
        with self._lock:
            self._targets[target.target_id] = target
        # Create FSM for this target type
        fsm = create_fsm_for_type(target.asset_type, target.alliance)
        if fsm is not None:
            target.fsm_state = fsm.current.name
            self._fsms[target.target_id] = fsm
        # Equip weapon
        if target.is_combatant:
            self.weapon_system.assign_default_weapon(target.target_id, target.asset_type)

    def remove_target(self, target_id: str) -> bool:
        self._fsms.pop(target_id, None)
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

    def dispatch_unit(self, target_id: str, destination: tuple[float, float]) -> None:
        """Dispatch a unit to a destination, using pathfinding when available.

        Drones fly direct.  Ground units route via the street graph when one
        is loaded; otherwise they move in a straight line to the destination.
        Stationary units (speed == 0) are silently ignored.
        """
        with self._lock:
            target = self._targets.get(target_id)
        if target is None:
            return
        if target.speed == 0:
            return

        drone_types = {"drone", "scout_drone"}
        if target.asset_type in drone_types:
            # Drones fly direct — no pathfinding needed
            target.waypoints = [target.position, destination]
        elif self._street_graph is not None:
            # Ground unit with a street graph — try road-aware pathfinding
            from engine.simulation.pathfinding import plan_path
            path = plan_path(
                target.position,
                destination,
                target.asset_type,
                street_graph=self._street_graph,
                obstacles=self._obstacles,
            )
            if path:
                target.waypoints = path
            else:
                # Pathfinding returned nothing — fall back to direct movement
                target.waypoints = [destination]
        else:
            # No street graph loaded — move directly
            target.waypoints = [destination]

        target._waypoint_index = 0
        target.status = "active"

    def reset_game(self) -> None:
        """Reset game state. Clear all hostiles, heal friendlies, reset combat."""
        self.game_mode.reset()
        self.combat.clear()
        self.combat.reset_streaks()
        self.behaviors.clear_dodge_state()
        # Reset extended subsystems
        self.morale_system.reset()
        self.cover_system.reset()
        self.degradation_system.reset()
        self.pursuit_system.reset()
        self.unit_comms.reset()
        self.stats_tracker.reset()
        self.terrain_map.reset()
        self.upgrade_system.reset()
        self.weapon_system.reset()
        self._fsms.clear()
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

            # Tick extended subsystems (always, regardless of game state)
            self.morale_system.tick(0.1, targets_dict)
            self.cover_system.tick(0.1, targets_dict)
            self.degradation_system.tick(0.1, targets_dict)
            self.pursuit_system.tick(0.1, targets_dict)
            self.unit_comms.tick(0.1, targets_dict)
            self.stats_tracker.tick(0.1, targets_dict)
            self.upgrade_system.tick(0.1, targets_dict)

            # Tick FSMs with enriched context and sync state back to targets
            self._tick_fsms(0.1, targets_dict)

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
                self._fsms.pop(tid, None)
                if removed is not None:
                    self._used_names.discard(removed.name)
                    if self._ambient_spawner is not None:
                        self._ambient_spawner.release_name(removed.name)

    # -- FSM context enrichment -------------------------------------------------

    def _tick_fsms(self, dt: float, targets_dict: dict[str, SimulationTarget]) -> None:
        """Tick all FSMs with enriched context and sync state back to targets.

        Context keys provided:
          - enemies_in_range: list of enemy targets within detection range
          - enemy_in_weapon_range: bool -- at least one enemy within weapon distance
          - health_pct: float 0.0-1.0 -- unit health fraction
          - nearest_enemy_stationary: bool -- closest enemy is a turret/static
          - enemies_at_recon_range: bool -- enemies at extended detection range
          - cover_available: bool -- obstacles exist for cover-seeking
          - ally_is_flanking: bool -- another hostile is in flanking state
          - detected: bool -- this hostile has been spotted by sensor
        """
        # Pre-compute: is any hostile in flanking state?
        flanking_hostiles = set()
        for tid, t in targets_dict.items():
            if t.alliance == "hostile" and getattr(t, "fsm_state", None) == "flanking":
                flanking_hostiles.add(tid)

        cover_available = self._obstacles is not None and bool(
            getattr(self._obstacles, "polygons", [])
        )

        # Expire stale detections
        self._expire_detections()

        for tid, fsm in list(self._fsms.items()):
            t = targets_dict.get(tid)
            if t is None or t.status != "active":
                continue

            # Build context for this target
            if t.alliance == "hostile":
                enemies = [
                    e for e in targets_dict.values()
                    if e.alliance == "friendly"
                    and e.status in ("active", "idle", "stationary")
                    and e.is_combatant
                ]
            else:
                enemies = [
                    e for e in targets_dict.values()
                    if e.alliance == "hostile" and e.status == "active"
                    and e.is_combatant
                ]

            # Find enemies in detection range (weapon_range * 1.5)
            detect_range = t.weapon_range * 1.5
            recon_range = t.weapon_range * 3.0
            enemies_in_range = []
            enemies_at_recon = False
            enemy_in_weapon_range = False
            nearest_dist = float("inf")
            nearest_enemy = None

            for e in enemies:
                dx = e.position[0] - t.position[0]
                dy = e.position[1] - t.position[1]
                dist = math.hypot(dx, dy)
                if dist <= detect_range:
                    enemies_in_range.append(e)
                if dist <= t.weapon_range:
                    enemy_in_weapon_range = True
                if dist <= recon_range:
                    enemies_at_recon = True
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest_enemy = e

            nearest_stationary = False
            if nearest_enemy is not None:
                nearest_stationary = (nearest_enemy.speed == 0)

            # Check if any other nearby hostile is flanking (for suppressing)
            ally_flanking = False
            if t.alliance == "hostile":
                for other_tid in flanking_hostiles:
                    if other_tid == tid:
                        continue
                    other = targets_dict.get(other_tid)
                    if other is not None:
                        dx = other.position[0] - t.position[0]
                        dy = other.position[1] - t.position[1]
                        if math.hypot(dx, dy) <= 40.0:
                            ally_flanking = True
                            break

            max_hp = getattr(t, "max_health", 100.0) or 100.0
            health_pct = t.health / max_hp if max_hp > 0 else 1.0

            ctx = {
                "enemies_in_range": enemies_in_range,
                "enemy_in_weapon_range": enemy_in_weapon_range,
                "health_pct": health_pct,
                "nearest_enemy_stationary": nearest_stationary,
                "enemies_at_recon_range": enemies_at_recon,
                "cover_available": cover_available,
                "ally_is_flanking": ally_flanking,
                "detected": getattr(t, "detected", False),
                "has_waypoints": bool(t.waypoints),
                "weapon_ready": t.can_fire(),
                "aimed_at_target": False,
                "just_fired": False,
                "degradation": getattr(t, "degradation", 0.0),
            }

            fsm.tick(dt, ctx)
            t.fsm_state = fsm.current.name

    def _handle_sensor_triggered(self, event: dict) -> None:
        """Handle a sensor_triggered event by marking the target as detected.

        Called from the EventBus subscription or directly in tests.
        """
        target_id = event.get("target_id")
        if target_id is None:
            return
        with self._lock:
            target = self._targets.get(target_id)
        if target is None:
            return
        if target.alliance != "hostile":
            return
        target.detected = True
        target.detected_at = time.monotonic()

    def _expire_detections(self) -> None:
        """Expire stale sensor detections (older than 30s)."""
        now = time.monotonic()
        with self._lock:
            for t in self._targets.values():
                if t.detected and t.detected_at > 0:
                    if now - t.detected_at > 30.0:
                        t.detected = False

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

        # Generate waypoints: use street graph if available, else legacy jitter
        waypoints = self._generate_hostile_waypoints(position)

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

    def _generate_hostile_waypoints(
        self, position: tuple[float, float]
    ) -> list[tuple[float, float]]:
        """Generate waypoints for a hostile spawn.

        Uses street graph pathfinding when available, otherwise falls back
        to legacy jitter-based waypoint generation.
        """
        objective = (
            random.uniform(-self._map_bounds * 0.04, self._map_bounds * 0.04),
            random.uniform(-self._map_bounds * 0.04, self._map_bounds * 0.04),
        )

        if self._street_graph is not None:
            try:
                from .pathfinding import plan_path
                path = plan_path(
                    position, objective, "person",
                    street_graph=self._street_graph,
                    obstacles=self._obstacles,
                    alliance="hostile",
                )
                if path and len(path) >= 2:
                    escape_edge = self._random_edge_position()
                    return list(path) + [escape_edge]
            except Exception:
                pass  # Fall through to legacy

        # Legacy jitter-based waypoints
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
