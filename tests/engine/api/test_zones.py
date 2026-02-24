"""Unit tests for zone management — models, checker, manager.

Tests Zone geometry (point-in-polygon, bbox overlap), ZoneManager CRUD,
event detection with cooldowns, and ZoneChecker camera caching.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.zones.models import Zone, ZoneEvent, ZoneType, ZoneEventType
from app.zones.manager import ZoneManager
from app.zones.checker import ZoneChecker


# --- Zone geometry tests ---

@pytest.mark.unit
class TestZoneContainsPoint:
    """Zone.contains_point — ray-casting point-in-polygon."""

    def _square_zone(self) -> Zone:
        """A 100x100 square zone from (0,0) to (100,100)."""
        return Zone(
            zone_id="z1", camera_id=1, name="Square",
            polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
            zone_type=ZoneType.ACTIVITY,
        )

    def test_center_inside(self):
        assert self._square_zone().contains_point(50, 50) is True

    def test_outside_right(self):
        assert self._square_zone().contains_point(150, 50) is False

    def test_outside_above(self):
        assert self._square_zone().contains_point(50, -10) is False

    def test_origin_inside(self):
        """Point near the origin corner should be inside."""
        assert self._square_zone().contains_point(1, 1) is True

    def test_far_corner_inside(self):
        assert self._square_zone().contains_point(99, 99) is True

    def test_triangle_zone(self):
        z = Zone(
            zone_id="z2", camera_id=1, name="Triangle",
            polygon=[(0, 0), (100, 0), (50, 100)],
            zone_type=ZoneType.TRIPWIRE,
        )
        assert z.contains_point(50, 50) is True
        assert z.contains_point(10, 90) is False

    def test_degenerate_polygon(self):
        """Less than 3 points should never contain anything."""
        z = Zone(
            zone_id="z3", camera_id=1, name="Line",
            polygon=[(0, 0), (100, 100)],
            zone_type=ZoneType.ACTIVITY,
        )
        assert z.contains_point(50, 50) is False


@pytest.mark.unit
class TestZoneContainsBbox:
    """Zone.contains_bbox — bounding box overlap detection."""

    def _square_zone(self) -> Zone:
        return Zone(
            zone_id="z1", camera_id=1, name="Square",
            polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
            zone_type=ZoneType.ACTIVITY,
        )

    def test_bbox_centered_inside(self):
        """Bbox fully inside zone — center check passes."""
        assert self._square_zone().contains_bbox((40, 40, 60, 60)) is True

    def test_bbox_fully_outside(self):
        assert self._square_zone().contains_bbox((200, 200, 300, 300)) is False

    def test_bbox_partially_overlapping(self):
        """Bbox straddles right edge — 2/4 corners inside >= 0.5."""
        assert self._square_zone().contains_bbox((80, 40, 120, 60)) is True

    def test_bbox_barely_touching(self):
        """Bbox mostly outside — only 1/4 corners inside < 0.5."""
        result = self._square_zone().contains_bbox((90, 90, 200, 200))
        # Center is at (145, 145) — outside. Corners: (90,90) inside, rest outside = 1/4 < 0.5
        # But center (145,145) is outside, so contains_point for center is False
        # Only 1 corner inside = 0.25 < 0.5
        assert result is False

    def test_bbox_center_in_zone(self):
        """Even if only center is in zone, returns True."""
        assert self._square_zone().contains_bbox((45, 45, 55, 55)) is True


@pytest.mark.unit
class TestZoneSerialization:
    """Zone.to_dict / Zone.from_dict round-trip."""

    def test_round_trip(self):
        z = Zone(
            zone_id="z1", camera_id=5, name="Driveway",
            polygon=[(10, 20), (30, 40), (50, 60)],
            zone_type=ZoneType.ENTRY_EXIT,
            cooldown_seconds=45,
            total_events=7,
        )
        d = z.to_dict()
        z2 = Zone.from_dict(d)
        assert z2.zone_id == "z1"
        assert z2.camera_id == 5
        assert z2.name == "Driveway"
        assert z2.polygon == [(10, 20), (30, 40), (50, 60)]
        assert z2.zone_type == ZoneType.ENTRY_EXIT
        assert z2.cooldown_seconds == 45
        assert z2.total_events == 7

    def test_all_zone_types(self):
        for zt in ZoneType:
            z = Zone(
                zone_id=f"z_{zt.value}", camera_id=1, name=zt.value,
                polygon=[(0, 0), (1, 0), (1, 1)],
                zone_type=zt,
            )
            d = z.to_dict()
            z2 = Zone.from_dict(d)
            assert z2.zone_type == zt


@pytest.mark.unit
class TestZoneEventSerialization:
    """ZoneEvent.to_dict / ZoneEvent.from_dict round-trip."""

    def test_round_trip(self):
        now = datetime(2026, 2, 20, 12, 0, 0)
        e = ZoneEvent(
            event_id="evt_1", zone_id="z1", zone_name="Driveway",
            event_type=ZoneEventType.ENTER, timestamp=now,
            camera_id=1, target_type="person",
        )
        d = e.to_dict()
        e2 = ZoneEvent.from_dict(d)
        assert e2.event_id == "evt_1"
        assert e2.event_type == ZoneEventType.ENTER
        assert e2.target_type == "person"

    def test_all_event_types(self):
        for et in ZoneEventType:
            e = ZoneEvent(
                event_id=f"evt_{et.value}", zone_id="z1", zone_name="Test",
                event_type=et, timestamp=datetime.now(), camera_id=1,
            )
            d = e.to_dict()
            e2 = ZoneEvent.from_dict(d)
            assert e2.event_type == et


# --- ZoneManager tests ---

@pytest.mark.unit
class TestZoneManagerCRUD:
    """ZoneManager create/read/update/delete."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.mgr = ZoneManager(tmp_path / "zones")

    def test_create_zone(self):
        z = self.mgr.create_zone(
            camera_id=1, name="Front Yard",
            polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
            zone_type=ZoneType.ACTIVITY,
        )
        assert z.zone_id.startswith("zone_")
        assert z.name == "Front Yard"
        assert z.camera_id == 1

    def test_get_zone(self):
        z = self.mgr.create_zone(1, "Test", [(0, 0), (1, 0), (1, 1)], ZoneType.ACTIVITY)
        found = self.mgr.get_zone(z.zone_id)
        assert found is not None
        assert found.name == "Test"

    def test_get_zone_not_found(self):
        assert self.mgr.get_zone("nonexistent") is None

    def test_get_zones_for_camera(self):
        self.mgr.create_zone(1, "A", [(0, 0), (1, 0), (1, 1)], ZoneType.ACTIVITY)
        self.mgr.create_zone(1, "B", [(2, 2), (3, 2), (3, 3)], ZoneType.TRIPWIRE)
        self.mgr.create_zone(2, "C", [(0, 0), (1, 0), (1, 1)], ZoneType.ENTRY_EXIT)

        cam1_zones = self.mgr.get_zones_for_camera(1)
        assert len(cam1_zones) == 2
        cam2_zones = self.mgr.get_zones_for_camera(2)
        assert len(cam2_zones) == 1

    def test_get_all_zones(self):
        self.mgr.create_zone(1, "A", [(0, 0), (1, 0), (1, 1)], ZoneType.ACTIVITY)
        self.mgr.create_zone(2, "B", [(0, 0), (1, 0), (1, 1)], ZoneType.ACTIVITY)
        assert len(self.mgr.get_all_zones()) == 2

    def test_update_zone(self):
        z = self.mgr.create_zone(1, "Old Name", [(0, 0), (1, 0), (1, 1)], ZoneType.ACTIVITY)
        updated = self.mgr.update_zone(z.zone_id, name="New Name", enabled=False)
        assert updated is not None
        assert updated.name == "New Name"
        assert updated.enabled is False

    def test_update_nonexistent(self):
        assert self.mgr.update_zone("fake_id", name="X") is None

    def test_delete_zone(self):
        z = self.mgr.create_zone(1, "Temp", [(0, 0), (1, 0), (1, 1)], ZoneType.ACTIVITY)
        assert self.mgr.delete_zone(z.zone_id) is True
        assert self.mgr.get_zone(z.zone_id) is None

    def test_delete_nonexistent(self):
        assert self.mgr.delete_zone("fake_id") is False

    def test_persistence(self, tmp_path):
        """Zones persist across manager instances."""
        path = tmp_path / "persist"
        mgr1 = ZoneManager(path)
        mgr1.create_zone(1, "Persist", [(0, 0), (1, 0), (1, 1)], ZoneType.ACTIVITY)

        mgr2 = ZoneManager(path)
        assert len(mgr2.get_all_zones()) == 1
        assert mgr2.get_all_zones()[0].name == "Persist"


@pytest.mark.unit
class TestZoneManagerDetection:
    """ZoneManager.check_detections — event generation."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.mgr = ZoneManager(tmp_path / "zones")
        self.zone = self.mgr.create_zone(
            camera_id=1, name="Test Zone",
            polygon=[(0, 0), (200, 0), (200, 200), (0, 200)],
            zone_type=ZoneType.ACTIVITY,
            cooldown_seconds=5,
        )

    def test_detection_inside_triggers_event(self):
        events = self.mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 100, 100), "class_name": "person", "confidence": 0.9}],
            timestamp=datetime.now(),
            video_path="test.mp4",
            frame_number=42,
        )
        assert len(events) == 1
        assert events[0].target_type == "person"
        assert events[0].zone_name == "Test Zone"

    def test_detection_outside_no_event(self):
        events = self.mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (500, 500, 600, 600), "class_name": "person", "confidence": 0.9}],
            timestamp=datetime.now(),
            video_path="test.mp4",
            frame_number=42,
        )
        assert len(events) == 0

    def test_cooldown_suppresses_events(self):
        now = datetime.now()
        # First detection
        events1 = self.mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 100, 100), "class_name": "person", "confidence": 0.9}],
            timestamp=now,
            video_path="test.mp4", frame_number=1,
        )
        assert len(events1) == 1

        # Second detection 1 second later (within cooldown)
        events2 = self.mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 100, 100), "class_name": "person", "confidence": 0.9}],
            timestamp=now + timedelta(seconds=1),
            video_path="test.mp4", frame_number=2,
        )
        assert len(events2) == 0  # Suppressed by cooldown

    def test_cooldown_expires(self):
        now = datetime.now()
        self.mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 100, 100), "class_name": "person", "confidence": 0.9}],
            timestamp=now,
            video_path="test.mp4", frame_number=1,
        )

        # After cooldown expires (6 > 5 seconds)
        events = self.mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 100, 100), "class_name": "person", "confidence": 0.9}],
            timestamp=now + timedelta(seconds=6),
            video_path="test.mp4", frame_number=2,
        )
        assert len(events) == 1

    def test_disabled_zone_ignored(self):
        self.mgr.update_zone(self.zone.zone_id, enabled=False)
        events = self.mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 100, 100), "class_name": "person", "confidence": 0.9}],
            timestamp=datetime.now(),
            video_path="test.mp4", frame_number=1,
        )
        assert len(events) == 0

    def test_wrong_camera_no_events(self):
        events = self.mgr.check_detections(
            camera_id=99,  # Wrong camera
            detections=[{"bbox": (50, 50, 100, 100), "class_name": "person", "confidence": 0.9}],
            timestamp=datetime.now(),
            video_path="test.mp4", frame_number=1,
        )
        assert len(events) == 0


@pytest.mark.unit
class TestZoneManagerQueries:
    """ZoneManager event query methods."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.mgr = ZoneManager(tmp_path / "zones")
        self.zone = self.mgr.create_zone(
            camera_id=1, name="Front Yard",
            polygon=[(0, 0), (500, 0), (500, 500), (0, 500)],
            zone_type=ZoneType.ACTIVITY,
            cooldown_seconds=0,  # No cooldown for query tests
        )

    def _add_events(self, count: int, hours_apart: float = 1.0) -> list[ZoneEvent]:
        now = datetime(2026, 2, 20, 12, 0, 0)
        events = []
        for i in range(count):
            result = self.mgr.check_detections(
                camera_id=1,
                detections=[{"bbox": (50, 50, 100, 100), "class_name": "person", "confidence": 0.9}],
                timestamp=now + timedelta(hours=i * hours_apart),
                video_path="test.mp4", frame_number=i,
            )
            events.extend(result)
        return events

    def test_get_events_for_zone(self):
        self._add_events(5)
        events = self.mgr.get_events_for_zone(self.zone.zone_id)
        assert len(events) == 5

    def test_events_sorted_recent_first(self):
        self._add_events(3)
        events = self.mgr.get_events_for_zone(self.zone.zone_id)
        assert events[0].timestamp > events[1].timestamp

    def test_events_limit(self):
        self._add_events(10)
        events = self.mgr.get_events_for_zone(self.zone.zone_id, limit=3)
        assert len(events) == 3

    def test_events_by_target_type(self):
        self._add_events(3)
        events = self.mgr.get_events_by_target(target_type="person")
        assert len(events) == 3
        events = self.mgr.get_events_by_target(target_type="vehicle")
        assert len(events) == 0

    def test_zone_summary(self):
        self._add_events(3)
        summary = self.mgr.get_zone_summary(self.zone.zone_id)
        assert summary["zone_name"] == "Front Yard"
        assert summary["total_events"] == 3
        assert "person" in summary["events_by_type"]
        assert len(summary["hourly_distribution"]) == 24


# --- ZoneChecker tests ---

@pytest.mark.unit
class TestZoneChecker:
    """ZoneChecker — wraps ZoneManager with camera caching."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.mgr = ZoneManager(tmp_path / "zones")
        self.checker = ZoneChecker(self.mgr)
        self.zone = self.mgr.create_zone(
            camera_id=1, name="Entry",
            polygon=[(0, 0), (200, 0), (200, 200), (0, 200)],
            zone_type=ZoneType.ENTRY_EXIT,
        )

    def test_get_zones_cached(self):
        zones1 = self.checker.get_zones_for_camera(1)
        zones2 = self.checker.get_zones_for_camera(1)
        assert zones1 is zones2  # Same object — cached

    def test_clear_cache(self):
        zones1 = self.checker.get_zones_for_camera(1)
        self.checker.clear_cache()
        zones2 = self.checker.get_zones_for_camera(1)
        assert zones1 is not zones2  # Different object — cache cleared

    def test_check_frame_detections(self):
        det = type("Det", (), {
            "bbox": (50, 50, 100, 100),
            "class_name": "person",
            "confidence": 0.85,
            "center": (75, 75),
        })()
        events = self.checker.check_frame_detections(
            camera_id=1,
            detections=[det],
            timestamp=datetime.now(),
            video_path="test.mp4",
            frame_number=1,
        )
        assert len(events) == 1

    def test_no_zones_for_camera(self):
        events = self.checker.check_frame_detections(
            camera_id=99,
            detections=[type("Det", (), {
                "bbox": (50, 50, 100, 100),
                "class_name": "person",
                "confidence": 0.85,
                "center": (75, 75),
            })()],
            timestamp=datetime.now(),
            video_path="test.mp4",
            frame_number=1,
        )
        assert len(events) == 0
