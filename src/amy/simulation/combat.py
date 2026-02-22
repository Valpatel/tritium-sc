"""CombatSystem — projectile flight, hit detection, and damage resolution.

Architecture
------------
CombatSystem manages the lifecycle of Projectile instances:

  1. ``fire()`` creates a Projectile if the source unit passes ``can_fire()``.
     The projectile starts at the source's position and flies toward the
     target's position at the time of firing.

  2. ``tick()`` advances each projectile toward its target_pos.  When the
     projectile enters the hit radius (1.5 units) of the *target* (tracked
     by ID, not by frozen position), damage is applied.  If the target is
     eliminated (health <= 0), a ``target_eliminated`` event is published
     and the interceptor's ``eliminations`` counter is incremented.

  3. Projectiles that fly past their target_pos by 3 units without hitting
     anything are marked as missed and removed.

Elimination streaks are tracked per source_id.  Consecutive neutralizations
within a single game session trigger escalating announcements (3=KILLING
SPREE, 5=RAMPAGE, 7=DOMINATING, 10=GODLIKE).  The streak counter resets
when the source is eliminated.

Events are published on the EventBus for the frontend and Amy's announcer:
  - ``projectile_fired``: new dart/rocket in the air
  - ``projectile_hit``: damage applied
  - ``target_eliminated``: health reached zero
  - ``elimination_streak``: milestone reached
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amy.comms.event_bus import EventBus
    from .target import SimulationTarget

# Hit detection radius — projectile is "close enough" to count as a hit
HIT_RADIUS = 1.5

# Miss distance — projectile has overshot target by this much
MISS_OVERSHOOT = 3.0

# Elimination streak thresholds and names
_STREAK_NAMES: list[tuple[int, str]] = [
    (10, "GODLIKE"),
    (7, "DOMINATING"),
    (5, "RAMPAGE"),
    (3, "ON A STREAK"),
]


@dataclass
class Projectile:
    """A single projectile in flight."""

    id: str
    source_id: str
    source_name: str
    target_id: str
    position: tuple[float, float]
    target_pos: tuple[float, float]
    speed: float = 25.0
    damage: float = 10.0
    projectile_type: str = "nerf_dart"  # nerf_dart, nerf_rocket, water_balloon
    created_at: float = field(default_factory=time.time)
    hit: bool = False
    missed: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "target_id": self.target_id,
            "position": {"x": self.position[0], "y": self.position[1]},
            "target_pos": {"x": self.target_pos[0], "y": self.target_pos[1]},
            "speed": self.speed,
            "damage": self.damage,
            "projectile_type": self.projectile_type,
            "hit": self.hit,
            "missed": self.missed,
        }


class CombatSystem:
    """Manages projectiles, hit detection, and damage resolution."""

    def __init__(self, event_bus: EventBus) -> None:
        self._projectiles: dict[str, Projectile] = {}
        self._event_bus = event_bus
        self._elimination_streaks: dict[str, int] = {}

    @property
    def projectile_count(self) -> int:
        return len(self._projectiles)

    def fire(
        self,
        source: SimulationTarget,
        target: SimulationTarget,
        projectile_type: str = "nerf_dart",
    ) -> Projectile | None:
        """Fire a projectile from *source* at *target*.

        Returns the Projectile if fired, None if source cannot fire.
        Updates source.last_fired timestamp.
        """
        if not source.can_fire():
            return None

        # Check range
        dx = target.position[0] - source.position[0]
        dy = target.position[1] - source.position[1]
        dist = math.hypot(dx, dy)
        if dist > source.weapon_range:
            return None

        source.last_fired = time.time()

        proj = Projectile(
            id=str(uuid.uuid4()),
            source_id=source.target_id,
            source_name=source.name,
            target_id=target.target_id,
            position=source.position,
            target_pos=target.position,
            speed=25.0,
            damage=source.weapon_damage,
            projectile_type=projectile_type,
        )
        self._projectiles[proj.id] = proj

        self._event_bus.publish("projectile_fired", {
            "id": proj.id,
            "source_id": source.target_id,
            "source_name": source.name,
            "source_pos": {"x": source.position[0], "y": source.position[1]},
            "target_pos": {"x": target.position[0], "y": target.position[1]},
            "projectile_type": projectile_type,
        })
        return proj

    def tick(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """Advance all projectiles, resolve hits and misses."""
        to_remove: list[str] = []

        for proj in self._projectiles.values():
            if proj.hit or proj.missed:
                to_remove.append(proj.id)
                continue

            # Move projectile toward target_pos
            dx = proj.target_pos[0] - proj.position[0]
            dy = proj.target_pos[1] - proj.position[1]
            dist_to_target_pos = math.hypot(dx, dy)

            if dist_to_target_pos > 0:
                step = proj.speed * dt
                if step >= dist_to_target_pos:
                    proj.position = proj.target_pos
                else:
                    proj.position = (
                        proj.position[0] + (dx / dist_to_target_pos) * step,
                        proj.position[1] + (dy / dist_to_target_pos) * step,
                    )

            # Check hit: is the projectile within HIT_RADIUS of the actual target?
            target = targets.get(proj.target_id)
            if target is not None and target.status in ("active", "idle", "stationary"):
                tdx = proj.position[0] - target.position[0]
                tdy = proj.position[1] - target.position[1]
                dist_to_target = math.hypot(tdx, tdy)

                if dist_to_target <= HIT_RADIUS:
                    proj.hit = True
                    eliminated = target.apply_damage(proj.damage)
                    self._event_bus.publish("projectile_hit", {
                        "projectile_id": proj.id,
                        "target_id": target.target_id,
                        "target_name": target.name,
                        "damage": proj.damage,
                        "remaining_health": target.health,
                        "source_id": proj.source_id,
                    })

                    if eliminated:
                        # Increment interceptor stats
                        interceptor = targets.get(proj.source_id)
                        interceptor_name = proj.source_name
                        if interceptor is not None:
                            interceptor.kills += 1
                            interceptor_name = interceptor.name

                        self._event_bus.publish("target_eliminated", {
                            "target_id": target.target_id,
                            "target_name": target.name,
                            "interceptor_id": proj.source_id,
                            "interceptor_name": interceptor_name,
                            "position": {"x": target.position[0], "y": target.position[1]},
                            "method": proj.projectile_type,
                        })

                        # Elimination streak tracking
                        self._elimination_streaks[proj.source_id] = (
                            self._elimination_streaks.get(proj.source_id, 0) + 1
                        )
                        streak = self._elimination_streaks[proj.source_id]
                        streak_name = self._get_streak_name(streak)
                        if streak_name:
                            self._event_bus.publish("elimination_streak", {
                                "interceptor_id": proj.source_id,
                                "interceptor_name": interceptor_name,
                                "streak": streak,
                                "streak_name": streak_name,
                            })

                    to_remove.append(proj.id)
                    continue

            # Check miss: projectile has overshot its target_pos
            # (distance from origin to current pos > distance from origin to target_pos + overshoot)
            dx_from_tpos = proj.position[0] - proj.target_pos[0]
            dy_from_tpos = proj.position[1] - proj.target_pos[1]
            overshoot_dist = math.hypot(dx_from_tpos, dy_from_tpos)
            if dist_to_target_pos < 0.1 or overshoot_dist > MISS_OVERSHOOT:
                proj.missed = True
                to_remove.append(proj.id)

        for pid in to_remove:
            self._projectiles.pop(pid, None)

    def reset_streaks(self) -> None:
        """Reset all elimination streak counters."""
        self._elimination_streaks.clear()

    def reset_streak(self, target_id: str) -> None:
        """Reset elimination streak for a specific unit (e.g. when eliminated)."""
        self._elimination_streaks.pop(target_id, None)

    def get_active_projectiles(self) -> list[dict]:
        """Return serializable list of active projectiles for frontend rendering."""
        return [p.to_dict() for p in self._projectiles.values()
                if not p.hit and not p.missed]

    def clear(self) -> None:
        """Remove all projectiles."""
        self._projectiles.clear()

    @staticmethod
    def _get_streak_name(streak: int) -> str | None:
        """Return the streak announcement name, or None if not a milestone."""
        for threshold, name in _STREAK_NAMES:
            if streak == threshold:
                return name
        return None
