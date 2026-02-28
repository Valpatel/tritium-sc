# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for GPX parser — waypoints, tracks with time, route points."""

import pytest
from engine.layers.parsers.gpx import parse_gpx


WAYPOINT_GPX = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="37.7749" lon="-122.4194">
    <ele>10.5</ele>
    <name>Waypoint A</name>
    <desc>Start point</desc>
  </wpt>
  <wpt lat="37.7850" lon="-122.4095">
    <name>Waypoint B</name>
  </wpt>
</gpx>
"""

TRACK_GPX = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>Morning Patrol</name>
    <trkseg>
      <trkpt lat="37.7749" lon="-122.4194">
        <ele>10</ele>
        <time>2026-02-27T08:00:00Z</time>
      </trkpt>
      <trkpt lat="37.7760" lon="-122.4180">
        <ele>12</ele>
        <time>2026-02-27T08:01:00Z</time>
      </trkpt>
      <trkpt lat="37.7770" lon="-122.4170">
        <ele>15</ele>
        <time>2026-02-27T08:02:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""

ROUTE_GPX = """\
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <rte>
    <name>Supply Route</name>
    <rtept lat="37.7749" lon="-122.4194">
      <name>Start</name>
    </rtept>
    <rtept lat="37.7800" lon="-122.4100">
      <name>Checkpoint</name>
    </rtept>
    <rtept lat="37.7850" lon="-122.4050">
      <name>End</name>
    </rtept>
  </rte>
</gpx>
"""


class TestGPXParser:
    """Parse GPX XML to Layer."""

    def test_parse_waypoints(self):
        """Waypoints become Point features with [lng, lat, alt] coordinates."""
        layer = parse_gpx(WAYPOINT_GPX)
        assert layer is not None
        assert layer.source_format == "gpx"
        assert len(layer.features) == 2
        f = layer.features[0]
        assert f.geometry_type == "Point"
        assert f.properties["name"] == "Waypoint A"
        # GPX lat/lon -> stored as [lng, lat, alt]
        assert f.coordinates[0] == pytest.approx(-122.4194)
        assert f.coordinates[1] == pytest.approx(37.7749)
        assert f.coordinates[2] == pytest.approx(10.5)

    def test_parse_track_with_time(self):
        """Track segments become LineString features; time attached."""
        layer = parse_gpx(TRACK_GPX)
        assert len(layer.features) == 1
        f = layer.features[0]
        assert f.geometry_type == "LineString"
        assert f.properties["name"] == "Morning Patrol"
        assert len(f.coordinates) == 3
        # First point: [lng, lat, alt]
        assert f.coordinates[0][0] == pytest.approx(-122.4194)
        assert f.coordinates[0][1] == pytest.approx(37.7749)

    def test_track_timestamps_preserved(self):
        """Track point timestamps are preserved in properties."""
        layer = parse_gpx(TRACK_GPX)
        f = layer.features[0]
        assert "timestamps" in f.properties
        assert len(f.properties["timestamps"]) == 3
        assert "2026-02-27T08:00:00Z" in f.properties["timestamps"][0]

    def test_parse_route_points(self):
        """Route rtept elements become a LineString feature."""
        layer = parse_gpx(ROUTE_GPX)
        assert len(layer.features) == 1
        f = layer.features[0]
        assert f.geometry_type == "LineString"
        assert f.properties["name"] == "Supply Route"
        assert len(f.coordinates) == 3

    def test_malformed_gpx_returns_empty_layer(self):
        """Malformed XML returns empty layer."""
        layer = parse_gpx("not gpx at all <<<")
        assert layer is not None
        assert len(layer.features) == 0

    def test_waypoint_description(self):
        """Waypoint desc element maps to properties.description."""
        layer = parse_gpx(WAYPOINT_GPX)
        f = layer.features[0]
        assert f.properties.get("description") == "Start point"
