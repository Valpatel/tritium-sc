"""NPCWorldBridge — connects NPCManager with NPC Intelligence Plugin.

The bridge is the critical integration point:
- When NPCManager spawns an NPC, bridge attaches a routine
- FSM state changes are translated to routing requests
- Spatial context is generated for LLM prompts
- Per-tick updates check routines and assign waypoints
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

from engine.simulation.npc_intelligence.npc_router import NPCRouter
from engine.simulation.npc_intelligence.routine import (
    RoutineScheduler,
    RoutineActivity,
)
from engine.simulation.npc_intelligence.world_model import WorldModel

if TYPE_CHECKING:
    from engine.simulation.npc_intelligence.brain import NPCPersonality


# FSM states that need new waypoints
_MOVEMENT_STATES = {"walking", "fleeing", "hiding", "curious", "driving", "evading"}

# FSM states that mean "stay in place"
_STATIONARY_STATES = {"pausing", "observing", "panicking", "stopped", "parked",
                      "resting", "yielding"}


class NPCWorldBridge:
    """Bridges NPCManager (spawn/movement) with NPC Intelligence (brains/FSMs).

    When NPCManager spawns an NPC, this bridge:
    1. Attaches a daily routine
    2. Routes the NPC to its first destination
    3. Listens for FSM state changes and translates to movement commands

    When the Intelligence Plugin decides an NPC should change behavior:
    1. Bridge translates the FSM state to a routing request
    2. NPCRouter generates appropriate waypoints
    3. Bridge updates the target's waypoints in the engine
    """

    def __init__(
        self,
        world: WorldModel,
        router: NPCRouter,
        scheduler: RoutineScheduler,
    ) -> None:
        self._world = world
        self._router = router
        self._scheduler = scheduler

        # Registered NPC data: id -> {target_ref, npc_type, last_state, last_waypoint_time}
        self._npcs: dict[str, dict] = {}

    # -- Registration --

    def register_npc(self, target: object) -> None:
        """Register an NPC target for routine management.

        Skips combatants and bound (real-data) targets.
        """
        if getattr(target, "is_combatant", False):
            return
        if getattr(target, "bound", False):
            return

        npc_id = target.id
        npc_type = getattr(target, "asset_type", "person")
        x = getattr(target, "x", 0.0)
        y = getattr(target, "y", 0.0)

        # Create a default personality if brain doesn't provide one
        from engine.simulation.npc_intelligence.brain import NPCPersonality
        personality = getattr(target, "personality", None)
        if not isinstance(personality, NPCPersonality):
            personality = NPCPersonality(
                curiosity=0.5, caution=0.5, sociability=0.5, aggression=0.2,
            )

        # Assign routine
        vehicle_role = None
        if npc_type == "vehicle":
            vehicle_role = getattr(target, "vehicle_role", "commuter")

        self._scheduler.assign_routine(
            npc_id, npc_type, personality, (x, y),
            vehicle_role=vehicle_role,
        )

        self._npcs[npc_id] = {
            "npc_type": npc_type,
            "last_state": None,
            "last_waypoint_time": 0.0,
        }

    def unregister_npc(self, npc_id: str) -> None:
        """Remove an NPC from bridge management."""
        self._npcs.pop(npc_id, None)
        self._scheduler.remove_routine(npc_id)

    def has_routine(self, npc_id: str) -> bool:
        """Check if an NPC has an assigned routine."""
        return npc_id in self._npcs

    @property
    def npc_count(self) -> int:
        return len(self._npcs)

    @property
    def active_npc_ids(self) -> set[str]:
        return set(self._npcs.keys())

    # -- Waypoint generation --

    def get_waypoints(
        self,
        npc_id: str,
        fsm_state: str,
        sim_time: float,
        threat_pos: tuple[float, float] | None = None,
    ) -> list[tuple[float, float]] | None:
        """Generate waypoints based on FSM state.

        Returns:
            List of waypoints, or None if NPC should stay in place.
        """
        npc = self._npcs.get(npc_id)
        if npc is None:
            return None

        npc_type = npc["npc_type"]

        if fsm_state in _STATIONARY_STATES:
            return None

        if fsm_state == "walking":
            return self._walking_waypoints(npc_id, npc_type, sim_time)
        elif fsm_state == "fleeing":
            return self._fleeing_waypoints(npc_id, npc_type, threat_pos)
        elif fsm_state == "hiding":
            return self._hiding_waypoints(npc_id, npc_type)
        elif fsm_state == "curious":
            return self._curious_waypoints(npc_id, npc_type, sim_time)
        elif fsm_state == "driving":
            return self._driving_waypoints(npc_id, sim_time)
        elif fsm_state == "evading":
            return self._evading_waypoints(npc_id, threat_pos)
        else:
            return None

    # -- Spatial context for LLM --

    def spatial_context(self, npc_id: str, x: float, y: float) -> str:
        """Generate a spatial context string for LLM prompts.

        Describes where the NPC is: on sidewalk, road, near buildings, etc.
        """
        parts = []

        # Location type
        if self._world.is_inside_building(x, y):
            b = self._world.nearest_building(x, y)
            if b:
                parts.append(f"You are inside a {b.building_type} building.")
            else:
                parts.append("You are inside a building.")
        elif self._world.is_on_sidewalk(x, y, tolerance=5.0):
            parts.append("You are on a sidewalk.")
        elif self._world.is_on_road(x, y, tolerance=5.0):
            road_type = self._world.road_type_at(x, y, tolerance=5.0)
            if road_type:
                parts.append(f"You are on a {road_type} road.")
            else:
                parts.append("You are on a road.")
        else:
            parts.append("You are in an open area (yard or park).")

        # Nearby buildings
        nearby_buildings = self._world.buildings_in_radius(x, y, 30.0)
        if nearby_buildings:
            count = len(nearby_buildings)
            nearest = self._world.nearest_building(x, y)
            if nearest:
                dist = math.hypot(x - nearest.center[0], y - nearest.center[1])
                parts.append(
                    f"There are {count} buildings within 30m. "
                    f"The nearest is a {nearest.building_type} building "
                    f"{dist:.0f}m away."
                )

        # Nearest door
        door = self._world.nearest_door(x, y)
        if door:
            door_dist = math.hypot(x - door.position[0], y - door.position[1])
            if door_dist < 20:
                parts.append(f"There is a door {door_dist:.0f}m away.")

        # Nearest crosswalk
        cw = self._world.nearest_crosswalk(x, y)
        if cw:
            cw_dist = math.hypot(x - cw.position[0], y - cw.position[1])
            if cw_dist < 30:
                parts.append(f"The nearest crosswalk is {cw_dist:.0f}m away.")

        # Current activity
        act = self._scheduler.current_activity(npc_id, sim_time=0)
        if act:
            parts.append(f"You are currently supposed to be: {act.activity_type}.")

        return " ".join(parts) if parts else "You are in an uncharted area."

    # -- Tick --

    def tick(
        self,
        dt: float,
        sim_time: float,
        targets: dict[str, object],
    ) -> None:
        """Per-tick update: check routines, update waypoints, sync state.

        Args:
            dt: delta time since last tick
            sim_time: current simulation time (seconds from midnight)
            targets: dict of target_id -> target object
        """
        for npc_id, npc_data in self._npcs.items():
            target = targets.get(npc_id)
            if target is None:
                continue
            if getattr(target, "bound", False):
                continue

            fsm_state = getattr(target, "fsm_state", None)
            if fsm_state is None:
                continue

            # Check if state changed or waypoints depleted
            state_changed = fsm_state != npc_data.get("last_state")
            waypoints_empty = not getattr(target, "waypoints", None)
            time_since_last = sim_time - npc_data.get("last_waypoint_time", 0)

            if state_changed or (waypoints_empty and time_since_last > 5.0):
                x = getattr(target, "x", 0.0)
                y = getattr(target, "y", 0.0)

                new_wp = self.get_waypoints(
                    npc_id, fsm_state, sim_time,
                    threat_pos=getattr(target, "threat_pos", None),
                )
                if new_wp:
                    target.waypoints = new_wp

                npc_data["last_state"] = fsm_state
                npc_data["last_waypoint_time"] = sim_time

    # -- Internal routing helpers --

    def _walking_waypoints(
        self, npc_id: str, npc_type: str, sim_time: float,
    ) -> list[tuple[float, float]] | None:
        """Generate walking waypoints toward current routine destination."""
        dest = self._scheduler.destination(npc_id, sim_time)
        if dest is None:
            return None

        # Get current position from last known data
        npc = self._npcs.get(npc_id)
        if npc is None:
            return None

        if npc_type == "vehicle":
            return self._router.route_vehicle(dest, dest)

        return self._router.route_pedestrian(dest, dest)

    def _fleeing_waypoints(
        self, npc_id: str, npc_type: str,
        threat_pos: tuple[float, float] | None,
    ) -> list[tuple[float, float]] | None:
        """Generate flee waypoints away from threat."""
        if threat_pos is None:
            threat_pos = (0, 0)

        dest = self._scheduler.destination(npc_id, sim_time=0)
        pos = dest if dest else (0, 0)

        return self._router.route_flee(pos, threat_pos, npc_type)

    def _hiding_waypoints(
        self, npc_id: str, npc_type: str,
    ) -> list[tuple[float, float]] | None:
        """Route to nearest building door for hiding."""
        dest = self._scheduler.destination(npc_id, sim_time=0)
        pos = dest if dest else (0, 0)

        building = self._world.nearest_building(pos[0], pos[1])
        if building:
            return self._router.route_to_building(pos, building)

        # No building — flee to safe direction
        return self._router.route_flee(pos, (0, 0), npc_type)

    def _curious_waypoints(
        self, npc_id: str, npc_type: str, sim_time: float,
    ) -> list[tuple[float, float]] | None:
        """Route toward nearest POI of interest."""
        dest = self._scheduler.destination(npc_id, sim_time)
        if dest is None:
            return None

        poi = self._world.nearest_poi(dest[0], dest[1], poi_type="commercial")
        if poi:
            return self._router.route_pedestrian(dest, poi.position)

        return None

    def _driving_waypoints(
        self, npc_id: str, sim_time: float,
    ) -> list[tuple[float, float]] | None:
        """Generate driving waypoints toward routine destination."""
        dest = self._scheduler.destination(npc_id, sim_time)
        if dest is None:
            return None
        return self._router.route_vehicle(dest, dest)

    def _evading_waypoints(
        self, npc_id: str,
        threat_pos: tuple[float, float] | None,
    ) -> list[tuple[float, float]] | None:
        """Vehicle evading: speed away on roads."""
        if threat_pos is None:
            threat_pos = (0, 0)
        dest = self._scheduler.destination(npc_id, sim_time=0)
        pos = dest if dest else (0, 0)
        return self._router.route_flee(pos, threat_pos, "vehicle")
