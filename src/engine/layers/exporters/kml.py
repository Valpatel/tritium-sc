# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Export Layer to KML 2.3 XML string.

Uses only xml.etree.ElementTree (stdlib).
KML coordinates are in "lng,lat,alt" order (longitude first).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from engine.layers.layer import Layer, LayerFeature


def export_kml(layer: Layer) -> str:
    """Export a Layer to a KML XML string.

    Args:
        layer: The Layer to export.

    Returns:
        KML XML string.
    """
    kml = ET.Element("kml")
    kml.set("xmlns", "http://www.opengis.net/kml/2.2")

    doc = ET.SubElement(kml, "Document")

    name_elem = ET.SubElement(doc, "name")
    name_elem.text = layer.name or layer.layer_id

    for feature in layer.features:
        pm = ET.SubElement(doc, "Placemark")
        _write_placemark(pm, feature)

    return ET.tostring(kml, encoding="unicode", xml_declaration=True)


def _write_placemark(pm: ET.Element, feature: LayerFeature) -> None:
    """Write a LayerFeature as a KML Placemark element."""
    # Name
    feat_name = feature.properties.get("name", feature.feature_id)
    name_elem = ET.SubElement(pm, "name")
    name_elem.text = feat_name

    # Description
    desc = feature.properties.get("description", "")
    if desc:
        desc_elem = ET.SubElement(pm, "description")
        desc_elem.text = desc

    # Style
    if feature.style:
        _write_style(pm, feature.style)

    # Geometry
    if feature.geometry_type == "Point":
        _write_point(pm, feature.coordinates)
    elif feature.geometry_type == "LineString":
        _write_linestring(pm, feature.coordinates)
    elif feature.geometry_type == "Polygon":
        _write_polygon(pm, feature.coordinates)


def _write_style(pm: ET.Element, style: dict) -> None:
    """Write a Style element from a style dict."""
    style_elem = ET.SubElement(pm, "Style")

    if "color" in style:
        icon_style = ET.SubElement(style_elem, "IconStyle")
        color_elem = ET.SubElement(icon_style, "color")
        color_elem.text = style["color"]

    if "lineWidth" in style:
        line_style = ET.SubElement(style_elem, "LineStyle")
        width_elem = ET.SubElement(line_style, "width")
        width_elem.text = str(style["lineWidth"])

    if "fillColor" in style:
        poly_style = ET.SubElement(style_elem, "PolyStyle")
        color_elem = ET.SubElement(poly_style, "color")
        color_elem.text = style["fillColor"]


def _coords_to_string(coord: list[float]) -> str:
    """Convert a single [lng, lat, alt] or [lng, lat] to 'lng,lat,alt' string."""
    lng = coord[0] if len(coord) > 0 else 0.0
    lat = coord[1] if len(coord) > 1 else 0.0
    alt = coord[2] if len(coord) > 2 else 0.0
    # Use repr-like precision but avoid trailing zeros for cleanliness
    return f"{lng},{lat},{alt}"


def _write_point(pm: ET.Element, coordinates: list) -> None:
    """Write a Point geometry element."""
    point = ET.SubElement(pm, "Point")
    coords_elem = ET.SubElement(point, "coordinates")
    coords_elem.text = _coords_to_string(coordinates)


def _write_linestring(pm: ET.Element, coordinates: list) -> None:
    """Write a LineString geometry element."""
    ls = ET.SubElement(pm, "LineString")
    coords_elem = ET.SubElement(ls, "coordinates")
    parts = [_coords_to_string(c) for c in coordinates]
    coords_elem.text = " ".join(parts)


def _write_polygon(pm: ET.Element, coordinates: list) -> None:
    """Write a Polygon geometry element."""
    polygon = ET.SubElement(pm, "Polygon")

    if coordinates:
        # First ring is outer boundary
        outer = ET.SubElement(polygon, "outerBoundaryIs")
        ring = ET.SubElement(outer, "LinearRing")
        coords_elem = ET.SubElement(ring, "coordinates")
        parts = [_coords_to_string(c) for c in coordinates[0]]
        coords_elem.text = " ".join(parts)

        # Remaining rings are inner boundaries
        for inner_ring in coordinates[1:]:
            inner = ET.SubElement(polygon, "innerBoundaryIs")
            ring = ET.SubElement(inner, "LinearRing")
            coords_elem = ET.SubElement(ring, "coordinates")
            parts = [_coords_to_string(c) for c in inner_ring]
            coords_elem.text = " ".join(parts)
