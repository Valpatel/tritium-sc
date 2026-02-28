# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
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

Combat fields (health, weapon_range, etc.) support the projectile-based
combat system.  Unit type stat profiles are applied via
``apply_combat_profile()`` or set explicitly by factories/spawners.
"""

from __future__ import annotations

import math
import time as _time
from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .movement import MovementController


# Battery drain rates per second by asset type
_DRAIN_RATES: dict[str, float] = {
    "rover": 0.001,
    "drone": 0.002,
    "turret": 0.0005,
    "scout_drone": 0.0025,
    "person": 0.0,
    "vehicle": 0.0,
    "animal": 0.0,
    "heavy_turret": 0.0004,
    "missile_turret": 0.0003,
    "tank": 0.0008,
    "apc": 0.0010,
    "swarm_drone": 0.003,
}

# Combat stat profiles by (asset_type, alliance).
# Format: (health, max_health, weapon_range, weapon_cooldown, weapon_damage, is_combatant)
_COMBAT_PROFILES: dict[str, tuple[float, float, float, float, float, bool]] = {
    "turret":           (200.0, 200.0, 80.0, 1.5, 15.0, True),
    "drone":            (60.0,  60.0,  50.0, 1.0,  8.0, True),
    "rover":            (150.0, 150.0, 60.0, 2.0, 12.0, True),
    "person_hostile":   (80.0,  80.0,  40.0, 2.5, 10.0, True),
    "person_neutral":   (50.0,  50.0,   0.0, 0.0,  0.0, False),
    "vehicle":          (300.0, 300.0,  0.0, 0.0,  0.0, False),
    "animal":           (30.0,  30.0,   0.0, 0.0,  0.0, False),
    # Heavy units
    "tank":             (400.0, 400.0, 100.0, 3.0, 30.0, True),
    "apc":              (300.0, 300.0,  60.0, 1.0,  8.0, True),
    "heavy_turret":     (350.0, 350.0, 120.0, 2.5, 25.0, True),
    "missile_turret":   (200.0, 200.0, 150.0, 5.0, 50.0, True),
    # Scout variant
    "scout_drone":      (40.0,  40.0,  40.0, 1.5,  5.0, True),
    # Hostile variants
    "hostile_vehicle":  (200.0, 200.0, 70.0, 2.0, 15.0, True),
    "hostile_leader":   (150.0, 150.0, 50.0, 2.0, 12.0, True),
    # Swarm drone: fast, fragile, short-range
    "swarm_drone":      (25.0,  25.0,  20.0, 1.0,  5.0, True),
}


def _profile_key(asset_type: str, alliance: str) -> str:
    """Return the combat profile lookup key for a target."""
    if asset_type == "person":
        if alliance == "hostile":
            return "person_hostile"
        return "person_neutral"
    return asset_type


@dataclass
class SimulationTarget:
    """A single simulated entity (rover, drone, turret, person, etc.).

    Lifecycle:
      active -> idle/stationary/arrived/escaped/neutralized/eliminated/despawned/low_battery -> destroyed
      Hostiles: active -> escaped (reached exit edge) or neutralized/eliminated (intercepted/killed)
      Friendlies: active -> arrived (dispatch) or loops patrol (loop_waypoints=True)
      Neutrals: active -> despawned (reached destination)
    """

    target_id: str
    name: str
    alliance: str  # "friendly", "hostile", "neutral", "unknown"
    asset_type: str  # "rover", "drone", "turret", "person", "vehicle", "animal"
    position: tuple[float, float]  # (x, y) on map — units are abstract map coords
    heading: float = 0.0  # degrees, 0 = north (+y), clockwise
    altitude: float = 0.0  # meters above ground (0 = ground level)
    speed: float = 1.0  # units/second (0.0 for turrets)
    battery: float = 1.0  # 0.0-1.0 (persons/animals drain at 0.0)
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    _waypoint_index: int = 0
    status: str = "active"  # "active", "idle", "stationary", "arrived", "escaped", "neutralized", "eliminated", "despawned", "low_battery", "destroyed"
    loop_waypoints: bool = False  # True for friendly patrol routes, False for one-shot paths

    # Combat fields
    health: float = 100.0
    max_health: float = 100.0
    weapon_range: float = 15.0    # meters — how far this unit can shoot
    weapon_cooldown: float = 2.0  # seconds between shots
    weapon_damage: float = 10.0   # damage per hit
    last_fired: float = 0.0       # timestamp of last shot
    kills: int = 0
    is_combatant: bool = True     # False for civilians/animals

    # FSM state name (set by engine from unit FSM, None when no FSM assigned)
    fsm_state: str | None = None

    # Extended simulation fields
    squad_id: str | None = None       # Squad membership (None = solo unit)
    morale: float = 1.0               # Unit morale 0.0 (broken) to 1.0 (full)
    max_morale: float = 1.0           # Maximum morale cap
    degradation: float = 0.0          # Equipment degradation 0.0 = pristine, 1.0 = broken
    detected: bool = False            # Whether this unit has been spotted by enemies
    detected_at: float = 0.0          # Timestamp when first detected
    visible: bool = True              # Whether this target is visible to friendlies
    detected_by: list[str] = field(default_factory=list)  # IDs of units that can see this target
    is_leader: bool = False           # Whether this unit is the squad leader
    _fleeing: bool = False            # Internal fleeing state (unit is retreating)

    # Smooth movement controller (assigned in __post_init__ for mobile combatants)
    movement: MovementController | None = field(default=None, repr=False)

    # Track waypoints version to detect external changes
    _waypoints_version: int = field(default=0, repr=False)

    # Building collision check: callable(x, y) -> True if blocked.
    # Set by engine.add_target() when obstacles are loaded.
    # Flying units (drone, scout_drone, swarm_drone) are exempt.
    _collision_check: Callable[[float, float], bool] | None = field(
        default=None, repr=False
    )

    # Types that fly over buildings (exempt from collision)
    _FLYING_TYPES: tuple[str, ...] = field(
        default=("drone", "scout_drone", "swarm_drone"), init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Auto-create MovementController for mobile combatant types.

        Only combatant units (friendly or hostile) with speed > 0 get smooth
        movement.  Neutral entities (pedestrians, animals, vehicles) use
        legacy linear movement which is simpler and adequate for ambient
        background activity.
        """
        if self.speed > 0 and self.is_combatant and self.alliance != "neutral":
            from .movement import MovementController
            # Convert target heading (0=north, 90=east) to MC heading (0=east, 90=north)
            mc_heading = (90.0 - self.heading) % 360.0
            self.movement = MovementController(
                max_speed=self.speed,
                turn_rate=max(180.0, self.speed * 90.0),
                acceleration=max(4.0, self.speed * 2.0),
                deceleration=max(6.0, self.speed * 3.0),
                x=self.position[0],
                y=self.position[1],
                heading=mc_heading,
            )
            # Push initial waypoints to controller if any
            if self.waypoints:
                self.movement.set_path(self.waypoints, loop=self.loop_waypoints)
                self._waypoints_version = id(self.waypoints)

    def apply_combat_profile(self) -> None:
        """Apply combat stats from _COMBAT_PROFILES based on asset_type and alliance."""
        key = _profile_key(self.asset_type, self.alliance)
        profile = _COMBAT_PROFILES.get(key)
        if profile is None:
            return
        (self.health, self.max_health, self.weapon_range,
         self.weapon_cooldown, self.weapon_damage, self.is_combatant) = profile

    def set_collision_check(
        self,
        check: Callable[[float, float], bool],
        height_at: Callable[[float, float], float | None] | None = None,
    ) -> None:
        """Set the building collision checker.

        For flying types with a *height_at* callable, collision is 3D-aware:
        blocked only when ``height_at(x, y)`` is not None AND ``self.altitude
        <= height``.  Without *height_at*, flying types are exempt (legacy).

        Ground types always use the 2D ``check`` callable as-is.
        """
        if self.asset_type in self._FLYING_TYPES:
            if height_at is not None:
                # 3D-aware collision: blocked only when inside footprint AND
                # altitude is at or below the roof height.
                def _3d_check(x: float, y: float) -> bool:
                    h = height_at(x, y)
                    return h is not None and self.altitude <= h
                self._collision_check = _3d_check
            else:
                self._collision_check = None
            return
        self._collision_check = check

    def apply_damage(self, amount: float) -> bool:
        """Apply *amount* damage. Returns True if this target is eliminated (health <= 0)."""
        if self.status in ("destroyed", "eliminated", "neutralized"):
            return True
        self.health = max(0.0, self.health - amount)
        if self.health <= 0:
            self.status = "eliminated"
            return True
        return False

    def can_fire(self) -> bool:
        """Check if this target can fire right now (cooldown elapsed, has weapon, alive)."""
        if self.status not in ("active", "idle", "stationary"):
            return False
        if self.weapon_range <= 0 or self.weapon_damage <= 0:
            return False
        if not self.is_combatant:
            return False
        now = _time.time()
        return (now - self.last_fired) >= self.weapon_cooldown

    def tick(self, dt: float) -> None:
        """Advance simulation by *dt* seconds."""
        if self.status in ("destroyed", "low_battery", "neutralized", "escaped", "eliminated"):
            return

        # Battery drain
        drain = _DRAIN_RATES.get(self.asset_type, 0.001) * dt
        self.battery = max(0.0, self.battery - drain)
        if self.battery < 0.05:
            self.status = "low_battery"
            return

        if self.movement is not None:
            self._tick_with_controller(dt)
        else:
            self._tick_legacy(dt)

    def _tick_with_controller(self, dt: float) -> None:
        """Movement driven by MovementController (smooth acceleration/turns)."""
        mc = self.movement
        assert mc is not None  # caller guarantees

        # Sync waypoints to controller if they changed externally
        wv = id(self.waypoints)
        if wv != self._waypoints_version:
            self._waypoints_version = wv
            if self.waypoints:
                mc.set_path(self.waypoints, loop=self.loop_waypoints)
            else:
                mc.stop()

        # No waypoints and controller has arrived => idle/stationary
        if not self.waypoints and mc.arrived:
            if self.status == "active":
                self.status = "idle"
            return
        if self.speed <= 0:
            if self.status == "active":
                self.status = "stationary"
            return

        # Save pre-tick position for collision rollback
        pre_x, pre_y = mc.x, mc.y

        # Tick the controller
        mc.tick(dt)

        # Building collision check: if new position is inside a building,
        # revert to pre-tick position and advance past the blocking waypoint.
        if self._collision_check is not None and self._collision_check(mc.x, mc.y):
            mc.x = pre_x
            mc.y = pre_y
            # Advance waypoint index past the blocking segment
            if mc._waypoints and mc._waypoint_index < len(mc._waypoints):
                mc._waypoint_index += 1
                if mc._waypoint_index >= len(mc._waypoints):
                    if mc._patrol_loop:
                        mc._waypoint_index = 0
                    elif self.alliance == "hostile":
                        # Hostiles blocked by buildings should NOT escape —
                        # stay active at current position to participate in combat.
                        # Rewind to last waypoint so they can retry or get engaged.
                        mc._waypoint_index = max(0, len(mc._waypoints) - 1)
                    else:
                        mc.arrived = True
                        mc.speed = 0.0

        # Sync position and heading from controller.
        # MovementController uses math convention: 0=east, 90=north (atan2(dy,dx)).
        # SimulationTarget uses map convention: 0=north, 90=east (atan2(dx,dy)).
        # Conversion: target_heading = (90 - mc_heading) % 360
        self.position = (mc.x, mc.y)
        self.heading = (90.0 - mc.heading) % 360.0

        # Check arrival
        if mc.arrived:
            # Controller finished its path — determine terminal status
            if self.alliance == "neutral":
                self.status = "despawned"
            elif self.alliance == "hostile":
                self.status = "escaped"
            elif self.loop_waypoints:
                # Friendly patrol — controller handles looping internally
                pass
            else:
                self.status = "arrived"

    def _tick_legacy(self, dt: float) -> None:
        """Legacy linear movement (non-combatants: neutrals, animals, etc.)."""
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

        # Pre-check: if the current waypoint itself is inside a building,
        # skip it immediately (path segment crosses a building).
        if self._collision_check is not None and self._collision_check(tx, ty):
            if self._waypoint_index >= len(self.waypoints) - 1:
                # All remaining waypoints blocked — terminal status
                if self.alliance == "neutral":
                    self.status = "despawned"
                elif self.alliance == "hostile":
                    # Don't escape — stay active to participate in combat
                    pass
                else:
                    self.status = "idle"
                return
            self._waypoint_index += 1
            return

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
        new_x = self.position[0] + (dx / dist) * step
        new_y = self.position[1] + (dy / dist) * step

        # Building collision check: reject moves into buildings
        if self._collision_check is not None and self._collision_check(new_x, new_y):
            # Movement would enter a building — skip to next waypoint
            if self._waypoint_index >= len(self.waypoints) - 1:
                if self.alliance == "neutral":
                    self.status = "despawned"
                elif self.alliance == "hostile":
                    # Don't escape — stay active to participate in combat
                    pass
                else:
                    self.status = "idle"
                return
            self._waypoint_index += 1
            return

        self.position = (new_x, new_y)

    def to_dict(self) -> dict:
        """Serialize for EventBus / API consumption.

        Includes both local position (meters from reference) and real
        lat/lng/alt from the server-side geo-reference.  If no reference
        is set, lat/lng default to 0.

        Note: threat_level is NOT included — it is computed externally by
        ThreatClassifier and lives in ThreatRecord, not on the target.
        """
        from engine.tactical.geo import local_to_latlng
        geo = local_to_latlng(self.position[0], self.position[1], self.altitude)
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
            "altitude": self.altitude,
            "speed": self.speed,
            "battery": round(self.battery, 4),
            "status": self.status,
            "waypoints": [{"x": w[0], "y": w[1]} for w in self.waypoints],
            "health": round(self.health, 1),
            "max_health": round(self.max_health, 1),
            "kills": self.kills,
            "is_combatant": self.is_combatant,
            "fsm_state": self.fsm_state,
            "squad_id": self.squad_id,
            "morale": round(self.morale, 2),
            "degradation": round(self.degradation, 2),
            "detected": self.detected,
            "visible": self.visible,
            "detected_by": self.detected_by,
            "weapon_range": round(self.weapon_range, 1),
        }
