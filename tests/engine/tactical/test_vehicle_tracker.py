# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for vehicle behavior tracking."""

import time

import pytest

from engine.tactical.vehicle_tracker import (
    VehicleBehavior,
    VehicleTrackingManager,
    VEHICLE_CLASSES,
)


class TestVehicleBehavior:
    def test_init(self):
        vb = VehicleBehavior("det_car_1", "car")
        assert vb.target_id == "det_car_1"
        assert vb.vehicle_class == "car"
        assert vb.speed_mph == 0.0
        assert not vb.is_moving
        assert not vb.is_parked

    def test_single_update(self):
        vb = VehicleBehavior("det_car_1")
        vb.update(0.0, 0.0, timestamp=100.0)
        assert len(vb.positions) == 1
        assert vb.speed_mph == 0.0  # No speed from single point

    def test_speed_computation(self):
        """Two positions 10m apart in 1 second = ~22 mph."""
        vb = VehicleBehavior("det_car_1")
        vb.update(0.0, 0.0, timestamp=100.0)
        vb.update(10.0, 0.0, timestamp=101.0)  # 10 meters east in 1 second
        # 10 m/s = 22.37 mph
        assert 22.0 < vb.speed_mph < 23.0
        assert vb.is_moving

    def test_heading_north(self):
        vb = VehicleBehavior("det_car_1")
        vb.update(0.0, 0.0, timestamp=100.0)
        vb.update(0.0, 10.0, timestamp=101.0)  # Moving north
        assert 350 < vb.heading or vb.heading < 10  # North

    def test_heading_east(self):
        vb = VehicleBehavior("det_car_1")
        vb.update(0.0, 0.0, timestamp=100.0)
        vb.update(10.0, 0.0, timestamp=101.0)  # Moving east
        assert 80 < vb.heading < 100  # East

    def test_stopped_detection(self):
        vb = VehicleBehavior("det_car_1")
        vb.update(5.0, 5.0, timestamp=100.0)
        vb.update(5.0, 5.0, timestamp=101.0)  # Not moving
        assert not vb.is_moving
        assert vb.stopped_since is not None

    def test_direction_label(self):
        vb = VehicleBehavior("det_car_1")
        vb.heading = 0
        assert vb.direction_label == "N"
        vb.heading = 90
        assert vb.direction_label == "E"
        vb.heading = 180
        assert vb.direction_label == "S"
        vb.heading = 270
        assert vb.direction_label == "W"

    def test_speed_variance(self):
        vb = VehicleBehavior("det_car_1")
        # Constant speed
        for i in range(10):
            vb.update(float(i * 10), 0.0, timestamp=100.0 + i)
        assert vb.speed_variance < 1.0  # Very consistent

    def test_suspicious_score_loitering(self):
        vb = VehicleBehavior("det_car_1")
        vb.update(5.0, 5.0, timestamp=100.0)
        vb.update(5.0, 5.0, timestamp=101.0)
        # Manually set stopped_since to simulate long stop
        vb.stopped_since = time.monotonic() - 400  # 400 seconds ago
        score = vb.get_suspicious_score()
        assert score >= 0.3  # Should flag loitering

    def test_suspicious_unusual_location(self):
        vb = VehicleBehavior("det_car_1")
        vb.update(5.0, 5.0, timestamp=100.0)
        vb.update(5.0, 5.0, timestamp=101.0)
        vb.stopped_since = time.monotonic() - 120
        score_normal = vb.get_suspicious_score(is_unusual_location=False)
        score_unusual = vb.get_suspicious_score(is_unusual_location=True)
        assert score_unusual > score_normal

    def test_to_dict(self):
        vb = VehicleBehavior("det_car_1", "truck")
        vb.update(0.0, 0.0, timestamp=100.0)
        vb.update(10.0, 0.0, timestamp=101.0)
        d = vb.to_dict()
        assert d["target_id"] == "det_car_1"
        assert d["vehicle_class"] == "truck"
        assert d["speed_mph"] > 0
        assert "direction" in d
        assert "trail" in d

    def test_trail_limit(self):
        vb = VehicleBehavior("det_car_1")
        for i in range(50):
            vb.update(float(i), 0.0, timestamp=100.0 + i)
        assert len(vb.positions) <= 20  # MAX_TRAIL_LENGTH


class TestVehicleTrackingManager:
    def test_init(self):
        mgr = VehicleTrackingManager()
        assert mgr.count == 0

    def test_update_creates_vehicle(self):
        mgr = VehicleTrackingManager()
        vb = mgr.update_vehicle("det_car_1", 0.0, 0.0)
        assert mgr.count == 1
        assert vb.target_id == "det_car_1"

    def test_update_existing_vehicle(self):
        mgr = VehicleTrackingManager()
        mgr.update_vehicle("det_car_1", 0.0, 0.0, timestamp=100.0)
        mgr.update_vehicle("det_car_1", 10.0, 0.0, timestamp=101.0)
        assert mgr.count == 1
        vb = mgr.get_vehicle("det_car_1")
        assert vb.speed_mph > 0

    def test_get_all(self):
        mgr = VehicleTrackingManager()
        mgr.update_vehicle("det_car_1", 0.0, 0.0)
        mgr.update_vehicle("det_car_2", 5.0, 5.0)
        assert len(mgr.get_all()) == 2

    def test_remove(self):
        mgr = VehicleTrackingManager()
        mgr.update_vehicle("det_car_1", 0.0, 0.0)
        mgr.remove("det_car_1")
        assert mgr.count == 0

    def test_get_stopped(self):
        mgr = VehicleTrackingManager()
        # Stopped vehicle
        mgr.update_vehicle("det_car_1", 5.0, 5.0, timestamp=100.0)
        mgr.update_vehicle("det_car_1", 5.0, 5.0, timestamp=101.0)
        # Moving vehicle
        mgr.update_vehicle("det_car_2", 0.0, 0.0, timestamp=100.0)
        mgr.update_vehicle("det_car_2", 50.0, 0.0, timestamp=101.0)
        stopped = mgr.get_stopped()
        assert len(stopped) == 1
        assert stopped[0].target_id == "det_car_1"

    def test_get_summary(self):
        mgr = VehicleTrackingManager()
        mgr.update_vehicle("det_car_1", 0.0, 0.0, timestamp=100.0)
        mgr.update_vehicle("det_car_1", 50.0, 0.0, timestamp=101.0)
        mgr.update_vehicle("det_car_2", 5.0, 5.0, timestamp=100.0)
        mgr.update_vehicle("det_car_2", 5.0, 5.0, timestamp=101.0)
        summary = mgr.get_summary()
        assert summary["total"] == 2
        assert summary["moving"] == 1
        assert summary["stopped"] == 1

    def test_max_vehicles_eviction(self):
        mgr = VehicleTrackingManager(max_vehicles=5)
        for i in range(10):
            mgr.update_vehicle(f"det_car_{i}", float(i), 0.0, timestamp=100.0 + i)
        assert mgr.count <= 5

    def test_vehicle_classes(self):
        assert "car" in VEHICLE_CLASSES
        assert "truck" in VEHICLE_CLASSES
        assert "bus" in VEHICLE_CLASSES
        assert "motorcycle" in VEHICLE_CLASSES
        assert "bicycle" in VEHICLE_CLASSES
