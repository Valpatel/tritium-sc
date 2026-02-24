"""HostileBehavior -- hostile kid combat AI with tactical layers.

Kids with nerf guns. Follow waypoints, shoot at defenders in range.

Tactical layers (checked in priority order):
  1. Cover-seeking: if damaged (<50% health), move toward building edge
  2. Flanking: if nearest enemy is a stationary turret, apply lateral offset
  3. Dodge: periodic random perpendicular offset (reduced during group rush)
  4. Fire: shoot at nearest defender in range

Hostile tactical behaviors:
  - Flanking: When nearest enemy is a stationary turret, the hostile
    offsets its position by 45-90 degrees laterally each tick instead of
    approaching head-on.
  - Group rush: When 3+ hostiles cluster within 30m, they get +20% speed
    and dodge less frequently (charging together).
  - Cover-seeking: When health drops below 50%, the hostile moves toward
    the nearest building polygon edge for cover.

Pursuit-evasion behaviors (via PursuitSystem):
  - Fleeing speed boost: +30% speed while in fleeing state.
  - Evasive zigzag: periodic lateral offset while fleeing.
  - Escape route planning: fleeing hostiles head toward the map edge
    farthest from defenders.
  - Flee timer: hostiles rally after 15s and return to advancing.
  - Recovery: hostiles return to advancing when no defenders are nearby.
"""

from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING

from engine.units import get_type as _get_unit_type
from engine.units.base import MovementCategory

from ..degradation import apply_degradation, can_fire_degraded, get_effective_cooldown
from .base import nearest_in_range

from ..pursuit import PursuitSystem

if TYPE_CHECKING:
    from engine.tactical.obstacles import BuildingObstacles
    from ..combat import CombatSystem
    from ..comms import UnitComms
    from ..target import SimulationTarget

# Hostile flanking parameters
_FLANK_STEP = 1.5                     # lateral distance per flank event (meters)
_FLANK_INTERVAL = (3.0, 5.0)          # seconds between flank offsets

# Group rush parameters
_GROUP_RUSH_RADIUS = 30.0             # meters -- hostiles within this distance form a group
_GROUP_RUSH_MIN_COUNT = 3             # minimum hostiles for a rush
_GROUP_RUSH_SPEED_BOOST = 1.2         # 20% speed increase
_GROUP_RUSH_DODGE_INTERVAL = (6.0, 10.0)  # reduced dodge frequency during rush

# Cover-seeking parameters
_COVER_HEALTH_THRESHOLD = 0.5         # seek cover below 50% max health
_COVER_STEP = 2.0                     # meters per tick toward cover

# Recon parameters
_RECON_SPEED_FACTOR = 0.5             # hostile moves at 50% speed while reconning

# Suppression parameters
_SUPPRESS_COOLDOWN_FACTOR = 0.5       # hostile fires at 50% cooldown while suppressing

# Retreating under fire parameters
_RETREAT_ZIGZAG_AMPLITUDE = 1.0       # lateral zigzag amplitude (meters)
_RETREAT_SPEED_FACTOR = 1.1           # slight speed boost when retreating to cover


class HostileBehavior:
    """Hostile kid combat AI with tactical layers. Stateful."""

    # Sensor detection speed boost factor (20% faster when detected)
    DETECTED_SPEED_BOOST = 1.2
    # Detected hostiles use wider flank step (doubled)
    DETECTED_FLANK_STEP = _FLANK_STEP * 2.0

    def __init__(self, combat_system: CombatSystem, engine: object | None = None) -> None:
        self._combat = combat_system
        self._engine = engine
        self._last_dodge: dict[str, float] = {}
        self._last_flank: dict[str, float] = {}
        self._obstacles: BuildingObstacles | None = None
        self._group_rush_ids: set[str] = set()
        self._base_speeds: dict[str, float] = {}
        self._recon_ids: set[str] = set()
        self._recon_base_speeds: dict[str, float] = {}
        self._suppress_ids: set[str] = set()
        self._suppress_base_cooldowns: dict[str, float] = {}
        self._detected_ids: set[str] = set()
        self._detected_base_speeds: dict[str, float] = {}
        # Pursuit-evasion system (set by coordinator when engine provides it)
        self._pursuit: PursuitSystem | None = None
        self._map_bounds: float = 200.0
        # Unit-to-unit tactical communication system (optional)
        self._comms: UnitComms | None = None
        # Track which enemies each hostile has already reported (first-contact dedup)
        self._contacted_enemies: dict[str, set[str]] = {}

    def set_obstacles(self, obstacles: BuildingObstacles) -> None:
        """Set building obstacles for cover-seeking behavior."""
        self._obstacles = obstacles

    def set_pursuit(self, pursuit: PursuitSystem, map_bounds: float = 200.0) -> None:
        """Set the pursuit-evasion system for flee behaviors."""
        self._pursuit = pursuit
        self._map_bounds = map_bounds

    def set_comms(self, comms: UnitComms) -> None:
        """Set the unit-to-unit communication system."""
        self._comms = comms

    def set_terrain(self, terrain: object) -> None:
        """Set terrain map for terrain-aware speed modifiers."""
        self._terrain = terrain

    def tick(
        self,
        kid: SimulationTarget,
        friendlies: dict[str, SimulationTarget],
    ) -> None:
        """Run hostile kid behavior for a single unit."""
        # Spawning hostiles do nothing (brief invulnerability)
        if kid.fsm_state == "spawning":
            self._restore_recon_speed(kid)
            self._restore_suppress_cooldown(kid)
            return
        # Fleeing hostiles: apply pursuit-evasion behaviors + emit retreat signal
        if kid.fsm_state == "fleeing":
            self._emit_retreat(kid)
            self._restore_recon_speed(kid)
            self._restore_suppress_cooldown(kid)
            if self._pursuit is not None:
                self._pursuit.apply_flee_speed_boost(kid)
                self._pursuit.start_flee_timer(kid)
                self._pursuit.apply_zigzag(kid)
                # Escape route: update waypoint toward safest edge
                defender_positions = [
                    f.position for f in friendlies.values()
                ]
                escape_dir = self._pursuit.find_escape_route(
                    kid.position, kid.heading, kid.speed,
                    defender_positions, self._map_bounds,
                )
                # Set waypoint toward the edge in escape direction
                edge_x = kid.position[0] + escape_dir[0] * self._map_bounds
                edge_y = kid.position[1] + escape_dir[1] * self._map_bounds
                # Clamp to map bounds
                edge_x = max(-self._map_bounds, min(self._map_bounds, edge_x))
                edge_y = max(-self._map_bounds, min(self._map_bounds, edge_y))
                kid.waypoints = [(edge_x, edge_y)]
                kid._waypoint_index = 0
            return

        # Morale check: broken units (< 0.1) flee, skip all combat
        if kid.morale < 0.1:
            self._restore_recon_speed(kid)
            self._restore_suppress_cooldown(kid)
            return

        # Morale check: suppressed units (< 0.3) skip attack, only dodge
        morale_suppressed = kid.morale < 0.3

        # Apply state-specific modifiers
        self._apply_recon_speed(kid)
        self._apply_suppress_cooldown(kid)
        self.apply_sensor_awareness(kid)

        if not morale_suppressed:
            target = nearest_in_range(kid, friendlies)
            if target is not None:
                # Emit contact signal on first sighting of this enemy
                self._emit_contact(kid, target)

                # Count enemies in weapon range for distress check
                enemies_in_range = sum(
                    1 for f in friendlies.values()
                    if math.hypot(
                        f.position[0] - kid.position[0],
                        f.position[1] - kid.position[1],
                    ) <= kid.weapon_range
                )
                if enemies_in_range >= 2 and kid.fsm_state == "engaging":
                    self._emit_distress(kid)

                # Fire at nearest defender (only when in combat states)
                if kid.fsm_state in (None, "advancing", "flanking", "engaging",
                                      "suppressing", "retreating_under_fire"):
                    # Check degradation before firing
                    apply_degradation(kid)
                    effective_cd = get_effective_cooldown(kid)
                    now = time.time()
                    if (now - kid.last_fired) >= effective_cd:
                        if can_fire_degraded(kid):
                            self._combat.fire(kid, target)
                        else:
                            self._combat._event_bus.publish("weapon_jam", {
                                "target_id": kid.target_id,
                                "target_name": kid.name,
                                "degradation": kid.degradation,
                            })

        # Retreating under fire: zigzag toward cover while still firing
        if kid.fsm_state == "retreating_under_fire":
            self._retreat_under_fire(kid, friendlies)
            return

        # Reconning: no additional movement behaviors (cautious scouting)
        if kid.fsm_state == "reconning":
            return

        # Morale suppressed: skip offensive behaviors, only dodge
        if morale_suppressed:
            self._dodge(kid)
            return

        # 0. Building flee: damaged hostiles flee to nearest building door
        if self._flee_to_building(kid):
            return

        # 1. Cover-seeking: damaged hostiles move toward nearest building edge
        if self._seek_cover(kid):
            return

        # 2. Flanking: offset approach when a stationary turret is ahead
        if self._try_flank(kid, friendlies):
            return

        # 3. Dodge: periodic random perpendicular offset
        self._dodge(kid)

    def _dodge(self, kid: SimulationTarget) -> None:
        """Apply periodic random perpendicular dodge offset."""
        now = time.time()
        last_dodge = self._last_dodge.get(kid.target_id, 0.0)
        # Group rush reduces dodge frequency
        if kid.target_id in self._group_rush_ids:
            dodge_interval = random.uniform(*_GROUP_RUSH_DODGE_INTERVAL)
        else:
            dodge_interval = random.uniform(2.0, 4.0)
        if now - last_dodge > dodge_interval:
            self._last_dodge[kid.target_id] = now
            offset = random.uniform(-1.5, 1.5)
            heading_rad = math.radians(kid.heading)
            kid.position = (
                kid.position[0] + math.cos(heading_rad) * offset,
                kid.position[1] - math.sin(heading_rad) * offset,
            )

    def check_group_rush(
        self,
        hostiles: dict[str, SimulationTarget],
    ) -> None:
        """Detect groups of 3+ hostiles within 30m and apply rush boost.

        Hostiles in a rush get +20% speed. When they leave the group
        (spread out or eliminated), their speed is restored.
        """
        hostile_list = list(hostiles.values())
        new_rush_ids: set[str] = set()

        for i, h1 in enumerate(hostile_list):
            nearby = 1  # count self
            for j, h2 in enumerate(hostile_list):
                if i == j:
                    continue
                dx = h1.position[0] - h2.position[0]
                dy = h1.position[1] - h2.position[1]
                if math.hypot(dx, dy) <= _GROUP_RUSH_RADIUS:
                    nearby += 1
            if nearby >= _GROUP_RUSH_MIN_COUNT:
                new_rush_ids.add(h1.target_id)

        # Apply speed boost to newly rushing hostiles
        for tid in new_rush_ids:
            if tid not in self._group_rush_ids:
                h = hostiles.get(tid)
                if h is not None:
                    self._base_speeds[tid] = h.speed
                    h.speed = h.speed * _GROUP_RUSH_SPEED_BOOST

        # Remove speed boost from hostiles that left the rush
        for tid in self._group_rush_ids - new_rush_ids:
            h = hostiles.get(tid)
            if h is not None and tid in self._base_speeds:
                h.speed = self._base_speeds.pop(tid)

        self._group_rush_ids = new_rush_ids

    def clear_state(self) -> None:
        """Reset all dodge timers and tactical state (for game reset)."""
        self._last_dodge.clear()
        self._last_flank.clear()
        self._group_rush_ids.clear()
        self._base_speeds.clear()
        self._recon_ids.clear()
        self._recon_base_speeds.clear()
        self._suppress_ids.clear()
        self._suppress_base_cooldowns.clear()
        self._detected_ids.clear()
        self._detected_base_speeds.clear()
        self._contacted_enemies.clear()
        if self._pursuit is not None:
            self._pursuit.clear()
        if self._comms is not None:
            self._comms.clear()

    # -- Unit-to-unit communication helpers ------------------------------------

    def _emit_distress(self, kid: SimulationTarget) -> None:
        """Emit distress signal if comms available."""
        if self._comms is not None:
            self._comms.emit_distress(kid.target_id, kid.position, kid.alliance)

    def _emit_contact(self, kid: SimulationTarget, enemy: SimulationTarget) -> None:
        """Emit contact signal on first sighting of this enemy (deduped per hostile)."""
        if self._comms is None:
            return
        contacted = self._contacted_enemies.setdefault(kid.target_id, set())
        if enemy.target_id not in contacted:
            contacted.add(enemy.target_id)
            self._comms.emit_contact(
                kid.target_id, kid.position, kid.alliance,
                enemy_pos=enemy.position,
            )

    def _emit_retreat(self, kid: SimulationTarget) -> None:
        """Emit retreat signal if comms available."""
        if self._comms is not None:
            self._comms.emit_retreat(kid.target_id, kid.position, kid.alliance)

    # -- Hostile tactical behaviors -------------------------------------------

    def apply_sensor_awareness(self, kid: SimulationTarget) -> None:
        """Apply +20% speed boost to a sensor-detected hostile."""
        tid = kid.target_id
        if kid.detected:
            if tid not in self._detected_ids:
                self._detected_base_speeds[tid] = kid.speed
                kid.speed = kid.speed * self.DETECTED_SPEED_BOOST
                self._detected_ids.add(tid)
        else:
            self.remove_sensor_awareness(kid)

    def remove_sensor_awareness(self, kid: SimulationTarget) -> None:
        """Remove sensor-detection speed boost and restore original speed."""
        tid = kid.target_id
        if tid in self._detected_ids:
            if tid in self._detected_base_speeds:
                kid.speed = self._detected_base_speeds.pop(tid)
            self._detected_ids.discard(tid)

    def _apply_recon_speed(self, kid: SimulationTarget) -> None:
        """Slow down a hostile that is in reconning state."""
        tid = kid.target_id
        if kid.fsm_state == "reconning":
            if tid not in self._recon_ids:
                self._recon_base_speeds[tid] = kid.speed
                kid.speed = kid.speed * _RECON_SPEED_FACTOR
                self._recon_ids.add(tid)
        else:
            self._restore_recon_speed(kid)

    def _restore_recon_speed(self, kid: SimulationTarget) -> None:
        """Restore speed for a hostile leaving recon state."""
        tid = kid.target_id
        if tid in self._recon_ids:
            if tid in self._recon_base_speeds:
                kid.speed = self._recon_base_speeds.pop(tid)
            self._recon_ids.discard(tid)

    def _apply_suppress_cooldown(self, kid: SimulationTarget) -> None:
        """Reduce weapon cooldown for a hostile in suppressing state."""
        tid = kid.target_id
        if kid.fsm_state == "suppressing":
            if tid not in self._suppress_ids:
                self._suppress_base_cooldowns[tid] = kid.weapon_cooldown
                kid.weapon_cooldown = kid.weapon_cooldown * _SUPPRESS_COOLDOWN_FACTOR
                self._suppress_ids.add(tid)
        else:
            self._restore_suppress_cooldown(kid)

    def _restore_suppress_cooldown(self, kid: SimulationTarget) -> None:
        """Restore weapon cooldown for a hostile leaving suppress state."""
        tid = kid.target_id
        if tid in self._suppress_ids:
            if tid in self._suppress_base_cooldowns:
                kid.weapon_cooldown = self._suppress_base_cooldowns.pop(tid)
            self._suppress_ids.discard(tid)

    def _retreat_under_fire(
        self,
        kid: SimulationTarget,
        friendlies: dict[str, SimulationTarget],
    ) -> None:
        """Zigzag retreat toward cover while still engaging enemies."""
        # Move toward cover if available
        if self._obstacles is not None and self._obstacles.polygons:
            best_point = None
            best_dist = float("inf")
            for poly in self._obstacles.polygons:
                n = len(poly)
                for i in range(n):
                    pt = self._nearest_point_on_segment(
                        kid.position[0], kid.position[1],
                        poly[i][0], poly[i][1],
                        poly[(i + 1) % n][0], poly[(i + 1) % n][1],
                    )
                    d = math.hypot(pt[0] - kid.position[0], pt[1] - kid.position[1])
                    if d < best_dist:
                        best_dist = d
                        best_point = pt

            if best_point is not None and best_dist >= 1.0:
                dx = best_point[0] - kid.position[0]
                dy = best_point[1] - kid.position[1]
                step = min(_COVER_STEP * _RETREAT_SPEED_FACTOR, best_dist)
                kid.position = (
                    kid.position[0] + (dx / best_dist) * step,
                    kid.position[1] + (dy / best_dist) * step,
                )

        # Add zigzag offset perpendicular to heading
        zigzag = random.uniform(-_RETREAT_ZIGZAG_AMPLITUDE, _RETREAT_ZIGZAG_AMPLITUDE)
        heading_rad = math.radians(kid.heading)
        kid.position = (
            kid.position[0] + math.cos(heading_rad) * zigzag,
            kid.position[1] - math.sin(heading_rad) * zigzag,
        )

    def _flee_to_building(self, kid: SimulationTarget) -> bool:
        """Make a damaged hostile flee to the nearest building door."""
        if kid.max_health <= 0:
            return False
        if kid.health / kid.max_health >= _COVER_HEALTH_THRESHOLD:
            return False
        if getattr(kid, '_fleeing_to_building', False):
            return True

        if self._engine is None:
            return False
        buildings = self._engine.get_buildings()
        if not buildings:
            return False

        best_door: tuple[float, float] | None = None
        best_dist = float('inf')
        for b in buildings:
            for d in b.doors:
                dx = d["position"][0] - kid.position[0]
                dy = d["position"][1] - kid.position[1]
                dist = math.hypot(dx, dy)
                if dist < best_dist:
                    best_dist = dist
                    best_door = d["position"]

        if best_door is None or best_dist >= 50.0:
            return False

        kid.waypoints = [best_door]
        kid._waypoint_index = 0
        kid._fleeing_to_building = True
        kid.speed = kid.speed * 1.3
        return True

    def _try_flank(
        self,
        kid: SimulationTarget,
        friendlies: dict[str, SimulationTarget],
    ) -> bool:
        """Apply lateral flanking offset when nearest enemy is a stationary turret."""
        now = time.time()
        last_flank = self._last_flank.get(kid.target_id, 0.0)
        if now - last_flank < random.uniform(*_FLANK_INTERVAL):
            return False

        best_target = None
        best_dist = 50.0
        for f in friendlies.values():
            td = _get_unit_type(f.asset_type)
            if td is None or td.category is not MovementCategory.STATIONARY:
                continue
            dx = f.position[0] - kid.position[0]
            dy = f.position[1] - kid.position[1]
            d = math.hypot(dx, dy)
            if d < best_dist:
                best_dist = d
                best_target = f

        if best_target is None:
            return False

        dx = best_target.position[0] - kid.position[0]
        dy = best_target.position[1] - kid.position[1]
        dist = math.hypot(dx, dy)
        if dist < 0.1:
            return False

        self._last_flank[kid.target_id] = now

        approach_angle = math.atan2(dx, dy)
        perp_angle = approach_angle + math.pi / 2
        if random.random() < 0.5:
            perp_angle = approach_angle - math.pi / 2

        step = self.DETECTED_FLANK_STEP if kid.detected else _FLANK_STEP

        kid.position = (
            kid.position[0] + math.sin(perp_angle) * step,
            kid.position[1] + math.cos(perp_angle) * step,
        )
        return True

    def _seek_cover(self, kid: SimulationTarget) -> bool:
        """Move a damaged hostile toward the nearest building edge for cover."""
        if self._obstacles is None or not self._obstacles.polygons:
            return False
        if kid.max_health <= 0:
            return False
        if kid.health / kid.max_health >= _COVER_HEALTH_THRESHOLD:
            return False

        best_point = None
        best_dist = float("inf")
        for poly in self._obstacles.polygons:
            n = len(poly)
            for i in range(n):
                pt = self._nearest_point_on_segment(
                    kid.position[0], kid.position[1],
                    poly[i][0], poly[i][1],
                    poly[(i + 1) % n][0], poly[(i + 1) % n][1],
                )
                d = math.hypot(pt[0] - kid.position[0], pt[1] - kid.position[1])
                if d < best_dist:
                    best_dist = d
                    best_point = pt

        if best_point is None or best_dist < 1.0:
            return False

        dx = best_point[0] - kid.position[0]
        dy = best_point[1] - kid.position[1]
        step = min(_COVER_STEP, best_dist)
        kid.position = (
            kid.position[0] + (dx / best_dist) * step,
            kid.position[1] + (dy / best_dist) * step,
        )
        return True

    @staticmethod
    def _nearest_point_on_segment(
        px: float, py: float,
        ax: float, ay: float,
        bx: float, by: float,
    ) -> tuple[float, float]:
        """Find the nearest point on segment AB to point P."""
        abx = bx - ax
        aby = by - ay
        ab_sq = abx * abx + aby * aby
        if ab_sq < 1e-10:
            return (ax, ay)
        t = ((px - ax) * abx + (py - ay) * aby) / ab_sq
        t = max(0.0, min(1.0, t))
        return (ax + t * abx, ay + t * aby)
