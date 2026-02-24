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


# ---------------------------------------------------------------------------
# Camera ground-plane projection
# ---------------------------------------------------------------------------

@dataclass
class CameraCalibration:
    """Calibration data for projecting camera pixel coords to ground plane.

    Simple ground-plane projection model: camera at known position + heading + FOV,
    assume flat ground. Gives +/-5m accuracy for objects 10-30m from camera.
    """

    position: tuple[float, float]   # (x, y) in local meters
    heading: float                  # degrees, 0=North, clockwise
    fov_h: float = 60.0            # horizontal FOV in degrees
    mount_height: float = 2.5      # meters above ground
    max_range: float = 30.0        # max detection range in meters


def camera_pixel_to_ground(
    cx: float, cy: float, calib: CameraCalibration
) -> tuple[float, float] | None:
    """Project normalized image coordinates to ground plane position.

    Args:
        cx: Horizontal position in image (0.0=left, 1.0=right)
        cy: Vertical position in image (0.0=top, 1.0=bottom)
        calib: Camera calibration data

    Returns:
        (x, y) in local meters, or None if projection fails
        (e.g., looking at sky, object above horizon)
    """
    # Horizontal angle offset from center of FOV
    angle_h = (cx - 0.5) * calib.fov_h
    bearing = calib.heading + angle_h

    # Range estimate from vertical position
    # cy=0.0 = top (far), cy=1.0 = bottom (close)
    # Objects above horizon (cy < ~0.1) can't be projected
    if cy < 0.1:
        return None

    range_factor = 1.0 - cy  # 0=close, 1=far
    range_m = 2.0 + range_factor * calib.max_range

    # Project to ground
    bearing_rad = math.radians(bearing)
    dx = range_m * math.sin(bearing_rad)
    dy = range_m * math.cos(bearing_rad)

    return (calib.position[0] + dx, calib.position[1] + dy)
