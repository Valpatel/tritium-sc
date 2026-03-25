# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for BLE device tracking in TargetTracker."""

import time

import pytest

from tritium_lib.tracking.target_tracker import TargetTracker, TrackedTarget


@pytest.mark.unit
class TestBLETracking:
    """Verify BLE sightings flow into TargetTracker correctly."""

    def test_basic_ble_sighting(self):
        tracker = TargetTracker()
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Matt's Watch",
            "rssi": -50,
            "node_id": "edge-01",
        })
        targets = tracker.get_all()
        assert len(targets) == 1
        t = targets[0]
        assert t.target_id == "ble_aabbccddeeff"
        assert t.name == "Matt's Watch"
        assert t.source == "ble"
        assert t.asset_type == "ble_device"
        assert t.alliance == "unknown"

    def test_ble_rssi_to_confidence(self):
        tracker = TargetTracker()

        # Strong signal → high confidence
        tracker.update_from_ble({"mac": "AA:BB:CC:DD:EE:01", "rssi": -30})
        t = tracker.get_target("ble_aabbccddee01")
        assert t.position_confidence == 1.0

        # Weak signal → low confidence
        tracker.update_from_ble({"mac": "AA:BB:CC:DD:EE:02", "rssi": -95})
        t = tracker.get_target("ble_aabbccddee02")
        assert t.position_confidence < 0.15

    def test_ble_updates_existing_target(self):
        tracker = TargetTracker()
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Watch",
            "rssi": -60,
        })
        first_seen = tracker.get_target("ble_aabbccddeeff").last_seen

        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Watch",
            "rssi": -40,
        })
        targets = tracker.get_all()
        assert len(targets) == 1
        t = targets[0]
        assert t.last_seen >= first_seen
        assert t.position_confidence > 0.8  # stronger signal

    def test_ble_with_trilateration_position(self):
        tracker = TargetTracker()
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Phone",
            "rssi": -50,
            "position": {"x": 10.5, "y": 20.3},
        })
        t = tracker.get_target("ble_aabbccddeeff")
        assert t.position == (10.5, 20.3)
        assert t.position_source == "trilateration"

    def test_ble_with_node_proximity(self):
        tracker = TargetTracker()
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Beacon",
            "rssi": -50,
            "node_position": {"x": 5.0, "y": 8.0},
        })
        t = tracker.get_target("ble_aabbccddeeff")
        assert t.position == (5.0, 8.0)
        assert t.position_source == "node_proximity"

    def test_ble_empty_mac_ignored(self):
        tracker = TargetTracker()
        tracker.update_from_ble({"mac": "", "name": "NoMAC"})
        assert len(tracker.get_all()) == 0

    def test_ble_stale_pruning(self):
        tracker = TargetTracker()
        tracker.BLE_STALE_TIMEOUT = 0.1  # 100ms for test speed
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "rssi": -50,
        })
        assert len(tracker.get_all()) == 1

        time.sleep(0.15)
        assert len(tracker.get_all()) == 0

    def test_ble_coexists_with_simulation_targets(self):
        tracker = TargetTracker()
        tracker.update_from_simulation({
            "target_id": "rover-01",
            "name": "Rover Alpha",
            "alliance": "friendly",
            "asset_type": "rover",
            "position": {"x": 1.0, "y": 2.0},
        })
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Watch",
            "rssi": -50,
        })
        targets = tracker.get_all()
        assert len(targets) == 2
        sources = {t.source for t in targets}
        assert sources == {"simulation", "ble"}

    def test_ble_uses_name_or_mac_as_fallback(self):
        tracker = TargetTracker()

        tracker.update_from_ble({"mac": "AA:BB:CC:DD:EE:01", "name": "My Device"})
        assert tracker.get_target("ble_aabbccddee01").name == "My Device"

        tracker.update_from_ble({"mac": "AA:BB:CC:DD:EE:02", "name": ""})
        assert tracker.get_target("ble_aabbccddee02").name == "AA:BB:CC:DD:EE:02"

        tracker.update_from_ble({"mac": "AA:BB:CC:DD:EE:03"})
        assert tracker.get_target("ble_aabbccddee03").name == "AA:BB:CC:DD:EE:03"

    def test_multiple_nodes_same_device_updates_not_duplicates(self):
        tracker = TargetTracker()
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Watch",
            "rssi": -60,
            "node_id": "edge-01",
        })
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Watch",
            "rssi": -45,
            "node_id": "edge-02",
        })
        targets = tracker.get_all()
        assert len(targets) == 1
        t = targets[0]
        assert t.target_id == "ble_aabbccddeeff"
        # Second update had stronger signal
        assert t.position_confidence > 0.7

    def test_mac_normalization_uppercase(self):
        tracker = TargetTracker()
        tracker.update_from_ble({"mac": "AA:BB:CC:DD:EE:FF", "rssi": -50})
        assert tracker.get_target("ble_aabbccddeeff") is not None

    def test_mac_normalization_lowercase(self):
        tracker = TargetTracker()
        tracker.update_from_ble({"mac": "aa:bb:cc:dd:ee:ff", "rssi": -50})
        assert tracker.get_target("ble_aabbccddeeff") is not None

    def test_mac_normalization_mixed_case_same_target(self):
        tracker = TargetTracker()
        tracker.update_from_ble({"mac": "AA:BB:CC:DD:EE:FF", "rssi": -60})
        tracker.update_from_ble({"mac": "aa:bb:cc:dd:ee:ff", "rssi": -50})
        assert len(tracker.get_all()) == 1

    def test_rapid_updates_no_duplicates(self):
        tracker = TargetTracker()
        for i in range(50):
            tracker.update_from_ble({
                "mac": "11:22:33:44:55:66",
                "name": "Rapid",
                "rssi": -50 - (i % 20),
            })
        targets = tracker.get_all()
        ble_targets = [t for t in targets if t.target_id == "ble_112233445566"]
        assert len(ble_targets) == 1

    def test_rapid_updates_different_macs_unique_targets(self):
        tracker = TargetTracker()
        for i in range(10):
            tracker.update_from_ble({
                "mac": f"AA:BB:CC:DD:EE:{i:02X}",
                "rssi": -50,
            })
        targets = tracker.get_all()
        assert len(targets) == 10

    def test_ble_update_preserves_position_on_unknown_source(self):
        tracker = TargetTracker()
        # First sighting with trilateration position
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "rssi": -50,
            "position": {"x": 5.0, "y": 10.0},
        })
        t = tracker.get_target("ble_aabbccddeeff")
        assert t.position == (5.0, 10.0)
        # Second sighting without position — should NOT reset position
        tracker.update_from_ble({
            "mac": "AA:BB:CC:DD:EE:FF",
            "rssi": -55,
        })
        t = tracker.get_target("ble_aabbccddeeff")
        assert t.position == (5.0, 10.0)
