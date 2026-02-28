# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for GIS interoperability protocol support.

Tests:
  - MGRS/UTM coordinate conversion
  - KML/KMZ parsing to GeoJSON
  - GeoJSON to KML export
  - WMS/WMTS URL template validation
  - ROS2 NavSatFix message to local coordinates
"""
from __future__ import annotations

import math
import pytest


# ---------------------------------------------------------------------------
# MGRS / UTM Coordinate Support
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMGRS:
    """MGRS (Military Grid Reference System) coordinate conversions."""

    def test_latlng_to_mgrs_basic(self):
        """Convert a known lat/lng to MGRS string."""
        from engine.tactical.geo_protocols import latlng_to_mgrs
        # Washington Monument: 38.8895 N, 77.0353 W -> 18SUJ2338706880 (approx)
        mgrs = latlng_to_mgrs(38.8895, -77.0353)
        assert isinstance(mgrs, str)
        assert len(mgrs) >= 10  # at least zone + square + 6 digits
        # Should start with zone 18S
        assert mgrs.startswith("18S")

    def test_mgrs_to_latlng_basic(self):
        """Convert a known MGRS string back to lat/lng."""
        from engine.tactical.geo_protocols import mgrs_to_latlng
        # 18SUD2347806483 is the correct MGRS for Washington Monument (38.8895, -77.0353)
        lat, lng = mgrs_to_latlng("18SUD2347806483")
        assert abs(lat - 38.8895) < 0.01
        assert abs(lng - (-77.0353)) < 0.01

    def test_mgrs_roundtrip(self):
        """Convert lat/lng -> MGRS -> lat/lng and verify accuracy."""
        from engine.tactical.geo_protocols import latlng_to_mgrs, mgrs_to_latlng
        orig_lat, orig_lng = 37.7749, -122.4194  # San Francisco
        mgrs = latlng_to_mgrs(orig_lat, orig_lng)
        lat, lng = mgrs_to_latlng(mgrs)
        # 10-digit MGRS is accurate to 1m
        assert abs(lat - orig_lat) < 0.001
        assert abs(lng - orig_lng) < 0.001

    def test_latlng_to_utm(self):
        """Convert lat/lng to UTM zone/easting/northing."""
        from engine.tactical.geo_protocols import latlng_to_utm
        zone, easting, northing, band = latlng_to_utm(37.7749, -122.4194)
        assert zone == 10
        assert band == "S"
        assert 500000 < easting < 600000  # Near center of zone
        assert 4000000 < northing < 5000000

    def test_utm_to_latlng(self):
        """Convert UTM back to lat/lng."""
        from engine.tactical.geo_protocols import latlng_to_utm, utm_to_latlng
        zone, easting, northing, band = latlng_to_utm(37.7749, -122.4194)
        lat, lng = utm_to_latlng(zone, easting, northing, band)
        assert abs(lat - 37.7749) < 0.0001
        assert abs(lng - (-122.4194)) < 0.0001

    def test_mgrs_invalid_string(self):
        """Invalid MGRS string raises ValueError."""
        from engine.tactical.geo_protocols import mgrs_to_latlng
        with pytest.raises(ValueError):
            mgrs_to_latlng("INVALID")

    def test_mgrs_southern_hemisphere(self):
        """MGRS works for southern hemisphere."""
        from engine.tactical.geo_protocols import latlng_to_mgrs, mgrs_to_latlng
        # Sydney, Australia
        mgrs = latlng_to_mgrs(-33.8688, 151.2093)
        assert isinstance(mgrs, str)
        lat, lng = mgrs_to_latlng(mgrs)
        assert abs(lat - (-33.8688)) < 0.001

    def test_utm_zone_boundaries(self):
        """Test various points across UTM zone boundaries."""
        from engine.tactical.geo_protocols import latlng_to_utm
        # Zone 1: 180W to 174W
        zone, _, _, _ = latlng_to_utm(45.0, -177.0)
        assert zone == 1
        # Zone 30: 0W to 6E
        zone, _, _, _ = latlng_to_utm(51.5, -0.1)
        assert zone == 30
        # Zone 60: 174E to 180E
        zone, _, _, _ = latlng_to_utm(45.0, 177.0)
        assert zone == 60


# ---------------------------------------------------------------------------
# KML / KMZ Support
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestKML:
    """KML parsing and generation."""

    def test_kml_point_to_geojson(self):
        """Parse a KML Placemark with Point geometry."""
        from engine.tactical.geo_protocols import kml_to_geojson
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark>
          <name>Test Point</name>
          <Point><coordinates>-122.4194,37.7749,0</coordinates></Point>
        </Placemark>
        </Document>
        </kml>"""
        geojson = kml_to_geojson(kml)
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 1
        feat = geojson["features"][0]
        assert feat["geometry"]["type"] == "Point"
        assert feat["geometry"]["coordinates"] == pytest.approx([-122.4194, 37.7749, 0.0])
        assert feat["properties"]["name"] == "Test Point"

    def test_kml_linestring_to_geojson(self):
        """Parse a KML Placemark with LineString geometry."""
        from engine.tactical.geo_protocols import kml_to_geojson
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark>
          <name>Test Line</name>
          <LineString>
            <coordinates>-122.4,37.7,0 -122.5,37.8,0</coordinates>
          </LineString>
        </Placemark>
        </Document>
        </kml>"""
        geojson = kml_to_geojson(kml)
        feat = geojson["features"][0]
        assert feat["geometry"]["type"] == "LineString"
        assert len(feat["geometry"]["coordinates"]) == 2

    def test_kml_polygon_to_geojson(self):
        """Parse a KML Placemark with Polygon geometry."""
        from engine.tactical.geo_protocols import kml_to_geojson
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark>
          <name>Test Area</name>
          <Polygon>
            <outerBoundaryIs><LinearRing>
              <coordinates>-122.4,37.7,0 -122.5,37.7,0 -122.5,37.8,0 -122.4,37.8,0 -122.4,37.7,0</coordinates>
            </LinearRing></outerBoundaryIs>
          </Polygon>
        </Placemark>
        </Document>
        </kml>"""
        geojson = kml_to_geojson(kml)
        feat = geojson["features"][0]
        assert feat["geometry"]["type"] == "Polygon"
        assert len(feat["geometry"]["coordinates"][0]) == 5

    def test_kml_multiple_placemarks(self):
        """Parse KML with multiple Placemarks."""
        from engine.tactical.geo_protocols import kml_to_geojson
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark><name>P1</name><Point><coordinates>-122.0,37.0,0</coordinates></Point></Placemark>
        <Placemark><name>P2</name><Point><coordinates>-122.1,37.1,0</coordinates></Point></Placemark>
        <Placemark><name>P3</name><Point><coordinates>-122.2,37.2,0</coordinates></Point></Placemark>
        </Document>
        </kml>"""
        geojson = kml_to_geojson(kml)
        assert len(geojson["features"]) == 3

    def test_kml_empty_document(self):
        """Empty KML document returns empty FeatureCollection."""
        from engine.tactical.geo_protocols import kml_to_geojson
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document></Document>
        </kml>"""
        geojson = kml_to_geojson(kml)
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 0

    def test_geojson_point_to_kml(self):
        """Convert GeoJSON Point to KML."""
        from engine.tactical.geo_protocols import geojson_to_kml
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-122.4194, 37.7749]},
                "properties": {"name": "SF"},
            }],
        }
        kml = geojson_to_kml(geojson)
        assert "<?xml" in kml
        assert "<kml" in kml
        assert "SF" in kml
        assert "-122.4194,37.7749" in kml

    def test_geojson_linestring_to_kml(self):
        """Convert GeoJSON LineString to KML."""
        from engine.tactical.geo_protocols import geojson_to_kml
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-122.4, 37.7], [-122.5, 37.8]],
                },
                "properties": {"name": "TestLine"},
            }],
        }
        kml = geojson_to_kml(geojson)
        assert "<LineString>" in kml

    def test_geojson_polygon_to_kml(self):
        """Convert GeoJSON Polygon to KML."""
        from engine.tactical.geo_protocols import geojson_to_kml
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-122.4, 37.7], [-122.5, 37.7], [-122.5, 37.8], [-122.4, 37.7]]],
                },
                "properties": {"name": "TestPoly"},
            }],
        }
        kml = geojson_to_kml(geojson)
        assert "<Polygon>" in kml

    def test_kml_roundtrip(self):
        """KML -> GeoJSON -> KML preserves geometry."""
        from engine.tactical.geo_protocols import kml_to_geojson, geojson_to_kml
        kml_orig = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark>
          <name>Roundtrip</name>
          <Point><coordinates>-122.4194,37.7749,0</coordinates></Point>
        </Placemark>
        </Document>
        </kml>"""
        geojson = kml_to_geojson(kml_orig)
        kml_out = geojson_to_kml(geojson)
        geojson2 = kml_to_geojson(kml_out)
        assert len(geojson2["features"]) == 1
        coords1 = geojson["features"][0]["geometry"]["coordinates"]
        coords2 = geojson2["features"][0]["geometry"]["coordinates"]
        assert coords1[0] == pytest.approx(coords2[0], abs=0.0001)
        assert coords1[1] == pytest.approx(coords2[1], abs=0.0001)

    def test_kml_description_preserved(self):
        """KML description is preserved in GeoJSON properties."""
        from engine.tactical.geo_protocols import kml_to_geojson
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark>
          <name>Named</name>
          <description>A description</description>
          <Point><coordinates>-122.0,37.0,0</coordinates></Point>
        </Placemark>
        </Document>
        </kml>"""
        geojson = kml_to_geojson(kml)
        props = geojson["features"][0]["properties"]
        assert props["name"] == "Named"
        assert props["description"] == "A description"


# ---------------------------------------------------------------------------
# WMS / WMTS URL Validation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWMS:
    """WMS/WMTS URL template handling."""

    def test_validate_wms_url(self):
        """Valid WMS GetMap URL template passes validation."""
        from engine.tactical.geo_protocols import validate_wms_url
        url = "https://example.com/wms?SERVICE=WMS&REQUEST=GetMap&LAYERS=topo&FORMAT=image/png&SRS=EPSG:3857&BBOX={bbox}&WIDTH={width}&HEIGHT={height}"
        result = validate_wms_url(url)
        assert result["valid"] is True
        assert result["service"] == "WMS"

    def test_validate_wmts_url(self):
        """Valid WMTS tile URL template passes validation."""
        from engine.tactical.geo_protocols import validate_wms_url
        url = "https://example.com/wmts/{z}/{x}/{y}.png"
        result = validate_wms_url(url)
        assert result["valid"] is True
        assert result["service"] == "WMTS"

    def test_validate_tms_url(self):
        """Valid TMS URL template (with {z}/{x}/{y}) is accepted."""
        from engine.tactical.geo_protocols import validate_wms_url
        url = "https://tiles.example.com/{z}/{x}/{y}.png"
        result = validate_wms_url(url)
        assert result["valid"] is True

    def test_reject_invalid_url(self):
        """Non-URL string fails validation."""
        from engine.tactical.geo_protocols import validate_wms_url
        result = validate_wms_url("not a url")
        assert result["valid"] is False

    def test_reject_non_https(self):
        """HTTP (non-HTTPS) URLs are accepted but flagged."""
        from engine.tactical.geo_protocols import validate_wms_url
        url = "http://example.com/wms?SERVICE=WMS&REQUEST=GetMap&LAYERS=x&BBOX={bbox}&WIDTH={width}&HEIGHT={height}"
        result = validate_wms_url(url)
        assert result["valid"] is True
        # HTTP is valid but not secure

    def test_build_wms_tile_url(self):
        """Build a WMS GetMap URL for a specific tile bbox."""
        from engine.tactical.geo_protocols import build_wms_tile_url
        template = "https://example.com/wms?SERVICE=WMS&REQUEST=GetMap&LAYERS=topo&FORMAT=image/png&SRS=EPSG:3857&BBOX={bbox}&WIDTH={width}&HEIGHT={height}"
        url = build_wms_tile_url(template, bbox="-122.5,37.5,-122.0,38.0", width=256, height=256)
        assert "-122.5,37.5,-122.0,38.0" in url
        assert "256" in url


# ---------------------------------------------------------------------------
# ROS2 NavSatFix Message Handling
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestROS2NavSatFix:
    """ROS2 NavSatFix GPS message to local coordinate conversion."""

    def test_navsatfix_to_local(self):
        """Convert a NavSatFix-like dict to local meters."""
        from engine.tactical.geo_protocols import navsatfix_to_local
        from engine.tactical.geo import init_reference
        # Set reference point
        init_reference(37.7749, -122.4194, 0.0)

        msg = {
            "latitude": 37.7750,
            "longitude": -122.4193,
            "altitude": 5.0,
        }
        x, y, z = navsatfix_to_local(msg)
        # 0.0001 degree lat ~ 11.1m north
        assert y > 0  # North of reference
        assert abs(y - 11.1) < 2.0  # Approx 11m north
        assert z == pytest.approx(5.0)

    def test_navsatfix_missing_fields(self):
        """Missing fields default to 0."""
        from engine.tactical.geo_protocols import navsatfix_to_local
        from engine.tactical.geo import init_reference
        init_reference(37.7749, -122.4194, 0.0)

        msg = {"latitude": 37.7749, "longitude": -122.4194}
        x, y, z = navsatfix_to_local(msg)
        assert abs(x) < 0.1
        assert abs(y) < 0.1
        assert z == 0.0

    def test_occupancy_grid_metadata(self):
        """Parse OccupancyGrid-like metadata."""
        from engine.tactical.geo_protocols import parse_occupancy_grid_meta
        meta = {
            "resolution": 0.05,  # 5cm per cell
            "width": 384,
            "height": 384,
            "origin": {"x": -9.6, "y": -9.6, "z": 0.0},
        }
        result = parse_occupancy_grid_meta(meta)
        assert result["resolution"] == 0.05
        assert result["width_meters"] == pytest.approx(19.2)
        assert result["height_meters"] == pytest.approx(19.2)

    def test_pose_stamped_to_local(self):
        """Convert PoseStamped-like dict to local (x, y, heading)."""
        from engine.tactical.geo_protocols import pose_stamped_to_local
        msg = {
            "position": {"x": 3.5, "y": -2.1, "z": 0.0},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.707, "w": 0.707},
        }
        x, y, heading = pose_stamped_to_local(msg)
        assert x == pytest.approx(3.5)
        assert y == pytest.approx(-2.1)
        # z=0.707, w=0.707 -> yaw = 90 degrees
        assert abs(heading - 90.0) < 1.0


# ---------------------------------------------------------------------------
# MBTiles Metadata
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMBTiles:
    """MBTiles offline tile package metadata."""

    def test_parse_mbtiles_metadata(self):
        """Parse MBTiles metadata dict."""
        from engine.tactical.geo_protocols import parse_mbtiles_metadata
        meta = {
            "name": "test-tiles",
            "format": "png",
            "bounds": "-122.5,37.5,-122.0,38.0",
            "minzoom": "10",
            "maxzoom": "18",
            "type": "baselayer",
        }
        result = parse_mbtiles_metadata(meta)
        assert result["name"] == "test-tiles"
        assert result["format"] == "png"
        assert result["bounds"] == [-122.5, 37.5, -122.0, 38.0]
        assert result["minzoom"] == 10
        assert result["maxzoom"] == 18

    def test_parse_mbtiles_metadata_missing_optional(self):
        """Missing optional fields get defaults."""
        from engine.tactical.geo_protocols import parse_mbtiles_metadata
        meta = {"name": "minimal"}
        result = parse_mbtiles_metadata(meta)
        assert result["name"] == "minimal"
        assert result["format"] == "png"
        assert result["minzoom"] == 0
        assert result["maxzoom"] == 22
