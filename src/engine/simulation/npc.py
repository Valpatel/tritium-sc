# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""NPC world population -- vehicles, pedestrians, missions, road following.

Fills the simulation world with realistic neutral traffic: vehicles that
follow roads via A* pathfinding, pedestrians on sidewalks, all with simple
missions (commute, patrol, deliver, drive through).

Each NPC publishes position updates through the standard SimulationTarget
pipeline, producing CoT-compatible telemetry identical in format to real
tracked entities.  This means real vehicle tracking data can seamlessly
replace simulated NPCs via the bind_to_track() API.

Architecture
------------
NPCManager is a peer of AmbientSpawner.  AmbientSpawner creates simple
neutral background noise (8 entities, basic paths).  NPCManager creates
a much richer population of vehicles and pedestrians with:
  - Road-following via StreetGraph A*
  - Mission objectives (commute, patrol, deliver, drive_through)
  - Time-of-day traffic density scaling
  - Configurable population caps (15-30 vehicles, 20-40 pedestrians at peak)
  - Binding to real data streams (CoT track replacement)

The two spawners are deliberately separate.  AmbientSpawner covers
animals, dogs, cats, delivery people.  NPCManager covers vehicles and
pedestrian foot traffic at scale.  No shared state except through the
engine's target list.
"""

from __future__ import annotations

import math
import random
import threading
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from .target import SimulationTarget

if TYPE_CHECKING:
    from .engine import SimulationEngine

# ---------------------------------------------------------------------------
# Mission types
# ---------------------------------------------------------------------------

MISSION_TYPES = {"commute", "patrol", "delivery", "drive_through", "walk"}


@dataclass
class NPCMission:
    """A simple mission for an NPC."""

    mission_type: str  # one of MISSION_TYPES
    origin: tuple[float, float]
    destination: tuple[float, float]
    patrol_points: list[tuple[float, float]] = field(default_factory=list)
    completed: bool = False


# ---------------------------------------------------------------------------
# Vehicle type definitions
# ---------------------------------------------------------------------------

NPC_VEHICLE_TYPES: dict[str, dict] = {
    "sedan": {
        "display_name": "Sedan",
        "icon": "S",
        "speed": 11.0,  # ~25 mph
        "names": [
            "Red Sedan", "Blue Sedan", "White Sedan", "Black Sedan",
            "Silver Sedan", "Gray Sedan",
        ],
    },
    "suv": {
        "display_name": "SUV",
        "icon": "U",
        "speed": 10.0,
        "names": [
            "Blue SUV", "Black SUV", "White SUV", "Red SUV",
            "Silver SUV", "Green SUV",
        ],
    },
    "pickup": {
        "display_name": "Pickup Truck",
        "icon": "K",
        "speed": 10.0,
        "names": [
            "White Pickup", "Red Pickup", "Black Pickup", "Blue Pickup",
            "Silver Pickup", "Tan Pickup",
        ],
    },
    "delivery_van": {
        "display_name": "Delivery Van",
        "icon": "D",
        "speed": 8.0,
        "names": [
            "FedEx Van", "UPS Van", "Amazon Van", "USPS Van",
            "DHL Van", "Local Delivery",
        ],
    },
    "police": {
        "display_name": "Police Car",
        "icon": "P",
        "speed": 12.0,
        "names": [
            "Police Cruiser 1", "Police Cruiser 2", "Police SUV",
            "Police Unit 7", "Police Unit 12",
        ],
    },
    "ambulance": {
        "display_name": "Ambulance",
        "icon": "A",
        "speed": 13.0,
        "names": [
            "Ambulance 1", "Ambulance 2", "EMS Unit 3",
            "Medic 1", "Paramedic Unit",
        ],
    },
    "school_bus": {
        "display_name": "School Bus",
        "icon": "B",
        "speed": 7.0,
        "names": [
            "School Bus 12", "School Bus 7", "School Bus 3",
            "School Bus 15", "Activity Bus",
        ],
    },
}

# Pedestrian name pool
_PEDESTRIAN_NAMES = [
    "Morning Jogger", "Dog Walker", "Office Worker", "Student",
    "Retiree", "Tourist", "Commuter", "Parent w/ Stroller",
    "Cyclist", "Runner", "Fitness Walker", "Window Shopper",
    "Lunch Break", "Phone Walker", "Couple Walking",
    "Power Walker", "Slow Stroller", "Speed Walker",
    "Mall Walker", "Nature Walker",
]


# ---------------------------------------------------------------------------
# Time-of-day traffic density
# ---------------------------------------------------------------------------

def traffic_density(hour: int) -> float:
    """Return a traffic density multiplier (0.0-1.0) for the given hour.

    Models typical residential neighborhood traffic patterns:
    - Rush hours (7-9am, 4-6pm): 0.8-1.0
    - Midday (10am-3pm): 0.4-0.6
    - Evening (7-10pm): 0.3-0.5
    - Night (11pm-5am): 0.05-0.15
    - Early morning (5-7am): 0.2-0.4
    """
    # Piecewise linear traffic curve
    _CURVE = {
        0: 0.10,  1: 0.08,  2: 0.05,  3: 0.05,
        4: 0.08,  5: 0.15,  6: 0.30,  7: 0.70,
        8: 0.90,  9: 0.80, 10: 0.55, 11: 0.50,
        12: 0.55, 13: 0.50, 14: 0.50, 15: 0.55,
        16: 0.75, 17: 0.90, 18: 0.80, 19: 0.55,
        20: 0.40, 21: 0.30, 22: 0.20, 23: 0.15,
    }
    return _CURVE.get(hour % 24, 0.2)


# ---------------------------------------------------------------------------
# NPCManager
# ---------------------------------------------------------------------------

class NPCManager:
    """Manages NPC vehicles and pedestrians with missions and road-following.

    When started, runs an auto-spawn loop on a daemon thread that continuously
    fills the world up to capacity (scaled by time-of-day traffic density).
    """

    # Auto-spawn loop timing
    SPAWN_INTERVAL = 3.0   # seconds between spawn ticks
    BATCH_SIZE = 5         # entities spawned per tick

    def __init__(
        self,
        engine: SimulationEngine,
        max_vehicles: int = 150,
        max_pedestrians: int = 200,
    ) -> None:
        self._engine = engine
        self.max_vehicles = max_vehicles
        self.max_pedestrians = max_pedestrians

        # NPC tracking: target_id -> metadata
        self._missions: dict[str, NPCMission] = {}
        self._vehicle_types: dict[str, str] = {}  # target_id -> vehicle type key
        self._bindings: dict[str, dict] = {}  # target_id -> {source, track_id}
        self._used_names: set[str] = set()
        self._npc_ids: set[str] = set()  # all NPC target_ids we manage

        # Auto-spawn thread state
        self._running = False
        self._thread: threading.Thread | None = None

    @property
    def npc_count(self) -> int:
        """Number of active NPCs we're managing."""
        return len(self._npc_ids)

    # -- Auto-spawn lifecycle -----------------------------------------------

    def start(self) -> None:
        """Start the auto-spawn loop on a daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._spawn_loop, name="npc-spawner", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the auto-spawn loop."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _spawn_loop(self) -> None:
        """Continuously spawn NPCs up to capacity, scaled by traffic density."""
        import time as _time
        from datetime import datetime as _dt

        while self._running:
            elapsed = 0.0
            while elapsed < self.SPAWN_INTERVAL and self._running:
                _time.sleep(0.5)
                elapsed += 0.5

            if not self._running:
                break

            # Skip if engine has spawners paused
            if getattr(self._engine, "spawners_paused", False):
                continue

            self._auto_spawn_tick()

    def _auto_spawn_tick(self) -> None:
        """Spawn a batch of NPCs up to capacity, scaled by traffic density."""
        from datetime import datetime as _dt

        hour = _dt.now().hour
        density = traffic_density(hour)

        # Scale caps by density
        effective_vehicles = int(self.max_vehicles * density)
        effective_peds = int(self.max_pedestrians * density)

        vehicle_count = sum(1 for tid in self._npc_ids if tid in self._vehicle_types)
        ped_count = sum(1 for tid in self._npc_ids if tid not in self._vehicle_types)

        spawned = 0
        for _ in range(self.BATCH_SIZE):
            if spawned >= self.BATCH_SIZE:
                break
            # Alternate between vehicles and pedestrians
            if vehicle_count < effective_vehicles and random.random() < 0.4:
                result = self.spawn_vehicle()
                if result is not None:
                    vehicle_count += 1
                    spawned += 1
            elif ped_count < effective_peds:
                result = self.spawn_pedestrian()
                if result is not None:
                    ped_count += 1
                    spawned += 1
            elif vehicle_count < effective_vehicles:
                result = self.spawn_vehicle()
                if result is not None:
                    vehicle_count += 1
                    spawned += 1

    # -- Spawning -----------------------------------------------------------

    def spawn_vehicle(
        self, vehicle_type: str | None = None
    ) -> SimulationTarget | None:
        """Spawn a neutral NPC vehicle following roads.

        Returns the spawned target, or None if at capacity.
        """
        # Check capacity
        vehicle_count = sum(
            1 for tid in self._npc_ids
            if tid in self._vehicle_types
        )
        if vehicle_count >= self.max_vehicles:
            return None

        # Pick vehicle type
        if vehicle_type is None:
            vehicle_type = random.choice(list(NPC_VEHICLE_TYPES.keys()))
        vtype = NPC_VEHICLE_TYPES.get(vehicle_type)
        if vtype is None:
            vtype = NPC_VEHICLE_TYPES["sedan"]
            vehicle_type = "sedan"

        # Name
        name = self._pick_name(vtype["names"])

        # Spawn position (map edge)
        start = self._random_edge()
        end = self._opposite_edge(start)

        # Generate road-following waypoints
        waypoints = self._road_waypoints(start, end)

        # Create mission
        mission_type = random.choice(["commute", "drive_through", "delivery", "patrol"])
        mission = NPCMission(
            mission_type=mission_type,
            origin=start,
            destination=end,
        )

        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=name,
            alliance="neutral",
            asset_type="vehicle",
            position=start,
            speed=vtype["speed"],
            waypoints=waypoints,
        )

        self._engine.add_target(target)
        self._npc_ids.add(target.target_id)
        self._missions[target.target_id] = mission
        self._vehicle_types[target.target_id] = vehicle_type

        return target

    def spawn_pedestrian(self) -> SimulationTarget | None:
        """Spawn a neutral NPC pedestrian walking on sidewalks.

        Returns the spawned target, or None if at capacity.
        """
        ped_count = sum(
            1 for tid in self._npc_ids
            if tid not in self._vehicle_types
        )
        if ped_count >= self.max_pedestrians:
            return None

        name = self._pick_name(_PEDESTRIAN_NAMES)
        start = self._random_edge()
        end = self._opposite_edge(start)

        # Pedestrian waypoints with sidewalk offset
        waypoints = self._sidewalk_waypoints(start, end)
        speed = random.uniform(1.0, 1.8)

        mission = NPCMission(
            mission_type="walk",
            origin=start,
            destination=end,
        )

        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=name,
            alliance="neutral",
            asset_type="person",
            position=start,
            speed=speed,
            waypoints=waypoints,
        )

        self._engine.add_target(target)
        self._npc_ids.add(target.target_id)
        self._missions[target.target_id] = mission

        return target

    # -- Queries ------------------------------------------------------------

    def get_mission(self, target_id: str) -> NPCMission | None:
        return self._missions.get(target_id)

    def get_vehicle_type(self, target_id: str) -> str | None:
        return self._vehicle_types.get(target_id)

    # -- Binding to real data -----------------------------------------------

    def bind_to_track(
        self, target_id: str, source: str, track_id: str
    ) -> bool:
        """Bind an NPC to a real data stream.

        When bound, the NPC's position comes from real tracking data
        instead of simulation movement.

        Args:
            target_id: The NPC target ID to bind
            source: Data source type (e.g. "cot", "mqtt", "yolo")
            track_id: External track identifier

        Returns:
            True if binding succeeded, False if target not found
        """
        if target_id not in self._npc_ids:
            return False
        self._bindings[target_id] = {"source": source, "track_id": track_id}
        return True

    def unbind(self, target_id: str) -> None:
        """Remove data binding from an NPC."""
        self._bindings.pop(target_id, None)

    def is_bound(self, target_id: str) -> bool:
        """Check if an NPC is bound to a real data stream."""
        return target_id in self._bindings

    def get_binding(self, target_id: str) -> dict | None:
        return self._bindings.get(target_id)

    def update_bound_position(
        self,
        target_id: str,
        position: tuple[float, float],
        heading: float = 0.0,
        speed: float = 0.0,
    ) -> None:
        """Update a bound NPC's position from external data."""
        if target_id not in self._bindings:
            return
        # Find target in engine
        targets = {t.target_id: t for t in self._engine.get_targets()}
        target = targets.get(target_id)
        if target is None:
            return
        target.position = position
        target.heading = heading
        target.speed = speed

    # -- Tick ---------------------------------------------------------------

    def tick(self, dt: float) -> None:
        """Called each tick to manage NPC lifecycle.

        - Marks missions complete for despawned NPCs
        - Cleans up despawned NPCs from tracking
        """
        to_remove = []
        for tid in list(self._npc_ids):
            targets = {t.target_id: t for t in self._engine.get_targets()}
            target = targets.get(tid)
            if target is None:
                to_remove.append(tid)
                continue
            if target.status in ("despawned", "destroyed"):
                mission = self._missions.get(tid)
                if mission is not None:
                    mission.completed = True
                to_remove.append(tid)

        for tid in to_remove:
            self._npc_ids.discard(tid)
            self._used_names.discard(
                self._missions.get(tid, NPCMission("", (0, 0), (0, 0))).mission_type
            )

    # -- Path generation ----------------------------------------------------

    def _road_waypoints(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> list[tuple[float, float]]:
        """Generate road-following waypoints using street graph A*."""
        sg = getattr(self._engine, "_street_graph", None)
        if sg is not None and getattr(sg, "graph", None) is not None:
            path = sg.shortest_path(start, end)
            if path and len(path) >= 2:
                return path
        # Fallback: simple L-shaped path following grid streets
        return self._grid_path(start, end)

    def _sidewalk_waypoints(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> list[tuple[float, float]]:
        """Generate pedestrian waypoints offset from road centerline."""
        # Offset from road by ~2m for sidewalk
        offset = random.choice([-2.0, 2.0])
        road_path = self._road_waypoints(start, end)
        # Apply lateral offset to each waypoint
        if len(road_path) < 2:
            return [end]
        sidewalk = []
        for i, (wx, wy) in enumerate(road_path):
            if i < len(road_path) - 1:
                nx, ny = road_path[i + 1]
                dx = nx - wx
                dy = ny - wy
                dist = math.hypot(dx, dy)
                if dist > 0.1:
                    # Perpendicular offset
                    px = -dy / dist * offset
                    py = dx / dist * offset
                    sidewalk.append((wx + px, wy + py))
                else:
                    sidewalk.append((wx, wy))
            else:
                sidewalk.append((wx, wy))
        return sidewalk

    def _grid_path(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> list[tuple[float, float]]:
        """Fallback grid-aligned path when no street graph is available."""
        sx, sy = start
        ex, ey = end
        # L-shaped path through map center area
        mid_x = (sx + ex) / 2 + random.uniform(-10, 10)
        mid_y = (sy + ey) / 2 + random.uniform(-10, 10)
        return [(mid_x, sy), (mid_x, mid_y), (ex, mid_y), end]

    # -- Helpers ------------------------------------------------------------

    def _pick_name(self, names: list[str]) -> str:
        """Pick an unused name from the pool, adding suffix if needed."""
        available = [n for n in names if n not in self._used_names]
        if not available:
            base = random.choice(names)
            suffix = 2
            name = f"{base} {suffix}"
            while name in self._used_names:
                suffix += 1
                name = f"{base} {suffix}"
        else:
            name = random.choice(available)
        self._used_names.add(name)
        return name

    def _random_edge(self) -> tuple[float, float]:
        """Random position on one of the four map edges."""
        bounds = self._engine._map_bounds
        edge = random.randint(0, 3)
        coord = random.uniform(-bounds * 0.8, bounds * 0.8)
        if edge == 0:
            return (coord, bounds)
        elif edge == 1:
            return (coord, -bounds)
        elif edge == 2:
            return (bounds, coord)
        else:
            return (-bounds, coord)

    def _opposite_edge(self, pos: tuple[float, float]) -> tuple[float, float]:
        """Return a position on the opposite edge from the given position."""
        x, y = pos
        bounds = self._engine._map_bounds
        if abs(y - bounds) < 2:
            return (x + random.uniform(-20, 20), -bounds)
        elif abs(y + bounds) < 2:
            return (x + random.uniform(-20, 20), bounds)
        elif abs(x - bounds) < 2:
            return (-bounds, y + random.uniform(-20, 20))
        else:
            return (bounds, y + random.uniform(-20, 20))
