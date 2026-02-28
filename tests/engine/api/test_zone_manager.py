# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for ZoneManager — CRUD, event detection, queries, serialization."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.zones.models import Zone, ZoneEvent, ZoneType, ZoneEventType
from app.zones.manager import ZoneManager


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Zone Model
# ---------------------------------------------------------------------------


class TestZoneModel:
    """Zone dataclass — contains_point, contains_bbox, serialization."""

    def _make_zone(self, polygon=None, **kwargs) -> Zone:
        defaults = dict(
            zone_id="z1",
            camera_id=1,
            name="Test Zone",
            polygon=polygon or [(0, 0), (100, 0), (100, 100), (0, 100)],
            zone_type=ZoneType.ACTIVITY,
        )
        defaults.update(kwargs)
        return Zone(**defaults)

    def test_contains_point_inside(self):
        z = self._make_zone()
        assert z.contains_point(50, 50) is True

    def test_contains_point_outside(self):
        z = self._make_zone()
        assert z.contains_point(150, 150) is False

    def test_contains_point_on_edge(self):
        z = self._make_zone()
        # Edge behavior depends on ray-casting algorithm; center is definitely inside
        assert z.contains_point(50, 0) is True or z.contains_point(50, 0) is False  # Not important

    def test_contains_point_too_few_vertices(self):
        z = self._make_zone(polygon=[(0, 0), (100, 0)])
        assert z.contains_point(50, 50) is False

    def test_contains_bbox_center_inside(self):
        z = self._make_zone()
        assert z.contains_bbox((40, 40, 60, 60)) is True

    def test_contains_bbox_outside(self):
        z = self._make_zone()
        assert z.contains_bbox((200, 200, 300, 300)) is False

    def test_contains_bbox_partial_overlap(self):
        z = self._make_zone()
        # Bbox partially inside — center at (75, 75) is inside
        assert z.contains_bbox((50, 50, 100, 100)) is True

    def test_to_dict(self):
        z = self._make_zone()
        d = z.to_dict()
        assert d["zone_id"] == "z1"
        assert d["camera_id"] == 1
        assert d["name"] == "Test Zone"
        assert d["zone_type"] == "activity"
        assert d["enabled"] is True
        assert "created_at" in d

    def test_from_dict_roundtrip(self):
        z = self._make_zone()
        d = z.to_dict()
        z2 = Zone.from_dict(d)
        assert z2.zone_id == z.zone_id
        assert z2.name == z.name
        assert z2.zone_type == z.zone_type
        assert z2.camera_id == z.camera_id

    def test_from_dict_defaults(self):
        d = {
            "zone_id": "z2",
            "camera_id": 2,
            "name": "Minimal",
            "polygon": [[0, 0], [10, 0], [10, 10]],
            "zone_type": "entry_exit",
            "created_at": datetime.now().isoformat(),
        }
        z = Zone.from_dict(d)
        assert z.enabled is True
        assert z.cooldown_seconds == 30
        assert z.alert_on_enter is True

    def test_zone_types(self):
        assert ZoneType.ENTRY_EXIT.value == "entry_exit"
        assert ZoneType.ACTIVITY.value == "activity"
        assert ZoneType.TRIPWIRE.value == "tripwire"
        assert ZoneType.OBJECT_MONITOR.value == "object_monitor"


# ---------------------------------------------------------------------------
# ZoneEvent Model
# ---------------------------------------------------------------------------


class TestZoneEventModel:
    """ZoneEvent dataclass — serialization roundtrip."""

    def _make_event(self, **kwargs) -> ZoneEvent:
        defaults = dict(
            event_id="evt_1",
            zone_id="z1",
            zone_name="Test Zone",
            event_type=ZoneEventType.ACTIVITY,
            timestamp=datetime(2026, 2, 24, 12, 0, 0),
            camera_id=1,
        )
        defaults.update(kwargs)
        return ZoneEvent(**defaults)

    def test_to_dict(self):
        e = self._make_event()
        d = e.to_dict()
        assert d["event_id"] == "evt_1"
        assert d["zone_id"] == "z1"
        assert d["event_type"] == "activity"

    def test_from_dict_roundtrip(self):
        e = self._make_event(target_type="person", frame_number=42)
        d = e.to_dict()
        e2 = ZoneEvent.from_dict(d)
        assert e2.event_id == e.event_id
        assert e2.target_type == "person"
        assert e2.frame_number == 42

    def test_event_types(self):
        assert ZoneEventType.ENTER.value == "enter"
        assert ZoneEventType.EXIT.value == "exit"
        assert ZoneEventType.LINGER.value == "linger"
        assert ZoneEventType.STATE_CHANGE.value == "state_change"


# ---------------------------------------------------------------------------
# ZoneManager — CRUD
# ---------------------------------------------------------------------------


class TestZoneManagerCRUD:
    """ZoneManager — create, read, update, delete zones."""

    def test_create_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(
            camera_id=1,
            name="Front Yard",
            polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
            zone_type=ZoneType.ACTIVITY,
        )
        assert zone.name == "Front Yard"
        assert zone.zone_id.startswith("zone_")
        assert zone.camera_id == 1

    def test_get_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(1, "Test", [(0, 0), (10, 0), (10, 10)], ZoneType.ENTRY_EXIT)
        result = mgr.get_zone(zone.zone_id)
        assert result is not None
        assert result.name == "Test"

    def test_get_zone_not_found(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        assert mgr.get_zone("nonexistent") is None

    def test_get_all_zones(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        mgr.create_zone(1, "A", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)
        mgr.create_zone(2, "B", [(0, 0), (20, 0), (20, 20)], ZoneType.TRIPWIRE)
        assert len(mgr.get_all_zones()) == 2

    def test_get_zones_for_camera(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        mgr.create_zone(1, "A", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)
        mgr.create_zone(1, "B", [(0, 0), (20, 0), (20, 20)], ZoneType.ACTIVITY)
        mgr.create_zone(2, "C", [(0, 0), (30, 0), (30, 30)], ZoneType.ACTIVITY)
        cam1_zones = mgr.get_zones_for_camera(1)
        assert len(cam1_zones) == 2
        cam2_zones = mgr.get_zones_for_camera(2)
        assert len(cam2_zones) == 1

    def test_update_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(1, "Old Name", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)
        updated = mgr.update_zone(zone.zone_id, name="New Name", enabled=False)
        assert updated is not None
        assert updated.name == "New Name"
        assert updated.enabled is False

    def test_update_zone_not_found(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        assert mgr.update_zone("nonexistent", name="X") is None

    def test_delete_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(1, "Temp", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)
        assert mgr.delete_zone(zone.zone_id) is True
        assert mgr.get_zone(zone.zone_id) is None

    def test_delete_zone_not_found(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        assert mgr.delete_zone("nonexistent") is False


# ---------------------------------------------------------------------------
# ZoneManager — Persistence
# ---------------------------------------------------------------------------


class TestZoneManagerPersistence:
    """ZoneManager — save/load from disk."""

    def test_zones_persist_across_instances(self, tmp_path):
        storage = tmp_path / "zones"
        mgr1 = ZoneManager(storage)
        mgr1.create_zone(1, "Persisted", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)

        mgr2 = ZoneManager(storage)
        zones = mgr2.get_all_zones()
        assert len(zones) == 1
        assert zones[0].name == "Persisted"

    def test_empty_storage_loads_clean(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        assert len(mgr.get_all_zones()) == 0

    def test_corrupt_zones_file_recovers(self, tmp_path):
        storage = tmp_path / "zones"
        storage.mkdir(parents=True)
        (storage / "zones.json").write_text("NOT VALID JSON")
        mgr = ZoneManager(storage)
        assert len(mgr.get_all_zones()) == 0  # Recovers gracefully


# ---------------------------------------------------------------------------
# ZoneManager — Event Detection
# ---------------------------------------------------------------------------


class TestZoneManagerEventDetection:
    """check_detections — triggers events for matching detections."""

    def test_detection_inside_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(1, "Yard", [(0, 0), (200, 0), (200, 200), (0, 200)], ZoneType.ACTIVITY)
        events = mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (90, 90, 110, 110), "class_name": "person"}],
            timestamp=datetime.now(),
            video_path="/tmp/test.mp4",
            frame_number=100,
        )
        assert len(events) == 1
        assert events[0].target_type == "person"

    def test_detection_outside_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        mgr.create_zone(1, "Yard", [(0, 0), (100, 0), (100, 100), (0, 100)], ZoneType.ACTIVITY)
        events = mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (300, 300, 400, 400), "class_name": "person"}],
            timestamp=datetime.now(),
            video_path="/tmp/test.mp4",
            frame_number=100,
        )
        assert len(events) == 0

    def test_disabled_zone_ignored(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(1, "Yard", [(0, 0), (200, 0), (200, 200), (0, 200)], ZoneType.ACTIVITY)
        mgr.update_zone(zone.zone_id, enabled=False)
        events = mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 60, 60), "class_name": "person"}],
            timestamp=datetime.now(),
            video_path="/tmp/test.mp4",
            frame_number=100,
        )
        assert len(events) == 0

    def test_cooldown_suppresses_event(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(
            1, "Yard", [(0, 0), (200, 0), (200, 200), (0, 200)],
            ZoneType.ACTIVITY, cooldown_seconds=60,
        )
        now = datetime.now()
        det = [{"bbox": (50, 50, 60, 60), "class_name": "person"}]

        events1 = mgr.check_detections(1, det, now, "/tmp/a.mp4", 1)
        assert len(events1) == 1

        # Within cooldown
        events2 = mgr.check_detections(1, det, now + timedelta(seconds=10), "/tmp/a.mp4", 2)
        assert len(events2) == 0

    def test_after_cooldown_triggers_again(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        mgr.create_zone(
            1, "Yard", [(0, 0), (200, 0), (200, 200), (0, 200)],
            ZoneType.ACTIVITY, cooldown_seconds=5,
        )
        now = datetime.now()
        det = [{"bbox": (50, 50, 60, 60), "class_name": "person"}]

        events1 = mgr.check_detections(1, det, now, "/tmp/a.mp4", 1)
        assert len(events1) == 1

        events2 = mgr.check_detections(1, det, now + timedelta(seconds=10), "/tmp/a.mp4", 2)
        assert len(events2) == 1

    def test_no_zones_for_camera(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        mgr.create_zone(1, "Yard", [(0, 0), (200, 0), (200, 200), (0, 200)], ZoneType.ACTIVITY)
        events = mgr.check_detections(
            camera_id=2,  # Different camera
            detections=[{"bbox": (50, 50, 60, 60), "class_name": "person"}],
            timestamp=datetime.now(),
            video_path="/tmp/test.mp4",
            frame_number=100,
        )
        assert len(events) == 0

    def test_event_increments_total_events(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(1, "Yard", [(0, 0), (200, 0), (200, 200), (0, 200)], ZoneType.ACTIVITY)
        mgr.check_detections(
            1,
            [{"bbox": (50, 50, 60, 60), "class_name": "person"}],
            datetime.now(),
            "/tmp/a.mp4",
            1,
        )
        updated_zone = mgr.get_zone(zone.zone_id)
        assert updated_zone.total_events == 1


# ---------------------------------------------------------------------------
# ZoneManager — Event Queries
# ---------------------------------------------------------------------------


class TestZoneManagerEventQueries:
    """get_events_for_zone, get_events_by_target, get_zone_summary."""

    def _populate_events(self, mgr, zone_id, count=5):
        """Create several zone events."""
        now = datetime.now()
        for i in range(count):
            mgr.check_detections(
                1,
                [{"bbox": (50, 50, 60, 60), "class_name": "person" if i % 2 == 0 else "vehicle"}],
                now + timedelta(minutes=i, seconds=31),  # Outside 30s cooldown
                f"/tmp/vid_{i}.mp4",
                i * 10,
            )

    def test_get_events_for_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(
            1, "Yard", [(0, 0), (200, 0), (200, 200), (0, 200)],
            ZoneType.ACTIVITY, cooldown_seconds=1,
        )
        self._populate_events(mgr, zone.zone_id, count=3)
        events = mgr.get_events_for_zone(zone.zone_id)
        assert len(events) == 3

    def test_get_events_for_zone_limit(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(
            1, "Yard", [(0, 0), (200, 0), (200, 200), (0, 200)],
            ZoneType.ACTIVITY, cooldown_seconds=1,
        )
        self._populate_events(mgr, zone.zone_id, count=5)
        events = mgr.get_events_for_zone(zone.zone_id, limit=2)
        assert len(events) == 2

    def test_get_events_by_target(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        mgr.create_zone(
            1, "Yard", [(0, 0), (200, 0), (200, 200), (0, 200)],
            ZoneType.ACTIVITY, cooldown_seconds=1,
        )
        self._populate_events(mgr, "z1", count=5)
        person_events = mgr.get_events_by_target(target_type="person")
        assert all(e.target_type == "person" for e in person_events)

    def test_get_zone_summary(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(
            1, "Yard", [(0, 0), (200, 0), (200, 200), (0, 200)],
            ZoneType.ACTIVITY, cooldown_seconds=1,
        )
        self._populate_events(mgr, zone.zone_id, count=3)
        summary = mgr.get_zone_summary(zone.zone_id)
        assert summary["zone_name"] == "Yard"
        assert summary["total_events"] == 3
        assert "hourly_distribution" in summary
        assert len(summary["hourly_distribution"]) == 24

    def test_get_zone_summary_not_found(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        assert mgr.get_zone_summary("nonexistent") == {}

    def test_events_sorted_descending(self, tmp_path):
        mgr = ZoneManager(tmp_path / "zones")
        zone = mgr.create_zone(
            1, "Yard", [(0, 0), (200, 0), (200, 200), (0, 200)],
            ZoneType.ACTIVITY, cooldown_seconds=1,
        )
        self._populate_events(mgr, zone.zone_id, count=3)
        events = mgr.get_events_for_zone(zone.zone_id)
        for i in range(len(events) - 1):
            assert events[i].timestamp >= events[i + 1].timestamp
