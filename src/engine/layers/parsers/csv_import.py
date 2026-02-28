# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Parse CSV with lat,lng columns to point Layer.

Uses stdlib csv module. Expects column headers to include 'lat' and 'lng'
(case-insensitive). All other columns become feature properties.
Coordinates stored as [lng, lat] (GeoJSON convention).
"""

from __future__ import annotations

import csv
import io
import uuid

from engine.layers.layer import Layer, LayerFeature


def parse_csv(csv_string: str) -> Layer:
    """Parse a CSV string with lat/lng columns into a Layer of Point features.

    Args:
        csv_string: Raw CSV content with headers.

    Returns:
        Layer with Point features. Returns empty layer if lat/lng columns
        are missing or content is malformed.
    """
    try:
        reader = csv.DictReader(io.StringIO(csv_string))
        if reader.fieldnames is None:
            return _empty_layer()
    except Exception:
        return _empty_layer()

    # Find lat/lng column names (case-insensitive)
    header_map = {h.lower().strip(): h for h in (reader.fieldnames or [])}
    lat_col = header_map.get("lat") or header_map.get("latitude")
    lng_col = (
        header_map.get("lng")
        or header_map.get("lon")
        or header_map.get("longitude")
    )

    if not lat_col or not lng_col:
        return _empty_layer()

    features: list[LayerFeature] = []
    for idx, row in enumerate(reader):
        try:
            lat = float(row[lat_col])
            lng = float(row[lng_col])
        except (ValueError, TypeError, KeyError):
            continue

        # All other columns become properties
        properties: dict = {}
        for key, value in row.items():
            if key != lat_col and key != lng_col:
                properties[key] = value

        features.append(
            LayerFeature(
                feature_id=f"csv-{idx}",
                geometry_type="Point",
                coordinates=[lng, lat],
                properties=properties,
            )
        )

    return Layer(
        layer_id=f"layer-{uuid.uuid4().hex[:8]}",
        name="CSV Import",
        source_format="csv",
        features=features,
    )


def _empty_layer() -> Layer:
    """Return an empty CSV layer."""
    return Layer(
        layer_id=f"layer-{uuid.uuid4().hex[:8]}",
        name="CSV Import",
        source_format="csv",
        features=[],
    )
