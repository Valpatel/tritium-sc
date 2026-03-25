# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shim: re-exports StreetGraph from tritium_lib.tracking.street_graph.

The canonical implementation now lives in tritium-lib. This file exists
so that existing SC imports (engine.tactical.street_graph) keep working
without modification.
"""

from tritium_lib.tracking.street_graph import (  # noqa: F401
    StreetGraph,
    _distance,
    _fetch_roads,
    _latlng_to_local,
    _node_key,
    _CACHE_EXPIRY_S,
    _DEFAULT_CACHE_DIR,
    _METERS_PER_DEG_LAT,
    _OVERPASS_URL,
    _USER_AGENT,
)
