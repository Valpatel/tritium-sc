# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for GIS protocol API endpoints.

Tests:
  - POST /api/geo/import/kml — parse KML text to GeoJSON
  - POST /api/geo/export/kml — convert GeoJSON to KML text
  - GET  /api/geo/convert/mgrs — lat/lng <-> MGRS conversion
  - GET  /api/geo/convert/utm — lat/lng <-> UTM conversion
  - POST /api/geo/validate-wms — validate WMS/WMTS URL templates
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.geo import router


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# KML Import (POST /api/geo/import/kml)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestKMLImportEndpoint:
    """POST /api/geo/import/kml — parse KML text to GeoJSON."""

    def test_import_kml_point(self):
        """Import KML with a Point Placemark."""
        client = TestClient(_make_app())
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark>
          <name>Test Point</name>
          <Point><coordinates>-122.4194,37.7749,0</coordinates></Point>
        </Placemark>
        </Document>
        </kml>"""
        resp = client.post("/api/geo/import/kml", json={"kml": kml})
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 1
        assert data["features"][0]["geometry"]["type"] == "Point"

    def test_import_kml_linestring(self):
        """Import KML with a LineString Placemark."""
        client = TestClient(_make_app())
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark>
          <name>Test Line</name>
          <LineString><coordinates>-122.4,37.7,0 -122.5,37.8,0</coordinates></LineString>
        </Placemark>
        </Document>
        </kml>"""
        resp = client.post("/api/geo/import/kml", json={"kml": kml})
        assert resp.status_code == 200
        data = resp.json()
        assert data["features"][0]["geometry"]["type"] == "LineString"

    def test_import_kml_polygon(self):
        """Import KML with a Polygon Placemark."""
        client = TestClient(_make_app())
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark>
          <name>Test Area</name>
          <Polygon><outerBoundaryIs><LinearRing>
            <coordinates>-122.4,37.7,0 -122.5,37.7,0 -122.5,37.8,0 -122.4,37.8,0 -122.4,37.7,0</coordinates>
          </LinearRing></outerBoundaryIs></Polygon>
        </Placemark>
        </Document>
        </kml>"""
        resp = client.post("/api/geo/import/kml", json={"kml": kml})
        assert resp.status_code == 200
        data = resp.json()
        assert data["features"][0]["geometry"]["type"] == "Polygon"

    def test_import_kml_preserves_name(self):
        """Placemark name is preserved in GeoJSON properties."""
        client = TestClient(_make_app())
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark>
          <name>Alpha Base</name>
          <Point><coordinates>-77.0,38.9,0</coordinates></Point>
        </Placemark>
        </Document>
        </kml>"""
        resp = client.post("/api/geo/import/kml", json={"kml": kml})
        data = resp.json()
        assert data["features"][0]["properties"]["name"] == "Alpha Base"

    def test_import_kml_empty_body(self):
        """Empty KML text returns 400."""
        client = TestClient(_make_app())
        resp = client.post("/api/geo/import/kml", json={"kml": ""})
        assert resp.status_code == 400

    def test_import_kml_invalid_xml(self):
        """Invalid XML returns 400."""
        client = TestClient(_make_app())
        resp = client.post("/api/geo/import/kml", json={"kml": "not xml at all"})
        assert resp.status_code == 400

    def test_import_kml_multiple_placemarks(self):
        """Multiple Placemarks are all parsed."""
        client = TestClient(_make_app())
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark><name>A</name><Point><coordinates>-77.0,38.9,0</coordinates></Point></Placemark>
        <Placemark><name>B</name><Point><coordinates>-77.1,38.8,0</coordinates></Point></Placemark>
        <Placemark><name>C</name><Point><coordinates>-77.2,38.7,0</coordinates></Point></Placemark>
        </Document>
        </kml>"""
        resp = client.post("/api/geo/import/kml", json={"kml": kml})
        data = resp.json()
        assert len(data["features"]) == 3


# ---------------------------------------------------------------------------
# KML Export (POST /api/geo/export/kml)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestKMLExportEndpoint:
    """POST /api/geo/export/kml — convert GeoJSON to KML text."""

    def test_export_point(self):
        """Export a GeoJSON Point feature to KML."""
        client = TestClient(_make_app())
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-122.4194, 37.7749]},
                "properties": {"name": "SF"},
            }],
        }
        resp = client.post("/api/geo/export/kml", json={"geojson": geojson})
        assert resp.status_code == 200
        data = resp.json()
        assert "kml" in data
        assert "<?xml" in data["kml"]
        assert "<kml" in data["kml"]
        assert "SF" in data["kml"]

    def test_export_linestring(self):
        """Export a GeoJSON LineString to KML."""
        client = TestClient(_make_app())
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-122.4, 37.7], [-122.5, 37.8]],
                },
                "properties": {"name": "Route"},
            }],
        }
        resp = client.post("/api/geo/export/kml", json={"geojson": geojson})
        data = resp.json()
        assert "<LineString>" in data["kml"]

    def test_export_empty_collection(self):
        """Empty FeatureCollection produces valid KML."""
        client = TestClient(_make_app())
        geojson = {"type": "FeatureCollection", "features": []}
        resp = client.post("/api/geo/export/kml", json={"geojson": geojson})
        assert resp.status_code == 200
        data = resp.json()
        assert "<kml" in data["kml"]

    def test_export_roundtrip(self):
        """KML -> import -> export -> import preserves geometry."""
        client = TestClient(_make_app())
        kml_orig = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
        <Placemark>
          <name>Roundtrip</name>
          <Point><coordinates>-77.0353,38.8895,0</coordinates></Point>
        </Placemark>
        </Document>
        </kml>"""
        # Import
        resp1 = client.post("/api/geo/import/kml", json={"kml": kml_orig})
        geojson = resp1.json()
        # Export
        resp2 = client.post("/api/geo/export/kml", json={"geojson": geojson})
        kml_out = resp2.json()["kml"]
        # Re-import
        resp3 = client.post("/api/geo/import/kml", json={"kml": kml_out})
        geojson2 = resp3.json()
        assert len(geojson2["features"]) == 1
        assert geojson2["features"][0]["properties"]["name"] == "Roundtrip"


# ---------------------------------------------------------------------------
# MGRS Conversion (GET /api/geo/convert/mgrs)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMGRSConversionEndpoint:
    """GET /api/geo/convert/mgrs — lat/lng <-> MGRS conversion."""

    def test_latlng_to_mgrs(self):
        """Convert lat/lng to MGRS string."""
        client = TestClient(_make_app())
        resp = client.get("/api/geo/convert/mgrs?lat=38.8895&lng=-77.0353")
        assert resp.status_code == 200
        data = resp.json()
        assert "mgrs" in data
        assert data["mgrs"].startswith("18S")

    def test_mgrs_to_latlng(self):
        """Convert MGRS string to lat/lng."""
        client = TestClient(_make_app())
        resp = client.get("/api/geo/convert/mgrs?mgrs=18SUD2347806483")
        assert resp.status_code == 200
        data = resp.json()
        assert "lat" in data
        assert "lng" in data
        assert abs(data["lat"] - 38.8895) < 0.01
        assert abs(data["lng"] - (-77.0353)) < 0.01

    def test_mgrs_roundtrip(self):
        """Convert lat/lng -> MGRS -> lat/lng via API."""
        client = TestClient(_make_app())
        resp1 = client.get("/api/geo/convert/mgrs?lat=37.7749&lng=-122.4194")
        mgrs = resp1.json()["mgrs"]
        resp2 = client.get(f"/api/geo/convert/mgrs?mgrs={mgrs}")
        data = resp2.json()
        assert abs(data["lat"] - 37.7749) < 0.001
        assert abs(data["lng"] - (-122.4194)) < 0.001

    def test_mgrs_no_params(self):
        """No parameters returns 400."""
        client = TestClient(_make_app())
        resp = client.get("/api/geo/convert/mgrs")
        assert resp.status_code == 400

    def test_mgrs_invalid_string(self):
        """Invalid MGRS string returns 400."""
        client = TestClient(_make_app())
        resp = client.get("/api/geo/convert/mgrs?mgrs=INVALID")
        assert resp.status_code == 400

    def test_mgrs_precision(self):
        """MGRS with custom precision."""
        client = TestClient(_make_app())
        resp = client.get("/api/geo/convert/mgrs?lat=38.8895&lng=-77.0353&precision=3")
        assert resp.status_code == 200
        data = resp.json()
        # 3-digit precision = 6 chars for digits (zone + band + 2 letters + 6 digits)
        assert len(data["mgrs"]) >= 9


# ---------------------------------------------------------------------------
# UTM Conversion (GET /api/geo/convert/utm)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestUTMConversionEndpoint:
    """GET /api/geo/convert/utm — lat/lng <-> UTM conversion."""

    def test_latlng_to_utm(self):
        """Convert lat/lng to UTM."""
        client = TestClient(_make_app())
        resp = client.get("/api/geo/convert/utm?lat=37.7749&lng=-122.4194")
        assert resp.status_code == 200
        data = resp.json()
        assert data["zone"] == 10
        assert data["band"] == "S"
        assert "easting" in data
        assert "northing" in data

    def test_utm_to_latlng(self):
        """Convert UTM to lat/lng."""
        client = TestClient(_make_app())
        resp = client.get(
            "/api/geo/convert/utm?zone=10&easting=551300&northing=4182000&band=S"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "lat" in data
        assert "lng" in data

    def test_utm_roundtrip(self):
        """Convert lat/lng -> UTM -> lat/lng via API."""
        client = TestClient(_make_app())
        resp1 = client.get("/api/geo/convert/utm?lat=40.7128&lng=-74.0060")
        d = resp1.json()
        resp2 = client.get(
            f"/api/geo/convert/utm?zone={d['zone']}&easting={d['easting']}"
            f"&northing={d['northing']}&band={d['band']}"
        )
        data = resp2.json()
        assert abs(data["lat"] - 40.7128) < 0.001
        assert abs(data["lng"] - (-74.0060)) < 0.001

    def test_utm_no_params(self):
        """No parameters returns 400."""
        client = TestClient(_make_app())
        resp = client.get("/api/geo/convert/utm")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# WMS URL Validation (POST /api/geo/validate-wms)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWMSValidationEndpoint:
    """POST /api/geo/validate-wms — validate WMS/WMTS URL templates."""

    def test_valid_wms_url(self):
        """Valid WMS URL passes validation."""
        client = TestClient(_make_app())
        url = "https://example.com/wms?SERVICE=WMS&REQUEST=GetMap&LAYERS=topo&BBOX={bbox}&WIDTH={width}&HEIGHT={height}"
        resp = client.post("/api/geo/validate-wms", json={"url": url})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["service"] == "WMS"

    def test_valid_wmts_url(self):
        """Valid WMTS XYZ tile URL passes validation."""
        client = TestClient(_make_app())
        url = "https://tiles.example.com/{z}/{x}/{y}.png"
        resp = client.post("/api/geo/validate-wms", json={"url": url})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True

    def test_invalid_url(self):
        """Non-URL string fails validation."""
        client = TestClient(_make_app())
        resp = client.post("/api/geo/validate-wms", json={"url": "not a url"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    def test_empty_url(self):
        """Empty URL returns 400."""
        client = TestClient(_make_app())
        resp = client.post("/api/geo/validate-wms", json={"url": ""})
        assert resp.status_code == 400
