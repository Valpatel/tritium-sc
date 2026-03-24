# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shim — canonical implementation lives in tritium_lib.tracking.geofence."""

from tritium_lib.tracking.geofence import *  # noqa: F401,F403
from tritium_lib.tracking.geofence import (  # noqa: F401 — explicit re-exports
    GeoEvent,
    GeoZone,
    GeofenceEngine,
)
