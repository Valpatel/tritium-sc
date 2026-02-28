# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Parse GPX 1.1 XML to Layer using xml.etree.ElementTree.

Handles wpt (waypoint), trk/trkseg/trkpt (track points), rte/rtept (route points).
Extracts name, desc, time, ele (elevation).

GPX uses lat/lon attributes on elements (latitude first).
All coordinates stored as [lng, lat, alt] (GeoJSON convention).
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET

from engine.layers.layer import Layer, LayerFeature

# GPX 1.1 namespace
_GPX_NS = "{http://www.topografix.com/GPX/1/1}"


def parse_gpx(gpx_string: str) -> Layer:
    """Parse a GPX XML string into a Layer.

    Args:
        gpx_string: Raw GPX XML content.

    Returns:
        Layer with parsed features. Returns empty layer on parse errors.
    """
    try:
        root = ET.fromstring(gpx_string)
    except ET.ParseError:
        return Layer(
            layer_id=f"layer-{uuid.uuid4().hex[:8]}",
            name="",
            source_format="gpx",
            features=[],
        )

    ns = _detect_namespace(root)
    features: list[LayerFeature] = []
    idx = 0

    # Parse waypoints (wpt)
    for wpt in _find_all(root, "wpt", ns):
        feature = _parse_waypoint(wpt, ns, idx)
        if feature is not None:
            features.append(feature)
            idx += 1

    # Parse tracks (trk/trkseg/trkpt)
    for trk in _find_all(root, "trk", ns):
        feature = _parse_track(trk, ns, idx)
        if feature is not None:
            features.append(feature)
            idx += 1

    # Parse routes (rte/rtept)
    for rte in _find_all(root, "rte", ns):
        feature = _parse_route(rte, ns, idx)
        if feature is not None:
            features.append(feature)
            idx += 1

    return Layer(
        layer_id=f"layer-{uuid.uuid4().hex[:8]}",
        name="",
        source_format="gpx",
        features=features,
    )


def _detect_namespace(root: ET.Element) -> str:
    """Detect GPX namespace from root tag."""
    tag = root.tag
    if "{" in tag:
        return tag.split("}")[0] + "}"
    return ""


def _find_all(parent: ET.Element, tag: str, ns: str) -> list[ET.Element]:
    """Find all direct children with the given tag."""
    full_tag = f"{ns}{tag}" if ns else tag
    return parent.findall(full_tag)


def _get_child_text(parent: ET.Element, tag: str, ns: str) -> str:
    """Get text of a direct child element."""
    full_tag = f"{ns}{tag}" if ns else tag
    elem = parent.find(full_tag)
    if elem is not None and elem.text:
        return elem.text.strip()
    return ""


def _parse_lat_lon_ele(
    elem: ET.Element, ns: str
) -> list[float]:
    """Extract [lng, lat, alt] from an element with lat/lon attributes."""
    try:
        lat = float(elem.get("lat", 0.0))
        lon = float(elem.get("lon", 0.0))
    except (ValueError, TypeError):
        return []

    ele_text = _get_child_text(elem, "ele", ns)
    alt = 0.0
    if ele_text:
        try:
            alt = float(ele_text)
        except ValueError:
            pass

    return [lon, lat, alt]


def _parse_waypoint(
    wpt: ET.Element, ns: str, idx: int
) -> LayerFeature | None:
    """Parse a wpt element into a Point LayerFeature."""
    coords = _parse_lat_lon_ele(wpt, ns)
    if not coords:
        return None

    name = _get_child_text(wpt, "name", ns)
    desc = _get_child_text(wpt, "desc", ns)
    time_str = _get_child_text(wpt, "time", ns)

    properties: dict = {}
    if name:
        properties["name"] = name
    if desc:
        properties["description"] = desc

    return LayerFeature(
        feature_id=f"gpx-wpt-{idx}",
        geometry_type="Point",
        coordinates=coords,
        properties=properties,
        timestamp=time_str if time_str else None,
    )


def _parse_track(
    trk: ET.Element, ns: str, idx: int
) -> LayerFeature | None:
    """Parse a trk element into a LineString LayerFeature.

    Concatenates all trkseg/trkpt points into a single LineString.
    """
    name = _get_child_text(trk, "name", ns)

    coordinates: list[list[float]] = []
    timestamps: list[str] = []

    seg_tag = f"{ns}trkseg" if ns else "trkseg"
    pt_tag = f"{ns}trkpt" if ns else "trkpt"

    for seg in trk.findall(seg_tag):
        for trkpt in seg.findall(pt_tag):
            coord = _parse_lat_lon_ele(trkpt, ns)
            if coord:
                coordinates.append(coord)
                time_str = _get_child_text(trkpt, "time", ns)
                timestamps.append(time_str)

    if not coordinates:
        return None

    properties: dict = {}
    if name:
        properties["name"] = name
    if any(timestamps):
        properties["timestamps"] = timestamps

    return LayerFeature(
        feature_id=f"gpx-trk-{idx}",
        geometry_type="LineString",
        coordinates=coordinates,
        properties=properties,
    )


def _parse_route(
    rte: ET.Element, ns: str, idx: int
) -> LayerFeature | None:
    """Parse a rte element into a LineString LayerFeature."""
    name = _get_child_text(rte, "name", ns)

    coordinates: list[list[float]] = []
    pt_tag = f"{ns}rtept" if ns else "rtept"

    for rtept in rte.findall(pt_tag):
        coord = _parse_lat_lon_ele(rtept, ns)
        if coord:
            coordinates.append(coord)

    if not coordinates:
        return None

    properties: dict = {}
    if name:
        properties["name"] = name

    return LayerFeature(
        feature_id=f"gpx-rte-{idx}",
        geometry_type="LineString",
        coordinates=coordinates,
        properties=properties,
    )
