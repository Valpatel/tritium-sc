# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Export Layer to GPX 1.1 XML string.

Uses only xml.etree.ElementTree (stdlib).
GPX uses lat/lon attributes on elements (latitude first in attributes).
Internal coordinates are [lng, lat, alt] (GeoJSON convention) —
we swap to lat/lon for GPX output.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from engine.layers.layer import Layer, LayerFeature


def export_gpx(layer: Layer) -> str:
    """Export a Layer to a GPX 1.1 XML string.

    Point features become <wpt> elements.
    LineString features become <trk> elements with a single <trkseg>.

    Args:
        layer: The Layer to export.

    Returns:
        GPX XML string.
    """
    gpx = ET.Element("gpx")
    gpx.set("version", "1.1")
    gpx.set("creator", "tritium-sc")
    gpx.set("xmlns", "http://www.topografix.com/GPX/1/1")

    for feature in layer.features:
        if feature.geometry_type == "Point":
            _write_waypoint(gpx, feature)
        elif feature.geometry_type == "LineString":
            _write_track(gpx, feature)

    return ET.tostring(gpx, encoding="unicode", xml_declaration=True)


def _write_waypoint(parent: ET.Element, feature: LayerFeature) -> None:
    """Write a Point feature as a <wpt> element."""
    coords = feature.coordinates
    if len(coords) < 2:
        return

    wpt = ET.SubElement(parent, "wpt")
    wpt.set("lat", str(coords[1]))  # lat is index 1
    wpt.set("lon", str(coords[0]))  # lng is index 0

    if len(coords) >= 3:
        ele = ET.SubElement(wpt, "ele")
        ele.text = str(coords[2])

    name = feature.properties.get("name", "")
    if name:
        name_elem = ET.SubElement(wpt, "name")
        name_elem.text = name

    desc = feature.properties.get("description", "")
    if desc:
        desc_elem = ET.SubElement(wpt, "desc")
        desc_elem.text = desc

    if feature.timestamp:
        time_elem = ET.SubElement(wpt, "time")
        time_elem.text = feature.timestamp


def _write_track(parent: ET.Element, feature: LayerFeature) -> None:
    """Write a LineString feature as a <trk> element with one <trkseg>."""
    trk = ET.SubElement(parent, "trk")

    name = feature.properties.get("name", "")
    if name:
        name_elem = ET.SubElement(trk, "name")
        name_elem.text = name

    trkseg = ET.SubElement(trk, "trkseg")

    timestamps = feature.properties.get("timestamps", [])

    for i, coord in enumerate(feature.coordinates):
        if len(coord) < 2:
            continue

        trkpt = ET.SubElement(trkseg, "trkpt")
        trkpt.set("lat", str(coord[1]))
        trkpt.set("lon", str(coord[0]))

        if len(coord) >= 3:
            ele = ET.SubElement(trkpt, "ele")
            ele.text = str(coord[2])

        if i < len(timestamps) and timestamps[i]:
            time_elem = ET.SubElement(trkpt, "time")
            time_elem.text = timestamps[i]
