# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Parse CoT (Cursor on Target) XML to LayerFeature.

Uses xml.etree.ElementTree (stdlib only). References the existing CoT parser
at src/engine/comms/cot.py for format conventions.

CoT events have a <point lat="" lon="" hae=""/> element.
Coordinates stored as [lng, lat, alt] (GeoJSON convention).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from engine.layers.layer import LayerFeature


def parse_cot_event(cot_xml: str) -> LayerFeature | None:
    """Parse a CoT XML event string into a LayerFeature.

    Args:
        cot_xml: Raw CoT XML string (a single <event> element).

    Returns:
        LayerFeature with Point geometry, or None on parse errors
        or if the XML is not a valid CoT event.
    """
    try:
        root = ET.fromstring(cot_xml)
    except ET.ParseError:
        return None

    if root.tag != "event":
        return None

    # Extract point
    point = root.find("point")
    if point is None:
        return None

    try:
        lat = float(point.get("lat", 0.0))
        lon = float(point.get("lon", 0.0))
        hae = float(point.get("hae", 0.0))
    except (ValueError, TypeError):
        return None

    # Extract event metadata
    uid = root.get("uid", "")
    cot_type = root.get("type", "")
    how = root.get("how", "")
    time_str = root.get("time", "")

    properties: dict = {
        "uid": uid,
        "cot_type": cot_type,
        "how": how,
    }

    # Parse detail element
    detail = root.find("detail")
    if detail is not None:
        contact = detail.find("contact")
        if contact is not None:
            callsign = contact.get("callsign", "")
            if callsign:
                properties["callsign"] = callsign

        track = detail.find("track")
        if track is not None:
            try:
                properties["speed"] = float(track.get("speed", 0.0))
                properties["course"] = float(track.get("course", 0.0))
            except (ValueError, TypeError):
                pass

        remarks = detail.find("remarks")
        if remarks is not None and remarks.text:
            properties["remarks"] = remarks.text.strip()

    return LayerFeature(
        feature_id=uid or f"cot-{id(root)}",
        geometry_type="Point",
        coordinates=[lon, lat, hae],
        properties=properties,
        timestamp=time_str if time_str else None,
    )
