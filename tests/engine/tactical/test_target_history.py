# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TargetHistory — position recording, trails, speed, heading."""

import math
import time

import pytest

from tritium_lib.tracking.target_history import TargetHistory


@pytest.mark.unit
class TestTargetHistoryRecording:
    """Basic record and retrieve operations."""

    def test_record_and_get_trail(self):
        h = TargetHistory()
        h.record("t1", (1.0, 2.0), timestamp=100.0)
        h.record("t1", (3.0, 4.0), timestamp=101.0)
        trail = h.get_trail("t1")
        assert len(trail) == 2
        assert trail[0] == (1.0, 2.0, 100.0)
        assert trail[1] == (3.0, 4.0, 101.0)

    def test_trail_empty_for_unknown_target(self):
        h = TargetHistory()
        assert h.get_trail("nonexistent") == []

    def test_trail_max_points_limits_output(self):
        h = TargetHistory()
        for i in range(50):
            h.record("t1", (float(i), 0.0), timestamp=float(i))
        trail = h.get_trail("t1", max_points=10)
        assert len(trail) == 10
        # Should be the most recent 10
        assert trail[0][0] == 40.0
        assert trail[-1][0] == 49.0

    def test_ring_buffer_max_capacity(self):
        h = TargetHistory()
        h.MAX_RECORDS_PER_TARGET = 100  # smaller for test speed
        for i in range(200):
            h.record("t1", (float(i), 0.0), timestamp=float(i))
        trail = h.get_trail("t1", max_points=200)
        assert len(trail) == 100
        # Oldest should be 100, newest 199
        assert trail[0][0] == 100.0
        assert trail[-1][0] == 199.0

    def test_multiple_targets_independent(self):
        h = TargetHistory()
        h.record("t1", (1.0, 0.0), timestamp=1.0)
        h.record("t2", (2.0, 0.0), timestamp=1.0)
        assert len(h.get_trail("t1")) == 1
        assert len(h.get_trail("t2")) == 1
        assert h.tracked_count == 2

    def test_default_timestamp_uses_monotonic(self):
        h = TargetHistory()
        before = time.monotonic()
        h.record("t1", (0.0, 0.0))
        after = time.monotonic()
        trail = h.get_trail("t1")
        assert before <= trail[0][2] <= after


@pytest.mark.unit
class TestTargetHistorySpeed:
    """Speed estimation from position history."""

    def test_speed_zero_single_point(self):
        h = TargetHistory()
        h.record("t1", (0.0, 0.0), timestamp=1.0)
        assert h.get_speed("t1") == 0.0

    def test_speed_zero_no_history(self):
        h = TargetHistory()
        assert h.get_speed("unknown") == 0.0

    def test_speed_linear_motion(self):
        h = TargetHistory()
        # Move 10 units in 2 seconds = 5 units/s
        h.record("t1", (0.0, 0.0), timestamp=0.0)
        h.record("t1", (5.0, 0.0), timestamp=1.0)
        h.record("t1", (10.0, 0.0), timestamp=2.0)
        speed = h.get_speed("t1")
        assert abs(speed - 5.0) < 0.01

    def test_speed_diagonal_motion(self):
        h = TargetHistory()
        h.record("t1", (0.0, 0.0), timestamp=0.0)
        h.record("t1", (3.0, 4.0), timestamp=1.0)
        speed = h.get_speed("t1")
        assert abs(speed - 5.0) < 0.01

    def test_speed_stationary(self):
        h = TargetHistory()
        h.record("t1", (5.0, 5.0), timestamp=0.0)
        h.record("t1", (5.0, 5.0), timestamp=1.0)
        h.record("t1", (5.0, 5.0), timestamp=2.0)
        assert h.get_speed("t1") == 0.0

    def test_speed_zero_dt(self):
        h = TargetHistory()
        h.record("t1", (0.0, 0.0), timestamp=1.0)
        h.record("t1", (5.0, 0.0), timestamp=1.0)
        assert h.get_speed("t1") == 0.0


@pytest.mark.unit
class TestTargetHistoryHeading:
    """Heading estimation from position history."""

    def test_heading_no_history(self):
        h = TargetHistory()
        assert h.get_heading("unknown") == 0.0

    def test_heading_single_point(self):
        h = TargetHistory()
        h.record("t1", (0.0, 0.0), timestamp=1.0)
        assert h.get_heading("t1") == 0.0

    def test_heading_north(self):
        h = TargetHistory()
        h.record("t1", (0.0, 0.0), timestamp=0.0)
        h.record("t1", (0.0, 10.0), timestamp=1.0)
        heading = h.get_heading("t1")
        assert abs(heading - 0.0) < 0.01 or abs(heading - 360.0) < 0.01

    def test_heading_east(self):
        h = TargetHistory()
        h.record("t1", (0.0, 0.0), timestamp=0.0)
        h.record("t1", (10.0, 0.0), timestamp=1.0)
        heading = h.get_heading("t1")
        assert abs(heading - 90.0) < 0.01

    def test_heading_south(self):
        h = TargetHistory()
        h.record("t1", (0.0, 0.0), timestamp=0.0)
        h.record("t1", (0.0, -10.0), timestamp=1.0)
        heading = h.get_heading("t1")
        assert abs(heading - 180.0) < 0.01

    def test_heading_west(self):
        h = TargetHistory()
        h.record("t1", (0.0, 0.0), timestamp=0.0)
        h.record("t1", (-10.0, 0.0), timestamp=1.0)
        heading = h.get_heading("t1")
        assert abs(heading - 270.0) < 0.01

    def test_heading_stationary(self):
        h = TargetHistory()
        h.record("t1", (5.0, 5.0), timestamp=0.0)
        h.record("t1", (5.0, 5.0), timestamp=1.0)
        assert h.get_heading("t1") == 0.0


@pytest.mark.unit
class TestTargetHistoryPruning:
    """Stale target pruning."""

    def test_prune_removes_stale(self):
        h = TargetHistory()
        h.PRUNE_TIMEOUT = 0.1
        h.record("t1", (0.0, 0.0), timestamp=time.monotonic() - 1.0)
        h.prune_stale()
        assert h.tracked_count == 0

    def test_prune_keeps_recent(self):
        h = TargetHistory()
        h.PRUNE_TIMEOUT = 600.0
        h.record("t1", (0.0, 0.0))
        h.prune_stale()
        assert h.tracked_count == 1


@pytest.mark.unit
class TestTargetHistoryClear:
    """Clear operations."""

    def test_clear_specific_target(self):
        h = TargetHistory()
        h.record("t1", (1.0, 0.0), timestamp=1.0)
        h.record("t2", (2.0, 0.0), timestamp=1.0)
        h.clear("t1")
        assert h.get_trail("t1") == []
        assert len(h.get_trail("t2")) == 1

    def test_clear_all(self):
        h = TargetHistory()
        h.record("t1", (1.0, 0.0), timestamp=1.0)
        h.record("t2", (2.0, 0.0), timestamp=1.0)
        h.clear()
        assert h.tracked_count == 0

    def test_clear_nonexistent_no_error(self):
        h = TargetHistory()
        h.clear("nonexistent")  # should not raise


@pytest.mark.unit
class TestTargetHistoryTrailDicts:
    """Serialization helpers."""

    def test_trail_dicts_format(self):
        h = TargetHistory()
        h.record("t1", (1.5, 2.5), timestamp=10.0)
        h.record("t1", (3.5, 4.5), timestamp=11.0)
        dicts = h.get_trail_dicts("t1", max_points=20)
        assert len(dicts) == 2
        assert dicts[0] == {"x": 1.5, "y": 2.5, "t": 10.0}
        assert dicts[1] == {"x": 3.5, "y": 4.5, "t": 11.0}

    def test_trail_dicts_empty(self):
        h = TargetHistory()
        assert h.get_trail_dicts("nonexistent") == []


@pytest.mark.unit
class TestTargetTrackerHistoryIntegration:
    """Verify TargetTracker wires history recording correctly."""

    def test_simulation_update_records_history(self):
        from engine.tactical.target_tracker import TargetTracker
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "rover-01",
            "name": "Rover",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 1.0, "y": 2.0},
        })
        tracker.update_from_simulation({
            "target_id": "rover-01",
            "name": "Rover",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 3.0, "y": 4.0},
        })
        trail = tracker.history.get_trail("rover-01")
        assert len(trail) == 2
        assert trail[0][:2] == (1.0, 2.0)
        assert trail[1][:2] == (3.0, 4.0)

    def test_detection_update_records_history(self):
        from engine.tactical.target_tracker import TargetTracker
        tracker = TargetTracker()
        tracker.update_from_detection({
            "class_name": "person",
            "confidence": 0.9,
            "center_x": 5.0,
            "center_y": 6.0,
        })
        # Find the target ID
        targets = tracker.get_all()
        assert len(targets) == 1
        tid = targets[0].target_id
        trail = tracker.history.get_trail(tid)
        assert len(trail) == 1
        assert trail[0][:2] == (5.0, 6.0)

    def test_ble_update_records_history_with_position(self):
        from engine.tactical.target_tracker import TargetTracker
        tracker = TargetTracker()
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "rssi": -50,
            "position": {"x": 10.0, "y": 20.0},
        })
        trail = tracker.history.get_trail("ble_aabbccddeeff")
        assert len(trail) == 1
        assert trail[0][:2] == (10.0, 20.0)

    def test_ble_update_no_position_skips_recording(self):
        from engine.tactical.target_tracker import TargetTracker
        tracker = TargetTracker()
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "rssi": -50,
        })
        trail = tracker.history.get_trail("ble_aabbccddeeff")
        assert len(trail) == 0

    def test_to_dict_includes_trail(self):
        from engine.tactical.target_tracker import TargetTracker
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "rover-01",
            "name": "Rover",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 1.0, "y": 2.0},
        })
        target = tracker.get_target("rover-01")
        d = target.to_dict(history=tracker.history)
        assert "trail" in d
        assert len(d["trail"]) == 1
        assert d["trail"][0]["x"] == 1.0

    def test_to_dict_without_history_no_trail_key(self):
        from engine.tactical.target_tracker import TargetTracker
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "rover-01",
            "name": "Rover",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 1.0, "y": 2.0},
        })
        target = tracker.get_target("rover-01")
        d = target.to_dict()
        assert "trail" not in d

    def test_stale_prune_clears_history(self):
        from engine.tactical.target_tracker import TargetTracker
        tracker = TargetTracker()
        tracker.STALE_TIMEOUT = 0.05
        tracker.update_from_detection({
            "class_name": "person",
            "confidence": 0.9,
            "center_x": 1.0,
            "center_y": 2.0,
        })
        targets = tracker.get_all()
        tid = targets[0].target_id

        time.sleep(0.1)
        tracker.get_all()  # triggers prune
        assert tracker.history.get_trail(tid) == []
