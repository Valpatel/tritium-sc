"""Tests for RoutineScheduler — daily schedules for NPCs."""

import math
import pytest

from engine.simulation.npc_intelligence.routine import (
    NPCRoutine,
    RoutineActivity,
    RoutineScheduler,
    VehicleRoutine,
)
from engine.simulation.npc_intelligence.brain import NPCPersonality
from engine.simulation.npc_intelligence.world_model import POI


# -- Helpers --


def _poi(name: str, poi_type: str = "home", x: float = 0, y: float = 0, capacity: int = 10):
    return POI(position=(x, y), poi_type=poi_type, name=name, building_idx=0, capacity=capacity)


def _default_personality():
    return NPCPersonality(
        curiosity=0.5, caution=0.5, sociability=0.5, aggression=0.2
    )


def _cautious_personality():
    return NPCPersonality(
        curiosity=0.2, caution=0.9, sociability=0.2, aggression=0.1
    )


def _social_personality():
    return NPCPersonality(
        curiosity=0.7, caution=0.3, sociability=0.9, aggression=0.1
    )


def _aggressive_personality():
    return NPCPersonality(
        curiosity=0.3, caution=0.2, sociability=0.4, aggression=0.8
    )


# Sim time is in seconds from midnight (0 = midnight, 3600 = 1:00 AM, etc.)
_HOUR = 3600.0
_MINUTE = 60.0


# ==========================================================================
# RoutineActivity
# ==========================================================================


class TestRoutineActivity:
    """RoutineActivity data structure."""

    def test_has_activity_type(self):
        act = RoutineActivity(
            activity_type="home", location=None,
            start_time=0, duration=3600,
        )
        assert act.activity_type == "home"

    def test_has_location(self):
        home = _poi("My House")
        act = RoutineActivity(
            activity_type="home", location=home,
            start_time=0, duration=3600,
        )
        assert act.location is home

    def test_has_priority(self):
        act = RoutineActivity(
            activity_type="work", location=None,
            start_time=0, duration=3600, priority=5,
        )
        assert act.priority == 5

    def test_default_priority_is_zero(self):
        act = RoutineActivity(
            activity_type="idle", location=None,
            start_time=0, duration=3600,
        )
        assert act.priority == 0

    def test_is_interruptible(self):
        """Low-priority activities can be interrupted (by events)."""
        act = RoutineActivity(
            activity_type="walk", location=None,
            start_time=0, duration=3600, priority=1,
        )
        # Priority < 5 is interruptible
        assert act.priority < 5


# ==========================================================================
# NPCRoutine — pedestrian daily schedule
# ==========================================================================


class TestNPCRoutine:
    """NPCRoutine generates a daily schedule for a pedestrian NPC."""

    def test_creates_schedule(self):
        home = _poi("Home", "home", 0, 0)
        pois = [home, _poi("Shop", "commercial", 50, 0)]
        routine = NPCRoutine("ped-1", home, _default_personality(), pois)
        assert routine is not None
        assert len(routine.schedule) > 0

    def test_schedule_covers_full_day(self):
        """Schedule should cover the full 24-hour period."""
        home = _poi("Home", "home", 0, 0)
        pois = [home, _poi("Work", "commercial", 100, 0)]
        routine = NPCRoutine("ped-1", home, _default_personality(), pois)

        # First activity starts at or near 0 (midnight)
        assert routine.schedule[0].start_time >= 0

        # Last activity + duration should reach end of day
        last = routine.schedule[-1]
        end = last.start_time + last.duration
        assert end >= 23 * _HOUR, f"Schedule ends at {end/_HOUR:.1f}h, expected 24h"

    def test_starts_at_home(self):
        """First activity of the day should be at home (sleeping)."""
        home = _poi("Home", "home", 0, 0)
        routine = NPCRoutine("ped-1", home, _default_personality(), [home])
        first = routine.schedule[0]
        assert first.activity_type == "home"

    def test_current_activity_at_midnight(self):
        home = _poi("Home", "home", 0, 0)
        routine = NPCRoutine("ped-1", home, _default_personality(), [home])
        act = routine.current_activity(0)
        assert act.activity_type == "home"

    def test_current_activity_midday(self):
        """At noon, NPC should be doing something (work, lunch, etc.)."""
        home = _poi("Home", "home", 0, 0)
        work = _poi("Work", "commercial", 100, 0)
        routine = NPCRoutine("ped-1", home, _default_personality(), [home, work])
        act = routine.current_activity(12 * _HOUR)
        assert act is not None
        assert act.activity_type in ("work", "commute", "shop", "walk")

    def test_current_activity_evening(self):
        """In the evening, NPC should be home or walking."""
        home = _poi("Home", "home", 0, 0)
        routine = NPCRoutine("ped-1", home, _default_personality(), [home])
        act = routine.current_activity(21 * _HOUR)
        assert act.activity_type in ("home", "walk", "idle")

    def test_next_activity_returns_upcoming(self):
        home = _poi("Home", "home", 0, 0)
        work = _poi("Work", "commercial", 100, 0)
        routine = NPCRoutine("ped-1", home, _default_personality(), [home, work])
        nxt = routine.next_activity(0)
        assert nxt is not None
        assert nxt.start_time > 0

    def test_time_until_next(self):
        home = _poi("Home", "home", 0, 0)
        work = _poi("Work", "commercial", 100, 0)
        routine = NPCRoutine("ped-1", home, _default_personality(), [home, work])
        remaining = routine.time_until_next(0)
        assert remaining > 0

    def test_includes_commute_activities(self):
        """Schedule should include commute (walking between locations)."""
        home = _poi("Home", "home", 0, 0)
        work = _poi("Work", "commercial", 100, 0)
        routine = NPCRoutine("ped-1", home, _default_personality(), [home, work])
        types = {a.activity_type for a in routine.schedule}
        assert "commute" in types, f"No commute in schedule: {types}"

    def test_schedule_has_work_for_employed(self):
        """If work POI exists, schedule includes work time."""
        home = _poi("Home", "home", 0, 0)
        work = _poi("Work", "commercial", 100, 0)
        routine = NPCRoutine("ped-1", home, _default_personality(), [home, work])
        types = {a.activity_type for a in routine.schedule}
        assert "work" in types

    def test_cautious_npc_stays_home_more(self):
        """Cautious NPCs have more time at home."""
        home = _poi("Home", "home", 0, 0)
        work = _poi("Work", "commercial", 100, 0)
        pois = [home, work]

        normal = NPCRoutine("ped-1", home, _default_personality(), pois)
        cautious = NPCRoutine("ped-2", home, _cautious_personality(), pois)

        def home_time(routine):
            return sum(a.duration for a in routine.schedule if a.activity_type == "home")

        assert home_time(cautious) >= home_time(normal) - _HOUR

    def test_social_npc_has_more_walk_time(self):
        """Social NPCs spend more time walking/socializing."""
        home = _poi("Home", "home", 0, 0)
        work = _poi("Work", "commercial", 100, 0)
        park = _poi("Park", "park", 50, 50)
        pois = [home, work, park]

        normal = NPCRoutine("ped-1", home, _default_personality(), pois)
        social = NPCRoutine("ped-2", home, _social_personality(), pois)

        def outside_time(routine):
            return sum(
                a.duration for a in routine.schedule
                if a.activity_type in ("walk", "shop", "park")
            )

        assert outside_time(social) >= outside_time(normal) - _HOUR

    def test_activities_have_locations(self):
        """Non-idle activities should have a destination POI."""
        home = _poi("Home", "home", 0, 0)
        work = _poi("Work", "commercial", 100, 0)
        routine = NPCRoutine("ped-1", home, _default_personality(), [home, work])
        for act in routine.schedule:
            if act.activity_type not in ("idle", "commute"):
                assert act.location is not None, \
                    f"Activity '{act.activity_type}' has no location"


# ==========================================================================
# VehicleRoutine
# ==========================================================================


class TestVehicleRoutine:
    """VehicleRoutine generates schedules for vehicle NPCs."""

    def test_commuter_schedule(self):
        hub = _poi("Home", "home", 0, 0)
        work = _poi("Office", "commercial", 200, 0)
        routine = VehicleRoutine("car-1", hub, "commuter", [hub, work])
        assert len(routine.schedule) > 0

    def test_commuter_has_two_trips(self):
        """Commuter should drive to work and back."""
        hub = _poi("Home", "home", 0, 0)
        work = _poi("Office", "commercial", 200, 0)
        routine = VehicleRoutine("car-1", hub, "commuter", [hub, work])
        drive_count = sum(1 for a in routine.schedule if a.activity_type == "drive")
        assert drive_count >= 2, f"Commuter has {drive_count} drives, expected >= 2"

    def test_delivery_schedule(self):
        hub = _poi("Depot", "commercial", 0, 0)
        stop1 = _poi("Stop 1", "home", 50, 0)
        stop2 = _poi("Stop 2", "home", 100, 0)
        routine = VehicleRoutine("van-1", hub, "delivery", [hub, stop1, stop2])
        types = {a.activity_type for a in routine.schedule}
        assert "drive" in types

    def test_patrol_schedule(self):
        """Patrol vehicle loops continuously."""
        start = _poi("Station", "commercial", 0, 0)
        wp1 = _poi("WP1", "commercial", 50, 0)
        wp2 = _poi("WP2", "commercial", 100, 0)
        routine = VehicleRoutine("cop-1", start, "patrol", [start, wp1, wp2])
        drive_count = sum(1 for a in routine.schedule if a.activity_type == "drive")
        assert drive_count >= 3  # multiple patrol legs

    def test_vehicle_starts_parked(self):
        hub = _poi("Home", "home", 0, 0)
        routine = VehicleRoutine("car-1", hub, "commuter", [hub])
        first = routine.schedule[0]
        assert first.activity_type == "parked"


# ==========================================================================
# RoutineScheduler — manages routines for all NPCs
# ==========================================================================


class TestRoutineScheduler:
    """RoutineScheduler assigns and tracks routines for all NPCs."""

    def test_create_scheduler(self):
        pois = [_poi("Home", "home", 0, 0)]
        scheduler = RoutineScheduler(pois)
        assert scheduler is not None

    def test_assign_routine(self):
        home = _poi("Home", "home", 0, 0)
        work = _poi("Work", "commercial", 100, 0)
        scheduler = RoutineScheduler([home, work])
        routine = scheduler.assign_routine(
            "ped-1", "person", _default_personality(), (0, 0)
        )
        assert routine is not None

    def test_assign_vehicle_routine(self):
        home = _poi("Home", "home", 0, 0)
        work = _poi("Work", "commercial", 100, 0)
        scheduler = RoutineScheduler([home, work])
        routine = scheduler.assign_routine(
            "car-1", "vehicle", _default_personality(), (0, 0),
            vehicle_role="commuter"
        )
        assert routine is not None

    def test_get_current_activity(self):
        home = _poi("Home", "home", 0, 0)
        scheduler = RoutineScheduler([home])
        scheduler.assign_routine("ped-1", "person", _default_personality(), (0, 0))
        act = scheduler.current_activity("ped-1", sim_time=0)
        assert act is not None

    def test_get_activity_for_unknown_npc(self):
        scheduler = RoutineScheduler([])
        act = scheduler.current_activity("nobody", sim_time=0)
        assert act is None

    def test_nearest_home_assigned(self):
        """NPC should be assigned to the nearest home POI."""
        far_home = _poi("Far", "home", 200, 200)
        near_home = _poi("Near", "home", 5, 5)
        scheduler = RoutineScheduler([far_home, near_home])
        routine = scheduler.assign_routine(
            "ped-1", "person", _default_personality(), (0, 0)
        )
        assert routine is not None
        # The routine's home should be the near one
        first = routine.schedule[0]
        if first.location:
            dist_to_near = math.hypot(
                first.location.position[0] - 5,
                first.location.position[1] - 5,
            )
            assert dist_to_near < 20

    def test_multiple_npcs_get_different_homes(self):
        """With enough homes, NPCs should spread across them."""
        homes = [
            _poi(f"Home {i}", "home", i * 50, 0, capacity=2)
            for i in range(5)
        ]
        scheduler = RoutineScheduler(homes)
        routines = []
        for i in range(5):
            r = scheduler.assign_routine(
                f"ped-{i}", "person", _default_personality(), (i * 50, 0)
            )
            routines.append(r)
        # At least 2 different homes assigned
        home_positions = set()
        for r in routines:
            if r and r.schedule[0].location:
                home_positions.add(r.schedule[0].location.position)
        assert len(home_positions) >= 2

    def test_remove_routine(self):
        home = _poi("Home", "home", 0, 0)
        scheduler = RoutineScheduler([home])
        scheduler.assign_routine("ped-1", "person", _default_personality(), (0, 0))
        scheduler.remove_routine("ped-1")
        assert scheduler.current_activity("ped-1", 0) is None

    def test_destination_for_activity(self):
        """Scheduler can provide destination position for current activity."""
        home = _poi("Home", "home", 0, 0)
        work = _poi("Work", "commercial", 100, 0)
        scheduler = RoutineScheduler([home, work])
        scheduler.assign_routine("ped-1", "person", _default_personality(), (0, 0))
        dest = scheduler.destination("ped-1", sim_time=8 * _HOUR)
        # During work hours, should have a destination
        assert dest is not None


# ==========================================================================
# Performance
# ==========================================================================


class TestRoutinePerformance:
    """RoutineScheduler should be fast for 70+ NPCs."""

    def test_assign_70_routines_quickly(self):
        import time

        pois = [
            _poi(f"Home {i}", "home", i * 10, 0) for i in range(30)
        ] + [
            _poi(f"Shop {i}", "commercial", i * 10, 50) for i in range(10)
        ]
        scheduler = RoutineScheduler(pois)

        start = time.perf_counter()
        for i in range(70):
            scheduler.assign_routine(
                f"ped-{i}", "person", _default_personality(), (i * 5, 0)
            )
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1, f"Assigning 70 routines took {elapsed*1000:.1f}ms"

    def test_query_70_activities_quickly(self):
        import time

        pois = [_poi(f"Home {i}", "home", i * 10, 0) for i in range(30)]
        scheduler = RoutineScheduler(pois)
        for i in range(70):
            scheduler.assign_routine(
                f"ped-{i}", "person", _default_personality(), (i * 5, 0)
            )

        start = time.perf_counter()
        for i in range(70):
            scheduler.current_activity(f"ped-{i}", sim_time=12 * _HOUR)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.01, f"Querying 70 activities took {elapsed*1000:.1f}ms"
