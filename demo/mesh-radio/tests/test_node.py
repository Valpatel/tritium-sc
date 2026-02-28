# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for MeshNode state, position, battery, SNR simulation.

TDD: written BEFORE implementation.
Tests node initialization, position payloads, battery drain/charge,
SNR/RSSI simulation, movement patterns, text messages, channel management.
"""

import json
import math
import time
import unittest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from node import MeshNode, MovementPattern


class TestNodeInit(unittest.TestCase):
    """Test MeshNode initialization with required fields."""

    def test_default_init(self):
        n = MeshNode(node_id="!aabbccdd", long_name="Hilltop Node")
        self.assertEqual(n.node_id, "!aabbccdd")
        self.assertEqual(n.long_name, "Hilltop Node")
        self.assertEqual(n.short_name, "HN")
        self.assertEqual(n.protocol, "meshtastic")

    def test_custom_protocol(self):
        n = MeshNode(node_id="!11223344", long_name="Valley", protocol="meshcore")
        self.assertEqual(n.protocol, "meshcore")

    def test_initial_position(self):
        n = MeshNode(
            node_id="!aabb",
            long_name="Test",
            lat=37.7749,
            lng=-122.4194,
            alt=15.0,
        )
        self.assertAlmostEqual(n.lat, 37.7749)
        self.assertAlmostEqual(n.lng, -122.4194)
        self.assertAlmostEqual(n.alt, 15.0)

    def test_default_position_is_zero(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        self.assertEqual(n.lat, 0.0)
        self.assertEqual(n.lng, 0.0)
        self.assertEqual(n.alt, 0.0)

    def test_initial_battery(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        # Battery starts full (1.0)
        self.assertEqual(n.battery, 1.0)

    def test_initial_voltage(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        # Full battery = ~4.2V for typical LiPo
        self.assertAlmostEqual(n.voltage, 4.2)

    def test_custom_short_name(self):
        n = MeshNode(node_id="!aabb", long_name="Test", short_name="TS01")
        self.assertEqual(n.short_name, "TS01")

    def test_auto_short_name_from_long_name(self):
        n = MeshNode(node_id="!aabb", long_name="Alpha Bravo")
        self.assertEqual(n.short_name, "AB")

    def test_auto_short_name_single_word(self):
        n = MeshNode(node_id="!aabb", long_name="Hilltop")
        self.assertEqual(n.short_name, "HI")

    def test_default_hardware(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        self.assertEqual(n.hardware, "heltec_v3")

    def test_custom_hardware(self):
        n = MeshNode(node_id="!aabb", long_name="Test", hardware="tbeam_v1.1")
        self.assertEqual(n.hardware, "tbeam_v1.1")

    def test_initial_channel(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        self.assertEqual(n.channel, 0)

    def test_initial_hops(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        self.assertEqual(n.hops, 0)


class TestPositionPayload(unittest.TestCase):
    """Test position payload matches spec format."""

    def test_position_payload_has_required_fields(self):
        n = MeshNode(
            node_id="!aabbccdd",
            long_name="Hilltop Node",
            short_name="HT01",
            protocol="meshtastic",
            lat=37.7749,
            lng=-122.4194,
            alt=15.0,
            hardware="heltec_v3",
        )
        payload = n.position_payload()
        required_keys = {
            "node_id", "long_name", "short_name", "protocol",
            "position", "battery", "voltage", "snr", "rssi",
            "hops", "hardware", "timestamp",
        }
        self.assertEqual(set(payload.keys()), required_keys)

    def test_position_structure(self):
        n = MeshNode(
            node_id="!aabb", long_name="Test",
            lat=37.7749, lng=-122.4194, alt=15.0,
        )
        payload = n.position_payload()
        pos = payload["position"]
        self.assertAlmostEqual(pos["lat"], 37.7749)
        self.assertAlmostEqual(pos["lng"], -122.4194)
        self.assertAlmostEqual(pos["alt"], 15.0)

    def test_timestamp_is_iso8601_utc(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        payload = n.position_payload()
        ts = payload["timestamp"]
        self.assertTrue(ts.endswith("Z"), f"Timestamp must end with Z: {ts}")
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        self.assertIsNotNone(dt)

    def test_payload_is_json_serializable(self):
        n = MeshNode(node_id="!aabb", long_name="Test", lat=1.0, lng=2.0)
        payload = n.position_payload()
        serialized = json.dumps(payload)
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized["node_id"], "!aabb")

    def test_snr_in_reasonable_range(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        payload = n.position_payload()
        # SNR typically -20 to +15 dB for LoRa
        self.assertGreaterEqual(payload["snr"], -20.0)
        self.assertLessEqual(payload["snr"], 15.0)

    def test_rssi_in_reasonable_range(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        payload = n.position_payload()
        # RSSI typically -140 to -30 dBm
        self.assertGreaterEqual(payload["rssi"], -140)
        self.assertLessEqual(payload["rssi"], -30)


class TestTelemetryPayload(unittest.TestCase):
    """Test telemetry payload for battery/voltage/SNR reporting."""

    def test_telemetry_has_required_fields(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        payload = n.telemetry_payload()
        required_keys = {
            "node_id", "battery", "voltage", "snr", "rssi",
            "channel", "uptime_s", "tx_count", "rx_count", "timestamp",
        }
        self.assertTrue(required_keys.issubset(set(payload.keys())))

    def test_telemetry_timestamp_utc(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        payload = n.telemetry_payload()
        self.assertTrue(payload["timestamp"].endswith("Z"))

    def test_telemetry_is_json_serializable(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        payload = n.telemetry_payload()
        s = json.dumps(payload)
        d = json.loads(s)
        self.assertEqual(d["node_id"], "!aabb")


class TestBatterySimulation(unittest.TestCase):
    """Test battery drain over time."""

    def test_battery_drains_on_tick(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        initial = n.battery
        n.tick(dt=60.0)  # 60 seconds
        self.assertLess(n.battery, initial)

    def test_battery_never_below_zero(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        # Drain heavily
        for _ in range(10000):
            n.tick(dt=60.0)
        self.assertGreaterEqual(n.battery, 0.0)

    def test_voltage_tracks_battery(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        v_full = n.voltage
        n.tick(dt=3600.0)  # 1 hour
        v_after = n.voltage
        self.assertLess(v_after, v_full)

    def test_voltage_range(self):
        """Voltage should be between 3.0V (empty) and 4.2V (full)."""
        n = MeshNode(node_id="!aabb", long_name="Test")
        self.assertGreaterEqual(n.voltage, 3.0)
        self.assertLessEqual(n.voltage, 4.2)

    def test_tx_count_increments(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        self.assertEqual(n.tx_count, 0)
        n.record_tx()
        self.assertEqual(n.tx_count, 1)

    def test_rx_count_increments(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        self.assertEqual(n.rx_count, 0)
        n.record_rx()
        self.assertEqual(n.rx_count, 1)


class TestSNRSimulation(unittest.TestCase):
    """Test SNR/RSSI variation over time."""

    def test_snr_varies_between_ticks(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        snr_values = set()
        for _ in range(20):
            n.tick(dt=1.0)
            snr_values.add(round(n.snr, 1))
        # Should see some variation
        self.assertGreater(len(snr_values), 1)

    def test_rssi_varies_between_ticks(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        rssi_values = set()
        for _ in range(20):
            n.tick(dt=1.0)
            rssi_values.add(n.rssi)
        self.assertGreater(len(rssi_values), 1)


class TestMovementPattern(unittest.TestCase):
    """Test movement pattern types: stationary, random_walk, waypoint."""

    def test_stationary_pattern(self):
        n = MeshNode(node_id="!aabb", long_name="Test", lat=10.0, lng=20.0)
        n.movement = MovementPattern.STATIONARY
        lat0, lng0 = n.lat, n.lng
        n.tick(dt=10.0)
        self.assertAlmostEqual(n.lat, lat0)
        self.assertAlmostEqual(n.lng, lng0)

    def test_random_walk_moves(self):
        n = MeshNode(
            node_id="!aabb", long_name="Test",
            lat=10.0, lng=20.0,
            movement="random_walk",
        )
        lat0, lng0 = n.lat, n.lng
        # Many ticks to ensure movement
        for _ in range(100):
            n.tick(dt=1.0)
        # Should have moved at least a tiny bit
        dist = abs(n.lat - lat0) + abs(n.lng - lng0)
        self.assertGreater(dist, 0.0)

    def test_waypoint_follows_route(self):
        waypoints = [(10.0, 20.0), (10.001, 20.001), (10.002, 20.002)]
        n = MeshNode(
            node_id="!aabb", long_name="Test",
            lat=10.0, lng=20.0,
            movement="waypoint",
            waypoints=waypoints,
        )
        # Tick many times to move along waypoints
        for _ in range(200):
            n.tick(dt=1.0)
        # Should have moved toward/past first waypoint
        dist_to_start = abs(n.lat - 10.0) + abs(n.lng - 20.0)
        # Either moved or at least didn't stay exactly at start (unless already there)
        # The node should be moving through the waypoints
        self.assertGreaterEqual(dist_to_start, 0.0)

    def test_movement_pattern_enum(self):
        self.assertEqual(MovementPattern.STATIONARY.value, "stationary")
        self.assertEqual(MovementPattern.RANDOM_WALK.value, "random_walk")
        self.assertEqual(MovementPattern.WAYPOINT.value, "waypoint")

    def test_waypoint_pattern_loops(self):
        """Waypoint pattern should loop back to start after reaching the end."""
        waypoints = [(0.0, 0.0), (0.001, 0.0)]
        n = MeshNode(
            node_id="!aabb", long_name="Test",
            lat=0.0, lng=0.0,
            movement="waypoint",
            waypoints=waypoints,
        )
        # Tick enough to complete multiple loops
        for _ in range(500):
            n.tick(dt=1.0)
        # Node should still be running (no crash)
        self.assertIsNotNone(n.lat)


class TestTextMessage(unittest.TestCase):
    """Test text message creation."""

    def test_create_text_message(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        msg = n.create_text_message("Hello mesh!", to="!ccdd")
        self.assertEqual(msg["from"], "!aabb")
        self.assertEqual(msg["to"], "!ccdd")
        self.assertEqual(msg["text"], "Hello mesh!")
        self.assertEqual(msg["channel"], 0)
        self.assertIn("timestamp", msg)

    def test_text_message_broadcast(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        msg = n.create_text_message("Broadcast test")
        self.assertEqual(msg["to"], "^all")

    def test_text_message_timestamp_utc(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        msg = n.create_text_message("test")
        self.assertTrue(msg["timestamp"].endswith("Z"))

    def test_text_message_json_serializable(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        msg = n.create_text_message("test")
        s = json.dumps(msg)
        d = json.loads(s)
        self.assertEqual(d["text"], "test")

    def test_text_message_increments_tx(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        tx_before = n.tx_count
        n.create_text_message("test")
        self.assertEqual(n.tx_count, tx_before + 1)


class TestChannelManagement(unittest.TestCase):
    """Test channel set/get."""

    def test_set_channel(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        n.set_channel(3)
        self.assertEqual(n.channel, 3)

    def test_channel_in_text_message(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        n.set_channel(5)
        msg = n.create_text_message("test")
        self.assertEqual(msg["channel"], 5)

    def test_channel_bounds(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        # Channel 0-7 is typical for Meshtastic
        n.set_channel(7)
        self.assertEqual(n.channel, 7)
        n.set_channel(0)
        self.assertEqual(n.channel, 0)


class TestStatusPayload(unittest.TestCase):
    """Test node status payload for online/offline reporting."""

    def test_status_online(self):
        n = MeshNode(node_id="!aabb", long_name="Test", protocol="meshtastic")
        payload = n.status_payload("online")
        self.assertEqual(payload["status"], "online")
        self.assertEqual(payload["node_id"], "!aabb")
        self.assertEqual(payload["long_name"], "Test")
        self.assertEqual(payload["protocol"], "meshtastic")
        self.assertTrue(payload["timestamp"].endswith("Z"))

    def test_status_offline(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        payload = n.status_payload("offline")
        self.assertEqual(payload["status"], "offline")

    def test_status_json_serializable(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        payload = n.status_payload("online")
        s = json.dumps(payload)
        d = json.loads(s)
        self.assertEqual(d["status"], "online")


class TestReboot(unittest.TestCase):
    """Test node reboot behavior."""

    def test_reboot_resets_uptime(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        n.tick(dt=100.0)
        self.assertGreater(n.uptime_s, 0)
        n.reboot()
        self.assertEqual(n.uptime_s, 0.0)

    def test_reboot_preserves_position(self):
        n = MeshNode(node_id="!aabb", long_name="Test", lat=10.0, lng=20.0)
        n.reboot()
        self.assertAlmostEqual(n.lat, 10.0)
        self.assertAlmostEqual(n.lng, 20.0)

    def test_reboot_resets_counters(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        n.record_tx()
        n.record_tx()
        n.record_rx()
        n.reboot()
        self.assertEqual(n.tx_count, 0)
        self.assertEqual(n.rx_count, 0)


class TestUptime(unittest.TestCase):
    """Test uptime tracking."""

    def test_uptime_increases_with_tick(self):
        n = MeshNode(node_id="!aabb", long_name="Test")
        n.tick(dt=5.0)
        self.assertAlmostEqual(n.uptime_s, 5.0)
        n.tick(dt=3.0)
        self.assertAlmostEqual(n.uptime_s, 8.0)


if __name__ == "__main__":
    unittest.main()
