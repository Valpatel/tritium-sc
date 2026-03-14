# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""DataProviderPlugin — abstract base for modular data source plugins.

Any external data source — satellite imagery, social media, threat feeds,
license plate databases, weather, AIS/ADS-B, etc. — implements this
interface to feed data into the Tritium map and intelligence layers.

Provider types:
    sensor       — real-time sensor feeds (cameras, radios, IoT)
    gis_layer    — static or semi-static geographic overlays
    intelligence — enrichment/lookup services (OSINT, databases)
    feed         — streaming event feeds (AIS, ADS-B, social media)

Data formats:
    geojson     — GeoJSON FeatureCollections for map rendering
    tiles       — raster tile layers (satellite, terrain)
    events      — timestamped event streams
    enrichment  — lookup/enrichment responses keyed to target IDs
"""

from __future__ import annotations

import uuid
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from engine.plugins.base import PluginInterface


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class DataItem:
    """A single data item returned by a provider query.

    Attributes:
        item_id:    Unique identifier for this item.
        data_type:  Semantic type (e.g., "vessel", "aircraft", "threat", "weather").
        geometry:   Location — dict with "lat", "lng", and optional "polygon"
                    (list of [lat, lng] pairs for area features).
        properties: Arbitrary key-value payload from the source.
        timestamp:  When this item was observed/generated (UTC).
        source:     Provider plugin_id that produced this item.
        confidence: Confidence score 0.0-1.0 (1.0 = ground truth).
    """

    item_id: str
    data_type: str
    geometry: dict[str, Any]
    properties: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""
    confidence: float = 1.0


@dataclass
class EnrichmentResult:
    """Result of an intelligence enrichment lookup.

    Attributes:
        target_id:    The target that was enriched.
        enrichments:  List of enrichment dicts (key-value data from the source).
        source:       Provider plugin_id that produced this result.
        timestamp:    When the enrichment was performed (UTC).
    """

    target_id: str
    enrichments: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Subscription:
    """Handle for a real-time data subscription.

    Call cancel() to stop receiving updates.

    Attributes:
        sub_id:   Unique subscription identifier.
        _cancel:  Internal cancel callback.
    """

    sub_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    _cancel: Callable[[], None] | None = None
    active: bool = True

    def cancel(self) -> None:
        """Cancel this subscription and stop receiving updates."""
        self.active = False
        if self._cancel is not None:
            self._cancel()


# ---------------------------------------------------------------------------
# Bounds / TimeRange helpers
# ---------------------------------------------------------------------------

@dataclass
class Bounds:
    """Geographic bounding box for spatial queries.

    Attributes:
        south: Southern latitude boundary.
        west:  Western longitude boundary.
        north: Northern latitude boundary.
        east:  Eastern longitude boundary.
    """

    south: float
    west: float
    north: float
    east: float

    def contains(self, lat: float, lng: float) -> bool:
        """Check whether a point falls within these bounds."""
        return (self.south <= lat <= self.north
                and self.west <= lng <= self.east)


@dataclass
class TimeRange:
    """Time window for temporal queries.

    Attributes:
        start: Beginning of the time range (UTC).
        end:   End of the time range (UTC).
    """

    start: datetime
    end: datetime


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class DataProviderPlugin(PluginInterface):
    """Abstract base for all data source plugins.

    Subclasses must implement:
        provider_type  — "sensor", "gis_layer", "intelligence", or "feed"
        data_format    — "geojson", "tiles", "events", or "enrichment"
        query()        — fetch data within bounds/time/filters

    Optional overrides:
        subscribe()    — for real-time streaming feeds
        enrich()       — for intelligence/lookup providers
    """

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Provider category: 'sensor', 'gis_layer', 'intelligence', 'feed'."""

    @property
    @abstractmethod
    def data_format(self) -> str:
        """Output format: 'geojson', 'tiles', 'events', 'enrichment'."""

    @abstractmethod
    async def query(
        self,
        bounds: Bounds | None = None,
        time_range: TimeRange | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[DataItem]:
        """Query data from this provider.

        Args:
            bounds:     Geographic bounding box to filter results.
            time_range: Time window to filter results.
            filters:    Provider-specific filter parameters.

        Returns:
            List of DataItem instances matching the query.
        """

    async def subscribe(
        self,
        callback: Callable[[DataItem], Awaitable[None]],
    ) -> Subscription:
        """Subscribe to real-time updates from this provider.

        Override for providers that support streaming (feeds, sensors).
        Default raises NotImplementedError.

        Args:
            callback: Async function called with each new DataItem.

        Returns:
            Subscription handle — call .cancel() to stop.
        """
        raise NotImplementedError(
            f"{self.plugin_id} does not support real-time subscriptions"
        )

    async def enrich(
        self,
        target_id: str,
        context: dict[str, Any] | None = None,
    ) -> EnrichmentResult:
        """Look up enrichment data for a specific target.

        Override for intelligence/lookup providers.
        Default raises NotImplementedError.

        Args:
            target_id: The target to enrich.
            context:   Additional context for the lookup.

        Returns:
            EnrichmentResult with enrichment data.
        """
        raise NotImplementedError(
            f"{self.plugin_id} does not support enrichment lookups"
        )
