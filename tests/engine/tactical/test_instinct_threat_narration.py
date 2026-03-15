# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Amy's threat assessment narration in the instinct layer."""

import pytest
from unittest.mock import MagicMock

from amy.brain.instinct import InstinctLayer


class TestBuildThreatNarration:
    """Test the _build_threat_narration method."""

    def _make_instinct(self):
        commander = MagicMock()
        commander.target_tracker = None
        layer = InstinctLayer(commander)
        return layer

    def test_basic_narration(self):
        layer = self._make_instinct()
        narration = layer._build_threat_narration(
            "ble_aabbccdd", "hostile", {},
        )
        assert "ble_aabb" in narration
        assert "hostile" in narration
        assert "suspicious" in narration.lower() or "threshold" in narration.lower()

    def test_strong_signal(self):
        layer = self._make_instinct()
        narration = layer._build_threat_narration(
            "ble_aabbccdd", "hostile",
            {"rssi": -30},
        )
        assert "-30" in narration
        assert "strong" in narration.lower() or "signal" in narration.lower()

    def test_unknown_classification(self):
        layer = self._make_instinct()
        narration = layer._build_threat_narration(
            "ble_aabbccdd", "hostile",
            {"classification": "unknown"},
        )
        assert "unknown" in narration.lower()

    def test_restricted_zone(self):
        layer = self._make_instinct()
        narration = layer._build_threat_narration(
            "ble_aabbccdd", "hostile",
            {"zone_name": "Server Room", "zone_type": "restricted"},
        )
        assert "Server Room" in narration
        assert "restricted" in narration.lower()

    def test_co_located_unknowns(self):
        layer = self._make_instinct()
        narration = layer._build_threat_narration(
            "ble_aabbccdd", "hostile",
            {"co_located_devices": [
                {"id": "x", "known": False},
                {"id": "y", "known": False},
            ]},
        )
        assert "unknown" in narration.lower()
        assert "co-located" in narration.lower()

    def test_dwell_time(self):
        layer = self._make_instinct()
        narration = layer._build_threat_narration(
            "ble_aabbccdd", "hostile",
            {"dwell_seconds": 7200},
        )
        assert "hour" in narration.lower() or "dwell" in narration.lower()

    def test_behavioral_anomaly(self):
        layer = self._make_instinct()
        narration = layer._build_threat_narration(
            "ble_aabbccdd", "hostile",
            {"anomaly": "unusual movement pattern at 3am"},
        )
        assert "unusual movement" in narration.lower()

    def test_multiple_reasons(self):
        layer = self._make_instinct()
        narration = layer._build_threat_narration(
            "ble_aabbccdd", "hostile",
            {
                "rssi": -35,
                "classification": "unknown",
                "zone_name": "Perimeter",
                "zone_type": "restricted",
                "first_seen_recently": True,
            },
        )
        # Should have multiple semicolons joining reasons
        assert narration.count(";") >= 2
