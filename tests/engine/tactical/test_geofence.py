# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for GeofenceEngine — point-in-polygon, enter/exit detection, edge cases."""

import pytest
import queue

from tritium_lib.tracking.geofence import (
    GeoZone,
    GeoEvent,
    GeofenceEngine,
    point_in_polygon,
)
from engine.comms.event_bus import EventBus


# ------------------------------------------------------------------
# point_in_polygon unit tests
# ------------------------------------------------------------------

class TestPointInPolygon:
    """Ray-casting algorithm tests."""

    def _square(self):
        """Unit square: (0,0), (10,0), (10,10), (0,10)."""
        return [(0, 0), (10, 0), (10, 10), (0, 10)]

    def test_inside_square(self):
        assert point_in_polygon(5, 5, self._square()) is True

    def test_outside_square(self):
        assert point_in_polygon(15, 5, self._square()) is False

    def test_outside_negative(self):
        assert point_in_polygon(-1, 5, self._square()) is False

    def test_above_square(self):
        assert point_in_polygon(5, 15, self._square()) is False

    def test_below_square(self):
        assert point_in_polygon(5, -1, self._square()) is False

    def test_near_edge(self):
        """Point just inside the polygon boundary."""
        assert point_in_polygon(0.1, 0.1, self._square()) is True

    def test_triangle_inside(self):
        tri = [(0, 0), (10, 0), (5, 10)]
        assert point_in_polygon(5, 3, tri) is True

    def test_triangle_outside(self):
        tri = [(0, 0), (10, 0), (5, 10)]
        assert point_in_polygon(1, 8, tri) is False

    def test_concave_polygon_inside(self):
        """L-shaped concave polygon."""
        poly = [(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)]
        # Inside bottom-left arm
        assert point_in_polygon(2, 2, poly) is True
        # Inside left arm upper
        assert point_in_polygon(2, 8, poly) is True

    def test_concave_polygon_outside_concavity(self):
        """Point in the concavity (outside the polygon)."""
        poly = [(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)]
        assert point_in_polygon(8, 8, poly) is False

    def test_degenerate_polygon_too_few_points(self):
        assert point_in_polygon(5, 5, [(0, 0), (10, 0)]) is False
        assert point_in_polygon(5, 5, [(0, 0)]) is False
        assert point_in_polygon(5, 5, []) is False

    def test_large_polygon(self):
        """Many-sided polygon (circle approximation)."""
        import math
        n = 100
        poly = [(math.cos(2 * math.pi * i / n) * 50,
                 math.sin(2 * math.pi * i / n) * 50) for i in range(n)]
        assert point_in_polygon(0, 0, poly) is True
        assert point_in_polygon(60, 0, poly) is False


# ------------------------------------------------------------------
# GeofenceEngine tests
# ------------------------------------------------------------------

class TestGeofenceEngine:
    """Enter/exit detection and zone management."""

    def _make_square_zone(self, zone_id="z1", name="Test Zone",
                          zone_type="monitored", alert_enter=True,
                          alert_exit=True):
        return GeoZone(
            zone_id=zone_id,
            name=name,
            polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
            zone_type=zone_type,
            alert_on_enter=alert_enter,
            alert_on_exit=alert_exit,
        )

    def test_add_and_list_zones(self):
        engine = GeofenceEngine()
        z = self._make_square_zone()
        engine.add_zone(z)
        zones = engine.list_zones()
        assert len(zones) == 1
        assert zones[0].zone_id == "z1"

    def test_remove_zone(self):
        engine = GeofenceEngine()
        engine.add_zone(self._make_square_zone())
        assert engine.remove_zone("z1") is True
        assert engine.list_zones() == []

    def test_remove_nonexistent_zone(self):
        engine = GeofenceEngine()
        assert engine.remove_zone("nope") is False

    def test_get_zone(self):
        engine = GeofenceEngine()
        engine.add_zone(self._make_square_zone())
        assert engine.get_zone("z1") is not None
        assert engine.get_zone("nope") is None

    def test_enter_detection(self):
        engine = GeofenceEngine()
        engine.add_zone(self._make_square_zone())

        # Target starts outside
        events = engine.check("t1", (15, 15))
        enters = [e for e in events if e.event_type == "enter"]
        assert len(enters) == 0

        # Target moves inside
        events = engine.check("t1", (5, 5))
        enters = [e for e in events if e.event_type == "enter"]
        assert len(enters) == 1
        assert enters[0].zone_id == "z1"
        assert enters[0].target_id == "t1"

    def test_exit_detection(self):
        engine = GeofenceEngine()
        engine.add_zone(self._make_square_zone())

        # Enter
        engine.check("t1", (5, 5))
        # Exit
        events = engine.check("t1", (15, 15))
        exits = [e for e in events if e.event_type == "exit"]
        assert len(exits) == 1
        assert exits[0].zone_id == "z1"

    def test_inside_repeated(self):
        """Staying inside should produce 'inside' events, not repeated 'enter'."""
        engine = GeofenceEngine()
        engine.add_zone(self._make_square_zone())

        events1 = engine.check("t1", (5, 5))
        assert any(e.event_type == "enter" for e in events1)

        events2 = engine.check("t1", (6, 6))
        assert not any(e.event_type == "enter" for e in events2)
        assert any(e.event_type == "inside" for e in events2)

    def test_multiple_zones(self):
        engine = GeofenceEngine()
        z1 = GeoZone(
            zone_id="z1", name="Zone A",
            polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
        )
        z2 = GeoZone(
            zone_id="z2", name="Zone B",
            polygon=[(20, 20), (30, 20), (30, 30), (20, 30)],
        )
        engine.add_zone(z1)
        engine.add_zone(z2)

        # Enter zone A only
        events = engine.check("t1", (5, 5))
        enters = [e for e in events if e.event_type == "enter"]
        assert len(enters) == 1
        assert enters[0].zone_id == "z1"

        # Move to zone B (exit A, enter B)
        events = engine.check("t1", (25, 25))
        exits = [e for e in events if e.event_type == "exit"]
        enters = [e for e in events if e.event_type == "enter"]
        assert len(exits) == 1
        assert exits[0].zone_id == "z1"
        assert len(enters) == 1
        assert enters[0].zone_id == "z2"

    def test_overlapping_zones(self):
        """Target in overlapping zones should enter both."""
        engine = GeofenceEngine()
        z1 = GeoZone(
            zone_id="z1", name="Big Zone",
            polygon=[(0, 0), (20, 0), (20, 20), (0, 20)],
        )
        z2 = GeoZone(
            zone_id="z2", name="Small Zone",
            polygon=[(3, 3), (7, 3), (7, 7), (3, 7)],
        )
        engine.add_zone(z1)
        engine.add_zone(z2)

        events = engine.check("t1", (5, 5))
        enters = [e for e in events if e.event_type == "enter"]
        assert len(enters) == 2
        zone_ids = {e.zone_id for e in enters}
        assert zone_ids == {"z1", "z2"}

    def test_disabled_zone_ignored(self):
        engine = GeofenceEngine()
        z = self._make_square_zone()
        z.enabled = False
        engine.add_zone(z)

        events = engine.check("t1", (5, 5))
        assert len(events) == 0

    def test_multiple_targets(self):
        engine = GeofenceEngine()
        engine.add_zone(self._make_square_zone())

        events_a = engine.check("t1", (5, 5))
        events_b = engine.check("t2", (5, 5))

        assert any(e.event_type == "enter" and e.target_id == "t1" for e in events_a)
        assert any(e.event_type == "enter" and e.target_id == "t2" for e in events_b)

    def test_event_log(self):
        engine = GeofenceEngine()
        engine.add_zone(self._make_square_zone())

        engine.check("t1", (5, 5))  # enter
        engine.check("t1", (15, 15))  # exit

        events = engine.get_events()
        assert len(events) == 2
        # Most recent first
        assert events[0].event_type == "exit"
        assert events[1].event_type == "enter"

    def test_event_log_filter_by_zone(self):
        engine = GeofenceEngine()
        engine.add_zone(self._make_square_zone("z1", "A"))
        engine.add_zone(GeoZone(
            zone_id="z2", name="B",
            polygon=[(20, 20), (30, 20), (30, 30), (20, 30)],
        ))

        engine.check("t1", (5, 5))
        engine.check("t2", (25, 25))

        events_z1 = engine.get_events(zone_id="z1")
        assert all(e.zone_id == "z1" for e in events_z1)
        assert len(events_z1) == 1

    def test_event_log_filter_by_type(self):
        engine = GeofenceEngine()
        engine.add_zone(self._make_square_zone())

        engine.check("t1", (5, 5))
        engine.check("t1", (15, 15))

        enters = engine.get_events(event_type="enter")
        exits = engine.get_events(event_type="exit")
        assert len(enters) == 1
        assert len(exits) == 1

    def test_get_target_zones(self):
        engine = GeofenceEngine()
        engine.add_zone(self._make_square_zone())

        assert engine.get_target_zones("t1") == set()
        engine.check("t1", (5, 5))
        assert engine.get_target_zones("t1") == {"z1"}
        engine.check("t1", (15, 15))
        assert engine.get_target_zones("t1") == set()

    def test_zone_removal_cleans_target_state(self):
        engine = GeofenceEngine()
        engine.add_zone(self._make_square_zone())
        engine.check("t1", (5, 5))
        assert engine.get_target_zones("t1") == {"z1"}

        engine.remove_zone("z1")
        assert engine.get_target_zones("t1") == set()


# ------------------------------------------------------------------
# EventBus integration
# ------------------------------------------------------------------

class TestGeofenceEventBus:
    """Verify geofence publishes to EventBus."""

    def test_enter_event_published(self):
        bus = EventBus()
        sub = bus.subscribe()
        engine = GeofenceEngine(event_bus=bus)
        engine.add_zone(GeoZone(
            zone_id="z1", name="Test",
            polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
            alert_on_enter=True,
        ))

        engine.check("t1", (5, 5))

        msg = sub.get(timeout=1)
        assert msg["type"] == "geofence:enter"
        assert msg["data"]["target_id"] == "t1"
        assert msg["data"]["zone_id"] == "z1"

    def test_exit_event_published(self):
        bus = EventBus()
        sub = bus.subscribe()
        engine = GeofenceEngine(event_bus=bus)
        engine.add_zone(GeoZone(
            zone_id="z1", name="Test",
            polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
            alert_on_exit=True,
        ))

        engine.check("t1", (5, 5))
        # Drain enter event
        sub.get(timeout=1)

        engine.check("t1", (15, 15))
        msg = sub.get(timeout=1)
        assert msg["type"] == "geofence:exit"
        assert msg["data"]["target_id"] == "t1"

    def test_no_event_when_alert_disabled(self):
        bus = EventBus()
        sub = bus.subscribe()
        engine = GeofenceEngine(event_bus=bus)
        engine.add_zone(GeoZone(
            zone_id="z1", name="Test",
            polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
            alert_on_enter=False,
            alert_on_exit=False,
        ))

        engine.check("t1", (5, 5))
        engine.check("t1", (15, 15))

        # Queue should be empty (no alerts published)
        assert sub.empty()


# ------------------------------------------------------------------
# GeoZone / GeoEvent serialization
# ------------------------------------------------------------------

class TestSerialization:

    def test_geozone_to_dict(self):
        z = GeoZone(
            zone_id="z1", name="Test", polygon=[(0, 0), (1, 1), (2, 0)],
            zone_type="restricted",
        )
        d = z.to_dict()
        assert d["zone_id"] == "z1"
        assert d["zone_type"] == "restricted"
        assert len(d["polygon"]) == 3

    def test_geoevent_to_dict(self):
        e = GeoEvent(
            event_id="e1", event_type="enter", target_id="t1",
            zone_id="z1", zone_name="Test", zone_type="monitored",
            position=(5.0, 5.0), timestamp=1000.0,
        )
        d = e.to_dict()
        assert d["event_type"] == "enter"
        assert d["position"] == [5.0, 5.0]
