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
    from tritium_lib.sim_engine.core.entity import SimulationTarget


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

    def __init__(self, event_bus=None) -> None:
        self._objectives: dict[str, Objective] = {}  # hostile_id -> objective
        self._last_assess: float = 0.0
        self._assess_count: int = 0
        self._last_assessment: dict = {}
        self._game_mode_type: str | None = None
        self._event_bus = event_bus
        self._router = None  # Callable[[start, end, asset_type, alliance], list]

    def set_router(self, route_fn) -> None:
        """Set the pathfinding router callback.

        route_fn signature: (start, end, unit_type, alliance) -> list[waypoints]
        """
        self._router = route_fn

    def _route(self, start: tuple[float, float], end: tuple[float, float],
               asset_type: str = "person", alliance: str = "hostile") -> list[tuple[float, float]]:
        """Route a waypoint through the pathfinder, or direct if no router set."""
        if self._router is not None:
            try:
                path = self._router(start, end, asset_type, alliance)
                if path:
                    return path
            except Exception:
                pass
        return [end]

    def set_game_mode_type(self, mode_type: str | None) -> None:
        """Set the current game mode type for coordination dispatch."""
        self._game_mode_type = mode_type

    def tick(self, dt: float, targets: dict[str, SimulationTarget]) -> None:
        """Called each engine tick. Reassesses at ASSESS_INTERVAL."""
        now = time.monotonic()
        if now - self._last_assess < self.ASSESS_INTERVAL:
            return
        self._last_assess = now
        self._assess_count += 1

        # Assess and assign
        self._last_assessment = self.assess(targets)

        # Publish hostile intel to EventBus so the WebSocket bridge can
        # forward it to the frontend in real time (no polling needed).
        # Only sends summary fields; per-unit objectives available via
        # GET /api/game/hostile-intel for detailed view.
        if self._event_bus is not None:
            self._event_bus.publish("hostile_intel", dict(self._last_assessment))

        hostiles = [t for t in targets.values()
                    if t.alliance == "hostile" and t.status == "active"]
        friendlies = [t for t in targets.values()
                      if t.alliance == "friendly" and t.status == "active"
                      and t.is_combatant]

        # Mode-specific coordination
        if self._game_mode_type == "drone_swarm":
            self._coordinate_saturation(hostiles, friendlies)
            self._assign_screening(hostiles, friendlies)
            self._scout_relay(hostiles, friendlies)
        elif self._game_mode_type == "civil_unrest":
            self._manage_instigator_cycle(hostiles)
            self._civilian_conversion_check(hostiles, targets)

        raw_orders = self._assign_objectives_raw(targets)

        # Apply orders: set waypoints on hostile units (routed through pathfinder)
        for tid, obj in raw_orders.items():
            t = targets.get(tid)
            if t is None or t.status != "active":
                continue
            # Set waypoints toward objective via pathfinder
            if obj.type in ("retreat", "assault", "flank", "advance"):
                t.waypoints = self._route(t.position, obj.target_position,
                                          t.asset_type, t.alliance)
                t._waypoint_index = 0
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

    # -- Mode-specific coordination -----------------------------------------------

    def _coordinate_saturation(
        self,
        hostiles: list[SimulationTarget],
        friendlies: list[SimulationTarget],
    ) -> None:
        """Coordinate saturation attack with 120-degree separated approaches.

        When 5+ attack_swarm drones are alive, assign waypoints at
        120-degree-separated approach angles toward the center of friendlies.
        """
        attack_drones = [h for h in hostiles
                         if getattr(h, "drone_variant", None) == "attack_swarm"
                         and h.status == "active"]

        if len(attack_drones) < 5 or not friendlies:
            return

        # Center of friendlies
        fx = sum(f.position[0] for f in friendlies) / len(friendlies)
        fy = sum(f.position[1] for f in friendlies) / len(friendlies)

        # Assign approach angles at 120-degree separation (3 prongs)
        for i, drone in enumerate(attack_drones):
            prong = i % 3
            angle = math.radians(prong * 120 + random.uniform(-10, 10))
            approach_dist = 15.0
            wp_x = fx + approach_dist * math.cos(angle)
            wp_y = fy + approach_dist * math.sin(angle)
            drone.waypoints = self._route(drone.position, (wp_x, wp_y),
                                          drone.asset_type, drone.alliance)

    def _assign_screening(
        self,
        hostiles: list[SimulationTarget],
        friendlies: list[SimulationTarget],
    ) -> None:
        """Position attack drones between bombers and nearest missile turret.

        When bombers are present, assign attack drones as sacrificial
        screens to absorb missile turret fire.
        """
        bombers = [h for h in hostiles
                   if getattr(h, "drone_variant", None) == "bomber_swarm"
                   and h.status == "active"]
        attack_drones = [h for h in hostiles
                         if getattr(h, "drone_variant", None) == "attack_swarm"
                         and h.status == "active"]
        missile_turrets = [f for f in friendlies
                           if f.asset_type == "missile_turret"
                           and f.status in ("active", "stationary")]

        if not bombers or not attack_drones or not missile_turrets:
            return

        # For each attack drone, position between nearest bomber and nearest missile turret
        for ad in attack_drones:
            # Find nearest bomber
            nearest_bomber = min(bombers, key=lambda b: math.hypot(
                b.position[0] - ad.position[0],
                b.position[1] - ad.position[1],
            ))
            # Find nearest missile turret
            nearest_turret = min(missile_turrets, key=lambda t: math.hypot(
                t.position[0] - ad.position[0],
                t.position[1] - ad.position[1],
            ))
            # Position midpoint between bomber and turret
            mid_x = (nearest_bomber.position[0] + nearest_turret.position[0]) / 2.0
            mid_y = (nearest_bomber.position[1] + nearest_turret.position[1]) / 2.0
            ad.waypoints = self._route(ad.position, (mid_x, mid_y),
                                       ad.asset_type, ad.alliance)

    def _scout_relay(
        self,
        hostiles: list[SimulationTarget],
        friendlies: list[SimulationTarget],
    ) -> None:
        """Scout drone SIGNAL_CONTACT triggers attack drone convergence.

        When scouts have marked targets, direct attack drones to converge.
        """
        scouts = [h for h in hostiles
                  if getattr(h, "drone_variant", None) == "scout_swarm"
                  and h.status == "active"]
        attack_drones = [h for h in hostiles
                         if getattr(h, "drone_variant", None) == "attack_swarm"
                         and h.status == "active"]

        if not scouts or not attack_drones or not friendlies:
            return

        # Find nearest friendly to any scout
        for scout in scouts:
            nearest = min(friendlies, key=lambda f: math.hypot(
                f.position[0] - scout.position[0],
                f.position[1] - scout.position[1],
            ))
            dist = math.hypot(
                nearest.position[0] - scout.position[0],
                nearest.position[1] - scout.position[1],
            )
            if dist <= 40.0:
                # Direct attack drones to converge on target
                for ad in attack_drones:
                    ad.waypoints = self._route(ad.position, nearest.position,
                                               ad.asset_type, ad.alliance)
                break

    def _manage_instigator_cycle(
        self,
        hostiles: list[SimulationTarget],
    ) -> None:
        """Coordinate instigator activation timing for maximum disruption.

        Stagger instigator activations so they don't all activate simultaneously.
        """
        instigators = [h for h in hostiles
                       if getattr(h, "crowd_role", None) == "instigator"
                       and h.status == "active"]

        if len(instigators) <= 1:
            return

        # Ensure instigators are staggered: at most one active at a time
        active_count = sum(1 for i in instigators
                           if i.instigator_state == "active")
        if active_count > 1:
            # Force extras back to hidden
            forced = 0
            for i in instigators:
                if i.instigator_state == "active":
                    if forced > 0:
                        i.instigator_state = "hidden"
                        i.instigator_timer = 0.0
                    forced += 1

    def _civilian_conversion_check(
        self,
        hostiles: list[SimulationTarget],
        all_targets: dict[str, SimulationTarget],
    ) -> None:
        """When instigator activates near civilians: 20% chance per civilian to convert to rioter.

        Conversion range is 15m from the active instigator.
        """
        active_instigators = [h for h in hostiles
                              if getattr(h, "crowd_role", None) == "instigator"
                              and getattr(h, "instigator_state", None) == "active"]

        if not active_instigators:
            return

        for instigator in active_instigators:
            for t in all_targets.values():
                if t.crowd_role != "civilian":
                    continue
                dx = t.position[0] - instigator.position[0]
                dy = t.position[1] - instigator.position[1]
                if math.hypot(dx, dy) <= 15.0:
                    if random.random() < 0.2:
                        t.crowd_role = "rioter"
                        t.is_combatant = True

    def remove_unit(self, target_id: str) -> None:
        """Remove objective state for a single unit."""
        self._objectives.pop(target_id, None)

    def reset(self) -> None:
        """Clear all objectives."""
        self._objectives.clear()
        self._assess_count = 0
        self._last_assess = 0.0
        self._last_assessment = {}
        self._game_mode_type = None
