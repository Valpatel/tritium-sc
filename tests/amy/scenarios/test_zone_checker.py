"""Unit tests for ZoneChecker — zone caching, detection checking, and factory.

Tests with mocked ZoneManager, no file system or database required.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.zones.checker import ZoneChecker, get_zone_checker
from app.zones.models import Zone, ZoneEvent, ZoneType, ZoneEventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_zone(zone_id="z1", camera_id=1, name="Front Yard"):
    return Zone(
        zone_id=zone_id,
        camera_id=camera_id,
        name=name,
        polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
        zone_type=ZoneType.ACTIVITY,
    )


def _make_detection(class_name="person", confidence=0.9,
                    bbox=(50, 50, 80, 80), center=(65, 65)):
    det = MagicMock()
    det.class_name = class_name
    det.confidence = confidence
    det.bbox = bbox
    det.center = center
    det.track_id = None
    return det


def _make_zone_event(zone_id="z1", event_type=ZoneEventType.ENTER):
    return ZoneEvent(
        event_id="evt-001",
        zone_id=zone_id,
        zone_name="Front Yard",
        event_type=event_type,
        timestamp=datetime(2026, 2, 20, 14, 0, 0),
        camera_id=1,
    )


# ---------------------------------------------------------------------------
# ZoneChecker — Initialization
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestZoneCheckerInit:
    """ZoneChecker init and basic properties."""

    def test_init(self):
        manager = MagicMock()
        checker = ZoneChecker(manager)
        assert checker.manager is manager
        assert checker._camera_zones_cache == {}


# ---------------------------------------------------------------------------
# ZoneChecker — Zone Caching
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestZoneCheckerCache:
    """Zone caching for camera lookups."""

    def test_get_zones_calls_manager(self):
        manager = MagicMock()
        zones = [_make_zone()]
        manager.get_zones_for_camera.return_value = zones

        checker = ZoneChecker(manager)
        result = checker.get_zones_for_camera(1)

        assert result == zones
        manager.get_zones_for_camera.assert_called_once_with(1)

    def test_get_zones_cached(self):
        """Second call uses cache, doesn't call manager again."""
        manager = MagicMock()
        zones = [_make_zone()]
        manager.get_zones_for_camera.return_value = zones

        checker = ZoneChecker(manager)
        checker.get_zones_for_camera(1)
        checker.get_zones_for_camera(1)

        # Only called once due to cache
        manager.get_zones_for_camera.assert_called_once()

    def test_different_cameras_cached_separately(self):
        manager = MagicMock()
        zones_1 = [_make_zone(camera_id=1)]
        zones_2 = [_make_zone(zone_id="z2", camera_id=2)]
        manager.get_zones_for_camera.side_effect = [zones_1, zones_2]

        checker = ZoneChecker(manager)
        r1 = checker.get_zones_for_camera(1)
        r2 = checker.get_zones_for_camera(2)

        assert r1 == zones_1
        assert r2 == zones_2
        assert manager.get_zones_for_camera.call_count == 2

    def test_clear_cache(self):
        manager = MagicMock()
        zones = [_make_zone()]
        manager.get_zones_for_camera.return_value = zones

        checker = ZoneChecker(manager)
        checker.get_zones_for_camera(1)
        checker.clear_cache()

        # After clear, should call manager again
        checker.get_zones_for_camera(1)
        assert manager.get_zones_for_camera.call_count == 2

    def test_cache_empty_zone_list(self):
        """Camera with no zones is still cached (avoids re-querying)."""
        manager = MagicMock()
        manager.get_zones_for_camera.return_value = []

        checker = ZoneChecker(manager)
        result = checker.get_zones_for_camera(99)
        assert result == []

        # Second call should use cache
        checker.get_zones_for_camera(99)
        manager.get_zones_for_camera.assert_called_once()


# ---------------------------------------------------------------------------
# ZoneChecker — Detection Checking
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestZoneCheckerDetections:
    """check_frame_detections — detection to zone event conversion."""

    def test_no_zones_returns_empty(self):
        manager = MagicMock()
        manager.get_zones_for_camera.return_value = []

        checker = ZoneChecker(manager)
        events = checker.check_frame_detections(
            camera_id=1,
            detections=[_make_detection()],
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4",
            frame_number=100,
        )
        assert events == []
        # Manager.check_detections should NOT be called when no zones
        manager.check_detections.assert_not_called()

    def test_with_zones_calls_check_detections(self):
        manager = MagicMock()
        manager.get_zones_for_camera.return_value = [_make_zone()]
        manager.check_detections.return_value = [_make_zone_event()]

        checker = ZoneChecker(manager)
        events = checker.check_frame_detections(
            camera_id=1,
            detections=[_make_detection()],
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4",
            frame_number=100,
        )

        assert len(events) == 1
        manager.check_detections.assert_called_once()

    def test_detection_dicts_format(self):
        """Detections are converted to dict format for manager."""
        manager = MagicMock()
        manager.get_zones_for_camera.return_value = [_make_zone()]
        manager.check_detections.return_value = []

        det = _make_detection(
            class_name="vehicle",
            confidence=0.85,
            bbox=(10, 20, 30, 40),
            center=(20, 30),
        )

        checker = ZoneChecker(manager)
        checker.check_frame_detections(
            camera_id=1,
            detections=[det],
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4",
            frame_number=100,
        )

        call_args = manager.check_detections.call_args
        det_dicts = call_args.kwargs.get("detections") or call_args[1].get("detections")
        # If passed as positional, grab from args
        if det_dicts is None:
            # check_detections(camera_id, detections, ...)
            det_dicts = call_args[1]["detections"] if "detections" in call_args[1] else call_args[0][1]

        assert len(det_dicts) == 1
        d = det_dicts[0]
        assert d["class_name"] == "vehicle"
        assert d["confidence"] == 0.85
        assert d["bbox"] == (10, 20, 30, 40)
        assert d["center"] == (20, 30)
        assert d["track_id"] is None

    def test_detection_with_track_id(self):
        """Detection with track_id passes it through."""
        manager = MagicMock()
        manager.get_zones_for_camera.return_value = [_make_zone()]
        manager.check_detections.return_value = []

        det = _make_detection()
        det.track_id = 42

        checker = ZoneChecker(manager)
        checker.check_frame_detections(
            camera_id=1,
            detections=[det],
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4",
            frame_number=100,
        )

        call_kwargs = manager.check_detections.call_args[1]
        det_dicts = call_kwargs.get("detections", [])
        if det_dicts:
            assert det_dicts[0]["track_id"] == 42

    def test_detection_without_track_id_attr(self):
        """Detection without track_id attribute gets None."""
        manager = MagicMock()
        manager.get_zones_for_camera.return_value = [_make_zone()]
        manager.check_detections.return_value = []

        det = MagicMock(spec=["class_name", "confidence", "bbox", "center"])
        det.class_name = "person"
        det.confidence = 0.9
        det.bbox = (10, 20, 30, 40)
        det.center = (20, 30)

        checker = ZoneChecker(manager)
        checker.check_frame_detections(
            camera_id=1,
            detections=[det],
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4",
            frame_number=100,
        )

        call_kwargs = manager.check_detections.call_args[1]
        det_dicts = call_kwargs.get("detections", [])
        if det_dicts:
            assert det_dicts[0]["track_id"] is None

    def test_multiple_detections(self):
        """Multiple detections all converted."""
        manager = MagicMock()
        manager.get_zones_for_camera.return_value = [_make_zone()]
        manager.check_detections.return_value = []

        dets = [_make_detection(class_name=c) for c in ("person", "car", "dog")]

        checker = ZoneChecker(manager)
        checker.check_frame_detections(
            camera_id=1,
            detections=dets,
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4",
            frame_number=100,
        )

        call_kwargs = manager.check_detections.call_args[1]
        det_dicts = call_kwargs.get("detections", [])
        assert len(det_dicts) == 3

    def test_empty_detections(self):
        """Empty detection list still calls manager if zones exist."""
        manager = MagicMock()
        manager.get_zones_for_camera.return_value = [_make_zone()]
        manager.check_detections.return_value = []

        checker = ZoneChecker(manager)
        events = checker.check_frame_detections(
            camera_id=1,
            detections=[],
            timestamp=datetime(2026, 2, 20, 14, 0),
            video_path="/v.mp4",
            frame_number=100,
        )
        assert events == []
        manager.check_detections.assert_called_once()

    def test_passes_all_kwargs(self):
        """All parameters forwarded to manager.check_detections."""
        manager = MagicMock()
        manager.get_zones_for_camera.return_value = [_make_zone()]
        manager.check_detections.return_value = []

        ts = datetime(2026, 2, 20, 15, 30)
        checker = ZoneChecker(manager)
        checker.check_frame_detections(
            camera_id=3,
            detections=[],
            timestamp=ts,
            video_path="/recordings/ch3/video.mp4",
            frame_number=999,
        )

        call_kwargs = manager.check_detections.call_args[1]
        assert call_kwargs["camera_id"] == 3
        assert call_kwargs["timestamp"] == ts
        assert call_kwargs["video_path"] == "/recordings/ch3/video.mp4"
        assert call_kwargs["frame_number"] == 999


# ---------------------------------------------------------------------------
# get_zone_checker factory
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetZoneChecker:
    """get_zone_checker() — factory function."""

    def test_success(self):
        with patch("app.zones.checker.ZoneManager") as MockManager, \
             patch("app.config.settings") as mock_settings:
            from pathlib import Path
            mock_settings.recordings_path = Path("/tmp/test-recordings")
            result = get_zone_checker()
            assert result is not None
            assert isinstance(result, ZoneChecker)

    def test_failure_returns_none(self):
        with patch("app.zones.checker.ZoneManager", side_effect=Exception("boom")), \
             patch("app.config.settings") as mock_settings:
            from pathlib import Path
            mock_settings.recordings_path = Path("/tmp/test-recordings")
            result = get_zone_checker()
            assert result is None
