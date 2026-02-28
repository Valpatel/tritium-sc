"""MobManager — riot and mob formation behavior for NPCs.

When an NPC radicalizes, nearby aggressive NPCs can be recruited into a mob.
The mob advances toward a target using loose formation, with behavior
escalating based on mob size.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class RiotLevel(IntEnum):
    """Escalation levels for mob behavior."""
    NONE = 0        # No riot (solo or pair)
    SHOUTING = 1    # 3-5 members: shouting, throwing objects, slow advance
    AGGRESSIVE = 2  # 6-9 members: aggressive advance, overwhelm defenses
    ASSAULT = 3     # 10+: full assault, coordinate flanking


# Minimum aggression trait to be recruited
_MIN_RECRUIT_AGGRESSION = 0.5

# FSM states that allow mob recruitment
_RECRUITABLE_STATES = {"observing", "curious", "walking"}

# Minimum mob size before scattering
_MIN_MOB_SIZE = 3

# Recruitment radius (meters)
_DEFAULT_RECRUIT_RADIUS = 50.0


@dataclass
class MobFormation:
    """Tracks a group of radicalized NPCs acting together."""

    leader_id: str
    rally_point: tuple[float, float]
    member_ids: set[str] = field(default_factory=set)
    target_point: Optional[tuple[float, float]] = None
    formation_time: float = 0.0
    aggression_level: float = 0.5

    @property
    def size(self) -> int:
        """Total mob size (leader + members)."""
        return 1 + len(self.member_ids)

    @property
    def riot_level(self) -> RiotLevel:
        """Current riot level based on mob size."""
        s = self.size
        if s < 3:
            return RiotLevel.NONE
        elif s <= 5:
            return RiotLevel.SHOUTING
        elif s <= 9:
            return RiotLevel.AGGRESSIVE
        else:
            return RiotLevel.ASSAULT

    @property
    def should_scatter(self) -> bool:
        """Whether the mob should disband (too few members)."""
        return self.size < _MIN_MOB_SIZE

    @property
    def all_ids(self) -> set[str]:
        """All NPC IDs in the mob (leader + members)."""
        return {self.leader_id} | self.member_ids


class MobManager:
    """Manages mob formation, recruitment, and lifecycle."""

    def __init__(self) -> None:
        self._mobs: list[MobFormation] = []
        self._npc_to_mob: dict[str, MobFormation] = {}

    @property
    def mob_count(self) -> int:
        return len(self._mobs)

    def form_mob(
        self,
        leader_id: str,
        rally_point: tuple[float, float],
        aggression_level: float = 0.5,
    ) -> MobFormation:
        """Create a new mob with a leader."""
        mob = MobFormation(
            leader_id=leader_id,
            rally_point=rally_point,
            aggression_level=aggression_level,
        )
        self._mobs.append(mob)
        self._npc_to_mob[leader_id] = mob
        return mob

    def recruit(
        self,
        mob: MobFormation,
        nearby_npcs: list[dict],
        radius: float = _DEFAULT_RECRUIT_RADIUS,
    ) -> set[str]:
        """Recruit eligible nearby NPCs into a mob.

        Args:
            mob: the mob to recruit into
            nearby_npcs: list of NPC info dicts with keys:
                id, x, y, fsm_state, alliance, personality
            radius: max distance from rally point for recruitment

        Returns:
            Set of recruited NPC IDs.
        """
        recruited = set()

        # Refresh mapping for any manually-added members
        for m in self._mobs:
            for mid in m.all_ids:
                if mid not in self._npc_to_mob:
                    self._npc_to_mob[mid] = m

        for npc in nearby_npcs:
            npc_id = npc["id"]

            # Skip if already in any mob
            if npc_id in self._npc_to_mob:
                continue

            # Skip hostiles (already radicalized)
            if npc.get("alliance", "neutral") == "hostile":
                continue

            # Check distance to rally point
            dist = math.hypot(
                npc["x"] - mob.rally_point[0],
                npc["y"] - mob.rally_point[1],
            )
            if dist > radius:
                continue

            # Check aggression
            personality = npc.get("personality")
            if personality is None:
                continue
            aggression = getattr(personality, "aggression", 0.0)
            if aggression < _MIN_RECRUIT_AGGRESSION:
                continue

            # Check FSM state
            fsm_state = npc.get("fsm_state", "")
            if fsm_state not in _RECRUITABLE_STATES:
                continue

            # Recruit!
            mob.member_ids.add(npc_id)
            self._npc_to_mob[npc_id] = mob
            recruited.add(npc_id)

        return recruited

    def set_target(
        self,
        mob: MobFormation,
        target_point: tuple[float, float],
    ) -> None:
        """Direct a mob toward a target."""
        mob.target_point = target_point

    def disband_mob(self, mob: MobFormation) -> set[str]:
        """Disband a mob, releasing all members.

        Returns set of all NPC IDs that were in the mob.
        """
        released = mob.all_ids
        for npc_id in released:
            self._npc_to_mob.pop(npc_id, None)
        self._mobs.remove(mob)
        return released

    def get_mob_for_npc(self, npc_id: str) -> MobFormation | None:
        """Find which mob an NPC belongs to."""
        mob = self._npc_to_mob.get(npc_id)
        if mob is not None:
            return mob
        # Scan mobs for manually-added members
        for m in self._mobs:
            if npc_id in m.all_ids:
                self._npc_to_mob[npc_id] = m
                return m
        return None

    def tick(self, dt: float) -> set[str]:
        """Per-tick update: disband mobs that are too small.

        Returns set of NPC IDs from disbanded mobs (they should scatter).
        """
        scattered = set()
        to_disband = [m for m in self._mobs if m.should_scatter]
        for mob in to_disband:
            released = self.disband_mob(mob)
            scattered.update(released)
        return scattered

    def advance_waypoints(
        self,
        mob: MobFormation,
        npc_id: str,
        npc_pos: tuple[float, float],
    ) -> list[tuple[float, float]] | None:
        """Generate advance waypoints for a mob member toward target.

        Members advance in loose formation with slight randomness to
        simulate a crowd, not a military unit.
        """
        if mob.target_point is None:
            # Rally at rally point
            return [npc_pos, mob.rally_point]

        target = mob.target_point

        # Add randomness for crowd effect (not a perfect line)
        spread = 5.0  # meters of random offset
        offset_x = random.uniform(-spread, spread)
        offset_y = random.uniform(-spread, spread)

        approach_target = (
            target[0] + offset_x,
            target[1] + offset_y,
        )

        # For SHOUTING level, stop 20m from target
        # For AGGRESSIVE, stop 10m
        # For ASSAULT, go right to target
        stop_distance = {
            RiotLevel.NONE: 30.0,
            RiotLevel.SHOUTING: 20.0,
            RiotLevel.AGGRESSIVE: 10.0,
            RiotLevel.ASSAULT: 3.0,
        }.get(mob.riot_level, 20.0)

        dx = approach_target[0] - npc_pos[0]
        dy = approach_target[1] - npc_pos[1]
        dist = math.hypot(dx, dy)

        if dist < stop_distance:
            # Already close enough
            return [npc_pos, approach_target]

        # Move toward target but stop at stop_distance
        ratio = max(0, (dist - stop_distance) / dist)
        intermediate = (
            npc_pos[0] + dx * ratio,
            npc_pos[1] + dy * ratio,
        )

        return [npc_pos, intermediate, approach_target]
