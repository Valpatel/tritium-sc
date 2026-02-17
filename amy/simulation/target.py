"""SimulationTarget — a movable entity on the battlespace map.

Architecture
------------
SimulationTarget is a *flat dataclass* by design.  Every entity type
(rover, drone, turret, person, vehicle, animal) shares the same fields.
Type-specific behaviour is encoded in lookup tables (_DRAIN_RATES) and
in the tick() state machine rather than in a class hierarchy.

Why flat, not subclassed:
  - All targets flow through the same tick loop, EventBus serialisation,
    and TargetTracker pipeline.  Polymorphism would add dispatch overhead
    with no behavioural gain — a turret is just speed=0, a person has
    battery drain=0.
  - The level-format loader and spawners create targets from data; a
    component/subclass system would require a factory registry for the
    same outcome.

Waypoints live *on* the target because navigation is per-entity state
(current index, loop vs. one-shot).  A separate pathfinding service
would be warranted if targets needed collision avoidance or A*; for
waypoint-following this is simpler.

Threat classification is NOT a property of the target — it is computed
by ThreatClassifier in ``amy/escalation.py`` from zone membership and
dwell time.  SimulationTarget carries only *intrinsic* state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# Battery drain rates per second by asset type
_DRAIN_RATES: dict[str, float] = {
    "rover": 0.001,
    "drone": 0.002,
    "turret": 0.0005,
    "person": 0.0,
    "vehicle": 0.0,
    "animal": 0.0,
}


@dataclass
class SimulationTarget:
    """A single simulated entity (rover, drone, turret, person, etc.).

    Lifecycle:
      active -> idle/stationary/arrived/escaped/neutralized/despawned/low_battery -> destroyed
      Hostiles: active -> escaped (reached exit edge) or neutralized (intercepted)
      Friendlies: active -> arrived (dispatch) or loops patrol (loop_waypoints=True)
      Neutrals: active -> despawned (reached destination)
    """

    target_id: str
    name: str
    alliance: str  # "friendly", "hostile", "neutral", "unknown"
    asset_type: str  # "rover", "drone", "turret", "person", "vehicle", "animal"
    position: tuple[float, float]  # (x, y) on map — units are abstract map coords
    heading: float = 0.0  # degrees, 0 = north (+y), clockwise
    speed: float = 1.0  # units/second (0.0 for turrets)
    battery: float = 1.0  # 0.0-1.0 (persons/animals drain at 0.0)
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    _waypoint_index: int = 0
    status: str = "active"  # "active", "idle", "stationary", "arrived", "escaped", "neutralized", "despawned", "low_battery", "destroyed"
    loop_waypoints: bool = False  # True for friendly patrol routes, False for one-shot paths

    def tick(self, dt: float) -> None:
        """Advance simulation by *dt* seconds."""
        if self.status in ("destroyed", "low_battery", "neutralized", "escaped"):
            return

        # Battery drain
        drain = _DRAIN_RATES.get(self.asset_type, 0.001) * dt
        self.battery = max(0.0, self.battery - drain)
        if self.battery < 0.05:
            self.status = "low_battery"
            return

        # Movement toward current waypoint
        if not self.waypoints:
            if self.status == "active":
                self.status = "idle"
            return
        if self.speed <= 0:
            if self.status == "active":
                self.status = "stationary"
            return

        tx, ty = self.waypoints[self._waypoint_index]
        dx = tx - self.position[0]
        dy = ty - self.position[1]
        dist = math.hypot(dx, dy)

        if dist < 1.0:
            # Arrived at waypoint — advance or finish
            if self._waypoint_index >= len(self.waypoints) - 1:
                # Path complete — terminal status depends on alliance
                if self.alliance == "neutral":
                    self.status = "despawned"
                elif self.alliance == "hostile":
                    self.status = "escaped"
                elif self.loop_waypoints:
                    # Friendly patrol — loop back to start
                    self._waypoint_index = 0
                else:
                    # Friendly one-shot dispatch — arrived at destination
                    self.status = "arrived"
                return
            else:
                self._waypoint_index += 1
            return

        # Update heading: atan2(dx, dy) so 0 = north (+y), convert to degrees
        self.heading = math.degrees(math.atan2(dx, dy))

        # Move toward waypoint
        step = min(self.speed * dt, dist)
        self.position = (
            self.position[0] + (dx / dist) * step,
            self.position[1] + (dy / dist) * step,
        )

    def to_dict(self) -> dict:
        """Serialize for EventBus / API consumption.

        Includes both local position (meters from reference) and real
        lat/lng/alt from the server-side geo-reference.  If no reference
        is set, lat/lng default to 0.

        Note: threat_level is NOT included — it is computed externally by
        ThreatClassifier and lives in ThreatRecord, not on the target.
        """
        from amy.geo import local_to_latlng
        geo = local_to_latlng(self.position[0], self.position[1])
        return {
            "target_id": self.target_id,
            "name": self.name,
            "alliance": self.alliance,
            "asset_type": self.asset_type,
            "position": {"x": self.position[0], "y": self.position[1]},
            "lat": geo["lat"],
            "lng": geo["lng"],
            "alt": geo["alt"],
            "heading": self.heading,
            "speed": self.speed,
            "battery": round(self.battery, 4),
            "status": self.status,
            "waypoints": [{"x": w[0], "y": w[1]} for w in self.waypoints],
        }
