"""RoutineScheduler — daily schedules for NPCs.

Gives each NPC a purpose: pedestrians commute to work, shop, walk in parks;
vehicles drive routes; animals wander.  Personality traits influence the
schedule shape (sociable NPCs spend more time outdoors, cautious NPCs stay
home longer).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

from engine.simulation.npc_intelligence.brain import NPCPersonality
from engine.simulation.npc_intelligence.world_model import POI


# Time constants (seconds from midnight)
_HOUR = 3600.0
_MINUTE = 60.0


@dataclass
class RoutineActivity:
    """A single block in an NPC's daily schedule."""

    activity_type: str          # home, commute, work, shop, walk, park, idle, drive, parked
    location: Optional[POI]     # destination POI (None for commute/idle)
    start_time: float           # sim-time offset from midnight (seconds)
    duration: float             # expected duration (seconds)
    priority: int = 0           # higher = harder to interrupt


# ============================================================================
# Pedestrian routine
# ============================================================================


class NPCRoutine:
    """A daily schedule for a pedestrian NPC.

    Generated once at spawn, consulted every tick to determine what the
    NPC should be doing.
    """

    def __init__(
        self,
        npc_id: str,
        home: POI,
        personality: NPCPersonality,
        available_pois: list[POI],
    ) -> None:
        self.npc_id = npc_id
        self.home = home
        self.personality = personality
        self.schedule: list[RoutineActivity] = []
        self._build_schedule(available_pois)

    def current_activity(self, sim_time: float) -> RoutineActivity:
        """Get the current activity at sim_time (seconds from midnight)."""
        t = sim_time % (24 * _HOUR)
        # Find the activity whose window contains t
        for i, act in enumerate(self.schedule):
            end = act.start_time + act.duration
            if act.start_time <= t < end:
                return act
        # Fallback: last activity (wraps around midnight)
        return self.schedule[-1] if self.schedule else RoutineActivity(
            activity_type="idle", location=self.home,
            start_time=0, duration=24 * _HOUR,
        )

    def next_activity(self, sim_time: float) -> RoutineActivity:
        """Get the next upcoming activity after sim_time."""
        t = sim_time % (24 * _HOUR)
        for act in self.schedule:
            if act.start_time > t:
                return act
        # Wrap: next day's first activity
        return self.schedule[0] if self.schedule else RoutineActivity(
            activity_type="home", location=self.home,
            start_time=0, duration=6 * _HOUR,
        )

    def time_until_next(self, sim_time: float) -> float:
        """Seconds until the next activity starts."""
        nxt = self.next_activity(sim_time)
        t = sim_time % (24 * _HOUR)
        if nxt.start_time > t:
            return nxt.start_time - t
        # Wrapped around midnight
        return (24 * _HOUR - t) + nxt.start_time

    # -- Internal schedule builder --

    def _build_schedule(self, pois: list[POI]) -> None:
        """Generate a personality-influenced daily schedule."""
        p = self.personality

        # Find work / shop / park POIs
        work_poi = self._find_poi(pois, "commercial")
        shop_poi = self._find_poi(pois, "commercial", exclude=work_poi)
        park_poi = self._find_poi(pois, "park")

        # Personality adjustments (in hours)
        # Cautious: sleep more, less outdoor
        wake_hour = 6.0 + (p.caution - 0.5) * 2.0      # 5-7h
        work_start = wake_hour + 1.0
        # Social: longer lunch, more walk time
        lunch_duration = 0.5 + p.sociability * 0.5       # 0.5-1h
        evening_walk = 0.5 + p.sociability * 1.0         # 0.5-1.5h
        # Aggressive: stays out later
        bed_hour = 20.0 + p.aggression * 3.0             # 20-23h

        s = self.schedule

        # SLEEP: midnight -> wake
        s.append(RoutineActivity(
            activity_type="home", location=self.home,
            start_time=0, duration=wake_hour * _HOUR, priority=1,
        ))

        # MORNING PREP
        s.append(RoutineActivity(
            activity_type="home", location=self.home,
            start_time=wake_hour * _HOUR,
            duration=1.0 * _HOUR, priority=0,
        ))

        # COMMUTE TO WORK
        commute_start = (wake_hour + 1.0) * _HOUR
        commute_duration = 0.5 * _HOUR
        if work_poi:
            s.append(RoutineActivity(
                activity_type="commute", location=work_poi,
                start_time=commute_start,
                duration=commute_duration, priority=2,
            ))

            # WORK (morning)
            work_morning_start = commute_start + commute_duration
            work_morning_end = 12.0 * _HOUR
            if work_morning_end > work_morning_start:
                s.append(RoutineActivity(
                    activity_type="work", location=work_poi,
                    start_time=work_morning_start,
                    duration=work_morning_end - work_morning_start,
                    priority=3,
                ))

            # LUNCH
            lunch_start = 12.0 * _HOUR
            lunch_poi = shop_poi or work_poi
            s.append(RoutineActivity(
                activity_type="shop", location=lunch_poi,
                start_time=lunch_start,
                duration=lunch_duration * _HOUR, priority=1,
            ))

            # WORK (afternoon)
            afternoon_start = lunch_start + lunch_duration * _HOUR
            afternoon_end = 17.0 * _HOUR
            if afternoon_end > afternoon_start:
                s.append(RoutineActivity(
                    activity_type="work", location=work_poi,
                    start_time=afternoon_start,
                    duration=afternoon_end - afternoon_start,
                    priority=3,
                ))

            # COMMUTE HOME
            s.append(RoutineActivity(
                activity_type="commute", location=self.home,
                start_time=17.0 * _HOUR,
                duration=commute_duration, priority=2,
            ))

            dinner_start = 17.0 * _HOUR + commute_duration
        else:
            # No work: stay home longer, then walk
            s.append(RoutineActivity(
                activity_type="walk", location=park_poi or self.home,
                start_time=commute_start,
                duration=2.0 * _HOUR, priority=0,
            ))
            dinner_start = commute_start + 2.0 * _HOUR

        # DINNER
        dinner_duration = 1.5 * _HOUR
        s.append(RoutineActivity(
            activity_type="home", location=self.home,
            start_time=dinner_start,
            duration=dinner_duration, priority=1,
        ))

        # EVENING WALK (if social enough or park available)
        evening_start = dinner_start + dinner_duration
        if evening_walk > 0.3 and evening_start < bed_hour * _HOUR:
            walk_poi = park_poi or self.home
            walk_dur = min(evening_walk * _HOUR, bed_hour * _HOUR - evening_start)
            if walk_dur > 0:
                s.append(RoutineActivity(
                    activity_type="walk", location=walk_poi,
                    start_time=evening_start,
                    duration=walk_dur, priority=0,
                ))
                evening_start += walk_dur

        # BED
        if evening_start < 24 * _HOUR:
            s.append(RoutineActivity(
                activity_type="home", location=self.home,
                start_time=evening_start,
                duration=24 * _HOUR - evening_start, priority=1,
            ))

    def _find_poi(
        self,
        pois: list[POI],
        poi_type: str,
        exclude: Optional[POI] = None,
    ) -> Optional[POI]:
        """Find a POI of the given type, closest to home."""
        candidates = [
            p for p in pois
            if p.poi_type == poi_type and p is not exclude
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda p: math.hypot(
                p.position[0] - self.home.position[0],
                p.position[1] - self.home.position[1],
            ),
        )


# ============================================================================
# Vehicle routine
# ============================================================================


class VehicleRoutine:
    """A daily schedule for a vehicle NPC."""

    def __init__(
        self,
        npc_id: str,
        hub: POI,
        role: str,          # commuter, delivery, patrol
        waypoints: list[POI],
    ) -> None:
        self.npc_id = npc_id
        self.hub = hub
        self.role = role
        self.schedule: list[RoutineActivity] = []
        self._build_schedule(waypoints)

    def current_activity(self, sim_time: float) -> RoutineActivity:
        t = sim_time % (24 * _HOUR)
        for act in self.schedule:
            end = act.start_time + act.duration
            if act.start_time <= t < end:
                return act
        return self.schedule[-1] if self.schedule else RoutineActivity(
            activity_type="parked", location=self.hub,
            start_time=0, duration=24 * _HOUR,
        )

    def _build_schedule(self, waypoints: list[POI]) -> None:
        s = self.schedule

        if self.role == "commuter":
            self._build_commuter(waypoints, s)
        elif self.role == "delivery":
            self._build_delivery(waypoints, s)
        elif self.role == "patrol":
            self._build_patrol(waypoints, s)
        else:
            # Default: parked all day
            s.append(RoutineActivity(
                activity_type="parked", location=self.hub,
                start_time=0, duration=24 * _HOUR,
            ))

    def _build_commuter(self, waypoints: list[POI], s: list[RoutineActivity]) -> None:
        """Home -> work -> home pattern."""
        work = waypoints[1] if len(waypoints) > 1 else self.hub

        # Parked overnight
        s.append(RoutineActivity(
            activity_type="parked", location=self.hub,
            start_time=0, duration=7 * _HOUR, priority=0,
        ))
        # Drive to work
        s.append(RoutineActivity(
            activity_type="drive", location=work,
            start_time=7 * _HOUR, duration=0.5 * _HOUR, priority=2,
        ))
        # Parked at work
        s.append(RoutineActivity(
            activity_type="parked", location=work,
            start_time=7.5 * _HOUR, duration=9 * _HOUR, priority=0,
        ))
        # Drive home
        s.append(RoutineActivity(
            activity_type="drive", location=self.hub,
            start_time=16.5 * _HOUR, duration=0.5 * _HOUR, priority=2,
        ))
        # Parked at home
        s.append(RoutineActivity(
            activity_type="parked", location=self.hub,
            start_time=17 * _HOUR, duration=7 * _HOUR, priority=0,
        ))

    def _build_delivery(self, waypoints: list[POI], s: list[RoutineActivity]) -> None:
        """Hub -> stop -> stop -> hub, repeating throughout the day."""
        stops = [w for w in waypoints if w is not self.hub]
        if not stops:
            stops = [self.hub]

        # Parked overnight
        s.append(RoutineActivity(
            activity_type="parked", location=self.hub,
            start_time=0, duration=6 * _HOUR, priority=0,
        ))

        t = 6 * _HOUR
        stop_idx = 0
        while t < 18 * _HOUR:
            dest = stops[stop_idx % len(stops)]
            # Drive to stop
            s.append(RoutineActivity(
                activity_type="drive", location=dest,
                start_time=t, duration=0.5 * _HOUR, priority=2,
            ))
            t += 0.5 * _HOUR
            # Parked at stop (unloading)
            s.append(RoutineActivity(
                activity_type="parked", location=dest,
                start_time=t, duration=0.25 * _HOUR, priority=1,
            ))
            t += 0.25 * _HOUR
            stop_idx += 1

        # Drive back to hub
        s.append(RoutineActivity(
            activity_type="drive", location=self.hub,
            start_time=t, duration=0.5 * _HOUR, priority=2,
        ))
        t += 0.5 * _HOUR

        # Parked overnight
        if t < 24 * _HOUR:
            s.append(RoutineActivity(
                activity_type="parked", location=self.hub,
                start_time=t, duration=24 * _HOUR - t, priority=0,
            ))

    def _build_patrol(self, waypoints: list[POI], s: list[RoutineActivity]) -> None:
        """Continuous patrol loop through waypoints."""
        stops = [w for w in waypoints if w is not self.hub]
        all_points = [self.hub] + stops

        # Parked at station briefly
        s.append(RoutineActivity(
            activity_type="parked", location=self.hub,
            start_time=0, duration=0.5 * _HOUR, priority=0,
        ))

        t = 0.5 * _HOUR
        wp_idx = 1
        while t < 23.5 * _HOUR:
            dest = all_points[wp_idx % len(all_points)]
            leg_duration = 0.5 * _HOUR
            s.append(RoutineActivity(
                activity_type="drive", location=dest,
                start_time=t, duration=leg_duration, priority=2,
            ))
            t += leg_duration
            wp_idx += 1

        # Park at end of shift
        if t < 24 * _HOUR:
            s.append(RoutineActivity(
                activity_type="parked", location=self.hub,
                start_time=t, duration=24 * _HOUR - t, priority=0,
            ))


# ============================================================================
# RoutineScheduler — manager for all NPC routines
# ============================================================================


class RoutineScheduler:
    """Assigns and manages daily routines for all NPCs."""

    def __init__(self, available_pois: list[POI]) -> None:
        self._pois = available_pois
        self._routines: dict[str, NPCRoutine | VehicleRoutine] = {}
        self._home_occupancy: dict[str, int] = {}  # poi.name -> count

    def assign_routine(
        self,
        npc_id: str,
        npc_type: str,
        personality: NPCPersonality,
        position: tuple[float, float],
        vehicle_role: str | None = None,
    ) -> NPCRoutine | VehicleRoutine | None:
        """Assign a daily routine to an NPC.

        Args:
            npc_id: unique NPC identifier
            npc_type: "person", "vehicle", or "animal"
            personality: NPC personality traits
            position: current (x, y) position for home assignment
            vehicle_role: "commuter", "delivery", "patrol" (for vehicles)
        """
        if npc_type == "vehicle":
            return self._assign_vehicle(npc_id, position, vehicle_role or "commuter")
        else:
            return self._assign_pedestrian(npc_id, personality, position)

    def current_activity(
        self, npc_id: str, sim_time: float
    ) -> RoutineActivity | None:
        """Get the current activity for an NPC."""
        routine = self._routines.get(npc_id)
        if routine is None:
            return None
        return routine.current_activity(sim_time)

    def destination(
        self, npc_id: str, sim_time: float
    ) -> tuple[float, float] | None:
        """Get the destination position for an NPC's current activity."""
        act = self.current_activity(npc_id, sim_time)
        if act is None or act.location is None:
            return None
        return act.location.position

    def remove_routine(self, npc_id: str) -> None:
        """Remove an NPC's routine."""
        self._routines.pop(npc_id, None)

    # -- Internal --

    def _assign_pedestrian(
        self,
        npc_id: str,
        personality: NPCPersonality,
        position: tuple[float, float],
    ) -> NPCRoutine:
        home = self._find_nearest_home(position)
        if home is None:
            # Create a virtual home POI at current position
            home = POI(
                position=position, poi_type="home",
                name=f"Home-{npc_id}", building_idx=None, capacity=4,
            )

        routine = NPCRoutine(npc_id, home, personality, self._pois)
        self._routines[npc_id] = routine
        return routine

    def _assign_vehicle(
        self,
        npc_id: str,
        position: tuple[float, float],
        role: str,
    ) -> VehicleRoutine:
        hub = self._find_nearest_home(position)
        if hub is None:
            hub = POI(
                position=position, poi_type="home",
                name=f"Hub-{npc_id}", building_idx=None, capacity=4,
            )

        routine = VehicleRoutine(npc_id, hub, role, self._pois)
        self._routines[npc_id] = routine
        return routine

    def _find_nearest_home(
        self, position: tuple[float, float]
    ) -> POI | None:
        """Find nearest home POI that isn't over capacity."""
        homes = [p for p in self._pois if p.poi_type == "home"]
        if not homes:
            return None

        # Sort by distance
        homes.sort(key=lambda p: math.hypot(
            p.position[0] - position[0],
            p.position[1] - position[1],
        ))

        # Prefer homes under capacity
        for h in homes:
            count = self._home_occupancy.get(h.name, 0)
            if count < h.capacity:
                self._home_occupancy[h.name] = count + 1
                return h

        # All full — just use nearest
        h = homes[0]
        self._home_occupancy[h.name] = self._home_occupancy.get(h.name, 0) + 1
        return h
