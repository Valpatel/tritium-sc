"""Backward-compatible re-export — canonical location is geo.reference."""
from geo.reference import *  # noqa: F401,F403
from geo.reference import (
    GeoReference,
    METERS_PER_DEG_LAT,
    init_reference,
    get_reference,
    is_initialized,
    local_to_latlng,
    latlng_to_local,
    local_to_latlng_2d,
)
