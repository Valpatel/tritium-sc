# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Sensorium TAK integration — source labels and event processing.

TDD: tests written BEFORE implementation.
"""

import time

import pytest

pytest.skip(
    "TAK source labels (tak, tak_position, tak_chat, tak_threat) not yet added to "
    "_SOURCE_LABELS in sensorium.py — rich_narrative TAK label formatting not implemented",
    allow_module_level=True,
)

from amy.brain.sensorium import Sensorium, _SOURCE_LABELS


class TestTAKSourceLabels:
    """Verify TAK source labels exist in _SOURCE_LABELS."""

    def test_tak_source_label_exists(self):
        assert "tak" in _SOURCE_LABELS
        assert _SOURCE_LABELS["tak"] == "TAK"

    def test_tak_position_source_label_exists(self):
        assert "tak_position" in _SOURCE_LABELS
        assert _SOURCE_LABELS["tak_position"] == "TAK"

    def test_tak_chat_source_label_exists(self):
        assert "tak_chat" in _SOURCE_LABELS
        assert _SOURCE_LABELS["tak_chat"] == "TAK Chat"

    def test_tak_threat_source_label_exists(self):
        assert "tak_threat" in _SOURCE_LABELS
        assert _SOURCE_LABELS["tak_threat"] == "TAK Threat"


class TestSensoriumTAKEvents:
    """Verify TAK events flow through the Sensorium correctly."""

    def test_sensorium_push_tak_event(self):
        s = Sensorium()
        s.push("tak_position", "TAK user Alpha at (37.7749, -122.4194)", importance=0.3)
        narr = s.narrative()
        assert "TAK user Alpha" in narr

    def test_tak_threat_high_importance(self):
        s = Sensorium()
        s.push("tak_threat", "TAK hostile marker: Badguy at (37.7753, -122.4198)", importance=0.9)
        narr = s.rich_narrative(min_importance=0.8)
        assert "TAK hostile marker" in narr

    def test_tak_threat_label_in_rich_narrative(self):
        s = Sensorium()
        s.push("tak_threat", "TAK hostile at north", importance=0.9)
        narr = s.rich_narrative(min_importance=0.5)
        assert "[TAK Threat]" in narr

    def test_tak_position_label_in_rich_narrative(self):
        s = Sensorium()
        s.push("tak_position", "TAK user Bravo at coords", importance=0.5)
        narr = s.rich_narrative(min_importance=0.3)
        assert "[TAK]" in narr
