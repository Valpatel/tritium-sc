"""AmbientSpawner — generates neutral neighborhood activity.

Spawns neighbors walking, cars driving, dogs roaming, delivery people,
and cats wandering to create a realistic "quiet phase" before any
threat escalation.  All targets use alliance='neutral' and auto-despawn
when they reach their destination.

Architecture
------------
AmbientSpawner is deliberately separate from the hostile spawner in
SimulationEngine.  The two serve different narrative purposes:

  - Hostile spawner (engine._random_hostile_spawner): creates *threats*
    at adaptive rates.  It is integral to the engine because hostile
    pressure drives the tactical loop — Amy must detect, classify, and
    dispatch against these.  The spawn rate adapts to current hostile
    count (back-pressure).

  - AmbientSpawner: creates *background noise* — neutral entities that
    test Amy's discrimination (is that person a threat or a neighbor?).
    It runs on its own thread with independent timing (15-45s intervals)
    and caps at MAX_NEUTRALS=8 to keep the map readable.

A unified SpawnerManager was considered and rejected: the two spawners
have no shared state, different timing models, different target profiles,
and different lifecycle rules.  Merging them would couple narrative pacing
(ambient) to tactical pressure (hostile) for no benefit.

Path generation is inline (_sidewalk_path, _road_path, _yard_wander,
_delivery_path) because each path type has unique topology.  A shared
pathfinding service would be warranted only if targets needed collision
avoidance or terrain-aware routing; for waypoint-following, inline
generators are simpler and more readable.
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from .target import SimulationTarget

if TYPE_CHECKING:
    from .engine import SimulationEngine

# Map bounds (same as engine)
_MAP_MIN = -30.0
_MAP_MAX = 30.0

# -- Neighborhood street grid ------------------------------------------------
# Two north-south streets and two east-west streets form a grid through the
# map.  Paths snap to these corridors so targets follow roads rather than
# cutting through houses diagonally.
#
# Scale: 1 unit = 1 meter.  Map is 60m x 60m (roughly one residential block).
# Streets are at the 1/3 and 2/3 lines: x = -10, x = +10, y = -10, y = +10.
_STREETS_NS_X = [-10.0, 10.0]   # North-south street X coordinates
_STREETS_EW_Y = [-10.0, 10.0]   # East-west street Y coordinates
_STREET_JITTER = 1.5            # Lateral jitter to avoid single-file lines


def _snap_to_nearest_street(x: float, y: float) -> tuple[float, float]:
    """Snap a point to the nearest street intersection or corridor."""
    # Find nearest NS street
    best_ns = min(_STREETS_NS_X, key=lambda sx: abs(sx - x))
    # Find nearest EW street
    best_ew = min(_STREETS_EW_Y, key=lambda sy: abs(sy - y))
    # Snap to whichever is closer
    if abs(best_ns - x) < abs(best_ew - y):
        return (best_ns + random.uniform(-_STREET_JITTER, _STREET_JITTER), y)
    else:
        return (x, best_ew + random.uniform(-_STREET_JITTER, _STREET_JITTER))


def _street_path(start: tuple[float, float], end: tuple[float, float]) -> list[tuple[float, float]]:
    """Generate an L-shaped path following the street grid from start to end.

    Instead of cutting diagonally through yards, the path walks along the
    nearest north-south street, turns at an east-west street, then continues
    to the destination.  This produces the right-angle walking patterns you
    see in real neighborhoods.
    """
    sx, sy = start
    ex, ey = end

    # Pick the NS street closest to the start
    ns_x = min(_STREETS_NS_X, key=lambda s: abs(s - sx))
    # Pick the EW street closest to the end
    ew_y = min(_STREETS_EW_Y, key=lambda s: abs(s - ey))

    jx = random.uniform(-_STREET_JITTER, _STREET_JITTER)
    jy = random.uniform(-_STREET_JITTER, _STREET_JITTER)

    # Path: start -> walk to NS street -> turn onto EW street -> end
    corner = (ns_x + jx, ew_y + jy)
    return [corner, end]


# -- Time-of-day activity scaling --------------------------------------------
# Real neighborhoods are quiet at 3am and busy at 5pm.  These multipliers
# scale spawn rates and type probabilities by hour of day.

def _hour_activity() -> tuple[float, float]:
    """Return (ambient_multiplier, hostile_multiplier) for the current hour.

    Ambient multiplier:  0.1 at 3am, 1.0 at 10am-6pm, 0.3 at midnight.
    Hostile multiplier:  0.3 during daytime, 1.0 at night (more intrusions
    after dark).
    """
    hour = datetime.now().hour
    if 6 <= hour < 22:
        # Daytime: full ambient, low hostile
        ambient = 1.0 if 8 <= hour < 20 else 0.6
        hostile = 0.3
    elif 22 <= hour or hour < 2:
        # Late evening: some ambient, rising hostile
        ambient = 0.3
        hostile = 0.8
    else:
        # Deep night (2am-6am): minimal ambient, peak hostile
        ambient = 0.1
        hostile = 1.0
    return ambient, hostile

# Predefined names for each target type
_NEIGHBOR_NAMES = [
    "Mrs. Henderson", "Mr. Kowalski", "Jenny", "Old Tom",
    "The Jogger", "Dog Walker", "Mail Carrier", "Teen on Bike",
    "Morning Walker", "Evening Stroller", "Couple", "Kid",
]

_CAR_NAMES = [
    "Red Sedan", "Blue SUV", "White Pickup", "Black Coupe",
    "Silver Minivan", "Green Hatchback", "Yellow Taxi", "Delivery Van",
]

_DOG_NAMES = [
    "Golden Retriever", "German Shepherd", "Beagle", "Husky",
    "Labrador", "Poodle", "Border Collie", "Corgi",
]

_CAT_NAMES = [
    "Orange Tabby", "Black Cat", "Calico", "Siamese",
    "Gray Cat", "White Cat", "Tuxedo Cat", "Maine Coon",
]

_DELIVERY_NAMES = [
    "FedEx Driver", "UPS Driver", "Amazon Delivery",
    "Pizza Delivery", "DoorDash", "Postman",
]


class AmbientSpawner:
    """Spawns neutral targets at random intervals to simulate neighborhood life."""

    MAX_NEUTRALS = 8
    SPAWN_MIN = 15.0  # seconds
    SPAWN_MAX = 45.0

    def __init__(self, engine: SimulationEngine) -> None:
        self._engine = engine
        self._running = False
        self._thread: threading.Thread | None = None
        self._used_names: set[str] = set()
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._spawn_loop, name="ambient-spawner", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _spawn_loop(self) -> None:
        while self._running:
            # Scale spawn interval by time of day — fewer spawns at 3am
            ambient_mult, _ = _hour_activity()
            base_delay = random.uniform(self.SPAWN_MIN, self.SPAWN_MAX)
            # Invert multiplier: low activity = longer delays
            delay = base_delay / max(ambient_mult, 0.1)

            elapsed = 0.0
            while elapsed < delay and self._running:
                time.sleep(0.5)
                elapsed += 0.5

            if not self._running or not self._enabled:
                continue

            # Respect engine-level spawner pause (LIVE mode)
            if self._engine.spawners_paused:
                continue

            # Count current neutrals
            neutral_count = sum(
                1 for t in self._engine.get_targets()
                if t.alliance == "neutral" and t.status not in ("despawned", "destroyed")
            )
            if neutral_count >= self.MAX_NEUTRALS:
                continue

            self._spawn_random()

    def _spawn_random(self) -> None:
        """Spawn a random neutral target type."""
        roll = random.random()
        if roll < 0.35:
            self._spawn_neighbor()
        elif roll < 0.55:
            self._spawn_car()
        elif roll < 0.70:
            self._spawn_dog()
        elif roll < 0.80:
            self._spawn_cat()
        else:
            self._spawn_delivery()

    def _pick_name(self, names: list[str]) -> str:
        """Pick an unused name, adding suffix if needed."""
        available = [n for n in names if n not in self._used_names]
        if not available:
            # All used -- pick random + suffix
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
        edge = random.randint(0, 3)
        coord = random.uniform(_MAP_MIN * 0.8, _MAP_MAX * 0.8)
        if edge == 0:
            return (coord, _MAP_MAX)
        elif edge == 1:
            return (coord, _MAP_MIN)
        elif edge == 2:
            return (_MAP_MAX, coord)
        else:
            return (_MAP_MIN, coord)

    def _opposite_edge(self, pos: tuple[float, float]) -> tuple[float, float]:
        """Return a position on the opposite edge from the given position."""
        x, y = pos
        if abs(y - _MAP_MAX) < 2:
            return (self._clamp(x + random.uniform(-10, 10)), _MAP_MIN)
        elif abs(y - _MAP_MIN) < 2:
            return (self._clamp(x + random.uniform(-10, 10)), _MAP_MAX)
        elif abs(x - _MAP_MAX) < 2:
            return (_MAP_MIN, self._clamp(y + random.uniform(-10, 10)))
        else:
            return (_MAP_MAX, self._clamp(y + random.uniform(-10, 10)))

    def _clamp(self, v: float) -> float:
        return max(_MAP_MIN, min(_MAP_MAX, v))

    def _sidewalk_path(self, start: tuple[float, float]) -> list[tuple[float, float]]:
        """Generate a path along sidewalks following the street grid.

        People walk along streets, not through houses.  The path makes an
        L-shaped turn at a street corner, producing the right-angle walking
        pattern you see in real neighborhoods.
        """
        end = self._opposite_edge(start)
        return _street_path(start, end)

    def _road_path(self, start: tuple[float, float]) -> list[tuple[float, float]]:
        """Generate a road path following the street grid.

        Cars follow streets.  Unlike the old straight-line path, this snaps
        to the nearest NS or EW street corridor so the car visibly drives
        along a road.
        """
        end = self._opposite_edge(start)
        return _street_path(start, end)

    def _yard_wander(self) -> tuple[tuple[float, float], list[tuple[float, float]]]:
        """Generate a start + wander path within a yard area."""
        # Pick a random yard area (not at edges)
        cx = random.uniform(-15, 15)
        cy = random.uniform(-15, 15)
        start = (cx + random.uniform(-3, 3), cy + random.uniform(-3, 3))
        points = []
        for _ in range(random.randint(3, 5)):
            points.append((
                self._clamp(cx + random.uniform(-5, 5)),
                self._clamp(cy + random.uniform(-5, 5)),
            ))
        # Exit toward nearest edge
        exit_point = self._random_edge()
        points.append(exit_point)
        return start, points

    def _delivery_path(self) -> tuple[tuple[float, float], list[tuple[float, float]]]:
        """Generate delivery path: road edge -> front door -> pause -> back."""
        start = self._random_edge()
        # "Front door" somewhere in the interior
        door = (random.uniform(-10, 10), random.uniform(-10, 10))
        # Path: approach -> door -> wait (same point, speed makes them pause) -> back to edge
        return_point = self._random_edge()
        return start, [door, door, return_point]

    def _spawn_neighbor(self) -> None:
        start = self._random_edge()
        waypoints = self._sidewalk_path(start)
        name = self._pick_name(_NEIGHBOR_NAMES)
        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=name,
            alliance="neutral",
            asset_type="person",
            position=start,
            speed=1.2,
            waypoints=waypoints,
        )
        self._engine.add_target(target)

    def _spawn_car(self) -> None:
        start = self._random_edge()
        waypoints = self._road_path(start)
        name = self._pick_name(_CAR_NAMES)
        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=name,
            alliance="neutral",
            asset_type="vehicle",
            position=start,
            speed=8.0,
            waypoints=waypoints,
        )
        self._engine.add_target(target)

    def _spawn_dog(self) -> None:
        start, waypoints = self._yard_wander()
        name = self._pick_name(_DOG_NAMES)
        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=name,
            alliance="neutral",
            asset_type="animal",
            position=start,
            speed=2.0,
            waypoints=waypoints,
        )
        self._engine.add_target(target)

    def _spawn_cat(self) -> None:
        start, waypoints = self._yard_wander()
        name = self._pick_name(_CAT_NAMES)
        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=name,
            alliance="neutral",
            asset_type="animal",
            position=start,
            speed=1.5,
            waypoints=waypoints,
        )
        self._engine.add_target(target)

    def _spawn_delivery(self) -> None:
        start, waypoints = self._delivery_path()
        name = self._pick_name(_DELIVERY_NAMES)
        target = SimulationTarget(
            target_id=str(uuid.uuid4()),
            name=name,
            alliance="neutral",
            asset_type="person",
            position=start,
            speed=1.0,
            waypoints=waypoints,
        )
        self._engine.add_target(target)

    def release_name(self, name: str) -> None:
        """Release a name when a target is removed."""
        self._used_names.discard(name)
