"""Unit tests for ZoneManager — CRUD, detection checking, event queries.

Uses tmp_path fixture for isolated file I/O.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.zones.manager import ZoneManager
from app.zones.models import Zone, ZoneEvent, ZoneType, ZoneEventType


# ===========================================================================
# Initialization
# ===========================================================================

@pytest.mark.unit
class TestZoneManagerInit:
    """ZoneManager initialization and persistence."""

    def test_init_creates_directory(self, tmp_path):
        path = tmp_path / "zones"
        mgr = ZoneManager(path)
        assert path.exists()
        assert mgr._zones == {}
        assert mgr._events == []

    def test_init_loads_empty(self, tmp_path):
        """No files on disk — starts empty."""
        mgr = ZoneManager(tmp_path)
        assert len(mgr.get_all_zones()) == 0


# ===========================================================================
# Zone CRUD
# ===========================================================================

@pytest.mark.unit
class TestZoneManagerCRUD:
    """Zone create, read, update, delete."""

    def test_create_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        z = mgr.create_zone(
            camera_id=1, name="Front Yard",
            polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
            zone_type=ZoneType.ACTIVITY,
        )
        assert z.zone_id.startswith("zone_")
        assert z.name == "Front Yard"
        assert z.camera_id == 1

    def test_get_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        z = mgr.create_zone(
            camera_id=1, name="Test",
            polygon=[(0, 0), (10, 0), (10, 10)],
            zone_type=ZoneType.ENTRY_EXIT,
        )
        fetched = mgr.get_zone(z.zone_id)
        assert fetched is not None
        assert fetched.name == "Test"

    def test_get_zone_not_found(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        assert mgr.get_zone("nonexistent") is None

    def test_get_zones_for_camera(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        mgr.create_zone(1, "Z1", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)
        mgr.create_zone(1, "Z2", [(20, 0), (30, 0), (30, 10)], ZoneType.ENTRY_EXIT)
        mgr.create_zone(2, "Z3", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)

        cam1_zones = mgr.get_zones_for_camera(1)
        assert len(cam1_zones) == 2
        cam2_zones = mgr.get_zones_for_camera(2)
        assert len(cam2_zones) == 1

    def test_get_all_zones(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        mgr.create_zone(1, "Z1", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)
        mgr.create_zone(2, "Z2", [(0, 0), (10, 0), (10, 10)], ZoneType.TRIPWIRE)
        assert len(mgr.get_all_zones()) == 2

    def test_update_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        z = mgr.create_zone(1, "Old Name", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)
        updated = mgr.update_zone(z.zone_id, name="New Name", enabled=False)
        assert updated is not None
        assert updated.name == "New Name"
        assert updated.enabled is False

    def test_update_zone_not_found(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        assert mgr.update_zone("nonexistent", name="X") is None

    def test_update_zone_ignores_unknown_fields(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        z = mgr.create_zone(1, "Test", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)
        updated = mgr.update_zone(z.zone_id, bogus_field="value")
        assert updated is not None
        assert not hasattr(updated, "bogus_field") or getattr(updated, "bogus_field", None) != "value"

    def test_delete_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        z = mgr.create_zone(1, "Doomed", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)
        assert mgr.delete_zone(z.zone_id) is True
        assert mgr.get_zone(z.zone_id) is None

    def test_delete_zone_not_found(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        assert mgr.delete_zone("nonexistent") is False


# ===========================================================================
# Persistence
# ===========================================================================

@pytest.mark.unit
class TestZoneManagerPersistence:
    """Zones and events survive reload from disk."""

    def test_zones_persist(self, tmp_path):
        mgr1 = ZoneManager(tmp_path)
        mgr1.create_zone(1, "Persistent", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)

        # Reload from same path
        mgr2 = ZoneManager(tmp_path)
        assert len(mgr2.get_all_zones()) == 1
        assert mgr2.get_all_zones()[0].name == "Persistent"

    def test_delete_persists(self, tmp_path):
        mgr1 = ZoneManager(tmp_path)
        z = mgr1.create_zone(1, "Temp", [(0, 0), (10, 0), (10, 10)], ZoneType.ACTIVITY)
        mgr1.delete_zone(z.zone_id)

        mgr2 = ZoneManager(tmp_path)
        assert len(mgr2.get_all_zones()) == 0


# ===========================================================================
# Detection Checking
# ===========================================================================

@pytest.mark.unit
class TestZoneManagerDetections:
    """check_detections — triggers zone events from frame detections."""

    def _make_mgr_with_zone(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        z = mgr.create_zone(
            camera_id=1, name="Front Yard",
            polygon=[(0, 0), (200, 0), (200, 200), (0, 200)],
            zone_type=ZoneType.ACTIVITY,
        )
        return mgr, z

    def test_detection_in_zone_triggers_event(self, tmp_path):
        mgr, z = self._make_mgr_with_zone(tmp_path)
        events = mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 80, 80), "class_name": "person", "confidence": 0.9}],
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4",
            frame_number=100,
        )
        assert len(events) == 1
        assert events[0].zone_id == z.zone_id
        assert events[0].target_type == "person"

    def test_detection_outside_zone_no_event(self, tmp_path):
        mgr, _ = self._make_mgr_with_zone(tmp_path)
        events = mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (500, 500, 600, 600), "class_name": "person"}],
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4",
            frame_number=100,
        )
        assert events == []

    def test_no_zones_for_camera(self, tmp_path):
        mgr, _ = self._make_mgr_with_zone(tmp_path)
        events = mgr.check_detections(
            camera_id=99,  # Different camera
            detections=[{"bbox": (50, 50, 80, 80), "class_name": "person"}],
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4",
            frame_number=100,
        )
        assert events == []

    def test_disabled_zone_skipped(self, tmp_path):
        mgr, z = self._make_mgr_with_zone(tmp_path)
        mgr.update_zone(z.zone_id, enabled=False)
        events = mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 80, 80), "class_name": "person"}],
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4",
            frame_number=100,
        )
        assert events == []

    def test_cooldown_suppresses_event(self, tmp_path):
        mgr, z = self._make_mgr_with_zone(tmp_path)
        t1 = datetime(2026, 2, 20, 14, 0, 0)
        t2 = t1 + timedelta(seconds=10)  # Within 30s cooldown

        # First detection triggers
        events1 = mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 80, 80), "class_name": "person"}],
            timestamp=t1, video_path="/v.mp4", frame_number=100,
        )
        assert len(events1) == 1

        # Second detection within cooldown — suppressed
        events2 = mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 80, 80), "class_name": "person"}],
            timestamp=t2, video_path="/v.mp4", frame_number=200,
        )
        assert events2 == []

    def test_after_cooldown_triggers(self, tmp_path):
        mgr, z = self._make_mgr_with_zone(tmp_path)
        t1 = datetime(2026, 2, 20, 14, 0, 0)
        t2 = t1 + timedelta(seconds=31)  # Past 30s cooldown

        mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 80, 80), "class_name": "person"}],
            timestamp=t1, video_path="/v.mp4", frame_number=100,
        )
        events2 = mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 80, 80), "class_name": "person"}],
            timestamp=t2, video_path="/v.mp4", frame_number=200,
        )
        assert len(events2) == 1

    def test_event_updates_zone_stats(self, tmp_path):
        mgr, z = self._make_mgr_with_zone(tmp_path)
        ts = datetime(2026, 2, 20, 14, 0)
        mgr.check_detections(
            camera_id=1,
            detections=[{"bbox": (50, 50, 80, 80), "class_name": "person"}],
            timestamp=ts, video_path="/v.mp4", frame_number=100,
        )
        zone = mgr.get_zone(z.zone_id)
        assert zone.total_events == 1
        assert zone.last_event_at == ts

    def test_empty_detections(self, tmp_path):
        mgr, _ = self._make_mgr_with_zone(tmp_path)
        events = mgr.check_detections(
            camera_id=1, detections=[],
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4", frame_number=0,
        )
        assert events == []


# ===========================================================================
# Event Queries
# ===========================================================================

@pytest.mark.unit
class TestZoneManagerEventQueries:
    """get_events_for_zone, get_events_by_target, get_zone_summary."""

    def _mgr_with_events(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        z = mgr.create_zone(
            camera_id=1, name="Entry",
            polygon=[(0, 0), (200, 0), (200, 200), (0, 200)],
            zone_type=ZoneType.ENTRY_EXIT,
        )

        base_time = datetime(2026, 2, 20, 10, 0, 0)
        for i in range(5):
            ts = base_time + timedelta(minutes=31 * i)  # Past cooldown each time
            mgr.check_detections(
                camera_id=1,
                detections=[{"bbox": (50, 50, 80, 80), "class_name": "person" if i % 2 == 0 else "vehicle"}],
                timestamp=ts, video_path="/v.mp4", frame_number=i * 100,
            )
        return mgr, z

    def test_get_events_for_zone(self, tmp_path):
        mgr, z = self._mgr_with_events(tmp_path)
        events = mgr.get_events_for_zone(z.zone_id)
        assert len(events) == 5

    def test_get_events_for_zone_limit(self, tmp_path):
        mgr, z = self._mgr_with_events(tmp_path)
        events = mgr.get_events_for_zone(z.zone_id, limit=3)
        assert len(events) == 3

    def test_get_events_for_zone_offset(self, tmp_path):
        mgr, z = self._mgr_with_events(tmp_path)
        all_events = mgr.get_events_for_zone(z.zone_id)
        offset_events = mgr.get_events_for_zone(z.zone_id, offset=2)
        assert len(offset_events) == 3
        assert offset_events[0].event_id == all_events[2].event_id

    def test_get_events_by_target_type(self, tmp_path):
        mgr, _ = self._mgr_with_events(tmp_path)
        person_events = mgr.get_events_by_target(target_type="person")
        assert len(person_events) == 3  # indices 0, 2, 4

    def test_get_events_by_target_vehicle(self, tmp_path):
        mgr, _ = self._mgr_with_events(tmp_path)
        vehicle_events = mgr.get_events_by_target(target_type="vehicle")
        assert len(vehicle_events) == 2  # indices 1, 3

    def test_get_zone_summary(self, tmp_path):
        mgr, z = self._mgr_with_events(tmp_path)
        summary = mgr.get_zone_summary(z.zone_id)
        assert summary["zone_id"] == z.zone_id
        assert summary["zone_name"] == "Entry"
        assert summary["total_events"] == 5
        assert "person" in summary["events_by_type"]
        assert "vehicle" in summary["events_by_type"]
        assert summary["peak_hour"] is not None
        assert len(summary["recent_events"]) <= 10

    def test_get_zone_summary_not_found(self, tmp_path):
        mgr = ZoneManager(tmp_path)
        assert mgr.get_zone_summary("nonexistent") == {}

    def test_events_sorted_descending(self, tmp_path):
        mgr, z = self._mgr_with_events(tmp_path)
        events = mgr.get_events_for_zone(z.zone_id)
        for i in range(len(events) - 1):
            assert events[i].timestamp >= events[i + 1].timestamp
