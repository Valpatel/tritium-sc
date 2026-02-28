# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""GIS interoperability protocol support.

Pure-function library for converting between standard GIS formats:
  - MGRS / UTM coordinate systems
  - KML / KMZ parsing and generation
  - WMS / WMTS URL validation and tile URL building
  - ROS2 message format conversion (NavSatFix, OccupancyGrid, PoseStamped)
  - MBTiles metadata parsing

Zero external dependencies — only stdlib (math, xml, re).
Coordinate transforms use engine.tactical.geo for the reference point.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from engine.tactical.geo import latlng_to_local


# ===========================================================================
# UTM / MGRS
# ===========================================================================

# UTM zone latitude band letters (C..X, omitting I and O)
_UTM_BANDS = "CDEFGHJKLMNPQRSTUVWX"

# 100km square column letters per set (1..8 repeat)
_MGRS_COL_LETTERS = [
    "ABCDEFGH",
    "JKLMNPQR",
    "STUVWXYZ",
    "ABCDEFGH",
    "JKLMNPQR",
    "STUVWXYZ",
]
# 100km square row letters (alternates between two sets)
_MGRS_ROW_LETTERS_EVEN = "ABCDEFGHJKLMNPQRSTUV"
_MGRS_ROW_LETTERS_ODD = "FGHJKLMNPQRSTUVABCDE"


def latlng_to_utm(
    lat: float, lng: float,
) -> tuple[int, float, float, str]:
    """Convert lat/lng (WGS84) to UTM zone, easting, northing, band.

    Returns:
        (zone, easting, northing, band_letter)
    """
    if lat < -80.0 or lat > 84.0:
        raise ValueError(f"Latitude {lat} outside UTM range (-80 to 84)")

    # Zone number
    zone = int((lng + 180) / 6) + 1

    # Special zones for Norway/Svalbard
    if 56.0 <= lat < 64.0 and 3.0 <= lng < 12.0:
        zone = 32
    if 72.0 <= lat < 84.0:
        if 0.0 <= lng < 9.0:
            zone = 31
        elif 9.0 <= lng < 21.0:
            zone = 33
        elif 21.0 <= lng < 33.0:
            zone = 35
        elif 33.0 <= lng < 42.0:
            zone = 37

    # Band letter
    band_idx = int((lat + 80) / 8)
    if band_idx >= len(_UTM_BANDS):
        band_idx = len(_UTM_BANDS) - 1
    band = _UTM_BANDS[band_idx]

    # Central meridian
    lon0 = (zone - 1) * 6 - 180 + 3

    # WGS84 constants
    a = 6378137.0
    f = 1 / 298.257223563
    e = math.sqrt(2 * f - f * f)
    e2 = e * e
    ep2 = e2 / (1 - e2)
    k0 = 0.9996

    lat_r = math.radians(lat)
    lng_r = math.radians(lng)
    lon0_r = math.radians(lon0)

    N = a / math.sqrt(1 - e2 * math.sin(lat_r) ** 2)
    T = math.tan(lat_r) ** 2
    C = ep2 * math.cos(lat_r) ** 2
    A = (lng_r - lon0_r) * math.cos(lat_r)

    # Meridional arc
    M = a * (
        (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * lat_r
        - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * math.sin(2 * lat_r)
        + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * lat_r)
        - (35 * e2**3 / 3072) * math.sin(6 * lat_r)
    )

    easting = k0 * N * (
        A
        + (1 - T + C) * A**3 / 6
        + (5 - 18 * T + T**2 + 72 * C - 58 * ep2) * A**5 / 120
    ) + 500000.0

    northing = k0 * (
        M
        + N * math.tan(lat_r) * (
            A**2 / 2
            + (5 - T + 9 * C + 4 * C**2) * A**4 / 24
            + (61 - 58 * T + T**2 + 600 * C - 330 * ep2) * A**6 / 720
        )
    )

    if lat < 0:
        northing += 10000000.0

    return (zone, easting, northing, band)


def utm_to_latlng(
    zone: int, easting: float, northing: float, band: str,
) -> tuple[float, float]:
    """Convert UTM zone/easting/northing/band to lat/lng (WGS84).

    Returns:
        (latitude, longitude) in degrees
    """
    a = 6378137.0
    f = 1 / 298.257223563
    e = math.sqrt(2 * f - f * f)
    e2 = e * e
    ep2 = e2 / (1 - e2)
    k0 = 0.9996

    # Check if southern hemisphere
    is_south = band < "N"
    x = easting - 500000.0
    y = northing
    if is_south:
        y -= 10000000.0

    lon0 = (zone - 1) * 6 - 180 + 3

    M = y / k0
    mu = M / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))

    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))

    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
    )

    N1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    T1 = math.tan(phi1) ** 2
    C1 = ep2 * math.cos(phi1) ** 2
    R1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    D = x / (N1 * k0)

    lat = phi1 - (N1 * math.tan(phi1) / R1) * (
        D**2 / 2
        - (5 + 3 * T1 + 10 * C1 - 4 * C1**2 - 9 * ep2) * D**4 / 24
        + (61 + 90 * T1 + 298 * C1 + 45 * T1**2 - 252 * ep2 - 3 * C1**2) * D**6 / 720
    )

    lng = (
        D
        - (1 + 2 * T1 + C1) * D**3 / 6
        + (5 - 2 * C1 + 28 * T1 - 3 * C1**2 + 8 * ep2 + 24 * T1**2) * D**5 / 120
    ) / math.cos(phi1)

    return (math.degrees(lat), lon0 + math.degrees(lng))


def latlng_to_mgrs(lat: float, lng: float, precision: int = 5) -> str:
    """Convert lat/lng to MGRS string.

    Args:
        lat: Latitude in degrees.
        lng: Longitude in degrees.
        precision: Number of digit pairs (5 = 1m, 4 = 10m, 3 = 100m).

    Returns:
        MGRS string (e.g., "18SUJ2338706880" for 5-digit precision).
    """
    zone, easting, northing, band = latlng_to_utm(lat, lng)

    # 100km grid square letters
    col_idx = int(easting / 100000) - 1
    set_idx = (zone - 1) % 6
    col_letter = _MGRS_COL_LETTERS[set_idx][col_idx % 8]

    row_letters = _MGRS_ROW_LETTERS_ODD if zone % 2 == 1 else _MGRS_ROW_LETTERS_EVEN
    row_idx = int(northing % 2000000 / 100000)
    row_letter = row_letters[row_idx % 20]

    # Numeric part (within 100km square)
    e_remainder = easting % 100000
    n_remainder = northing % 100000

    # Format to requested precision
    divisor = 10 ** (5 - precision)
    e_digits = int(e_remainder / divisor)
    n_digits = int(n_remainder / divisor)

    return f"{zone}{band}{col_letter}{row_letter}{e_digits:0{precision}d}{n_digits:0{precision}d}"


def mgrs_to_latlng(mgrs_str: str) -> tuple[float, float]:
    """Convert MGRS string to lat/lng.

    Args:
        mgrs_str: MGRS string (e.g., "18SUJ2338706880").

    Returns:
        (latitude, longitude) in degrees.

    Raises:
        ValueError: If the MGRS string is invalid.
    """
    mgrs_str = mgrs_str.strip().upper()

    # Parse: zone number (1-2 digits) + band letter + 2 grid letters + even digit string
    m = re.match(r'^(\d{1,2})([C-X])([A-Z])([A-Z])(\d+)$', mgrs_str)
    if not m:
        raise ValueError(f"Invalid MGRS string: {mgrs_str}")

    zone = int(m.group(1))
    band = m.group(2)
    col_letter = m.group(3)
    row_letter = m.group(4)
    digits = m.group(5)

    if len(digits) % 2 != 0:
        raise ValueError(f"MGRS digit string must have even length: {digits}")

    precision = len(digits) // 2
    if precision == 0:
        raise ValueError("MGRS string must have at least 2 digits")

    e_digits = int(digits[:precision])
    n_digits = int(digits[precision:])

    # Scale to meters
    multiplier = 10 ** (5 - precision)
    e_within = e_digits * multiplier
    n_within = n_digits * multiplier

    # Recover full easting from column letter
    set_idx = (zone - 1) % 6
    col_letters = _MGRS_COL_LETTERS[set_idx]
    col_pos = col_letters.find(col_letter)
    if col_pos < 0:
        raise ValueError(f"Invalid column letter {col_letter} for zone {zone}")
    easting = (col_pos + 1) * 100000 + e_within

    # Recover full northing from row letter
    row_letters = _MGRS_ROW_LETTERS_ODD if zone % 2 == 1 else _MGRS_ROW_LETTERS_EVEN
    row_pos = row_letters.find(row_letter)
    if row_pos < 0:
        raise ValueError(f"Invalid row letter {row_letter} for zone {zone}")
    n_100k = row_pos * 100000 + n_within

    # Estimate northing from band
    band_idx = _UTM_BANDS.index(band)
    min_lat = -80.0 + band_idx * 8.0

    # Get approximate northing for the band's southern edge
    _, _, approx_northing, _ = latlng_to_utm(min_lat + 0.1, (zone - 1) * 6 - 180 + 3)

    # Find the right 2_000_000 cycle
    base = int(approx_northing / 2000000) * 2000000
    northing = base + n_100k

    # Adjust if wrapping
    if northing < approx_northing - 500000:
        northing += 2000000
    if northing > approx_northing + 2000000:
        northing -= 2000000

    return utm_to_latlng(zone, easting, northing, band)


# ===========================================================================
# KML / KMZ
# ===========================================================================

_KML_NS = "http://www.opengis.net/kml/2.2"


def _parse_coordinates(text: str) -> list[list[float]]:
    """Parse a KML coordinates string into [[lng, lat, alt], ...]."""
    coords = []
    for chunk in text.strip().split():
        parts = chunk.split(",")
        if len(parts) >= 2:
            lng = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) >= 3 else 0.0
            coords.append([lng, lat, alt])
    return coords


def kml_to_geojson(kml_text: str) -> dict:
    """Parse KML XML text and return a GeoJSON FeatureCollection.

    Supports Point, LineString, and Polygon Placemarks.
    """
    root = ET.fromstring(kml_text)
    ns = {"kml": _KML_NS}

    features = []

    for pm in root.iter(f"{{{_KML_NS}}}Placemark"):
        props: dict = {}
        name_el = pm.find(f"kml:name", ns)
        if name_el is not None and name_el.text:
            props["name"] = name_el.text.strip()
        desc_el = pm.find(f"kml:description", ns)
        if desc_el is not None and desc_el.text:
            props["description"] = desc_el.text.strip()

        geometry = None

        # Point
        point_el = pm.find(f"kml:Point/kml:coordinates", ns)
        if point_el is not None and point_el.text:
            coords = _parse_coordinates(point_el.text)
            if coords:
                geometry = {"type": "Point", "coordinates": coords[0]}

        # LineString
        if geometry is None:
            line_el = pm.find(f"kml:LineString/kml:coordinates", ns)
            if line_el is not None and line_el.text:
                coords = _parse_coordinates(line_el.text)
                if len(coords) >= 2:
                    geometry = {"type": "LineString", "coordinates": coords}

        # Polygon
        if geometry is None:
            poly_el = pm.find(
                f"kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", ns
            )
            if poly_el is not None and poly_el.text:
                coords = _parse_coordinates(poly_el.text)
                if len(coords) >= 3:
                    geometry = {"type": "Polygon", "coordinates": [coords]}

        if geometry is not None:
            features.append({
                "type": "Feature",
                "geometry": geometry,
                "properties": props,
            })

    return {"type": "FeatureCollection", "features": features}


def geojson_to_kml(geojson: dict) -> str:
    """Convert a GeoJSON FeatureCollection to KML XML string.

    Supports Point, LineString, and Polygon features.
    """
    kml = ET.Element("kml", xmlns=_KML_NS)
    doc = ET.SubElement(kml, "Document")

    for feat in geojson.get("features", []):
        geom = feat.get("geometry", {})
        props = feat.get("properties", {})

        pm = ET.SubElement(doc, "Placemark")

        if "name" in props:
            name_el = ET.SubElement(pm, "name")
            name_el.text = str(props["name"])
        if "description" in props:
            desc_el = ET.SubElement(pm, "description")
            desc_el.text = str(props["description"])

        geom_type = geom.get("type", "")
        coords = geom.get("coordinates", [])

        if geom_type == "Point":
            pt = ET.SubElement(pm, "Point")
            coord_el = ET.SubElement(pt, "coordinates")
            c = coords
            coord_el.text = f"{c[0]},{c[1]}" + (f",{c[2]}" if len(c) > 2 else "")

        elif geom_type == "LineString":
            ls = ET.SubElement(pm, "LineString")
            coord_el = ET.SubElement(ls, "coordinates")
            coord_el.text = " ".join(
                f"{c[0]},{c[1]}" + (f",{c[2]}" if len(c) > 2 else "")
                for c in coords
            )

        elif geom_type == "Polygon":
            poly = ET.SubElement(pm, "Polygon")
            outer = ET.SubElement(poly, "outerBoundaryIs")
            ring = ET.SubElement(outer, "LinearRing")
            coord_el = ET.SubElement(ring, "coordinates")
            outer_coords = coords[0] if coords else []
            coord_el.text = " ".join(
                f"{c[0]},{c[1]}" + (f",{c[2]}" if len(c) > 2 else "")
                for c in outer_coords
            )

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        kml, encoding="unicode"
    )


# ===========================================================================
# WMS / WMTS URL Validation
# ===========================================================================

def validate_wms_url(url: str) -> dict:
    """Validate a WMS/WMTS/TMS tile URL template.

    Returns:
        {"valid": bool, "service": str, "error": str | None}
    """
    # Basic URL check
    if not re.match(r'^https?://', url, re.IGNORECASE):
        return {"valid": False, "service": "unknown", "error": "Not a valid URL"}

    # Detect service type
    url_upper = url.upper()

    if "SERVICE=WMS" in url_upper or "REQUEST=GETMAP" in url_upper:
        # WMS GetMap URL
        return {"valid": True, "service": "WMS", "error": None}

    if "{z}" in url and "{x}" in url and "{y}" in url:
        # TMS/WMTS XYZ tile template
        if "WMTS" in url_upper or "TILEMATRIX" in url_upper:
            return {"valid": True, "service": "WMTS", "error": None}
        return {"valid": True, "service": "WMTS", "error": None}

    if "SERVICE=WMTS" in url_upper:
        return {"valid": True, "service": "WMTS", "error": None}

    if "{bbox}" in url.lower() or "BBOX" in url_upper:
        return {"valid": True, "service": "WMS", "error": None}

    # Generic HTTPS URL -- might be a custom tile server
    return {"valid": True, "service": "unknown", "error": None}


def build_wms_tile_url(
    template: str,
    bbox: str,
    width: int = 256,
    height: int = 256,
) -> str:
    """Build a WMS GetMap URL from a template and tile parameters.

    Replaces {bbox}, {width}, {height} placeholders.
    """
    return (
        template
        .replace("{bbox}", bbox)
        .replace("{width}", str(width))
        .replace("{height}", str(height))
    )


# ===========================================================================
# ROS2 Message Format Conversion
# ===========================================================================

def navsatfix_to_local(msg: dict) -> tuple[float, float, float]:
    """Convert a ROS2 sensor_msgs/NavSatFix-like dict to local meters.

    Uses the global geo reference for conversion.

    Args:
        msg: Dict with keys "latitude", "longitude", optionally "altitude".

    Returns:
        (x, y, z) in local meters.
    """
    lat = msg.get("latitude", 0.0)
    lng = msg.get("longitude", 0.0)
    alt = msg.get("altitude", 0.0)
    return latlng_to_local(lat, lng, alt)


def parse_occupancy_grid_meta(meta: dict) -> dict:
    """Parse ROS2 nav_msgs/OccupancyGrid metadata.

    Args:
        meta: Dict with keys "resolution", "width", "height", "origin".

    Returns:
        Dict with "resolution", "width", "height", "width_meters",
        "height_meters", "origin_x", "origin_y".
    """
    resolution = meta.get("resolution", 0.05)
    width = meta.get("width", 0)
    height = meta.get("height", 0)
    origin = meta.get("origin", {})

    return {
        "resolution": resolution,
        "width": width,
        "height": height,
        "width_meters": width * resolution,
        "height_meters": height * resolution,
        "origin_x": origin.get("x", 0.0),
        "origin_y": origin.get("y", 0.0),
    }


def pose_stamped_to_local(msg: dict) -> tuple[float, float, float]:
    """Convert a ROS2 geometry_msgs/PoseStamped-like dict to (x, y, heading).

    The quaternion orientation is converted to yaw (heading in degrees).

    Args:
        msg: Dict with "position" (x, y, z) and "orientation" (x, y, z, w).

    Returns:
        (x, y, heading_degrees)
    """
    pos = msg.get("position", {})
    x = pos.get("x", 0.0)
    y = pos.get("y", 0.0)

    orient = msg.get("orientation", {})
    qx = orient.get("x", 0.0)
    qy = orient.get("y", 0.0)
    qz = orient.get("z", 0.0)
    qw = orient.get("w", 1.0)

    # Quaternion to yaw (rotation around Z axis)
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    yaw_rad = math.atan2(siny_cosp, cosy_cosp)
    heading = math.degrees(yaw_rad)

    # Normalize to [0, 360)
    if heading < 0:
        heading += 360.0

    return (x, y, heading)


# ===========================================================================
# MBTiles Metadata
# ===========================================================================

def parse_mbtiles_metadata(meta: dict) -> dict:
    """Parse MBTiles metadata dict into structured format.

    Args:
        meta: Dict from MBTiles `metadata` table (key-value pairs).

    Returns:
        Structured dict with typed fields.
    """
    bounds_str = meta.get("bounds", "")
    bounds = None
    if bounds_str:
        try:
            bounds = [float(x) for x in bounds_str.split(",")]
        except (ValueError, TypeError):
            bounds = None

    return {
        "name": meta.get("name", ""),
        "description": meta.get("description", ""),
        "format": meta.get("format", "png"),
        "type": meta.get("type", "baselayer"),
        "bounds": bounds,
        "center": meta.get("center"),
        "minzoom": int(meta.get("minzoom", 0)),
        "maxzoom": int(meta.get("maxzoom", 22)),
        "attribution": meta.get("attribution", ""),
    }
