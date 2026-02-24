"""SquadManager — coordinated hostile unit formations with leader-follower dynamics.

Architecture
------------
SquadManager auto-detects clusters of hostile units and organizes them
into squads with formation-keeping behavior.  Each squad has a leader
(highest health), a formation type, and a shared target for focus fire.

Leader-follower hierarchy:
  - Each squad has an optional officer_rank (0=none, 1=sergeant, 2=lieutenant).
  - Cohesion (0.0-1.0) measures squad discipline; drops on leader elimination.
  - Leaders issue tactical orders: advance, hold, flank_left, flank_right, retreat.
  - Followers respond to orders by adjusting movement (hold=stop, flank=lateral
    offset, retreat=flee toward spawn edge).
  - When a leader is eliminated: cohesion drops to 0.3, retreat order issued for
    all members, morale penalty applied.
  - New leader is promoted by proximity to the old leader's position.
  - Cohesion slowly recovers (+0.01/s) when a new leader is active.
  - Orders expire after ORDER_TIMEOUT_S seconds (10s default).

Squad lifecycle:
  1. Auto-formation: When 2+ active hostiles are within SQUAD_RADIUS (15m)
     of each other, they are grouped into a squad.
  2. Tick: Each tick, the manager re-evaluates squads — updates leader
     (highest health), computes formation offsets, selects shared target,
     and nudges members toward their formation positions.
  3. Dissolution: Squads dissolve when <2 active members remain (eliminated
     or scattered beyond SQUAD_RADIUS).

Formation types:
  - ``wedge``: Leader at front, followers at 45 degrees behind, 4m spacing.
    Good for advancing on a position.
  - ``line``: Members side by side, 4m spacing, no depth offset.
    Good for wide-approach sweeps.
  - ``column``: Members in single file behind leader, 4m spacing.
  - ``circle``: Followers distributed evenly around leader at 4m radius.
    Good for defensive perimeters.

Integration:
  SquadManager.tick() is called from SimulationEngine._tick_loop during
  active game mode, after behaviors.tick() so that squad formation offsets
  layer on top of individual behavior decisions.
"""

from __future__ import annotations

import math
import random
import time as _time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.units import get_type as _get_unit_type
from engine.units.base import MovementCategory

if TYPE_CHECKING:
    from .target import SimulationTarget

# Squad auto-formation radius (meters)
SQUAD_RADIUS = 15.0

# Formation spacing (meters between members)
FORMATION_SPACING = 4.0

# How fast members converge toward formation position (fraction per tick)
_FORMATION_CONVERGENCE = 0.15

# Leader-follower constants
ORDER_TIMEOUT_S = 10.0            # Orders expire after this many seconds
LEADER_SAFE_RANGE = 30.0          # No defenders within this range = safe to advance
RETREAT_HEALTH_THRESHOLD = 0.3    # Average squad health below this triggers retreat
COHESION_DROP_ON_LEADER_DEATH = 0.3   # Cohesion drops to this on leader elimination
COHESION_RECOVERY_RATE = 0.01     # Cohesion recovery per second when leader is active
FLANK_OFFSET_STEP = 2.0           # Meters per tick of lateral flank offset


@dataclass
class Squad:
    """A coordinated group of hostile units with command hierarchy."""

    squad_id: str
    member_ids: list[str] = field(default_factory=list)
    leader_id: str | None = None
    formation: str = "wedge"  # "wedge", "line", "column", or "circle"
    shared_target_id: str | None = None

    # Leader-follower hierarchy fields
    officer_rank: int = 0           # 0 = no officer, 1 = sergeant, 2 = lieutenant
    cohesion: float = 1.0           # 0.0-1.0, drops when leader killed
    last_order: str | None = None   # "advance", "hold", "flank_left", "flank_right", "retreat"
    order_timestamp: float = 0.0    # monotonic time when last order was issued

    def get_formation_offsets(self) -> dict[str, tuple[float, float]]:
        """Return per-member (dx, dy) offsets relative to the leader.

        Offsets are in local coordinates: +x = right, +y = forward (toward enemy).
        The leader is always at (0, 0).

        Wedge formation (default):
          Leader at front (0, 0).
          Followers alternate left/right, 45 degrees behind leader.
          Spacing: FORMATION_SPACING meters from leader along the 45-degree line.

        Line formation:
          All members on the same horizontal line (y=0).
          Spread evenly left/right of center.
        """
        offsets: dict[str, tuple[float, float]] = {}

        if not self.member_ids:
            return offsets

        # Leader always at origin
        if self.leader_id is not None:
            offsets[self.leader_id] = (0.0, 0.0)

        followers = [m for m in self.member_ids if m != self.leader_id]

        if self.formation == "wedge":
            # 45-degree wedge: each follower is FORMATION_SPACING meters
            # from leader along a 45-degree line behind and to the side.
            # Component at 45 deg: cos(45) = sin(45) = sqrt(2)/2
            _cos45 = math.sqrt(2.0) / 2.0
            for i, tid in enumerate(followers):
                rank = i + 1
                # Alternate left (-x) and right (+x)
                side = -1 if rank % 2 == 1 else 1
                row = (rank + 1) // 2  # row 1, 1, 2, 2, 3, 3...
                dist = FORMATION_SPACING * row
                dx = side * dist * _cos45
                dy = -dist * _cos45
                offsets[tid] = (dx, dy)

        elif self.formation == "line":
            n = len(followers)
            for i, tid in enumerate(followers):
                rank = i + 1
                side = -1 if rank % 2 == 1 else 1
                col = (rank + 1) // 2
                dx = side * FORMATION_SPACING * col
                dy = 0.0
                offsets[tid] = (dx, dy)

        elif self.formation == "column":
            # Single file behind the leader, FORMATION_SPACING apart
            for i, tid in enumerate(followers):
                rank = i + 1
                offsets[tid] = (0.0, -FORMATION_SPACING * rank)

        elif self.formation == "circle":
            # Followers distributed evenly around a circle of radius FORMATION_SPACING
            n = len(followers)
            if n > 0:
                angle_step = 2.0 * math.pi / n
                for i, tid in enumerate(followers):
                    angle = angle_step * i
                    dx = FORMATION_SPACING * math.cos(angle)
                    dy = FORMATION_SPACING * math.sin(angle)
                    offsets[tid] = (dx, dy)

        return offsets


class SquadManager:
    """Manages hostile unit squads with formation-keeping behavior."""

    def __init__(self) -> None:
        self._squads: dict[str, Squad] = {}
        # Track original speeds for hold-order restoration
        self._hold_base_speeds: dict[str, float] = {}

    def get_squad(self, squad_id: str | None) -> Squad | None:
        """Return a squad by ID, or None if not found."""
        if squad_id is None:
            return None
        return self._squads.get(squad_id)

    def clear(self, targets: dict[str, SimulationTarget] | None = None) -> None:
        """Dissolve all squads and clear squad_id on targets."""
        # Restore held speeds before clearing
        if targets is not None:
            for tid, speed in self._hold_base_speeds.items():
                t = targets.get(tid)
                if t is not None:
                    t.speed = speed
            for t in targets.values():
                t.squad_id = None
        self._hold_base_speeds.clear()
        self._squads.clear()

    # -- Leader-follower order system ----------------------------------------

    def issue_order(self, squad_id: str, order: str) -> None:
        """Leader issues a tactical order to the squad.

        Args:
            squad_id: ID of the squad to order.
            order: One of "advance", "hold", "flank_left", "flank_right", "retreat".
        """
        squad = self.get_squad(squad_id)
        if squad is None:
            return
        squad.last_order = order
        squad.order_timestamp = _time.monotonic()

    def on_leader_eliminated(self, squad_id: str) -> None:
        """Cascade effects when a squad leader is eliminated.

        - Cohesion drops to COHESION_DROP_ON_LEADER_DEATH (0.3).
        - All members receive a "retreat" order.
        - (Morale penalty is handled separately by MoraleSystem.)
        """
        squad = self.get_squad(squad_id)
        if squad is None:
            return
        squad.cohesion = COHESION_DROP_ON_LEADER_DEATH
        squad.last_order = "retreat"
        squad.order_timestamp = _time.monotonic()

    def promote_new_leader(
        self,
        squad_id: str,
        old_leader_pos: tuple[float, float],
        targets: dict[str, SimulationTarget],
    ) -> None:
        """Promote the member nearest to the old leader's position as new leader.

        Args:
            squad_id: ID of the squad needing a new leader.
            old_leader_pos: Position of the eliminated leader.
            targets: Current targets dict for position lookup.
        """
        squad = self.get_squad(squad_id)
        if squad is None:
            return

        best_id: str | None = None
        best_dist = float("inf")

        for mid in squad.member_ids:
            if mid == squad.leader_id:
                continue  # skip old leader (might still be in member list)
            t = targets.get(mid)
            if t is None or t.status != "active":
                continue
            dx = t.position[0] - old_leader_pos[0]
            dy = t.position[1] - old_leader_pos[1]
            d = math.hypot(dx, dy)
            if d < best_dist:
                best_dist = d
                best_id = mid

        if best_id is not None:
            squad.leader_id = best_id

    def is_leader(self, target_id: str) -> bool:
        """Check if a target is currently a squad leader."""
        for squad in self._squads.values():
            if squad.leader_id == target_id:
                return True
        return False

    def tick_orders(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """Tick the order system: expire old orders, issue leader AI orders, apply follower responses.

        Called each engine tick (10 Hz).  Steps:
          1. Expire orders older than ORDER_TIMEOUT_S.
          2. Run leader AI to issue new orders based on tactical situation.
          3. Apply follower responses (hold=stop, flank=lateral, retreat=flee).
          4. Recover cohesion when a leader is active.
        """
        now = _time.monotonic()

        for squad in self._squads.values():
            # Step 1: Expire stale orders
            if squad.last_order is not None and squad.order_timestamp > 0:
                elapsed = now - squad.order_timestamp
                if elapsed >= ORDER_TIMEOUT_S:
                    # Order expired -- leader AI will issue a new one below
                    squad.last_order = None

            # Step 2: Leader AI issues orders if no active order
            if squad.last_order is None and squad.leader_id is not None:
                self._leader_ai_decide(squad, targets)

            # Step 3: Apply follower responses
            self._apply_order_to_followers(squad, targets)

            # Step 4: Cohesion recovery (slow when leader is active)
            if squad.leader_id is not None and squad.cohesion < 1.0:
                leader = targets.get(squad.leader_id)
                if leader is not None and leader.status == "active":
                    squad.cohesion = min(1.0, squad.cohesion + COHESION_RECOVERY_RATE * dt)

    def _leader_ai_decide(
        self,
        squad: Squad,
        targets: dict[str, SimulationTarget],
    ) -> None:
        """Leader AI: decide what order to issue based on tactical situation.

        Decision priority:
          1. Retreat when squad average health < 30%
          2. Flank when nearest enemy is a stationary turret within 30m
          3. Advance when no defenders within 30m (safe)
          4. Advance (default)
        """
        leader = targets.get(squad.leader_id) if squad.leader_id else None
        if leader is None:
            return

        active_members = [
            targets[mid] for mid in squad.member_ids
            if mid in targets and targets[mid].status == "active"
        ]
        if not active_members:
            return

        # Check average health
        avg_health = sum(
            m.health / m.max_health if m.max_health > 0 else 1.0
            for m in active_members
        ) / len(active_members)

        if avg_health < RETREAT_HEALTH_THRESHOLD:
            self.issue_order(squad.squad_id, "retreat")
            return

        # Check for nearby defenders
        friendlies = {
            tid: t for tid, t in targets.items()
            if t.alliance == "friendly"
            and t.status in ("active", "idle", "stationary")
            and t.is_combatant
        }

        nearest_defender = None
        nearest_dist = float("inf")
        for fid, f in friendlies.items():
            dx = f.position[0] - leader.position[0]
            dy = f.position[1] - leader.position[1]
            d = math.hypot(dx, dy)
            if d < nearest_dist:
                nearest_dist = d
                nearest_defender = f

        # If no defenders within LEADER_SAFE_RANGE, advance
        if nearest_dist > LEADER_SAFE_RANGE:
            self.issue_order(squad.squad_id, "advance")
            return

        # If nearest defender is stationary (turret), flank
        if nearest_defender is not None:
            td = _get_unit_type(nearest_defender.asset_type)
            if td is not None and td.category is MovementCategory.STATIONARY:
                flank_dir = random.choice(["flank_left", "flank_right"])
                self.issue_order(squad.squad_id, flank_dir)
                return

        # Default: advance
        self.issue_order(squad.squad_id, "advance")

    def _apply_order_to_followers(
        self,
        squad: Squad,
        targets: dict[str, SimulationTarget],
    ) -> None:
        """Apply the current squad order to all follower members.

        Leader is not affected by orders (they issue them).
        """
        order = squad.last_order
        if order is None:
            # No order: restore any held speeds
            self._restore_held_speeds(squad, targets)
            return

        for mid in squad.member_ids:
            if mid == squad.leader_id:
                continue
            t = targets.get(mid)
            if t is None or t.status != "active":
                continue

            if order == "advance":
                # Normal movement -- restore speed if held
                self._restore_speed(mid, t)

            elif order == "hold":
                # Stop movement
                if mid not in self._hold_base_speeds:
                    self._hold_base_speeds[mid] = t.speed
                t.speed = 0.0

            elif order in ("flank_left", "flank_right"):
                # Restore speed first (in case of hold -> flank transition)
                self._restore_speed(mid, t)
                # Apply lateral offset perpendicular to heading
                heading_rad = math.radians(t.heading)
                # Perpendicular direction: heading + 90 (left) or heading - 90 (right)
                sign = -1.0 if order == "flank_left" else 1.0
                step = FLANK_OFFSET_STEP * 0.1  # Scale by approx dt
                t.position = (
                    t.position[0] + math.sin(heading_rad + sign * math.pi / 2) * step,
                    t.position[1] + math.cos(heading_rad + sign * math.pi / 2) * step,
                )

            elif order == "retreat":
                # Restore speed first
                self._restore_speed(mid, t)
                # Set waypoint away from map center (toward spawn edge)
                dist_from_center = math.hypot(t.position[0], t.position[1])
                if dist_from_center < 0.1:
                    # At center, flee in heading direction
                    heading_rad = math.radians(t.heading)
                    flee_x = math.sin(heading_rad) * 100.0
                    flee_y = math.cos(heading_rad) * 100.0
                else:
                    # Flee away from center
                    flee_x = t.position[0] / dist_from_center * 100.0
                    flee_y = t.position[1] / dist_from_center * 100.0
                t.waypoints = [(flee_x, flee_y)]
                t._waypoint_index = 0

    def _restore_speed(self, target_id: str, target: SimulationTarget) -> None:
        """Restore a single target's speed if it was held."""
        if target_id in self._hold_base_speeds:
            target.speed = self._hold_base_speeds.pop(target_id)

    def _restore_held_speeds(
        self,
        squad: Squad,
        targets: dict[str, SimulationTarget],
    ) -> None:
        """Restore speeds for all held squad members."""
        for mid in squad.member_ids:
            if mid in self._hold_base_speeds:
                t = targets.get(mid)
                if t is not None:
                    t.speed = self._hold_base_speeds.pop(mid)

    def tick(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """Main tick: re-evaluate squads, update formations, select targets.

        Called each engine tick (10 Hz).  Steps:
          1. Identify active hostiles.
          2. Remove eliminated/scattered members from existing squads.
          3. Dissolve squads with <2 active members.
          4. Form new squads from unassigned hostiles within SQUAD_RADIUS.
          5. Update leader (highest health) for each squad.
          6. Select shared target (nearest enemy to leader).
          7. Nudge followers toward formation positions.
        """
        # Step 1: Identify active hostiles
        active_hostiles = {
            tid: t for tid, t in targets.items()
            if t.alliance == "hostile" and t.status == "active"
        }

        # Step 2-3: Prune existing squads
        self._prune_squads(active_hostiles, targets)

        # Step 4: Form new squads from unassigned hostiles
        self._form_new_squads(active_hostiles)

        # Step 5: Update leaders
        for squad in self._squads.values():
            self._update_leader(squad, active_hostiles)

        # Step 6: Select shared targets
        friendlies = {
            tid: t for tid, t in targets.items()
            if t.alliance == "friendly"
            and t.status in ("active", "idle", "stationary")
            and t.is_combatant
        }
        for squad in self._squads.values():
            self._select_shared_target(squad, active_hostiles, friendlies)

        # Step 7: Apply formation offsets to followers
        for squad in self._squads.values():
            self._apply_formation(squad, active_hostiles, dt)

    def _prune_squads(
        self,
        active_hostiles: dict[str, SimulationTarget],
        all_targets: dict[str, SimulationTarget],
    ) -> None:
        """Remove dead/escaped members; dissolve squads with <2 active members."""
        to_dissolve: list[str] = []

        for sid, squad in self._squads.items():
            # Filter to only active members
            alive = [mid for mid in squad.member_ids if mid in active_hostiles]

            # Check proximity — members must still be within SQUAD_RADIUS of each other
            if len(alive) >= 2:
                alive = self._filter_by_proximity(alive, active_hostiles)

            # Remove members no longer in squad
            for mid in squad.member_ids:
                if mid not in alive:
                    t = all_targets.get(mid)
                    if t is not None:
                        t.squad_id = None

            squad.member_ids = alive

            if len(alive) < 2:
                to_dissolve.append(sid)

        for sid in to_dissolve:
            squad = self._squads.pop(sid)
            # Clear squad_id on remaining members
            for mid in squad.member_ids:
                t = all_targets.get(mid)
                if t is not None:
                    t.squad_id = None

    def _filter_by_proximity(
        self,
        member_ids: list[str],
        active_hostiles: dict[str, SimulationTarget],
    ) -> list[str]:
        """Keep only members that are within SQUAD_RADIUS of at least one other member."""
        if len(member_ids) < 2:
            return member_ids

        connected: set[str] = set()
        for i, mid_a in enumerate(member_ids):
            ta = active_hostiles.get(mid_a)
            if ta is None:
                continue
            for mid_b in member_ids[i + 1:]:
                tb = active_hostiles.get(mid_b)
                if tb is None:
                    continue
                dx = ta.position[0] - tb.position[0]
                dy = ta.position[1] - tb.position[1]
                if math.hypot(dx, dy) <= SQUAD_RADIUS:
                    connected.add(mid_a)
                    connected.add(mid_b)

        return [mid for mid in member_ids if mid in connected]

    def _form_new_squads(
        self,
        active_hostiles: dict[str, SimulationTarget],
    ) -> None:
        """Form squads from unassigned hostiles within SQUAD_RADIUS."""
        unassigned = [
            tid for tid, t in active_hostiles.items()
            if t.squad_id is None
        ]

        if len(unassigned) < 2:
            return

        # Simple greedy clustering: for each unassigned hostile, find all
        # other unassigned hostiles within SQUAD_RADIUS and form a squad.
        assigned: set[str] = set()

        for tid in unassigned:
            if tid in assigned:
                continue
            t = active_hostiles[tid]

            # Find neighbors within SQUAD_RADIUS
            neighbors = [tid]
            for other_tid in unassigned:
                if other_tid == tid or other_tid in assigned:
                    continue
                other = active_hostiles[other_tid]
                dx = t.position[0] - other.position[0]
                dy = t.position[1] - other.position[1]
                if math.hypot(dx, dy) <= SQUAD_RADIUS:
                    neighbors.append(other_tid)

            if len(neighbors) >= 2:
                squad_id = f"squad-{uuid.uuid4().hex[:8]}"
                squad = Squad(
                    squad_id=squad_id,
                    member_ids=neighbors,
                )
                # Set leader to highest health
                self._update_leader(squad, active_hostiles)
                self._squads[squad_id] = squad

                for mid in neighbors:
                    active_hostiles[mid].squad_id = squad_id
                    assigned.add(mid)

    def _update_leader(
        self,
        squad: Squad,
        active_hostiles: dict[str, SimulationTarget],
    ) -> None:
        """Set leader to the member with highest health."""
        best_id: str | None = None
        best_health = -1.0

        for mid in squad.member_ids:
            t = active_hostiles.get(mid)
            if t is None:
                continue
            if t.health > best_health:
                best_health = t.health
                best_id = mid

        squad.leader_id = best_id

    def _select_shared_target(
        self,
        squad: Squad,
        active_hostiles: dict[str, SimulationTarget],
        friendlies: dict[str, SimulationTarget],
    ) -> None:
        """Select the nearest enemy to the squad leader as shared target."""
        if squad.leader_id is None or not friendlies:
            squad.shared_target_id = None
            return

        leader = active_hostiles.get(squad.leader_id)
        if leader is None:
            squad.shared_target_id = None
            return

        best_id: str | None = None
        best_dist = float("inf")

        for fid, f in friendlies.items():
            dx = f.position[0] - leader.position[0]
            dy = f.position[1] - leader.position[1]
            d = math.hypot(dx, dy)
            if d < best_dist:
                best_dist = d
                best_id = fid

        squad.shared_target_id = best_id

    def _apply_formation(
        self,
        squad: Squad,
        active_hostiles: dict[str, SimulationTarget],
        dt: float,
    ) -> None:
        """Nudge followers toward their formation positions relative to leader.

        The leader's position is not modified.  Followers are smoothly
        interpolated toward (leader_pos + offset) each tick.
        """
        if squad.leader_id is None:
            return

        leader = active_hostiles.get(squad.leader_id)
        if leader is None:
            return

        offsets = squad.get_formation_offsets()
        leader_heading_rad = math.radians(leader.heading)

        for mid in squad.member_ids:
            if mid == squad.leader_id:
                continue

            follower = active_hostiles.get(mid)
            if follower is None:
                continue

            offset = offsets.get(mid, (0.0, 0.0))
            if offset == (0.0, 0.0):
                continue

            # Rotate offset by leader's heading
            # heading: 0 = north (+y), clockwise
            # We need to rotate the local offset (dx_local, dy_local)
            # where +y_local = forward (toward leader heading)
            cos_h = math.cos(leader_heading_rad)
            sin_h = math.sin(leader_heading_rad)
            # Rotation: world_dx = local_dx * cos(h) + local_dy * sin(h)
            #           world_dy = -local_dx * sin(h) + local_dy * cos(h)
            world_dx = offset[0] * cos_h + offset[1] * sin_h
            world_dy = -offset[0] * sin_h + offset[1] * cos_h

            target_x = leader.position[0] + world_dx
            target_y = leader.position[1] + world_dy

            # Smooth interpolation toward target position
            dx = target_x - follower.position[0]
            dy = target_y - follower.position[1]
            dist = math.hypot(dx, dy)

            if dist > 0.5:  # Only adjust if more than 0.5m off
                step = min(dist * _FORMATION_CONVERGENCE, follower.speed * dt)
                follower.position = (
                    follower.position[0] + (dx / dist) * step,
                    follower.position[1] + (dy / dist) * step,
                )
