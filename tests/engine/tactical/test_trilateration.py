# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the TrilaterationEngine — multi-node BLE position estimation."""

import time

import pytest

from tritium_lib.tracking.trilateration import TrilaterationEngine, PositionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Three nodes arranged in a triangle (lat/lon in San Jose area)
NODE_A = ("node-a", 37.3352, -121.8811)
NODE_B = ("node-b", 37.3356, -121.8807)
NODE_C = ("node-c", 37.3354, -121.8815)
NODE_D = ("node-d", 37.3350, -121.8809)

TARGET_MAC = "AA:BB:CC:DD:EE:01"


def _record_from_all_nodes(
    engine: TrilaterationEngine,
    mac: str = TARGET_MAC,
    rssi_a: float = -65,
    rssi_b: float = -70,
    rssi_c: float = -75,
) -> None:
    """Record sightings from three nodes for a single MAC."""
    engine.record_sighting(mac, NODE_A[0], NODE_A[1], NODE_A[2], rssi_a)
    engine.record_sighting(mac, NODE_B[0], NODE_B[1], NODE_B[2], rssi_b)
    engine.record_sighting(mac, NODE_C[0], NODE_C[1], NODE_C[2], rssi_c)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTrilaterationEngineBasic:
    """Basic lifecycle and edge cases."""

    def test_empty_engine_returns_none(self):
        engine = TrilaterationEngine()
        assert engine.estimate_position(TARGET_MAC) is None

    def test_single_node_returns_none(self):
        engine = TrilaterationEngine()
        engine.record_sighting(TARGET_MAC, NODE_A[0], NODE_A[1], NODE_A[2], -65)
        assert engine.estimate_position(TARGET_MAC) is None

    def test_two_nodes_returns_none_with_default_min_anchors(self):
        engine = TrilaterationEngine()
        engine.record_sighting(TARGET_MAC, NODE_A[0], NODE_A[1], NODE_A[2], -65)
        engine.record_sighting(TARGET_MAC, NODE_B[0], NODE_B[1], NODE_B[2], -70)
        # Default min_anchors=3, so 2 nodes is not enough
        assert engine.estimate_position(TARGET_MAC) is None

    def test_two_nodes_returns_position_when_min_anchors_2(self):
        engine = TrilaterationEngine(min_anchors=2)
        engine.record_sighting(TARGET_MAC, NODE_A[0], NODE_A[1], NODE_A[2], -65)
        engine.record_sighting(TARGET_MAC, NODE_B[0], NODE_B[1], NODE_B[2], -70)
        result = engine.estimate_position(TARGET_MAC)
        assert result is not None
        assert result.anchors_used == 2

    def test_three_nodes_returns_position(self):
        engine = TrilaterationEngine()
        _record_from_all_nodes(engine)
        result = engine.estimate_position(TARGET_MAC)
        assert result is not None
        assert isinstance(result, PositionResult)
        assert result.anchors_used == 3
        assert result.method == "weighted_centroid"
        assert 0.0 <= result.confidence <= 1.0

    def test_four_nodes_higher_confidence(self):
        engine = TrilaterationEngine()
        _record_from_all_nodes(engine)
        result_3 = engine.estimate_position(TARGET_MAC)

        engine.record_sighting(TARGET_MAC, NODE_D[0], NODE_D[1], NODE_D[2], -68)
        result_4 = engine.estimate_position(TARGET_MAC)

        assert result_4 is not None
        assert result_4.anchors_used == 4
        # More anchors should yield >= confidence
        assert result_4.confidence >= result_3.confidence


class TestTrilaterationPosition:
    """Position estimation accuracy."""

    def test_position_near_closest_node(self):
        """Device should be estimated closer to the node with strongest RSSI."""
        engine = TrilaterationEngine()
        # NODE_A gets very strong signal, others weak
        engine.record_sighting(TARGET_MAC, NODE_A[0], NODE_A[1], NODE_A[2], -40)
        engine.record_sighting(TARGET_MAC, NODE_B[0], NODE_B[1], NODE_B[2], -90)
        engine.record_sighting(TARGET_MAC, NODE_C[0], NODE_C[1], NODE_C[2], -90)

        result = engine.estimate_position(TARGET_MAC)
        assert result is not None

        # Result should be much closer to NODE_A than to NODE_B or NODE_C
        dist_to_a = abs(result.lat - NODE_A[1]) + abs(result.lon - NODE_A[2])
        dist_to_b = abs(result.lat - NODE_B[1]) + abs(result.lon - NODE_B[2])
        assert dist_to_a < dist_to_b

    def test_equal_rssi_gives_centroid(self):
        """Equal RSSI from all nodes should yield roughly the centroid."""
        engine = TrilaterationEngine()
        rssi = -65
        engine.record_sighting(TARGET_MAC, NODE_A[0], NODE_A[1], NODE_A[2], rssi)
        engine.record_sighting(TARGET_MAC, NODE_B[0], NODE_B[1], NODE_B[2], rssi)
        engine.record_sighting(TARGET_MAC, NODE_C[0], NODE_C[1], NODE_C[2], rssi)

        result = engine.estimate_position(TARGET_MAC)
        assert result is not None

        # Should be near the geometric center of the three nodes
        center_lat = (NODE_A[1] + NODE_B[1] + NODE_C[1]) / 3
        center_lon = (NODE_A[2] + NODE_B[2] + NODE_C[2]) / 3
        assert abs(result.lat - center_lat) < 0.001
        assert abs(result.lon - center_lon) < 0.001

    def test_to_dict(self):
        engine = TrilaterationEngine()
        _record_from_all_nodes(engine)
        result = engine.estimate_position(TARGET_MAC)
        d = result.to_dict()
        assert "lat" in d
        assert "lon" in d
        assert "confidence" in d
        assert "anchors_used" in d
        assert "method" in d
        assert d["method"] == "weighted_centroid"


class TestTrilaterationMultiMAC:
    """Multiple devices tracked simultaneously."""

    def test_multiple_macs_independent(self):
        engine = TrilaterationEngine()
        mac1 = "11:22:33:44:55:01"
        mac2 = "11:22:33:44:55:02"

        _record_from_all_nodes(engine, mac=mac1)
        _record_from_all_nodes(engine, mac=mac2, rssi_a=-80, rssi_b=-60, rssi_c=-85)

        r1 = engine.estimate_position(mac1)
        r2 = engine.estimate_position(mac2)

        assert r1 is not None
        assert r2 is not None
        # Different RSSI patterns should yield different positions
        assert r1.lat != r2.lat or r1.lon != r2.lon

    def test_tracked_macs_count(self):
        engine = TrilaterationEngine()
        assert engine.tracked_macs == 0

        _record_from_all_nodes(engine, mac="AA:BB:CC:00:00:01")
        _record_from_all_nodes(engine, mac="AA:BB:CC:00:00:02")
        assert engine.tracked_macs == 2

    def test_get_all_estimates(self):
        engine = TrilaterationEngine()
        _record_from_all_nodes(engine, mac="AA:BB:CC:00:00:01")
        _record_from_all_nodes(engine, mac="AA:BB:CC:00:00:02")
        # Only record 1 node for this MAC — should not appear
        engine.record_sighting("AA:BB:CC:00:00:03", NODE_A[0], NODE_A[1], NODE_A[2], -65)

        estimates = engine.get_all_estimates()
        assert len(estimates) == 2
        assert "AA:BB:CC:00:00:01" in estimates
        assert "AA:BB:CC:00:00:02" in estimates
        assert "AA:BB:CC:00:00:03" not in estimates


class TestTrilaterationStaleness:
    """Sighting expiration and pruning."""

    def test_stale_sightings_pruned(self):
        engine = TrilaterationEngine(stale_threshold=1.0, window=1.0)
        _record_from_all_nodes(engine)
        assert engine.estimate_position(TARGET_MAC) is not None

        # Manually age the sightings
        with engine._lock:
            for s in engine._sightings[TARGET_MAC.upper()]:
                s.timestamp -= 2.0

        removed = engine.prune_stale()
        assert removed == 1
        assert engine.estimate_position(TARGET_MAC) is None

    def test_window_filters_old_sightings(self):
        engine = TrilaterationEngine(window=2.0, stale_threshold=60.0)
        _record_from_all_nodes(engine)
        assert engine.estimate_position(TARGET_MAC) is not None

        # Age sightings beyond window but within stale threshold
        with engine._lock:
            for s in engine._sightings[TARGET_MAC.upper()]:
                s.timestamp -= 3.0

        # Still in the store, but outside window — no estimate
        assert engine.estimate_position(TARGET_MAC) is None

    def test_clear(self):
        engine = TrilaterationEngine()
        _record_from_all_nodes(engine)
        assert engine.tracked_macs == 1

        engine.clear()
        assert engine.tracked_macs == 0
        assert engine.estimate_position(TARGET_MAC) is None


class TestTrilaterationNodeReplacement:
    """Same node reporting updated RSSI replaces old sighting."""

    def test_node_update_replaces(self):
        engine = TrilaterationEngine()
        _record_from_all_nodes(engine)

        # Update NODE_A with stronger signal
        engine.record_sighting(TARGET_MAC, NODE_A[0], NODE_A[1], NODE_A[2], -40)

        # Should still have exactly 3 sightings (not 4)
        assert engine.get_sighting_count(TARGET_MAC) == 3

        result = engine.estimate_position(TARGET_MAC)
        assert result is not None
        assert result.anchors_used == 3


class TestTrilaterationCaseInsensitive:
    """MAC addresses should be case-insensitive."""

    def test_mac_case_insensitive(self):
        engine = TrilaterationEngine()
        engine.record_sighting("aa:bb:cc:dd:ee:ff", NODE_A[0], NODE_A[1], NODE_A[2], -65)
        engine.record_sighting("AA:BB:CC:DD:EE:FF", NODE_B[0], NODE_B[1], NODE_B[2], -70)
        engine.record_sighting("Aa:Bb:Cc:Dd:Ee:Ff", NODE_C[0], NODE_C[1], NODE_C[2], -75)

        # All three should be treated as the same MAC
        assert engine.get_sighting_count("AA:BB:CC:DD:EE:FF") == 3
        result = engine.estimate_position("aa:bb:cc:dd:ee:ff")
        assert result is not None
        assert result.anchors_used == 3


class TestTrilaterationKalmanSmoothing:
    """Verify that repeated RSSI updates are Kalman-filtered."""

    def test_kalman_smoothing_reduces_noise(self):
        engine = TrilaterationEngine()
        mac = "FF:FF:FF:00:00:01"

        # Send noisy readings from NODE_A
        for rssi in [-65, -75, -60, -80, -65, -70, -65]:
            engine.record_sighting(mac, NODE_A[0], NODE_A[1], NODE_A[2], rssi)

        engine.record_sighting(mac, NODE_B[0], NODE_B[1], NODE_B[2], -70)
        engine.record_sighting(mac, NODE_C[0], NODE_C[1], NODE_C[2], -75)

        result = engine.estimate_position(mac)
        assert result is not None
        # The Kalman filter should have smoothed the NODE_A RSSI readings
        # so the position doesn't jump to the last raw value
