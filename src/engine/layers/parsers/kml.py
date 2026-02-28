# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Parse KML 2.3 XML to Layer using only xml.etree.ElementTree.

Handles Placemark/Point, Placemark/LineString, Placemark/Polygon.
Extracts name, description, styles (IconStyle/color, LineStyle/width, PolyStyle/color).
KML coordinate format: "lng,lat,alt lng,lat,alt" (longitude first, latitude second).
All coordinates stored as [lng, lat, alt] (GeoJSON convention).
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET

from engine.layers.layer import Layer, LayerFeature

# KML 2.2 namespace
_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def parse_kml(kml_string: str) -> Layer:
    """Parse a KML XML string into a Layer.

    Args:
        kml_string: Raw KML XML content.

    Returns:
        Layer with parsed features. Returns empty layer on parse errors.
    """
    try:
        root = ET.fromstring(kml_string)
    except ET.ParseError:
        return Layer(
            layer_id=f"layer-{uuid.uuid4().hex[:8]}",
            name="",
            source_format="kml",
            features=[],
        )

    # Detect namespace from root tag
    ns = _detect_namespace(root)

    # Extract document name
    doc_name = ""
    doc = root.find(f"{ns}Document") if ns else root.find("Document")
    if doc is not None:
        name_elem = doc.find(f"{ns}name") if ns else doc.find("name")
        if name_elem is not None and name_elem.text:
            doc_name = name_elem.text.strip()

    # Find all Placemarks (search recursively)
    placemarks = _find_all_recursive(root, "Placemark", ns)

    features: list[LayerFeature] = []
    for idx, pm in enumerate(placemarks):
        feature = _parse_placemark(pm, ns, idx)
        if feature is not None:
            features.append(feature)

    return Layer(
        layer_id=f"layer-{uuid.uuid4().hex[:8]}",
        name=doc_name,
        source_format="kml",
        features=features,
    )


def _detect_namespace(root: ET.Element) -> str:
    """Detect KML namespace from root element tag."""
    tag = root.tag
    if "{" in tag:
        ns_uri = tag.split("}")[0] + "}"
        return ns_uri
    return ""


def _find_all_recursive(root: ET.Element, tag: str, ns: str) -> list[ET.Element]:
    """Find all elements with the given tag name, searching recursively."""
    results = []
    full_tag = f"{ns}{tag}" if ns else tag
    for elem in root.iter(full_tag):
        results.append(elem)
    return results


def _parse_placemark(
    pm: ET.Element, ns: str, idx: int
) -> LayerFeature | None:
    """Parse a single Placemark element into a LayerFeature."""
    # Extract name and description
    name = _get_text(pm, "name", ns)
    description = _get_text(pm, "description", ns)

    properties: dict = {}
    if name:
        properties["name"] = name
    if description:
        properties["description"] = description

    # Extract style
    style = _parse_style(pm, ns)

    # Try Point
    point = _find_child(pm, "Point", ns)
    if point is not None:
        coords = _parse_coordinates_single(point, ns)
        if coords:
            return LayerFeature(
                feature_id=f"kml-{idx}",
                geometry_type="Point",
                coordinates=coords,
                properties=properties,
                style=style if style else None,
            )

    # Try LineString
    linestring = _find_child(pm, "LineString", ns)
    if linestring is not None:
        coords = _parse_coordinates_list(linestring, ns)
        if coords:
            return LayerFeature(
                feature_id=f"kml-{idx}",
                geometry_type="LineString",
                coordinates=coords,
                properties=properties,
                style=style if style else None,
            )

    # Try Polygon
    polygon = _find_child(pm, "Polygon", ns)
    if polygon is not None:
        rings = _parse_polygon_rings(polygon, ns)
        if rings:
            return LayerFeature(
                feature_id=f"kml-{idx}",
                geometry_type="Polygon",
                coordinates=rings,
                properties=properties,
                style=style if style else None,
            )

    return None


def _find_child(parent: ET.Element, tag: str, ns: str) -> ET.Element | None:
    """Find a direct or nested child element by tag."""
    full_tag = f"{ns}{tag}" if ns else tag
    return parent.find(f".//{full_tag}")


def _get_text(parent: ET.Element, tag: str, ns: str) -> str:
    """Get text content of a child element."""
    elem = _find_child(parent, tag, ns)
    if elem is not None and elem.text:
        return elem.text.strip()
    return ""


def _parse_coordinate_string(coord_str: str) -> list[list[float]]:
    """Parse KML coordinate string: 'lng,lat,alt lng,lat,alt ...'

    Returns list of [lng, lat, alt] arrays.
    """
    coords = []
    for token in coord_str.strip().split():
        parts = token.strip().split(",")
        if len(parts) >= 2:
            try:
                lng = float(parts[0])
                lat = float(parts[1])
                alt = float(parts[2]) if len(parts) >= 3 else 0.0
                coords.append([lng, lat, alt])
            except (ValueError, IndexError):
                continue
    return coords


def _parse_coordinates_single(
    geom_elem: ET.Element, ns: str
) -> list[float]:
    """Parse coordinates for a Point geometry (single coordinate)."""
    coord_elem = _find_child(geom_elem, "coordinates", ns)
    if coord_elem is None or not coord_elem.text:
        return []
    coords = _parse_coordinate_string(coord_elem.text)
    if coords:
        return coords[0]  # Single point: [lng, lat, alt]
    return []


def _parse_coordinates_list(
    geom_elem: ET.Element, ns: str
) -> list[list[float]]:
    """Parse coordinates for a LineString geometry (list of coordinates)."""
    coord_elem = _find_child(geom_elem, "coordinates", ns)
    if coord_elem is None or not coord_elem.text:
        return []
    return _parse_coordinate_string(coord_elem.text)


def _parse_polygon_rings(
    polygon_elem: ET.Element, ns: str
) -> list[list[list[float]]]:
    """Parse polygon rings (outer boundary + optional inner boundaries)."""
    rings = []

    # Outer boundary
    outer = _find_child(polygon_elem, "outerBoundaryIs", ns)
    if outer is not None:
        linear_ring = _find_child(outer, "LinearRing", ns)
        if linear_ring is not None:
            coords = _parse_coordinates_list(linear_ring, ns)
            if coords:
                rings.append(coords)

    # Inner boundaries (holes)
    inner_tag = f"{ns}innerBoundaryIs" if ns else "innerBoundaryIs"
    for inner in polygon_elem.findall(f".//{inner_tag}"):
        linear_ring = _find_child(inner, "LinearRing", ns)
        if linear_ring is not None:
            coords = _parse_coordinates_list(linear_ring, ns)
            if coords:
                rings.append(coords)

    return rings


def _parse_style(pm: ET.Element, ns: str) -> dict:
    """Parse inline Style element from a Placemark."""
    style_elem = _find_child(pm, "Style", ns)
    if style_elem is None:
        return {}

    style: dict = {}

    # IconStyle/color
    icon_style = _find_child(style_elem, "IconStyle", ns)
    if icon_style is not None:
        color = _get_text(icon_style, "color", ns)
        if color:
            style["color"] = color

    # LineStyle/width
    line_style = _find_child(style_elem, "LineStyle", ns)
    if line_style is not None:
        width_str = _get_text(line_style, "width", ns)
        if width_str:
            try:
                style["lineWidth"] = float(width_str)
            except ValueError:
                pass

    # PolyStyle/color
    poly_style = _find_child(style_elem, "PolyStyle", ns)
    if poly_style is not None:
        color = _get_text(poly_style, "color", ns)
        if color:
            style["fillColor"] = color

    return style
