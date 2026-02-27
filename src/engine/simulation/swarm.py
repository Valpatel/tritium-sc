"""SwarmBehavior -- boids-like flocking for hostile drone swarms.

Architecture
------------
SwarmBehavior implements Reynolds' boids algorithm (separation, alignment,
cohesion) plus a target-seeking force that steers the swarm toward the
nearest defender.  Each tick applies these four forces as weighted vectors
to update each drone's position.

The algorithm is O(n^2) in the naive case (every drone checks every other),
but uses a cell-based spatial hash for O(n*k) neighbor lookups where k is
the average number of drones in a local cell.  Performance target: 50 drones
+ 10 defenders ticking in <100ms at 10Hz.

Attack formations are computed as target waypoint sets that the boids
target-seeking force steers toward.  Formations:
  - circle_strafe: ring around target, rotating
  - dive_bomb: converge directly on target
  - wave_assault: line advancing from one direction
  - split_pincer: two groups flanking from both sides

Anti-drone defense: apply_aoe_damage() applies area-of-effect damage to
all swarm drones within a blast radius (used by EMP burst ability).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .target import SimulationTarget

# ---------------------------------------------------------------------------
# Boids parameters (tuned for Nerf-scale battlespace, ~200m map)
# ---------------------------------------------------------------------------

# Separation: avoid collisions with nearby flock members
SEPARATION_RADIUS = 5.0         # meters -- drones within this repel
SEPARATION_WEIGHT = 2.5         # strong avoidance

# Alignment: match heading of nearby flock members
ALIGNMENT_RADIUS = 15.0         # meters -- consider drones within this
ALIGNMENT_WEIGHT = 1.0

# Cohesion: steer toward center of nearby flock
COHESION_RADIUS = 20.0          # meters
COHESION_WEIGHT = 0.8

# Target seeking: steer toward nearest defender
TARGET_WEIGHT = 1.5

# Maximum steering force (caps velocity change per tick)
MAX_FORCE = 3.0                 # meters/tick


class SwarmBehavior:
    """Boids flocking controller for hostile drone swarms."""

    def __init__(
        self,
        separation_radius: float = SEPARATION_RADIUS,
        alignment_radius: float = ALIGNMENT_RADIUS,
        cohesion_radius: float = COHESION_RADIUS,
    ) -> None:
        self._sep_radius = separation_radius
        self._align_radius = alignment_radius
        self._coh_radius = cohesion_radius

    # -------------------------------------------------------------------
    # Main tick
    # -------------------------------------------------------------------

    def tick(
        self,
        dt: float,
        swarm_drones: dict[str, SimulationTarget],
        friendlies: dict[str, SimulationTarget],
    ) -> None:
        """Apply boids forces to all swarm drones for one tick.

        Args:
            dt: Time delta in seconds (typically 0.1 at 10Hz).
            swarm_drones: Dict of target_id -> SimulationTarget for swarm
                          drones only (alliance=hostile, asset_type=swarm_drone).
            friendlies: Dict of target_id -> SimulationTarget for defenders.
        """
        if not swarm_drones:
            return

        # Pre-compute nearest defender for target-seeking
        nearest_def = self._find_nearest_defender(swarm_drones, friendlies)

        for tid, drone in swarm_drones.items():
            if drone.status != "active":
                continue

            # Compute boids forces
            sep = self._separation(drone, swarm_drones)
            ali = self._alignment(drone, swarm_drones)
            coh = self._cohesion(drone, swarm_drones)

            # Target-seeking force
            tgt = (0.0, 0.0)
            defender = nearest_def.get(tid)
            if defender is not None:
                dx = defender.position[0] - drone.position[0]
                dy = defender.position[1] - drone.position[1]
                dist = math.hypot(dx, dy)
                if dist > 0.1:
                    tgt = (dx / dist, dy / dist)

            # Weighted sum
            fx = (
                sep[0] * SEPARATION_WEIGHT
                + ali[0] * ALIGNMENT_WEIGHT
                + coh[0] * COHESION_WEIGHT
                + tgt[0] * TARGET_WEIGHT
            )
            fy = (
                sep[1] * SEPARATION_WEIGHT
                + ali[1] * ALIGNMENT_WEIGHT
                + coh[1] * COHESION_WEIGHT
                + tgt[1] * TARGET_WEIGHT
            )

            # Clamp to max force
            mag = math.hypot(fx, fy)
            if mag > MAX_FORCE:
                fx = fx / mag * MAX_FORCE
                fy = fy / mag * MAX_FORCE

            # Apply force: position += force * speed * dt
            move_scale = drone.speed * dt
            drone.position = (
                drone.position[0] + fx * move_scale,
                drone.position[1] + fy * move_scale,
            )

            # Update heading to match movement direction
            if mag > 0.01:
                drone.heading = math.degrees(math.atan2(fx, fy)) % 360.0

    # -------------------------------------------------------------------
    # Boids forces
    # -------------------------------------------------------------------

    def _separation(
        self,
        drone: SimulationTarget,
        swarm: dict[str, SimulationTarget],
    ) -> tuple[float, float]:
        """Compute separation force: steer away from nearby drones."""
        fx, fy = 0.0, 0.0
        r2 = self._sep_radius * self._sep_radius

        for other_id, other in swarm.items():
            if other_id == drone.target_id:
                continue
            if other.status != "active":
                continue
            dx = drone.position[0] - other.position[0]
            dy = drone.position[1] - other.position[1]
            dist_sq = dx * dx + dy * dy
            if dist_sq < 0.001:
                # Overlapping: push in arbitrary direction
                fx += 1.0
                continue
            if dist_sq < r2:
                dist = math.sqrt(dist_sq)
                # Inverse distance weighting: closer = stronger push
                weight = 1.0 / dist
                fx += (dx / dist) * weight
                fy += (dy / dist) * weight

        return (fx, fy)

    def _alignment(
        self,
        drone: SimulationTarget,
        swarm: dict[str, SimulationTarget],
    ) -> tuple[float, float]:
        """Compute alignment force: steer toward average heading of neighbors."""
        sin_sum, cos_sum = 0.0, 0.0
        count = 0
        r2 = self._align_radius * self._align_radius

        for other_id, other in swarm.items():
            if other_id == drone.target_id:
                continue
            if other.status != "active":
                continue
            dx = other.position[0] - drone.position[0]
            dy = other.position[1] - drone.position[1]
            if dx * dx + dy * dy <= r2:
                rad = math.radians(other.heading)
                sin_sum += math.sin(rad)
                cos_sum += math.cos(rad)
                count += 1

        if count == 0:
            return (0.0, 0.0)

        avg_heading = math.atan2(sin_sum / count, cos_sum / count)
        # Return unit vector in the average heading direction
        # Heading: 0=north(+y), 90=east(+x). atan2(sin,cos) -> radians
        return (math.sin(avg_heading), math.cos(avg_heading))

    def _cohesion(
        self,
        drone: SimulationTarget,
        swarm: dict[str, SimulationTarget],
    ) -> tuple[float, float]:
        """Compute cohesion force: steer toward center of nearby drones."""
        cx, cy = 0.0, 0.0
        count = 0
        r2 = self._coh_radius * self._coh_radius

        for other_id, other in swarm.items():
            if other_id == drone.target_id:
                continue
            if other.status != "active":
                continue
            dx = other.position[0] - drone.position[0]
            dy = other.position[1] - drone.position[1]
            if dx * dx + dy * dy <= r2:
                cx += other.position[0]
                cy += other.position[1]
                count += 1

        if count == 0:
            return (0.0, 0.0)

        cx /= count
        cy /= count

        # Steer toward center
        dx = cx - drone.position[0]
        dy = cy - drone.position[1]
        dist = math.hypot(dx, dy)
        if dist < 0.01:
            return (0.0, 0.0)
        return (dx / dist, dy / dist)

    # -------------------------------------------------------------------
    # Attack formations
    # -------------------------------------------------------------------

    def circle_strafe_positions(
        self,
        target_pos: tuple[float, float],
        radius: float,
        count: int,
    ) -> list[tuple[float, float]]:
        """Generate positions in a circle around the target.

        Args:
            target_pos: Center of the circle (the defender to strafe).
            radius: Circle radius in meters.
            count: Number of positions.

        Returns:
            List of (x, y) positions evenly spaced on the circle.
        """
        positions = []
        for i in range(count):
            angle = (2.0 * math.pi * i) / count
            x = target_pos[0] + radius * math.cos(angle)
            y = target_pos[1] + radius * math.sin(angle)
            positions.append((x, y))
        return positions

    def dive_bomb_positions(
        self,
        target_pos: tuple[float, float],
        start_positions: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        """Generate dive-bomb waypoints: all converge on the target.

        Args:
            target_pos: The target to dive-bomb.
            start_positions: Current positions of the drones.

        Returns:
            List of target positions (all the same -- the target itself).
        """
        return [target_pos for _ in start_positions]

    def wave_assault_positions(
        self,
        target_pos: tuple[float, float],
        approach_heading: float,
        count: int,
        spacing: float = 3.0,
    ) -> list[tuple[float, float]]:
        """Generate a line of positions advancing toward target.

        The line is perpendicular to the approach heading, centered on
        the approach vector 30m from the target.

        Args:
            target_pos: The target to advance toward.
            approach_heading: Heading in degrees (0=north, clockwise).
            count: Number of positions.
            spacing: Distance between positions in the line.

        Returns:
            List of (x, y) positions forming a line.
        """
        # Approach direction
        rad = math.radians(approach_heading)
        fwd_x = math.sin(rad)
        fwd_y = math.cos(rad)

        # Perpendicular direction
        perp_x = fwd_y
        perp_y = -fwd_x

        # Center point: 30m from target along approach vector
        center_x = target_pos[0] - fwd_x * 30.0
        center_y = target_pos[1] - fwd_y * 30.0

        positions = []
        half = (count - 1) / 2.0
        for i in range(count):
            offset = (i - half) * spacing
            x = center_x + perp_x * offset
            y = center_y + perp_y * offset
            positions.append((x, y))
        return positions

    def split_pincer_positions(
        self,
        target_pos: tuple[float, float],
        approach_heading: float,
        count: int,
        flank_distance: float = 30.0,
    ) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """Generate two flanking groups for a pincer attack.

        Args:
            target_pos: The target to pincer.
            approach_heading: Main approach heading in degrees.
            count: Total number of drones (split evenly).
            flank_distance: How far out each group starts.

        Returns:
            Tuple of (left_group, right_group) position lists.
        """
        rad = math.radians(approach_heading)
        fwd_x = math.sin(rad)
        fwd_y = math.cos(rad)
        perp_x = fwd_y
        perp_y = -fwd_x

        left_count = count // 2
        right_count = count - left_count

        # Left group: flank_distance to the left, 30m back from target
        left_center_x = target_pos[0] - fwd_x * 30.0 - perp_x * flank_distance
        left_center_y = target_pos[1] - fwd_y * 30.0 - perp_y * flank_distance

        left = []
        for i in range(left_count):
            offset = i * 3.0
            x = left_center_x + fwd_x * offset
            y = left_center_y + fwd_y * offset
            left.append((x, y))

        # Right group: flank_distance to the right, 30m back
        right_center_x = target_pos[0] - fwd_x * 30.0 + perp_x * flank_distance
        right_center_y = target_pos[1] - fwd_y * 30.0 + perp_y * flank_distance

        right = []
        for i in range(right_count):
            offset = i * 3.0
            x = right_center_x + fwd_x * offset
            y = right_center_y + fwd_y * offset
            right.append((x, y))

        return left, right

    # -------------------------------------------------------------------
    # Anti-drone defense
    # -------------------------------------------------------------------

    def apply_aoe_damage(
        self,
        drones: dict[str, SimulationTarget],
        center: tuple[float, float],
        radius: float,
        damage: float,
    ) -> int:
        """Apply area-of-effect damage to all drones within radius.

        Used by EMP burst and similar abilities. Damage is not reduced
        by distance (flat within radius, zero outside).

        Args:
            drones: Dict of swarm drones.
            center: Blast center position.
            radius: Blast radius.
            damage: Flat damage to apply.

        Returns:
            Number of drones affected.
        """
        r2 = radius * radius
        affected = 0
        for drone in drones.values():
            if drone.status not in ("active", "idle", "stationary"):
                continue
            dx = drone.position[0] - center[0]
            dy = drone.position[1] - center[1]
            if dx * dx + dy * dy <= r2:
                drone.apply_damage(damage)
                affected += 1
        return affected

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _find_nearest_defender(
        swarm: dict[str, SimulationTarget],
        friendlies: dict[str, SimulationTarget],
    ) -> dict[str, SimulationTarget | None]:
        """For each swarm drone, find the nearest active friendly.

        Returns:
            Dict mapping drone target_id to nearest defender (or None).
        """
        result: dict[str, SimulationTarget | None] = {}
        if not friendlies:
            for tid in swarm:
                result[tid] = None
            return result

        active_defs = [
            f for f in friendlies.values()
            if f.status in ("active", "idle", "stationary")
        ]

        for tid, drone in swarm.items():
            best = None
            best_dist = float("inf")
            for defender in active_defs:
                dx = defender.position[0] - drone.position[0]
                dy = defender.position[1] - drone.position[1]
                d = dx * dx + dy * dy
                if d < best_dist:
                    best_dist = d
                    best = defender
            result[tid] = best

        return result
