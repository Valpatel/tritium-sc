# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""LayerRegistry — manages map layers fed by DataProviderPlugins.

Bridges the data provider plugin system into the map layer system.
Each data provider can register one or more named layers. The registry
tracks visibility state and routes viewport queries to the correct
provider.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from engine.plugins.data_provider import (
    Bounds,
    DataItem,
    DataProviderPlugin,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layer registration record
# ---------------------------------------------------------------------------

@dataclass
class RegisteredLayer:
    """A map layer registered by a data provider.

    Attributes:
        provider_id: plugin_id of the DataProviderPlugin that owns this layer.
        layer_name:  Unique display name for the layer.
        layer_type:  Geometry type hint ("point", "line", "polygon", "heatmap").
        visible:     Whether the layer is currently shown on the map.
        provider:    Reference to the DataProviderPlugin instance.
        metadata:    Extra metadata (color, icon, opacity, etc.).
    """

    provider_id: str
    layer_name: str
    layer_type: str
    visible: bool = True
    provider: DataProviderPlugin | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class LayerRegistry:
    """Manages map layers from all data providers.

    Thread-safe for reads; writes should happen during plugin
    startup (single-threaded boot sequence).
    """

    def __init__(self) -> None:
        self._layers: dict[str, RegisteredLayer] = {}

    def register_layer(
        self,
        provider_id: str,
        layer_name: str,
        layer_type: str = "point",
        default_visible: bool = True,
        provider: DataProviderPlugin | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a new map layer from a data provider.

        Args:
            provider_id:     plugin_id of the owning DataProviderPlugin.
            layer_name:      Unique display name for the layer.
            layer_type:      Geometry type ("point", "line", "polygon", "heatmap").
            default_visible: Whether visible by default.
            provider:        Reference to the provider instance.
            metadata:        Extra rendering hints (color, icon, opacity).

        Raises:
            ValueError: If a layer with this name is already registered.
        """
        if layer_name in self._layers:
            raise ValueError(f"Layer already registered: {layer_name}")

        self._layers[layer_name] = RegisteredLayer(
            provider_id=provider_id,
            layer_name=layer_name,
            layer_type=layer_type,
            visible=default_visible,
            provider=provider,
            metadata=metadata or {},
        )
        logger.info(
            "Registered layer '%s' (type=%s, provider=%s)",
            layer_name, layer_type, provider_id,
        )

    def unregister_layer(self, layer_name: str) -> bool:
        """Remove a layer from the registry.

        Returns:
            True if removed, False if it didn't exist.
        """
        if layer_name in self._layers:
            del self._layers[layer_name]
            logger.info("Unregistered layer '%s'", layer_name)
            return True
        return False

    def list_layers(self) -> list[dict[str, Any]]:
        """List all registered layers with their visibility state.

        Returns:
            List of dicts with layer_name, provider_id, layer_type,
            visible, and metadata for each registered layer.
        """
        return [
            {
                "layer_name": reg.layer_name,
                "provider_id": reg.provider_id,
                "layer_type": reg.layer_type,
                "visible": reg.visible,
                "metadata": reg.metadata,
            }
            for reg in self._layers.values()
        ]

    def toggle_layer(self, layer_name: str, visible: bool) -> None:
        """Set the visibility of a layer.

        Args:
            layer_name: Name of the layer to toggle.
            visible:    Whether the layer should be visible.

        Raises:
            KeyError: If the layer_name is not registered.
        """
        reg = self._layers.get(layer_name)
        if reg is None:
            raise KeyError(f"Layer not found: {layer_name}")
        reg.visible = visible
        logger.debug("Layer '%s' visibility -> %s", layer_name, visible)

    async def get_layer_data(
        self,
        layer_name: str,
        bounds: Bounds | None = None,
    ) -> dict[str, Any]:
        """Get GeoJSON FeatureCollection for a layer within bounds.

        Queries the owning DataProviderPlugin and converts DataItems
        to GeoJSON features.

        Args:
            layer_name: Name of the layer to query.
            bounds:     Geographic bounding box (optional).

        Returns:
            GeoJSON FeatureCollection dict.

        Raises:
            KeyError: If the layer_name is not registered.
            RuntimeError: If the layer has no provider attached.
        """
        reg = self._layers.get(layer_name)
        if reg is None:
            raise KeyError(f"Layer not found: {layer_name}")

        if reg.provider is None:
            raise RuntimeError(
                f"Layer '{layer_name}' has no provider attached"
            )

        items = await reg.provider.query(bounds=bounds)
        features = [_data_item_to_feature(item) for item in items]

        return {
            "type": "FeatureCollection",
            "features": features,
        }

    def get_layer(self, layer_name: str) -> RegisteredLayer | None:
        """Get a registered layer by name."""
        return self._layers.get(layer_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _data_item_to_feature(item: DataItem) -> dict[str, Any]:
    """Convert a DataItem to a GeoJSON Feature dict."""
    geometry = item.geometry
    geojson_geometry: dict[str, Any]

    if "polygon" in geometry:
        coords = geometry["polygon"]
        geojson_geometry = {
            "type": "Polygon",
            "coordinates": [[[p[1], p[0]] for p in coords]],
        }
    elif "lat" in geometry and "lng" in geometry:
        geojson_geometry = {
            "type": "Point",
            "coordinates": [geometry["lng"], geometry["lat"]],
        }
    else:
        geojson_geometry = {"type": "Point", "coordinates": [0, 0]}

    props = dict(item.properties)
    props["item_id"] = item.item_id
    props["data_type"] = item.data_type
    props["source"] = item.source
    props["confidence"] = item.confidence
    props["timestamp"] = item.timestamp.isoformat()

    return {
        "type": "Feature",
        "geometry": geojson_geometry,
        "properties": props,
    }
