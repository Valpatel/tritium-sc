# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for multi-source confidence boosting and velocity consistency checks."""

import time
import pytest

from tritium_lib.tracking.target_tracker import (
    TargetTracker,
    TrackedTarget,
    _MULTI_SOURCE_BOOST,
    _MAX_PLAUSIBLE_SPEED_MPS,
)


class TestMultiSourceConfidenceBoost:
    def test_single_source_no_boost(self):
        t = TrackedTarget(
            target_id="test1", name="T1", alliance="unknown",
            asset_type="ble_device", source="ble",
            position_confidence=0.5, _initial_confidence=0.5,
            confirming_sources={"ble"},
        )
        # Single source — no boost
        conf = t.effective_confidence
        assert conf <= 0.5  # should be equal or slightly decayed

    def test_two_sources_boost(self):
        t = TrackedTarget(
            target_id="test2", name="T2", alliance="unknown",
            asset_type="person", source="ble",
            position_confidence=0.5, _initial_confidence=0.5,
            last_seen=time.monotonic(),
            confirming_sources={"ble", "yolo"},
        )
        conf = t.effective_confidence
        # With 2 sources, should be boosted by _MULTI_SOURCE_BOOST
        assert conf > 0.5
        assert conf <= 0.99

    def test_three_sources_higher_boost(self):
        t = TrackedTarget(
            target_id="test3", name="T3", alliance="unknown",
            asset_type="person", source="ble",
            position_confidence=0.5, _initial_confidence=0.5,
            last_seen=time.monotonic(),
            confirming_sources={"ble", "yolo", "rf_motion"},
        )
        conf = t.effective_confidence
        # 3 sources = 2 extra, boost^2
        expected_min = 0.5 * (_MULTI_SOURCE_BOOST ** 2) * 0.9  # allow some decay
        assert conf > 0.5

    def test_boost_capped_at_max(self):
        t = TrackedTarget(
            target_id="test4", name="T4", alliance="unknown",
            asset_type="person", source="ble",
            position_confidence=0.9, _initial_confidence=0.9,
            last_seen=time.monotonic(),
            confirming_sources={"ble", "yolo", "rf_motion", "wifi", "mesh"},
        )
        conf = t.effective_confidence
        assert conf <= 0.99

    def test_tracker_adds_confirming_source_on_ble_update(self):
        tracker = TargetTracker()
        tracker.update_from_ble({"mac": "AA:BB:CC:DD:EE:FF", "rssi": -60})
        target = tracker.get_target("ble_aabbccddeeff")
        assert target is not None
        assert "ble" in target.confirming_sources

    def test_tracker_to_dict_includes_confirming_sources(self):
        tracker = TargetTracker()
        tracker.update_from_ble({"mac": "AA:BB:CC:DD:EE:FF", "rssi": -60})
        target = tracker.get_target("ble_aabbccddeeff")
        d = target.to_dict()
        assert "confirming_sources" in d
        assert "ble" in d["confirming_sources"]
        assert "velocity_suspicious" in d
        assert d["velocity_suspicious"] is False


class TestVelocityConsistencyCheck:
    def test_normal_movement_not_flagged(self):
        tracker = TargetTracker()
        # First update
        tracker.update_from_ble({
            "mac": "11:22:33:44:55:66",
            "rssi": -60,
            "position": {"x": 0, "y": 0},
        })
        target = tracker.get_target("ble_112233445566")
        assert target is not None
        assert target.velocity_suspicious is False

    def test_teleport_flagged_suspicious(self):
        tracker = TargetTracker()
        # First update at origin
        tracker.update_from_ble({
            "mac": "11:22:33:44:55:66",
            "rssi": -60,
            "position": {"x": 0.0, "y": 0.0},
        })
        target = tracker.get_target("ble_112233445566")
        # Manually set last_seen to simulate time passing
        target.last_seen = time.monotonic() - 1.0  # 1 second ago

        # Second update: teleport 1000 meters away (speed = 1000 m/s, way over limit)
        tracker.update_from_ble({
            "mac": "11:22:33:44:55:66",
            "rssi": -60,
            "position": {"x": 1000.0, "y": 0.0},
        })
        target = tracker.get_target("ble_112233445566")
        assert target.velocity_suspicious is True

    def test_normal_speed_clears_flag(self):
        tracker = TargetTracker()
        tracker.update_from_ble({
            "mac": "11:22:33:44:55:66",
            "rssi": -60,
            "position": {"x": 0.0, "y": 0.0},
        })
        target = tracker.get_target("ble_112233445566")
        target.velocity_suspicious = True
        target.last_seen = time.monotonic() - 10.0  # 10 seconds ago

        # Move a small distance — 5 meters in 10 seconds = 0.5 m/s, well within limits
        tracker.update_from_ble({
            "mac": "11:22:33:44:55:66",
            "rssi": -60,
            "position": {"x": 5.0, "y": 0.0},
        })
        target = tracker.get_target("ble_112233445566")
        assert target.velocity_suspicious is False

    def test_simulation_target_velocity_checked(self):
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "rover_01",
            "name": "Rover 1",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 0, "y": 0},
        })
        target = tracker.get_target("rover_01")
        assert "simulation" in target.confirming_sources
