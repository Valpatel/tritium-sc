# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for KML parser — Point, LineString, Polygon, styles, coordinates."""

import pytest
from engine.layers.parsers.kml import parse_kml


POINT_KML = """\
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Test Points</name>
    <Placemark>
      <name>HQ</name>
      <description>Command Post</description>
      <Point>
        <coordinates>-122.4194,37.7749,10</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>
"""

LINESTRING_KML = """\
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Patrol Route</name>
      <LineString>
        <coordinates>
          -122.4,37.77,0 -122.41,37.78,0 -122.42,37.79,0
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""

POLYGON_KML = """\
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Zone Alpha</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              -122.4,37.77,0 -122.41,37.78,0 -122.42,37.77,0 -122.4,37.77,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>
"""

STYLED_KML = """\
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Styled Point</name>
      <Style>
        <IconStyle>
          <color>ff0000ff</color>
        </IconStyle>
        <LineStyle>
          <width>3.5</width>
        </LineStyle>
        <PolyStyle>
          <color>7f00ff00</color>
        </PolyStyle>
      </Style>
      <Point>
        <coordinates>-122.4,37.7,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>
"""

MULTI_KML = """\
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Multi Features</name>
    <Placemark>
      <name>Point A</name>
      <Point><coordinates>-122.4,37.7,0</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>Point B</name>
      <Point><coordinates>-122.5,37.8,0</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>Route</name>
      <LineString>
        <coordinates>-122.4,37.7,0 -122.5,37.8,0</coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""


class TestKMLParser:
    """Parse KML XML to Layer."""

    def test_parse_point_placemark(self):
        """Point Placemark extracts name, description, coordinates [lng, lat, alt]."""
        layer = parse_kml(POINT_KML)
        assert layer is not None
        assert layer.source_format == "kml"
        assert len(layer.features) == 1
        f = layer.features[0]
        assert f.geometry_type == "Point"
        assert f.properties["name"] == "HQ"
        assert f.properties["description"] == "Command Post"
        # Coordinates stored as [lng, lat, alt] — GeoJSON convention
        assert f.coordinates[0] == pytest.approx(-122.4194, abs=1e-4)
        assert f.coordinates[1] == pytest.approx(37.7749, abs=1e-4)

    def test_parse_linestring(self):
        """LineString Placemark parses multiple coordinate pairs."""
        layer = parse_kml(LINESTRING_KML)
        assert len(layer.features) == 1
        f = layer.features[0]
        assert f.geometry_type == "LineString"
        assert len(f.coordinates) == 3
        # Each coordinate is [lng, lat, alt]
        assert f.coordinates[0][0] == pytest.approx(-122.4)
        assert f.coordinates[0][1] == pytest.approx(37.77)

    def test_parse_polygon(self):
        """Polygon parses outer boundary ring."""
        layer = parse_kml(POLYGON_KML)
        assert len(layer.features) == 1
        f = layer.features[0]
        assert f.geometry_type == "Polygon"
        # Polygon coordinates are [[ring]] — ring is list of [lng, lat, alt]
        assert len(f.coordinates) == 1  # one ring
        assert len(f.coordinates[0]) == 4  # 4 points in ring

    def test_parse_styles(self):
        """Style elements map to feature style dict."""
        layer = parse_kml(STYLED_KML)
        f = layer.features[0]
        assert f.style is not None
        assert "color" in f.style
        assert "lineWidth" in f.style
        assert f.style["lineWidth"] == pytest.approx(3.5)
        assert "fillColor" in f.style

    def test_parse_multiple_placemarks(self):
        """Multiple placemarks produce multiple features."""
        layer = parse_kml(MULTI_KML)
        assert len(layer.features) == 3
        types = {f.geometry_type for f in layer.features}
        assert "Point" in types
        assert "LineString" in types

    def test_layer_name_from_document(self):
        """Layer name comes from Document/name element."""
        layer = parse_kml(POINT_KML)
        assert layer.name == "Test Points"

    def test_malformed_xml_returns_empty_layer(self):
        """Malformed XML returns an empty layer, not a crash."""
        layer = parse_kml("this is not xml at all")
        assert layer is not None
        assert len(layer.features) == 0

    def test_empty_document_returns_empty_layer(self):
        """KML with no placemarks returns empty layer."""
        kml = '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Empty</name></Document></kml>'
        layer = parse_kml(kml)
        assert len(layer.features) == 0
        assert layer.name == "Empty"
