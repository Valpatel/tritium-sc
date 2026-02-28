# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""LayerManager — registry of active map layers.

Manages the lifecycle of Layer objects: add, remove, get, list,
import from file, export to format, and visibility control.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from engine.layers.layer import Layer


class LayerManager:
    """Registry of active map layers."""

    def __init__(self) -> None:
        self._layers: dict[str, Layer] = {}

    def add_layer(self, layer: Layer) -> str:
        """Add a layer to the registry.

        Args:
            layer: The Layer to register.

        Returns:
            The layer_id of the added layer.
        """
        self._layers[layer.layer_id] = layer
        return layer.layer_id

    def remove_layer(self, layer_id: str) -> bool:
        """Remove a layer from the registry.

        Args:
            layer_id: ID of the layer to remove.

        Returns:
            True if the layer was removed, False if it didn't exist.
        """
        if layer_id in self._layers:
            del self._layers[layer_id]
            return True
        return False

    def get_layer(self, layer_id: str) -> Layer | None:
        """Get a layer by ID.

        Args:
            layer_id: ID of the layer to retrieve.

        Returns:
            The Layer if found, None otherwise.
        """
        return self._layers.get(layer_id)

    def list_layers(self) -> list[Layer]:
        """List all registered layers.

        Returns:
            List of all Layer objects in the registry.
        """
        return list(self._layers.values())

    def set_visibility(self, layer_id: str, visible: bool) -> None:
        """Set the visibility of a layer.

        Args:
            layer_id: ID of the layer.
            visible: Whether the layer should be visible.

        Raises:
            KeyError: If the layer_id is not found.
        """
        layer = self._layers.get(layer_id)
        if layer is None:
            raise KeyError(f"Layer not found: {layer_id}")
        layer.visible = visible

    def import_file(self, path: str, format: str = "auto") -> Layer:
        """Import a file into a new layer.

        Args:
            path: Path to the file to import.
            format: File format ("kml", "geojson", "gpx", "cot", "csv", or "auto").
                    "auto" detects format from file extension.

        Returns:
            The imported Layer (also registered in the manager).
        """
        if format == "auto":
            ext = os.path.splitext(path)[1].lower()
            format_map = {
                ".kml": "kml",
                ".kmz": "kml",
                ".geojson": "geojson",
                ".json": "geojson",
                ".gpx": "gpx",
                ".csv": "csv",
                ".xml": "cot",
            }
            format = format_map.get(ext, "geojson")

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        layer = self._parse_content(content, format)

        # Generate an ID if the parser didn't set one meaningfully
        if not layer.layer_id or layer.layer_id.startswith("layer-"):
            layer.layer_id = f"layer-{uuid.uuid4().hex[:8]}"

        now = datetime.now(timezone.utc).isoformat()
        layer.created_at = now
        layer.updated_at = now

        self.add_layer(layer)
        return layer

    def export_layer(self, layer_id: str, format: str) -> str:
        """Export a layer to a string in the given format.

        Args:
            layer_id: ID of the layer to export.
            format: Output format ("kml", "geojson", "gpx").

        Returns:
            String representation in the requested format.

        Raises:
            KeyError: If the layer_id is not found.
            ValueError: If the format is not supported.
        """
        layer = self._layers.get(layer_id)
        if layer is None:
            raise KeyError(f"Layer not found: {layer_id}")

        if format == "geojson":
            from engine.layers.exporters.geojson import export_geojson
            return json.dumps(export_geojson(layer))
        elif format == "kml":
            from engine.layers.exporters.kml import export_kml
            return export_kml(layer)
        elif format == "gpx":
            from engine.layers.exporters.gpx import export_gpx
            return export_gpx(layer)
        else:
            raise ValueError(f"Unsupported export format: {format}")

    def _parse_content(self, content: str, format: str) -> Layer:
        """Parse content string into a Layer using the appropriate parser."""
        if format == "kml":
            from engine.layers.parsers.kml import parse_kml
            return parse_kml(content)
        elif format == "geojson":
            from engine.layers.parsers.geojson import parse_geojson
            return parse_geojson(content)
        elif format == "gpx":
            from engine.layers.parsers.gpx import parse_gpx
            return parse_gpx(content)
        elif format == "csv":
            from engine.layers.parsers.csv_import import parse_csv
            return parse_csv(content)
        elif format == "cot":
            from engine.layers.parsers.cot import parse_cot_event
            feature = parse_cot_event(content)
            layer = Layer(
                layer_id=f"layer-{uuid.uuid4().hex[:8]}",
                name="CoT Import",
                source_format="cot",
                features=[feature] if feature else [],
            )
            return layer
        else:
            raise ValueError(f"Unsupported import format: {format}")
