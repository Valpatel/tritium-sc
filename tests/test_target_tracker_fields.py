# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Test target tracker first_seen and signal_count fields."""

import time
import pytest
from engine.tactical.target_tracker import TargetTracker, TrackedTarget


class TestTrackedTargetFields:
    def test_first_seen_default(self):
        t = TrackedTarget(target_id="t1", name="Test", alliance="unknown", asset_type="test")
        assert t.first_seen > 0
        assert t.signal_count == 0

    def test_signal_count_increments(self):
        tracker = TargetTracker()
        # First sighting
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:01",
            "name": "Phone",
            "rssi": -60,
            "type": "phone",
        })
        targets = tracker.get_all()
        assert len(targets) == 1
        assert targets[0].signal_count == 1

        # Second sighting
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:01",
            "name": "Phone",
            "rssi": -55,
            "type": "phone",
        })
        targets = tracker.get_all()
        assert targets[0].signal_count == 2

    def test_first_seen_stable(self):
        tracker = TargetTracker()
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:02",
            "name": "Watch",
            "rssi": -70,
            "type": "watch",
        })
        first = tracker.get_all()[0].first_seen

        time.sleep(0.01)
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:02",
            "name": "Watch",
            "rssi": -65,
            "type": "watch",
        })
        assert tracker.get_all()[0].first_seen == first

    def test_to_dict_includes_fields(self):
        t = TrackedTarget(
            target_id="t1", name="Test", alliance="unknown",
            asset_type="test", signal_count=5,
        )
        d = t.to_dict()
        assert "first_seen" in d
        assert "signal_count" in d
        assert d["signal_count"] == 5

    def test_sim_update_increments(self):
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "sim_1",
            "name": "Rover",
            "alliance": "friendly",
            "asset_type": "rover",
            "x": 10, "y": 20,
        })
        assert tracker.get_all()[0].signal_count == 1

        tracker.update_from_simulation({
            "target_id": "sim_1",
            "x": 15, "y": 25,
        })
        assert tracker.get_all()[0].signal_count == 2
