# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
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
from .hostile_commander import HostileCommander
from .degradation import DegradationSystem
from .unit_missions import UnitMissionSystem
from .game_mode import GameMode
from .morale import MoraleSystem
from .npc import NPCManager
from .pursuit import PursuitSystem
from .replay import ReplayRecorder
from .sensors import SensorSimulator
from .squads import SquadManager
from .stats import StatsTracker
from .target import SimulationTarget
from .terrain import TerrainMap
from .unit_states import create_fsm_for_type
from .upgrades import UpgradeSystem
from .spatial import SpatialGrid
from .vision import VisionSystem
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

    MAX_HOSTILES = 200

    def __init__(self, event_bus: EventBus, map_bounds: float | None = None,
                 max_hostiles: int | None = None) -> None:
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

        # Overridable max hostiles
        if max_hostiles is not None:
            self.MAX_HOSTILES = max_hostiles

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

        # Spatial partitioning grid for O(1) neighbor queries
        self._spatial_grid = SpatialGrid()

        # Stats tracker (created first so combat can record to it)
        self.stats_tracker = StatsTracker()

        # Combat subsystems
        self.weapon_system = WeaponSystem()
        self.upgrade_system = UpgradeSystem()
        self.combat = CombatSystem(event_bus, stats_tracker=self.stats_tracker,
                                   weapon_system=self.weapon_system,
                                   upgrade_system=self.upgrade_system)
        self.game_mode = GameMode(event_bus, self, self.combat)
        self.behaviors = UnitBehaviors(self.combat)
        # Terrain map set below after terrain_map is created

        # Extended subsystems
        self.morale_system = MoraleSystem()
        self.cover_system = CoverSystem()
        self.degradation_system = DegradationSystem()
        self.pursuit_system = PursuitSystem()
        self.unit_comms = UnitComms()
        self.behaviors.set_comms(self.unit_comms)
        # stats_tracker already created above (before CombatSystem)
        self.terrain_map = TerrainMap(map_bounds=self._map_bounds)
        self.behaviors.set_terrain_map(self.terrain_map)
        self.vision_system = VisionSystem(terrain_map=self.terrain_map)
        self.squad_manager = SquadManager()
        self.hostile_commander = HostileCommander()
        self.unit_missions = UnitMissionSystem(map_bounds=self._map_bounds)
        self.replay_recorder = ReplayRecorder(event_bus)

        # FSM per target (target_id -> StateMachine)
        self._fsms: dict[str, object] = {}

        # Wire target_eliminated events back to game mode for scoring
        self._combat_sub_thread: threading.Thread | None = None

        # Optional navigation aids (set after construction)
        self._street_graph = None
        self._obstacles = None

        # Sensor simulation
        self.sensor_sim = SensorSimulator(event_bus)

        # NPC world population (vehicles + pedestrians)
        self._npc_manager: NPCManager | None = None

        # NPC intelligence plugin (brains + thoughts, set externally)
        self._npc_intelligence = None

        # Plugin manager for ticking plugins that have tick() methods
        self._plugin_manager = None

        # Idle-unit telemetry throttling — track per-target state snapshots
        # to detect no-change ticks.  After 5 consecutive identical ticks,
        # downgrade to 2Hz (publish every 5th tick) until something changes.
        self._idle_ticks: dict[str, int] = {}       # target_id -> consecutive idle ticks
        self._last_snapshot: dict[str, tuple] = {}  # target_id -> (pos_x, pos_y, heading, health, status)
        self._tick_counter: int = 0

        # Stall detection — force-escape hostiles stuck against buildings
        self._stall_positions: dict[str, tuple[float, float]] = {}  # target_id -> last_position
        self._stall_ticks: dict[str, int] = {}  # target_id -> ticks stalled

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

    _FLYING_TYPES = {"drone", "scout_drone", "swarm_drone"}

    def add_target(self, target: SimulationTarget) -> None:
        # Assign altitude from unit type registry for flying types
        if target.asset_type in self._FLYING_TYPES:
            try:
                from engine.units import get_type
                utype = get_type(target.asset_type)
                if utype is not None:
                    target.altitude = utype.cruising_altitude
            except Exception:
                pass

        # Wire building collision check
        if self._obstacles is not None:
            if target.asset_type in self._FLYING_TYPES:
                # 3D-aware collision for flying types
                target.set_collision_check(
                    self._obstacles.point_in_building,
                    height_at=self._obstacles.building_height_at,
                )
            else:
                target.set_collision_check(self._obstacles.point_in_building)
                # Filter waypoints that land inside buildings
                if target.waypoints:
                    target.waypoints = [
                        wp for wp in target.waypoints
                        if not self._obstacles.point_in_building(wp[0], wp[1])
                    ]
                    target._waypoint_index = 0

        # Assign roof altitude for stationary units inside buildings
        if self._obstacles is not None and target.speed == 0:
            h = self._obstacles.building_height_at(
                target.position[0], target.position[1],
            )
            if h is not None:
                target.altitude = h

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
        # Register with stats tracker
        self.stats_tracker.register_unit(
            target.target_id, target.name, target.alliance, target.asset_type
        )

        # Assign starter mission metadata + backstory
        # Note: don't set waypoints here — the mission system tick() handles
        # idle units, and the loader's second pass may add layout waypoints
        # after add_target() returns.
        self.unit_missions.assign_starter_mission(target)
        self.unit_missions.generate_backstory_scripted(target)
        self.unit_missions.request_llm_backstory(target)

        # Attach NPC brain for neutral units (person, vehicle, animal)
        if (
            self._npc_intelligence is not None
            and target.alliance == "neutral"
            and target.asset_type in ("person", "vehicle", "animal")
        ):
            self._npc_intelligence.attach_brain(
                target.target_id, target.asset_type, target.alliance,
            )

    def remove_target(self, target_id: str) -> bool:
        if self._npc_intelligence is not None:
            self._npc_intelligence.detach_brain(target_id)
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
    def npc_manager(self) -> NPCManager | None:
        return self._npc_manager

    @property
    def npc_intelligence(self):
        """NPC intelligence plugin reference (or None)."""
        return self._npc_intelligence

    def set_npc_intelligence(self, plugin) -> None:
        """Wire the NPC intelligence plugin into the engine tick loop.

        Retroactively attaches brains to any existing neutral targets that
        were added before the plugin was registered (boot order issue).
        """
        self._npc_intelligence = plugin
        # Attach brains to existing neutral NPCs
        with self._lock:
            targets = list(self._targets.values())
        for t in targets:
            if (
                t.alliance == "neutral"
                and t.asset_type in ("person", "vehicle", "animal")
                and plugin.get_brain(t.target_id) is None
            ):
                plugin.attach_brain(t.target_id, t.asset_type, t.alliance)

    def set_plugin_manager(self, mgr) -> None:
        """Set the plugin manager for ticking plugins each frame."""
        self._plugin_manager = mgr

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
        """Start a new game (delegates to GameMode).

        Uses MissionDirector if a scenario was pre-generated (from the modal),
        otherwise falls back to ScenarioGenerator for backward compatibility.
        Publishes scenario context on the event bus for the frontend.
        """
        # Check if MissionDirector has a pre-generated scenario
        md = getattr(self, '_mission_director', None)
        if md and md.get_current_scenario():
            scenario = md.get_current_scenario()
            self._event_bus.publish("scenario_generated", scenario)
        else:
            # Fallback: generate scenario inline (backward compatible)
            from .scenario_gen import ScenarioGenerator
            if not hasattr(self, '_scenario_gen'):
                self._scenario_gen = ScenarioGenerator()
            scenario = self._scenario_gen.generate_scripted(
                wave=1, total_waves=10, score=0,
            )
            self._event_bus.publish("scenario_generated", scenario)

            # Start async LLM upgrade in background
            def _llm_gen():
                try:
                    llm_scenario = self._scenario_gen.generate_via_llm(wave=1, total_waves=10)
                    if llm_scenario:
                        self._event_bus.publish("scenario_generated", llm_scenario)
                except Exception:
                    pass
            threading.Thread(target=_llm_gen, daemon=True, name="scenario-llm").start()

        self.replay_recorder.clear()
        self.replay_recorder.start()
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
        self.squad_manager.clear()
        self.hostile_commander.reset()
        self.unit_missions.reset()
        self.replay_recorder.clear()
        self._fsms.clear()
        self._stall_positions.clear()
        self._stall_ticks.clear()
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

        # NPC world population
        try:
            from app.config import settings
            npc_max_v = settings.npc_max_vehicles
            npc_max_p = settings.npc_max_pedestrians
            npc_on = settings.npc_enabled
        except Exception:
            npc_max_v = 150
            npc_max_p = 200
            npc_on = True
        if npc_on:
            self._npc_manager = NPCManager(
                self, max_vehicles=npc_max_v, max_pedestrians=npc_max_p
            )
            self._npc_manager.start()

        # Start combat event listener
        self._combat_sub_thread = threading.Thread(
            target=self._combat_event_listener, name="combat-events", daemon=True
        )
        self._combat_sub_thread.start()

        # Start replay event listener (captures combat/wave/game events)
        self.replay_recorder.start_listener()

    def stop(self) -> None:
        self._running = False
        self.replay_recorder.stop_listener()
        if self._ambient_spawner is not None:
            self._ambient_spawner.stop()
            self._ambient_spawner = None
        if self._npc_manager is not None:
            self._npc_manager.stop()
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
            self._do_tick(0.1)

    def _do_tick(self, dt: float) -> None:
        """Execute one simulation tick.  Called from the tick loop thread, or
        directly in tests to exercise the engine without starting threads."""
        with self._lock:
            targets = list(self._targets.values())
            targets_dict = dict(self._targets)

        # Rebuild spatial grid once per tick (O(n)) and share with behaviors
        self._spatial_grid.rebuild(targets)
        self.behaviors.set_spatial_grid(self._spatial_grid)
        self._tick_counter += 1

        for target in targets:
            target.tick(dt)

        # Game mode active — run combat subsystems
        game_active = self.game_mode.state == "active"
        if self.game_mode.state in ("countdown", "active", "wave_complete"):
            self.game_mode.tick(dt)
        if game_active:
            # Vision: compute what each unit can see this tick
            vision_state = self.vision_system.tick(dt, targets_dict, self._spatial_grid)
            for tid, t in targets_dict.items():
                if t.alliance == "hostile":
                    t.visible = tid in vision_state.friendly_visible
                    t.detected_by = list(vision_state.visible_to.get(tid, set()))
            self.combat.tick(dt, targets_dict, cover_system=self.cover_system)
            self.behaviors.tick(dt, targets_dict, vision_state=vision_state)
            self.squad_manager.tick(dt, targets_dict)
            self.squad_manager.tick_orders(dt, targets_dict)
            self.hostile_commander.tick(dt, targets_dict)
        else:
            # Legacy interception check (non-game-mode)
            if self.game_mode.state == "setup":
                self._check_interceptions(targets)

        # Tick extended subsystems (always, regardless of game state)
        self.morale_system.tick(dt, targets_dict)
        self._sync_morale(targets_dict)
        self.cover_system.tick(dt, targets_dict)
        self.degradation_system.tick(dt, targets_dict)
        self._sync_degradation(targets)
        self.pursuit_system.tick(dt, targets_dict)
        self.unit_comms.tick(dt, targets_dict)
        self.stats_tracker.tick(dt, targets_dict)
        self.upgrade_system.tick(dt, targets_dict)
        self.weapon_system.tick(dt)

        # Tick unit missions (idle unit assignment, patrol loops)
        self.unit_missions.tick(dt, targets_dict)

        # Tick NPC manager (mission lifecycle, cleanup)
        if self._npc_manager is not None:
            self._npc_manager.tick(dt)

        # Tick NPC intelligence (brains, thoughts, crowd dynamics)
        if self._npc_intelligence is not None:
            twp = [
                (tid, (t.position[0], t.position[1]))
                for tid, t in targets_dict.items()
                if t.alliance == "neutral" and t.asset_type in ("person", "vehicle", "animal")
            ]
            self._npc_intelligence.tick(dt, targets_with_positions=twp)

        # Tick external plugins that have tick() methods (e.g. npc_thoughts)
        if self._plugin_manager is not None:
            for info in self._plugin_manager.list_plugins():
                if info["status"] != "running":
                    continue
                p = self._plugin_manager.get_plugin(info["id"])
                # Skip NPC intelligence (already ticked above)
                if p is self._npc_intelligence:
                    continue
                tick_fn = getattr(p, "tick", None)
                if tick_fn is not None:
                    try:
                        tick_fn(dt)
                    except Exception:
                        pass  # Plugin tick errors don't crash the engine

        # Record replay snapshot at 2Hz (every 5 ticks at 10Hz)
        if self._tick_counter % 5 == 0 and self.replay_recorder.is_recording:
            self.replay_recorder.record_snapshot(targets)

        # Tick FSMs with enriched context and sync state back to targets
        self._tick_fsms(dt, targets_dict)

        # Batch telemetry: collect all target dicts AFTER all subsystems have
        # ticked, so the batch reflects combat damage, eliminations, FSM state
        # changes, etc. from this tick — not from the previous tick.
        # Idle units (no state change for 5+ ticks) are throttled to 2Hz.
        batch: list[dict] = []
        for target in targets:
            snap = (
                round(target.position[0], 2),
                round(target.position[1], 2),
                round(target.heading, 1),
                round(target.health, 1),
                target.status,
            )
            tid = target.target_id
            prev = self._last_snapshot.get(tid)
            if prev == snap:
                idle = self._idle_ticks.get(tid, 0) + 1
                self._idle_ticks[tid] = idle
            else:
                self._idle_ticks[tid] = 0
                self._last_snapshot[tid] = snap

            # Throttle: idle for 5+ ticks → only publish every 5th tick
            idle_count = self._idle_ticks.get(tid, 0)
            if idle_count >= 5 and self._tick_counter % 5 != 0:
                continue
            batch.append(target.to_dict())

        self._event_bus.publish("sim_telemetry_batch", batch)

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

            # Map boundary escape: hostiles past the map edge have fled the AO
            if target.alliance == "hostile" and target.status == "active":
                x, y = target.position
                if (abs(x) > self._map_bounds or abs(y) > self._map_bounds):
                    target.status = "escaped"

            # Stall detection: hostiles stuck or oscillating for 15+s escape.
            # Uses distance-based check — if net displacement from the
            # recorded position is < 3m, increment the stall counter.
            # At 150 ticks (15s at 10Hz), the hostile is force-escaped.
            if target.alliance == "hostile" and target.status == "active":
                tid = target.target_id
                pos = target.position
                prev_pos = self._stall_positions.get(tid)
                if prev_pos is not None:
                    dx = pos[0] - prev_pos[0]
                    dy = pos[1] - prev_pos[1]
                    dist = (dx * dx + dy * dy) ** 0.5
                    if dist < 3.0:
                        ticks = self._stall_ticks.get(tid, 0) + 1
                        self._stall_ticks[tid] = ticks
                        if ticks >= 150:  # 15 seconds at 10Hz
                            target.status = "escaped"
                    else:
                        # Moved significantly — reset stall tracking
                        self._stall_positions[tid] = pos
                        self._stall_ticks.pop(tid, None)
                else:
                    self._stall_positions[tid] = pos

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

    def _sync_morale(self, targets_dict: dict[str, SimulationTarget]) -> None:
        """Sync morale values from MoraleSystem back to target.morale fields."""
        for tid, t in targets_dict.items():
            if t.status in ("eliminated", "destroyed", "neutralized"):
                continue
            t.morale = self.morale_system.get_morale(tid)

    def _sync_degradation(self, targets: list[SimulationTarget]) -> None:
        """Sync degradation values from health to target.degradation fields."""
        from .degradation import apply_degradation
        for t in targets:
            if t.status in ("eliminated", "destroyed", "neutralized"):
                continue
            apply_degradation(t)

    def _on_combat_elimination(
        self, eliminated_id: str, targets_dict: dict[str, SimulationTarget]
    ) -> None:
        """Handle morale effects when a unit is eliminated.

        Allies of the eliminated unit lose morale; enemies gain morale.
        """
        eliminated = targets_dict.get(eliminated_id)
        if eliminated is None:
            return

        for tid, t in targets_dict.items():
            if tid == eliminated_id:
                continue
            if t.status in ("eliminated", "destroyed", "neutralized"):
                continue
            if t.alliance == eliminated.alliance:
                # Same team — ally eliminated, morale drops
                self.morale_system.on_ally_eliminated(tid)
            else:
                # Enemy eliminated — morale boost
                self.morale_system.on_enemy_eliminated(tid)

    def _combat_event_listener(self) -> None:
        """Listen for combat events and forward to game mode + morale system."""
        sub = self._event_bus.subscribe()
        while self._running:
            try:
                msg = sub.get(timeout=0.5)
                msg_type = msg.get("type")
                data = msg.get("data", {})

                if msg_type == "target_eliminated":
                    target_id = data.get("target_id")
                    if target_id:
                        self.game_mode.on_target_eliminated(target_id)
                        # Morale effects from elimination
                        with self._lock:
                            targets_dict = dict(self._targets)
                        self._on_combat_elimination(target_id, targets_dict)

                elif msg_type == "projectile_hit":
                    # Morale loss from taking damage
                    target_id = data.get("target_id")
                    damage = data.get("damage", 0)
                    if target_id and damage > 0:
                        self.morale_system.on_damage_taken(target_id, damage)

                elif msg_type == "game_over":
                    # Stop replay recording when game ends
                    self.replay_recorder.stop()

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
            # Use closer spawn during wave combat for faster engagement
            combat = self.game_mode.state == "active"
            position = self._random_edge_position(combat=combat)

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

    def spawn_hostile_typed(
        self,
        asset_type: str,
        name: str | None = None,
        position: tuple[float, float] | None = None,
        speed: float | None = None,
        health: float | None = None,
    ) -> SimulationTarget:
        """Create a hostile target of any type (person, hostile_vehicle, hostile_leader).

        This is the multi-type variant of spawn_hostile(), used by the scenario
        system to spawn mixed hostile waves.
        """
        if position is None:
            combat = self.game_mode.state == "active"
            position = self._random_edge_position(combat=combat)

        # Name generation
        if name is None:
            base_name = random.choice(_HOSTILE_NAMES)
        else:
            base_name = name
        final_name = base_name
        suffix = 2
        while final_name in self._used_names:
            final_name = f"{base_name}-{suffix}"
            suffix += 1
        self._used_names.add(final_name)

        # Default speed by type
        default_speeds = {
            "person": 1.5,
            "hostile_vehicle": 6.0,
            "hostile_leader": 1.8,
            "swarm_drone": 6.0,
        }
        target_speed = speed if speed is not None else default_speeds.get(asset_type, 1.5)

        waypoints = self._generate_hostile_waypoints(position)

        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=final_name,
            alliance="hostile",
            asset_type=asset_type,
            position=position,
            speed=target_speed,
            waypoints=waypoints,
        )
        target.apply_combat_profile()

        # Override health if specified
        if health is not None:
            target.health = health
            target.max_health = health

        # Mark leaders
        if asset_type == "hostile_leader":
            target.is_leader = True

        self.add_target(target)
        return target

    def _random_edge_position(self, combat: bool = False) -> tuple[float, float]:
        """Return a random position on one of the four map edges.

        When *combat* is True, spawns at 35% of map bounds (~70m on a
        200m map) so wave hostiles reach engagement range in ~15-20s
        instead of 60+s from the full edge.
        """
        frac = 0.35 if combat else 1.0
        edge_max = self._map_max * frac
        edge_min = self._map_min * frac
        edge = random.randint(0, 3)
        coord = random.uniform(edge_min, edge_max)
        if edge == 0:  # north
            return (coord, edge_max)
        elif edge == 1:  # south
            return (coord, edge_min)
        elif edge == 2:  # east
            return (edge_max, coord)
        else:  # west
            return (edge_min, coord)

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

        # Legacy waypoints: direct to objective then escape.
        # Fewer intermediate waypoints = fewer building collisions.
        escape_edge = self._random_edge_position()
        return [objective, escape_edge]

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
