# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""HostileCommander — centralized tactical AI for hostile forces.

Coordinates hostile units as a group: assigns objectives, orders flanking
maneuvers, coordinates multi-prong attacks, and issues retreat orders when
overwhelmed. Runs on a ~1Hz assessment cycle (not every tick).

The commander does NOT use an LLM — it uses deterministic tactical logic
based on force ratios, positions, and threat assessment. This ensures
consistent behavior without network latency.

Integration:
    engine._do_tick() calls hostile_commander.tick(dt, targets_dict)
    The commander reads unit positions and sets waypoints/FSM hints.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .target import SimulationTarget


@dataclass
class Objective:
    """A tactical objective assigned to a hostile unit."""
    type: str                           # assault, flank, retreat, evade, advance, hold
    target_position: tuple[float, float]
    priority: int = 1                   # 1-5, 5 = highest
    target_id: str | None = None        # friendly target being attacked
    assigned_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "target_position": self.target_position,
            "priority": self.priority,
            "target_id": self.target_id,
        }


class HostileCommander:
    """Centralized tactical AI coordinating hostile forces."""

    # Assess every N seconds (not every tick)
    ASSESS_INTERVAL = 1.0

    def __init__(self) -> None:
        self._objectives: dict[str, Objective] = {}  # hostile_id -> objective
        self._last_assess: float = 0.0
        self._assess_count: int = 0
        self._last_assessment: dict = {}

    def tick(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """Called each engine tick. Reassesses at ASSESS_INTERVAL."""
        now = time.monotonic()
        if now - self._last_assess < self.ASSESS_INTERVAL:
            return
        self._last_assess = now
        self._assess_count += 1

        # Assess and assign
        self._last_assessment = self.assess(targets)
        raw_orders = self._assign_objectives_raw(targets)

        # Apply orders: set waypoints on hostile units
        for tid, obj in raw_orders.items():
            t = targets.get(tid)
            if t is None or t.status != "active":
                continue
            # Set waypoints toward objective
            if obj.type in ("retreat", "assault", "flank", "advance"):
                t.waypoints = [obj.target_position]
            # Store objective for reference
            self._objectives[tid] = obj

    def assess(self, targets: dict[str, SimulationTarget]) -> dict:
        """Assess the current battlefield situation."""
        hostiles = [t for t in targets.values()
                    if t.alliance == "hostile" and t.status == "active"]
        friendlies = [t for t in targets.values()
                      if t.alliance == "friendly" and t.status == "active"
                      and t.is_combatant]

        h_count = len(hostiles)
        f_count = len(friendlies)

        # Force ratio
        if f_count == 0:
            force_ratio = 10.0
        else:
            force_ratio = h_count / f_count

        # Threat level based on ratio
        if force_ratio >= 2.0:
            threat_level = "low"
        elif force_ratio >= 1.0:
            threat_level = "moderate"
        elif force_ratio >= 0.5:
            threat_level = "high"
        else:
            threat_level = "critical"

        # Identify priority targets (stationary = turrets = dangerous)
        priority_targets = []
        for f in friendlies:
            prio = {"id": f.target_id, "type": f.asset_type,
                    "position": f.position, "priority": 1}
            if f.speed == 0:
                # Stationary units (turrets) are high priority
                prio["priority"] = 5
            elif f.asset_type in ("drone", "scout_drone"):
                prio["priority"] = 3  # Eyes in the sky
            else:
                prio["priority"] = 2
            priority_targets.append(prio)
        priority_targets.sort(key=lambda p: p["priority"], reverse=True)

        # Recommended action
        if threat_level == "critical":
            recommended = "retreat"
        elif threat_level == "high":
            recommended = "flank"
        elif threat_level == "moderate":
            recommended = "assault"
        else:
            recommended = "advance"

        return {
            "threat_level": threat_level,
            "force_ratio": force_ratio,
            "hostile_count": h_count,
            "friendly_count": f_count,
            "priority_targets": priority_targets,
            "recommended_action": recommended,
        }

    def assign_objectives(self, targets: dict[str, SimulationTarget]) -> dict:
        """Assign tactical objectives to hostile units.

        Returns dict[hostile_target_id, dict] (serialized objectives).
        """
        raw = self._assign_objectives_raw(targets)
        return {tid: obj.to_dict() for tid, obj in raw.items()}

    def _assign_objectives_raw(self, targets: dict[str, SimulationTarget]) -> dict[str, Objective]:
        """Internal: assign objectives, returning Objective dataclasses."""
        assessment = self.assess(targets)
        hostiles = [t for t in targets.values()
                    if t.alliance == "hostile" and t.status == "active"]
        friendlies = [t for t in targets.values()
                      if t.alliance == "friendly" and t.status == "active"
                      and t.is_combatant]

        if not hostiles or not friendlies:
            return {}

        orders: dict[str, Objective] = {}
        recommended = assessment["recommended_action"]
        priority_targets = assessment["priority_targets"]

        if recommended == "retreat":
            for h in hostiles:
                edge = self._nearest_edge(h.position)
                orders[h.target_id] = Objective(
                    type="retreat",
                    target_position=edge,
                    priority=5,
                    assigned_at=time.monotonic(),
                )
        elif recommended == "flank":
            self._assign_flanking(hostiles, friendlies, orders)
        elif recommended == "assault":
            self._assign_assault(hostiles, priority_targets, orders)
        else:
            self._assign_advance(hostiles, friendlies, orders)

        return orders

    def _assign_flanking(
        self,
        hostiles: list[SimulationTarget],
        friendlies: list[SimulationTarget],
        orders: dict[str, Objective],
    ) -> None:
        """Split hostiles into flanking groups attacking from different angles."""
        if not friendlies:
            return

        # Find center of friendly positions
        fx = sum(f.position[0] for f in friendlies) / len(friendlies)
        fy = sum(f.position[1] for f in friendlies) / len(friendlies)

        # Split hostiles into 2-3 groups
        n = len(hostiles)
        groups = min(3, max(2, n // 3))
        group_size = n // groups

        for gi in range(groups):
            start = gi * group_size
            end = start + group_size if gi < groups - 1 else n
            group = hostiles[start:end]

            # Each group approaches from a different angle
            angle = (gi / groups) * 2 * math.pi + random.uniform(-0.3, 0.3)
            flank_dist = 8.0
            target_x = fx + flank_dist * math.cos(angle)
            target_y = fy + flank_dist * math.sin(angle)

            for h in group:
                orders[h.target_id] = Objective(
                    type="flank",
                    target_position=(target_x, target_y),
                    priority=3,
                    assigned_at=time.monotonic(),
                )

    def _assign_assault(
        self,
        hostiles: list[SimulationTarget],
        priority_targets: list[dict],
        orders: dict[str, Objective],
    ) -> None:
        """Assign hostiles to assault priority targets."""
        if not priority_targets:
            return

        for i, h in enumerate(hostiles):
            # Round-robin assignment to priority targets
            pt = priority_targets[i % len(priority_targets)]
            pos = pt["position"]
            # Add slight offset to avoid stacking
            offset_x = random.uniform(-3, 3)
            offset_y = random.uniform(-3, 3)
            orders[h.target_id] = Objective(
                type="assault",
                target_position=(pos[0] + offset_x, pos[1] + offset_y),
                priority=pt["priority"],
                target_id=pt["id"],
                assigned_at=time.monotonic(),
            )

    def _assign_advance(
        self,
        hostiles: list[SimulationTarget],
        friendlies: list[SimulationTarget],
        orders: dict[str, Objective],
    ) -> None:
        """Assign hostiles to advance toward nearest friendly."""
        for h in hostiles:
            nearest = min(
                friendlies,
                key=lambda f: math.hypot(
                    f.position[0] - h.position[0],
                    f.position[1] - h.position[1],
                ),
            )
            # Move toward the friendly with some offset
            dx = nearest.position[0] - h.position[0]
            dy = nearest.position[1] - h.position[1]
            dist = math.hypot(dx, dy)
            if dist > 5:
                # Move 80% of the way
                target_x = h.position[0] + dx * 0.8
                target_y = h.position[1] + dy * 0.8
            else:
                target_x = nearest.position[0]
                target_y = nearest.position[1]
            orders[h.target_id] = Objective(
                type="advance",
                target_position=(target_x, target_y),
                priority=2,
                target_id=nearest.target_id,
                assigned_at=time.monotonic(),
            )

    def _nearest_edge(self, pos: tuple[float, float], bounds: float = 200.0) -> tuple[float, float]:
        """Find the nearest map edge from a position."""
        x, y = pos
        distances = [
            (abs(y - bounds), (x, bounds)),       # north
            (abs(y + bounds), (x, -bounds)),       # south
            (abs(x - bounds), (bounds, y)),        # east
            (abs(x + bounds), (-bounds, y)),       # west
        ]
        distances.sort(key=lambda d: d[0])
        return distances[0][1]

    def reset(self) -> None:
        """Clear all objectives."""
        self._objectives.clear()
        self._assess_count = 0
        self._last_assess = 0.0
        self._last_assessment = {}
