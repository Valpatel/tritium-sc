# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for CoT XML parser — event to feature, position, type code."""

import pytest
from engine.layers.parsers.cot import parse_cot_event


COT_TARGET = """\
<event version="2.0" uid="rover-01" type="a-f-G-E-V" how="m-s"
       time="2026-02-27T12:00:00Z" start="2026-02-27T12:00:00Z"
       stale="2026-02-27T12:02:00Z">
  <point lat="37.7749" lon="-122.4194" hae="10.0" ce="10.0" le="10.0"/>
  <detail>
    <contact callsign="Rover Alpha"/>
    <track speed="2.5" course="135.0"/>
  </detail>
</event>
"""

COT_HOSTILE = """\
<event version="2.0" uid="hostile-03" type="a-h-G-U" how="m-r"
       time="2026-02-27T12:00:00Z" start="2026-02-27T12:00:00Z"
       stale="2026-02-27T12:02:00Z">
  <point lat="37.7800" lon="-122.4100" hae="0.0" ce="10.0" le="10.0"/>
  <detail>
    <contact callsign="Unknown Hostile"/>
  </detail>
</event>
"""


class TestCoTParser:
    """Parse CoT XML to LayerFeature."""

    def test_parse_cot_position(self):
        """CoT event point becomes a Point feature with [lng, lat, alt]."""
        feature = parse_cot_event(COT_TARGET)
        assert feature is not None
        assert feature.geometry_type == "Point"
        # Stored as [lng, lat, alt]
        assert feature.coordinates[0] == pytest.approx(-122.4194)
        assert feature.coordinates[1] == pytest.approx(37.7749)
        assert feature.coordinates[2] == pytest.approx(10.0)

    def test_parse_cot_type_code(self):
        """CoT type code is preserved in properties."""
        feature = parse_cot_event(COT_TARGET)
        assert feature.properties["cot_type"] == "a-f-G-E-V"
        assert feature.properties["callsign"] == "Rover Alpha"

    def test_parse_cot_hostile(self):
        """Hostile CoT event preserves type and callsign."""
        feature = parse_cot_event(COT_HOSTILE)
        assert feature is not None
        assert feature.properties["cot_type"] == "a-h-G-U"
        assert feature.properties["callsign"] == "Unknown Hostile"

    def test_malformed_cot_returns_none(self):
        """Malformed CoT XML returns None."""
        assert parse_cot_event("not xml") is None
        assert parse_cot_event("<wrong/>") is None
