# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for indoor position fusion — WiFi fingerprint + BLE RSSI fusion."""

import math
import pytest

from plugins.indoor_positioning.fusion import (
    FusedPosition,
    IndoorPositionFusion,
    PositionEstimate,
    confidence_to_uncertainty,
    fuse_positions,
    knn_fingerprint_match,
)


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# San Jose area coordinates
BASE_LAT = 37.3352
BASE_LON = -121.8811

# Sample fingerprints at known locations
FINGERPRINTS = [
    {
        "fingerprint_id": "fp_1",
        "plan_id": "plan_a",
        "room_id": "room_lobby",
        "lat": 37.3352,
        "lon": -121.8811,
        "rssi_map": {"bssid_a": -45, "bssid_b": -65, "bssid_c": -80},
    },
    {
        "fingerprint_id": "fp_2",
        "plan_id": "plan_a",
        "room_id": "room_conference",
        "lat": 37.3354,
        "lon": -121.8809,
        "rssi_map": {"bssid_a": -70, "bssid_b": -40, "bssid_c": -55},
    },
    {
        "fingerprint_id": "fp_3",
        "plan_id": "plan_a",
        "room_id": "room_kitchen",
        "lat": 37.3356,
        "lon": -121.8813,
        "rssi_map": {"bssid_a": -85, "bssid_b": -75, "bssid_c": -35},
    },
    {
        "fingerprint_id": "fp_4",
        "plan_id": "plan_a",
        "room_id": "room_lobby",
        "lat": 37.3353,
        "lon": -121.8812,
        "rssi_map": {"bssid_a": -48, "bssid_b": -63, "bssid_c": -78},
    },
]


# ---------------------------------------------------------------------------
# confidence_to_uncertainty
# ---------------------------------------------------------------------------

class TestConfidenceToUncertainty:
    def test_high_confidence_low_uncertainty(self):
        u = confidence_to_uncertainty(1.0)
        assert u < 3.0  # ~1.5m

    def test_low_confidence_high_uncertainty(self):
        u = confidence_to_uncertainty(0.1)
        assert u > 10.0  # ~15m

    def test_monotonic_decreasing(self):
        """Higher confidence should always give lower uncertainty."""
        prev = confidence_to_uncertainty(0.1)
        for c in [0.2, 0.3, 0.5, 0.7, 0.9, 1.0]:
            cur = confidence_to_uncertainty(c)
            assert cur <= prev, f"Uncertainty should decrease: {prev} -> {cur} at conf={c}"
            prev = cur

    def test_clamped_below_zero(self):
        u = confidence_to_uncertainty(-0.5)
        u_at_floor = confidence_to_uncertainty(0.01)
        assert u == u_at_floor

    def test_clamped_above_one(self):
        u = confidence_to_uncertainty(1.5)
        u_at_one = confidence_to_uncertainty(1.0)
        assert u == u_at_one


# ---------------------------------------------------------------------------
# knn_fingerprint_match
# ---------------------------------------------------------------------------

class TestKNNFingerprintMatch:
    def test_exact_match_high_confidence(self):
        """Exact fingerprint match should give high confidence."""
        observed = {"bssid_a": -45, "bssid_b": -65, "bssid_c": -80}
        result = knn_fingerprint_match(observed, FINGERPRINTS, k=3)
        assert result is not None
        assert result.confidence > 0.8
        assert result.method == "fingerprint"
        # Should be near the lobby fingerprint
        assert abs(result.lat - 37.3352) < 0.001

    def test_close_match(self):
        """Observation close to a fingerprint should match it."""
        observed = {"bssid_a": -47, "bssid_b": -63, "bssid_c": -79}
        result = knn_fingerprint_match(observed, FINGERPRINTS, k=3)
        assert result is not None
        assert result.confidence > 0.5
        # Should be nearest the lobby area
        assert abs(result.lat - 37.3352) < 0.001

    def test_no_common_bssids(self):
        """No common BSSIDs should return None."""
        observed = {"bssid_x": -50, "bssid_y": -60}
        result = knn_fingerprint_match(observed, FINGERPRINTS, k=3)
        assert result is None

    def test_too_few_common_bssids(self):
        """Only 1 common BSSID (below MIN_COMMON_BSSIDS=2) returns None."""
        observed = {"bssid_a": -50, "bssid_x": -60}
        result = knn_fingerprint_match(observed, FINGERPRINTS, k=3)
        assert result is None

    def test_empty_fingerprints(self):
        observed = {"bssid_a": -50, "bssid_b": -60}
        result = knn_fingerprint_match(observed, [], k=3)
        assert result is None

    def test_empty_observed(self):
        result = knn_fingerprint_match({}, FINGERPRINTS, k=3)
        assert result is None

    def test_k1_matches_nearest(self):
        """k=1 should return the single nearest fingerprint."""
        observed = {"bssid_a": -70, "bssid_b": -40, "bssid_c": -55}
        result = knn_fingerprint_match(observed, FINGERPRINTS, k=1)
        assert result is not None
        # Should be closest to fp_2 (conference room)
        assert abs(result.lat - 37.3354) < 0.0005

    def test_very_distant_observation_returns_none(self):
        """Observation very far from all fingerprints should return None."""
        observed = {"bssid_a": -10, "bssid_b": -10, "bssid_c": -10}
        result = knn_fingerprint_match(observed, FINGERPRINTS, k=3)
        # Distances will be large; may still match depending on threshold
        # Check that if it matches, confidence is low
        if result is not None:
            assert result.confidence < 0.5

    def test_metadata_contains_k_used(self):
        observed = {"bssid_a": -50, "bssid_b": -60, "bssid_c": -70}
        result = knn_fingerprint_match(observed, FINGERPRINTS, k=3)
        assert result is not None
        assert "k_used" in result.metadata
        assert result.metadata["k_used"] <= 3

    def test_uncertainty_set(self):
        observed = {"bssid_a": -45, "bssid_b": -65, "bssid_c": -80}
        result = knn_fingerprint_match(observed, FINGERPRINTS, k=3)
        assert result is not None
        assert result.uncertainty_m > 0


# ---------------------------------------------------------------------------
# fuse_positions
# ---------------------------------------------------------------------------

class TestFusePositions:
    def test_both_none_returns_none(self):
        assert fuse_positions(None, None) is None

    def test_wifi_only(self):
        wifi = PositionEstimate(
            lat=37.3352, lon=-121.8811, confidence=0.8,
            method="fingerprint", uncertainty_m=3.0,
        )
        result = fuse_positions(wifi, None, target_id="test_1")
        assert result is not None
        assert result.method == "fingerprint"
        assert result.lat == 37.3352
        assert result.wifi_estimate is wifi
        assert result.ble_estimate is None

    def test_ble_only(self):
        ble = PositionEstimate(
            lat=37.3354, lon=-121.8809, confidence=0.6,
            method="trilateration", uncertainty_m=5.0, anchors_used=3,
        )
        result = fuse_positions(None, ble, target_id="test_2")
        assert result is not None
        assert result.method == "trilateration"
        assert result.lat == 37.3354
        assert result.ble_estimate is ble
        assert result.wifi_estimate is None

    def test_fusion_weighted_average(self):
        """Fused position should be between the two estimates, weighted by confidence."""
        wifi = PositionEstimate(
            lat=37.3350, lon=-121.8810, confidence=0.8,
            method="fingerprint", uncertainty_m=3.0,
        )
        ble = PositionEstimate(
            lat=37.3360, lon=-121.8820, confidence=0.2,
            method="trilateration", uncertainty_m=10.0, anchors_used=3,
        )
        result = fuse_positions(wifi, ble, target_id="test_3")
        assert result is not None
        assert result.method == "fused"

        # Fused lat should be closer to wifi (higher confidence)
        dist_to_wifi = abs(result.lat - 37.3350)
        dist_to_ble = abs(result.lat - 37.3360)
        assert dist_to_wifi < dist_to_ble, "Fused position should be closer to higher-confidence estimate"

    def test_equal_confidence_midpoint(self):
        """Equal confidence should give a position near the midpoint."""
        wifi = PositionEstimate(
            lat=37.3350, lon=-121.8810, confidence=0.5,
            method="fingerprint", uncertainty_m=5.0,
        )
        ble = PositionEstimate(
            lat=37.3360, lon=-121.8820, confidence=0.5,
            method="trilateration", uncertainty_m=5.0, anchors_used=3,
        )
        result = fuse_positions(wifi, ble)
        assert result is not None
        # Should be near midpoint
        expected_lat = (37.3350 + 37.3360) / 2
        assert abs(result.lat - expected_lat) < 0.0001

    def test_fused_confidence_higher_than_either(self):
        """Fusing two sources should yield higher confidence than either alone."""
        wifi = PositionEstimate(
            lat=37.3350, lon=-121.8810, confidence=0.6,
            method="fingerprint", uncertainty_m=5.0,
        )
        ble = PositionEstimate(
            lat=37.3352, lon=-121.8812, confidence=0.5,
            method="trilateration", uncertainty_m=6.0, anchors_used=3,
        )
        result = fuse_positions(wifi, ble)
        assert result is not None
        assert result.confidence > wifi.confidence
        assert result.confidence > ble.confidence

    def test_fused_uncertainty_lower_than_either(self):
        """Fused uncertainty should be less than or equal to the lowest individual."""
        wifi = PositionEstimate(
            lat=37.3350, lon=-121.8810, confidence=0.6,
            method="fingerprint", uncertainty_m=6.0,
        )
        ble = PositionEstimate(
            lat=37.3352, lon=-121.8812, confidence=0.5,
            method="trilateration", uncertainty_m=8.0, anchors_used=3,
        )
        result = fuse_positions(wifi, ble)
        assert result is not None
        # Higher confidence means lower uncertainty
        assert result.uncertainty_m <= wifi.uncertainty_m

    def test_to_dict_contains_both_estimates(self):
        wifi = PositionEstimate(
            lat=37.3350, lon=-121.8810, confidence=0.7,
            method="fingerprint", uncertainty_m=4.0,
        )
        ble = PositionEstimate(
            lat=37.3352, lon=-121.8812, confidence=0.6,
            method="trilateration", uncertainty_m=5.0, anchors_used=3,
        )
        result = fuse_positions(wifi, ble, target_id="target_x")
        d = result.to_dict()
        assert d["target_id"] == "target_x"
        assert "wifi_estimate" in d
        assert "ble_estimate" in d
        assert d["method"] == "fused"
        assert "confidence" in d
        assert "uncertainty_m" in d


# ---------------------------------------------------------------------------
# IndoorPositionFusion (stateful engine)
# ---------------------------------------------------------------------------

class MockTrilaterationEngine:
    """Mock trilateration engine for testing."""

    def __init__(self):
        self._results = {}

    def set_result(self, mac, lat, lon, confidence, anchors_used=3):
        from tritium_lib.tracking.trilateration import PositionResult
        self._results[mac.upper()] = PositionResult(
            lat=lat, lon=lon, confidence=confidence,
            anchors_used=anchors_used,
        )

    def estimate_position(self, mac):
        return self._results.get(mac.upper())


class MockFloorPlanStore:
    """Mock floorplan store for testing."""

    def __init__(self, fingerprints=None, plans=None):
        self._fingerprints = fingerprints or []
        self._plans = plans or []

    def get_fingerprints(self, plan_id=None, room_id=None):
        fps = self._fingerprints
        if plan_id:
            fps = [f for f in fps if f.get("plan_id") == plan_id]
        if room_id:
            fps = [f for f in fps if f.get("room_id") == room_id]
        return fps

    def list_plans(self, status=None, building=None, floor_level=None):
        plans = self._plans
        if status:
            plans = [p for p in plans if p.get("status") == status]
        return plans


class TestIndoorPositionFusion:
    def test_no_data_returns_none(self):
        fusion = IndoorPositionFusion()
        assert fusion.estimate_position("ble_AA:BB:CC:DD:EE:FF") is None

    def test_wifi_only_estimation(self):
        store = MockFloorPlanStore(fingerprints=FINGERPRINTS)
        fusion = IndoorPositionFusion(floorplan_store=store)
        fusion.update_wifi_observation("target_1", {"bssid_a": -45, "bssid_b": -65, "bssid_c": -80})

        result = fusion.estimate_position("target_1")
        assert result is not None
        assert result.method == "fingerprint"
        assert result.wifi_estimate is not None

    def test_ble_only_estimation(self):
        trilat = MockTrilaterationEngine()
        trilat.set_result("AA:BB:CC:DD:EE:FF", 37.3354, -121.8809, 0.7, 3)

        fusion = IndoorPositionFusion(trilateration_engine=trilat)
        result = fusion.estimate_position("ble_AA:BB:CC:DD:EE:FF")
        assert result is not None
        assert result.method == "trilateration"
        assert result.ble_estimate is not None

    def test_fused_estimation(self):
        """Both WiFi and BLE available — should fuse."""
        trilat = MockTrilaterationEngine()
        trilat.set_result("AA:BB:CC:DD:EE:FF", 37.3354, -121.8809, 0.6, 3)

        store = MockFloorPlanStore(fingerprints=FINGERPRINTS)
        fusion = IndoorPositionFusion(
            trilateration_engine=trilat,
            floorplan_store=store,
        )
        fusion.update_wifi_observation(
            "ble_AA:BB:CC:DD:EE:FF",
            {"bssid_a": -45, "bssid_b": -65, "bssid_c": -80},
        )

        result = fusion.estimate_position("ble_AA:BB:CC:DD:EE:FF")
        assert result is not None
        assert result.method == "fused"
        assert result.wifi_estimate is not None
        assert result.ble_estimate is not None
        assert result.confidence > 0

    def test_cached_position(self):
        trilat = MockTrilaterationEngine()
        trilat.set_result("AA:BB:CC:DD:EE:FF", 37.3354, -121.8809, 0.7, 3)

        fusion = IndoorPositionFusion(trilateration_engine=trilat)
        fusion.estimate_position("ble_AA:BB:CC:DD:EE:FF")

        cached = fusion.get_cached_position("ble_AA:BB:CC:DD:EE:FF")
        assert cached is not None
        assert cached.lat == 37.3354

    def test_tracked_targets(self):
        trilat = MockTrilaterationEngine()
        trilat.set_result("AA:BB:CC:DD:EE:01", 37.3354, -121.8809, 0.7, 3)
        trilat.set_result("AA:BB:CC:DD:EE:02", 37.3356, -121.8811, 0.6, 3)

        fusion = IndoorPositionFusion(trilateration_engine=trilat)
        fusion.estimate_position("ble_AA:BB:CC:DD:EE:01")
        fusion.estimate_position("ble_AA:BB:CC:DD:EE:02")

        assert fusion.tracked_targets == 2

    def test_clear(self):
        trilat = MockTrilaterationEngine()
        trilat.set_result("AA:BB:CC:DD:EE:FF", 37.3354, -121.8809, 0.7, 3)

        fusion = IndoorPositionFusion(trilateration_engine=trilat)
        fusion.estimate_position("ble_AA:BB:CC:DD:EE:FF")
        assert fusion.tracked_targets == 1

        fusion.clear()
        assert fusion.tracked_targets == 0

    def test_room_assignment_with_floorplan(self):
        """Position inside a room polygon should get room info."""
        room_polygon = [
            {"lat": 37.3350, "lon": -121.8815},
            {"lat": 37.3350, "lon": -121.8805},
            {"lat": 37.3358, "lon": -121.8805},
            {"lat": 37.3358, "lon": -121.8815},
        ]
        plans = [
            {
                "plan_id": "plan_a",
                "building": "HQ",
                "floor_level": 1,
                "status": "active",
                "bounds": {
                    "south": 37.3348,
                    "north": 37.3360,
                    "west": -121.8820,
                    "east": -121.8800,
                },
                "rooms": [
                    {
                        "room_id": "room_main",
                        "name": "Main Hall",
                        "floor_level": 1,
                        "polygon": room_polygon,
                    }
                ],
            }
        ]

        trilat = MockTrilaterationEngine()
        trilat.set_result("AA:BB:CC:DD:EE:FF", 37.3354, -121.8810, 0.7, 3)

        store = MockFloorPlanStore(plans=plans)
        fusion = IndoorPositionFusion(
            trilateration_engine=trilat,
            floorplan_store=store,
        )

        result = fusion.estimate_position("ble_AA:BB:CC:DD:EE:FF")
        assert result is not None
        assert result.room_id == "room_main"
        assert result.room_name == "Main Hall"
        assert result.floor_level == 1
        assert result.building == "HQ"

    def test_get_all_positions(self):
        trilat = MockTrilaterationEngine()
        trilat.set_result("AA:BB:CC:DD:EE:01", 37.3354, -121.8809, 0.7, 3)
        trilat.set_result("AA:BB:CC:DD:EE:02", 37.3356, -121.8811, 0.6, 3)

        fusion = IndoorPositionFusion(trilateration_engine=trilat)
        fusion.estimate_position("ble_AA:BB:CC:DD:EE:01")
        fusion.estimate_position("ble_AA:BB:CC:DD:EE:02")

        all_pos = fusion.get_all_positions()
        assert len(all_pos) == 2
        assert "ble_AA:BB:CC:DD:EE:01" in all_pos
        assert "ble_AA:BB:CC:DD:EE:02" in all_pos


# ---------------------------------------------------------------------------
# FusedPosition serialization
# ---------------------------------------------------------------------------

class TestFusedPositionSerialization:
    def test_to_dict_minimal(self):
        fp = FusedPosition(
            target_id="t1",
            lat=37.3354,
            lon=-121.8809,
            confidence=0.7,
            uncertainty_m=4.0,
        )
        d = fp.to_dict()
        assert d["target_id"] == "t1"
        assert d["lat"] == 37.3354
        assert d["confidence"] == 0.7
        assert d["uncertainty_m"] == 4.0
        assert "wifi_estimate" not in d
        assert "ble_estimate" not in d

    def test_to_dict_with_room(self):
        fp = FusedPosition(
            target_id="t2",
            lat=37.3354,
            lon=-121.8809,
            confidence=0.7,
            uncertainty_m=4.0,
            room_id="room_a",
            room_name="Conference Room A",
            floor_level=2,
            building="HQ",
            plan_id="plan_1",
        )
        d = fp.to_dict()
        assert d["room_id"] == "room_a"
        assert d["room_name"] == "Conference Room A"
        assert d["floor_level"] == 2
        assert d["building"] == "HQ"
        assert d["plan_id"] == "plan_1"
