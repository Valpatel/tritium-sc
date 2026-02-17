"""Server-side geo-reference — coordinate transforms between lat/lng and local meters.

The geo-reference point (map center) grounds all simulation coordinates to
real-world lat/lng.  Physics runs in local meters for speed; lat/lng is
computed on serialization so every API response carries real coordinates.

Convention:
    - Local origin (0, 0, 0) = geo-reference point (lat, lng, alt)
    - 1 local unit = 1 meter
    - +X = East, +Y = North, +Z = Up
    - Heading 0 = North, clockwise in degrees

The same math is mirrored in frontend/js/geo.js for client-side use.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

METERS_PER_DEG_LAT = 111_320.0


@dataclass
class GeoReference:
    """A real-world reference point that anchors local coordinates."""

    lat: float = 0.0
    lng: float = 0.0
    alt: float = 0.0  # meters above sea level
    initialized: bool = False

    @property
    def meters_per_deg_lng(self) -> float:
        return METERS_PER_DEG_LAT * math.cos(math.radians(self.lat))


# Module-level singleton — set once at startup, read from any thread.
_ref = GeoReference()
_lock = threading.Lock()


def init_reference(lat: float, lng: float, alt: float = 0.0) -> GeoReference:
    """Set the geo-reference point (map center).

    Call once at startup (from config or geocoding result).
    Thread-safe; subsequent calls update the reference.
    """
    global _ref
    with _lock:
        _ref = GeoReference(lat=lat, lng=lng, alt=alt, initialized=True)
    return _ref


def get_reference() -> GeoReference:
    """Return the current geo-reference point."""
    return _ref


def is_initialized() -> bool:
    """True if a real reference point has been set."""
    return _ref.initialized


# ---------------------------------------------------------------------------
# Coordinate transforms
# ---------------------------------------------------------------------------

def local_to_latlng(x: float, y: float, z: float = 0.0) -> dict:
    """Convert local meters (x=East, y=North, z=Up) to lat/lng/alt.

    Returns {"lat": float, "lng": float, "alt": float}.
    """
    ref = _ref
    if not ref.initialized:
        return {"lat": 0.0, "lng": 0.0, "alt": z}
    lat = ref.lat + y / METERS_PER_DEG_LAT
    lng = ref.lng + x / ref.meters_per_deg_lng
    alt = ref.alt + z
    return {"lat": lat, "lng": lng, "alt": alt}


def latlng_to_local(lat: float, lng: float, alt: float = 0.0) -> tuple[float, float, float]:
    """Convert lat/lng/alt to local meters (x=East, y=North, z=Up).

    Returns (x, y, z) tuple.
    """
    ref = _ref
    if not ref.initialized:
        return (0.0, 0.0, alt)
    y = (lat - ref.lat) * METERS_PER_DEG_LAT
    x = (lng - ref.lng) * ref.meters_per_deg_lng
    z = alt - ref.alt
    return (x, y, z)


def local_to_latlng_2d(x: float, y: float) -> tuple[float, float]:
    """Convert 2D local meters to (lat, lng). Convenience for flat targets."""
    result = local_to_latlng(x, y, 0.0)
    return (result["lat"], result["lng"])
