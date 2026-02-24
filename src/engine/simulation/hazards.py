"""HazardManager — environmental hazards that block paths and force rerouting.

Hazards are dynamic obstacles (roadblocks, fires, floods) that spawn during
combat waves and expire after a set duration.  They are communicated to the
pathfinder as blocked positions so units must reroute around them.

Data flow:
  GameMode._start_wave -> HazardManager.spawn_random()
  HazardManager.tick(dt) -> expire old hazards
  Engine._tick_loop -> hazard_manager.tick(dt)
  Engine.dispatch_unit -> passes blocked nodes to pathfinder
  HazardManager.to_telemetry() -> sent to frontend via sim_hazards event

Events published on EventBus:
  - hazard_spawned: new hazard created (type, position, radius)
  - hazard_expired: hazard timed out and removed
"""

from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus

HAZARD_TYPES = ("roadblock", "fire", "flood")


@dataclass
class Hazard:
    """A single environmental hazard on the battlespace map."""

    id: str
    hazard_type: str       # "roadblock", "fire", "flood"
    position: tuple[float, float]  # (x, y) center in local meters
    radius: float          # blocking radius in meters
    duration: float        # total lifetime in seconds
    active: bool = True
    elapsed: float = 0.0   # seconds since spawn


class HazardManager:
    """Manages active environmental hazards on the map.

    Spawns, tracks, expires, and reports hazards. Provides blocked-node
    data to the pathfinder so units reroute around active hazards.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._hazards: list[Hazard] = []

    # -- Spawn ---------------------------------------------------------------

    def spawn_hazard(
        self,
        hazard_type: str,
        position: tuple[float, float],
        radius: float,
        duration: float,
    ) -> Hazard:
        """Create and register a new hazard.

        Args:
            hazard_type: One of "roadblock", "fire", "flood".
            position: (x, y) center in local meters.
            radius: Blocking radius in meters.
            duration: Lifetime in seconds before auto-expire.

        Returns:
            The newly created Hazard.
        """
        h = Hazard(
            id=str(uuid.uuid4()),
            hazard_type=hazard_type,
            position=position,
            radius=radius,
            duration=duration,
            active=True,
            elapsed=0.0,
        )
        self._hazards.append(h)
        self._event_bus.publish("hazard_spawned", {
            "id": h.id,
            "hazard_type": h.hazard_type,
            "position": {"x": h.position[0], "y": h.position[1]},
            "radius": h.radius,
            "duration": h.duration,
        })
        return h

    def spawn_random(self, count: int, map_bounds: float) -> list[Hazard]:
        """Spawn *count* hazards at random positions within map bounds.

        Randomly selects hazard type, radius (5-15m), and duration (20-60s).

        Args:
            count: Number of hazards to spawn.
            map_bounds: Half-extent of the map in meters (positions range
                        from -map_bounds to +map_bounds).

        Returns:
            List of newly created hazards.
        """
        spawned: list[Hazard] = []
        for _ in range(count):
            htype = random.choice(HAZARD_TYPES)
            pos = (
                random.uniform(-map_bounds, map_bounds),
                random.uniform(-map_bounds, map_bounds),
            )
            radius = random.uniform(5.0, 15.0)
            duration = random.uniform(20.0, 60.0)
            h = self.spawn_hazard(htype, pos, radius, duration)
            spawned.append(h)
        return spawned

    # -- Tick ----------------------------------------------------------------

    def tick(self, dt: float) -> None:
        """Update hazard timers and expire those past their duration.

        Args:
            dt: Time step in seconds.
        """
        expired: list[Hazard] = []
        for h in self._hazards:
            if not h.active:
                continue
            h.elapsed += dt
            if h.elapsed >= h.duration:
                h.active = False
                expired.append(h)

        for h in expired:
            self._hazards.remove(h)
            self._event_bus.publish("hazard_expired", {
                "id": h.id,
                "hazard_type": h.hazard_type,
                "position": {"x": h.position[0], "y": h.position[1]},
            })

    # -- Queries -------------------------------------------------------------

    def is_blocked(self, position: tuple[float, float]) -> bool:
        """Check if a position falls inside any active hazard radius.

        Args:
            position: (x, y) in local meters.

        Returns:
            True if the position is within any active hazard's radius.
        """
        px, py = position
        for h in self._hazards:
            if not h.active:
                continue
            dist = math.hypot(px - h.position[0], py - h.position[1])
            if dist <= h.radius:
                return True
        return False

    def get_blocked_nodes(self) -> list[tuple[float, float]]:
        """Return center positions of all active hazards.

        Used by the pathfinder to exclude these positions from path
        computation.

        Returns:
            List of (x, y) positions blocked by active hazards.
        """
        return [h.position for h in self._hazards if h.active]

    @property
    def active_hazards(self) -> list[Hazard]:
        """Return a list of currently active hazards."""
        return [h for h in self._hazards if h.active]

    # -- Management ----------------------------------------------------------

    def clear(self) -> None:
        """Remove all hazards (active and inactive)."""
        self._hazards.clear()

    # -- Telemetry -----------------------------------------------------------

    def to_telemetry(self) -> list[dict]:
        """Serialize active hazards for frontend rendering.

        Returns:
            List of dicts with hazard data for the WebSocket telemetry.
        """
        result: list[dict] = []
        for h in self._hazards:
            if not h.active:
                continue
            remaining = max(0.0, h.duration - h.elapsed)
            result.append({
                "id": h.id,
                "hazard_type": h.hazard_type,
                "position": {"x": h.position[0], "y": h.position[1]},
                "radius": h.radius,
                "active": h.active,
                "remaining": round(remaining, 1),
            })
        return result
