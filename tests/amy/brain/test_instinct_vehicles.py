# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Amy instinct layer vehicle behavior awareness."""

import time
from unittest.mock import MagicMock

import pytest

from amy.brain.instinct import InstinctLayer
from engine.tactical.vehicle_tracker import VehicleBehavior, VehicleTrackingManager


def _make_commander(vehicle_mgr=None):
    """Create a mock Commander with optional VehicleTrackingManager."""
    commander = MagicMock()
    commander.event_bus = MagicMock()
    commander.event_bus.subscribe.return_value = MagicMock()
    commander.sensorium = MagicMock()
    commander.vehicle_tracker = vehicle_mgr
    return commander


class TestVehicleNarration:
    """Test vehicle behavior narration generation."""

    def test_build_narration_loitering(self):
        commander = _make_commander()
        instinct = InstinctLayer(commander)

        vb = VehicleBehavior("det_car_1", "car")
        # Simulate stopped for 5+ minutes
        vb.stopped_since = time.monotonic() - 400
        vb.speed_mph = 0.5

        narration = instinct._build_vehicle_narration(vb, 0.45)
        assert "stopped" in narration.lower()
        assert "det_car_" in narration
        assert "45%" in narration

    def test_build_narration_crawling(self):
        commander = _make_commander()
        instinct = InstinctLayer(commander)

        vb = VehicleBehavior("det_truck_2", "truck")
        vb.speed_mph = 5.0
        vb.heading = 90.0

        narration = instinct._build_vehicle_narration(vb, 0.35)
        assert "crawling" in narration.lower() or "5.0 mph" in narration
        assert "surveillance" in narration.lower()

    def test_build_narration_erratic(self):
        commander = _make_commander()
        instinct = InstinctLayer(commander)

        vb = VehicleBehavior("det_car_3", "car")
        vb.speed_mph = 25.0
        # Fill speed history with high variance
        vb.speed_history = [5.0, 40.0, 10.0, 35.0, 8.0, 42.0]

        narration = instinct._build_vehicle_narration(vb, 0.5)
        assert "erratic" in narration.lower() or "inconsistent" in narration.lower()

    def test_build_narration_high_score(self):
        commander = _make_commander()
        instinct = InstinctLayer(commander)

        vb = VehicleBehavior("det_car_4", "car")
        vb.stopped_since = time.monotonic() - 600

        narration = instinct._build_vehicle_narration(vb, 0.7)
        assert "high" in narration.lower()

    def test_build_narration_moderate_score(self):
        commander = _make_commander()
        instinct = InstinctLayer(commander)

        vb = VehicleBehavior("det_car_5", "car")
        vb.speed_mph = 7.0

        narration = instinct._build_vehicle_narration(vb, 0.45)
        assert "moderate" in narration.lower()


class TestPeriodicVehicleCheck:
    """Test the periodic vehicle behavior polling."""

    def test_no_vehicle_tracker(self):
        commander = _make_commander(vehicle_mgr=None)
        instinct = InstinctLayer(commander)
        instinct._last_vehicle_check = 0  # Force check
        # Should not crash
        instinct._periodic_vehicle_check()
        commander.sensorium.push.assert_not_called()

    def test_no_suspicious_vehicles(self):
        mgr = VehicleTrackingManager()
        # Simulate a clearly moving vehicle at normal speed
        t = time.monotonic()
        mgr.update_vehicle("v1", 0.0, 0.0, timestamp=t - 2.0)
        mgr.update_vehicle("v1", 50.0, 0.0, timestamp=t - 1.0)  # 50m in 1s = ~112mph
        mgr.update_vehicle("v1", 100.0, 0.0, timestamp=t)  # Clearly moving

        commander = _make_commander(vehicle_mgr=mgr)
        instinct = InstinctLayer(commander)
        instinct._last_vehicle_check = 0

        instinct._periodic_vehicle_check()
        # Fast-moving vehicle -> not suspicious -> no narration
        commander.sensorium.push.assert_not_called()

    def test_suspicious_vehicle_triggers_narration(self):
        mgr = VehicleTrackingManager()
        # Create a crawling vehicle
        vb = mgr.update_vehicle("det_car_1", 10.0, 20.0, timestamp=1.0)
        vb.speed_mph = 5.0  # Slow crawling
        vb.stopped_since = time.monotonic() - 120  # Stopped for 2 min

        commander = _make_commander(vehicle_mgr=mgr)
        instinct = InstinctLayer(commander)
        instinct._last_vehicle_check = 0

        instinct._periodic_vehicle_check()
        commander.sensorium.push.assert_called()
        call_args = commander.sensorium.push.call_args
        assert call_args[0][0] == "thought"
        assert "det_car_1" in call_args[0][1] or "Suspicious" in call_args[0][1]

    def test_cooldown_prevents_spam(self):
        mgr = VehicleTrackingManager()
        vb = mgr.update_vehicle("det_car_1", 10.0, 20.0, timestamp=1.0)
        vb.speed_mph = 5.0
        vb.stopped_since = time.monotonic() - 120

        commander = _make_commander(vehicle_mgr=mgr)
        instinct = InstinctLayer(commander)
        instinct._last_vehicle_check = 0

        # First check triggers
        instinct._periodic_vehicle_check()
        assert commander.sensorium.push.call_count == 1

        # Second check within cooldown should not trigger again
        instinct._last_vehicle_check = 0  # Reset check timer
        instinct._periodic_vehicle_check()
        assert commander.sensorium.push.call_count == 1  # Still 1

    def test_event_published(self):
        mgr = VehicleTrackingManager()
        vb = mgr.update_vehicle("det_car_1", 10.0, 20.0, timestamp=1.0)
        vb.speed_mph = 5.0
        vb.stopped_since = time.monotonic() - 120

        commander = _make_commander(vehicle_mgr=mgr)
        instinct = InstinctLayer(commander)
        instinct._last_vehicle_check = 0

        instinct._periodic_vehicle_check()
        commander.event_bus.publish.assert_called()
        call_args = commander.event_bus.publish.call_args
        assert call_args[0][0] == "vehicle_suspicious"
        assert "target_id" in call_args[0][1]

    def test_check_interval_respected(self):
        commander = _make_commander(vehicle_mgr=VehicleTrackingManager())
        instinct = InstinctLayer(commander)
        instinct._last_vehicle_check = time.monotonic()  # Just checked

        instinct._periodic_vehicle_check()
        # Should skip due to interval
        commander.sensorium.push.assert_not_called()


class TestInstinctConstants:
    """Test that vehicle-related constants are properly set."""

    def test_vehicle_cooldown(self):
        assert InstinctLayer.VEHICLE_SUSPICIOUS_COOLDOWN == 20.0

    def test_vehicle_check_interval(self):
        assert InstinctLayer.VEHICLE_CHECK_INTERVAL == 5.0
