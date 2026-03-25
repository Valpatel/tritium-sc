# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""RadarTracker — core radar track management and target conversion.

Subscribes to MQTT radar track data, converts range/azimuth to lat/lng
using the radar's configured position, and creates/updates TrackedTarget
entries in the unified target tracker.

Supports multiple radars per site. Each radar has its own configuration
(position, orientation, range limits). Tracks are aged out after a
configurable TTL.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("radar-tracker")

# Earth radius in meters (WGS-84 mean)
EARTH_RADIUS_M = 6_371_000.0

# Default track time-to-live in seconds
DEFAULT_TRACK_TTL = 30.0

# Maximum tracks to retain per radar
MAX_TRACKS_PER_RADAR = 500


@dataclass
class RadarUnit:
    """Configuration for a single radar installation."""

    radar_id: str
    lat: float = 0.0
    lng: float = 0.0
    altitude_m: float = 0.0
    orientation_deg: float = 0.0  # boresight direction from north
    max_range_m: float = 20000.0
    min_range_m: float = 50.0
    name: str = ""
    enabled: bool = True
    online: bool = False
    last_seen: float = 0.0

    def to_dict(self) -> dict:
        return {
            "radar_id": self.radar_id,
            "lat": self.lat,
            "lng": self.lng,
            "altitude_m": self.altitude_m,
            "orientation_deg": self.orientation_deg,
            "max_range_m": self.max_range_m,
            "min_range_m": self.min_range_m,
            "name": self.name or self.radar_id,
            "enabled": self.enabled,
            "online": self.online,
            "last_seen": self.last_seen,
        }


@dataclass
class LiveTrack:
    """A live radar track with computed lat/lng."""

    track_id: str
    radar_id: str
    range_m: float
    azimuth_deg: float
    elevation_deg: float = 0.0
    velocity_mps: float = 0.0
    rcs_dbsm: float = 0.0
    classification: str = "unknown"
    confidence: float = 1.0
    lat: float = 0.0
    lng: float = 0.0
    timestamp: float = field(default_factory=time.time)
    target_id: str = ""

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "radar_id": self.radar_id,
            "range_m": self.range_m,
            "azimuth_deg": self.azimuth_deg,
            "elevation_deg": self.elevation_deg,
            "velocity_mps": self.velocity_mps,
            "rcs_dbsm": self.rcs_dbsm,
            "classification": self.classification,
            "confidence": self.confidence,
            "lat": self.lat,
            "lng": self.lng,
            "timestamp": self.timestamp,
            "target_id": self.target_id,
        }


def range_azimuth_to_latlng(
    radar_lat: float,
    radar_lng: float,
    range_m: float,
    azimuth_deg: float,
    orientation_deg: float = 0.0,
) -> tuple[float, float]:
    """Convert range/azimuth from radar position to lat/lng.

    Uses the haversine forward formula (destination point given
    distance and bearing from start).

    Parameters
    ----------
    radar_lat, radar_lng:
        Radar position in decimal degrees.
    range_m:
        Distance from radar to target in meters.
    azimuth_deg:
        Azimuth from radar boresight in degrees (0=boresight, CW positive).
    orientation_deg:
        Radar boresight direction in degrees from true north.

    Returns
    -------
    Tuple of (lat, lng) in decimal degrees.
    """
    # True bearing = orientation + azimuth
    bearing_deg = (orientation_deg + azimuth_deg) % 360.0
    bearing_rad = math.radians(bearing_deg)
    lat1 = math.radians(radar_lat)
    lng1 = math.radians(radar_lng)
    angular_dist = range_m / EARTH_RADIUS_M

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_dist)
        + math.cos(lat1) * math.sin(angular_dist) * math.cos(bearing_rad)
    )
    lng2 = lng1 + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_dist) * math.cos(lat1),
        math.cos(angular_dist) - math.sin(lat1) * math.sin(lat2),
    )

    return (math.degrees(lat2), math.degrees(lng2))


def classify_from_rcs_velocity(
    rcs_dbsm: float, velocity_mps: float
) -> str:
    """Heuristic classification from radar cross section and velocity.

    RCS reference values (approximate):
    - Person: -10 to 0 dBsm
    - Car: 0 to 10 dBsm
    - Truck: 10 to 20 dBsm
    - Small aircraft/UAV: -20 to -5 dBsm (but fast)
    - Large aircraft: 10 to 40 dBsm (fast)
    - Ship: 20 to 50 dBsm (slow)
    """
    abs_vel = abs(velocity_mps)

    # Aircraft: fast + any RCS
    if abs_vel > 50.0:
        if rcs_dbsm < -5.0:
            return "uav"
        return "aircraft"

    # Ship: slow-to-moderate, very high RCS (check before vehicle)
    if abs_vel < 15.0 and rcs_dbsm > 20.0:
        return "ship"

    # Animal: slow, very low RCS (check before person)
    if abs_vel < 5.0 and rcs_dbsm < -10.0:
        return "animal"

    # Vehicle: moderate speed, moderate-to-high RCS
    if abs_vel > 2.0 and rcs_dbsm > -5.0:
        return "vehicle"

    # Person: slow, low RCS
    if abs_vel < 3.0 and rcs_dbsm < 5.0:
        return "person"

    return "unknown"


class RadarTracker:
    """Core radar track manager.

    Maintains radar configurations and live tracks. Converts incoming
    track data to lat/lng and pushes updates to the TargetTracker.
    """

    def __init__(
        self,
        target_tracker: Any = None,
        event_bus: Any = None,
        track_ttl: float = DEFAULT_TRACK_TTL,
    ) -> None:
        self._target_tracker = target_tracker
        self._event_bus = event_bus
        self._track_ttl = track_ttl

        # Radar units: radar_id -> RadarUnit
        self._radars: dict[str, RadarUnit] = {}

        # Live tracks: target_id -> LiveTrack
        self._tracks: dict[str, LiveTrack] = {}

        self._lock = threading.Lock()

        # Statistics
        self._stats = {
            "tracks_received": 0,
            "tracks_active": 0,
            "tracks_expired": 0,
            "radars_configured": 0,
        }

    # -- Radar configuration -----------------------------------------------

    def configure_radar(
        self,
        radar_id: str,
        lat: float,
        lng: float,
        altitude_m: float = 0.0,
        orientation_deg: float = 0.0,
        max_range_m: float = 20000.0,
        min_range_m: float = 50.0,
        name: str = "",
        enabled: bool = True,
    ) -> RadarUnit:
        """Configure (or update) a radar unit."""
        with self._lock:
            if radar_id in self._radars:
                unit = self._radars[radar_id]
                unit.lat = lat
                unit.lng = lng
                unit.altitude_m = altitude_m
                unit.orientation_deg = orientation_deg
                unit.max_range_m = max_range_m
                unit.min_range_m = min_range_m
                unit.name = name or unit.name
                unit.enabled = enabled
            else:
                unit = RadarUnit(
                    radar_id=radar_id,
                    lat=lat,
                    lng=lng,
                    altitude_m=altitude_m,
                    orientation_deg=orientation_deg,
                    max_range_m=max_range_m,
                    min_range_m=min_range_m,
                    name=name or radar_id,
                    enabled=enabled,
                )
                self._radars[radar_id] = unit
                self._stats["radars_configured"] = len(self._radars)

            log.info(
                "Radar configured: %s at (%.6f, %.6f) orient=%.1f max_range=%.0fm",
                radar_id, lat, lng, orientation_deg, max_range_m,
            )
            return unit

    def get_radar(self, radar_id: str) -> Optional[RadarUnit]:
        """Get a radar unit by ID."""
        with self._lock:
            return self._radars.get(radar_id)

    def list_radars(self) -> list[dict]:
        """List all configured radars."""
        with self._lock:
            return [r.to_dict() for r in self._radars.values()]

    def remove_radar(self, radar_id: str) -> bool:
        """Remove a radar unit and its tracks."""
        with self._lock:
            if radar_id not in self._radars:
                return False
            del self._radars[radar_id]
            # Remove associated tracks
            to_remove = [
                tid for tid, t in self._tracks.items()
                if t.radar_id == radar_id
            ]
            for tid in to_remove:
                del self._tracks[tid]
            self._stats["radars_configured"] = len(self._radars)
            return True

    # -- Track ingestion ---------------------------------------------------

    def ingest_tracks(self, radar_id: str, tracks: list[dict]) -> int:
        """Ingest a batch of radar tracks from MQTT or API.

        Each track dict should have at minimum:
            track_id, range_m, azimuth_deg

        Optional fields:
            elevation_deg, velocity_mps, rcs_dbsm, classification,
            confidence, timestamp, snr_db

        Returns the number of tracks processed.
        """
        with self._lock:
            radar = self._radars.get(radar_id)

        if radar is None:
            # Auto-configure radar with zero position — must be configured
            # explicitly for position conversion to work.
            log.warning(
                "Tracks from unconfigured radar '%s' — auto-registering "
                "with zero position. Configure position for map display.",
                radar_id,
            )
            radar = self.configure_radar(radar_id, lat=0.0, lng=0.0)

        if not radar.enabled:
            return 0

        processed = 0
        now = time.time()

        for track_data in tracks:
            track_id = str(track_data.get("track_id", ""))
            if not track_id:
                continue

            range_m = float(track_data.get("range_m", 0.0))
            azimuth_deg = float(track_data.get("azimuth_deg", 0.0))

            # Skip tracks outside configured range
            if range_m < radar.min_range_m or range_m > radar.max_range_m:
                continue

            elevation_deg = float(track_data.get("elevation_deg", 0.0))
            velocity_mps = float(track_data.get("velocity_mps", 0.0))
            rcs_dbsm = float(track_data.get("rcs_dbsm", 0.0))
            confidence = float(track_data.get("confidence", 1.0))
            timestamp = float(track_data.get("timestamp", now))

            # Classification: use provided or infer from RCS + velocity
            classification = track_data.get("classification", "")
            if not classification or classification == "unknown":
                classification = classify_from_rcs_velocity(rcs_dbsm, velocity_mps)

            # Convert range/azimuth to lat/lng
            if radar.lat != 0.0 or radar.lng != 0.0:
                lat, lng = range_azimuth_to_latlng(
                    radar.lat, radar.lng, range_m, azimuth_deg,
                    orientation_deg=radar.orientation_deg,
                )
            else:
                lat, lng = 0.0, 0.0

            target_id = f"radar_{radar_id}_{track_id}"

            live_track = LiveTrack(
                track_id=track_id,
                radar_id=radar_id,
                range_m=range_m,
                azimuth_deg=azimuth_deg,
                elevation_deg=elevation_deg,
                velocity_mps=velocity_mps,
                rcs_dbsm=rcs_dbsm,
                classification=classification,
                confidence=confidence,
                lat=lat,
                lng=lng,
                timestamp=timestamp,
                target_id=target_id,
            )

            with self._lock:
                self._tracks[target_id] = live_track
                self._stats["tracks_received"] += 1

            # Update TargetTracker
            self._update_target(live_track)

            processed += 1

        # Mark radar as online
        with self._lock:
            radar.online = True
            radar.last_seen = now
            self._stats["tracks_active"] = len(self._tracks)

        # Publish event
        if self._event_bus and processed > 0:
            self._event_bus.publish("radar:tracks_updated", data={
                "radar_id": radar_id,
                "track_count": processed,
                "timestamp": now,
            })

        return processed

    def _update_target(self, track: LiveTrack) -> None:
        """Create or update a TrackedTarget from a radar track."""
        if self._target_tracker is None:
            return

        try:
            from tritium_lib.tracking.target_tracker import TrackedTarget
            from engine.tactical.geo import latlng_to_local

            # Convert lat/lng to local coordinates for the tracker
            if track.lat != 0.0 or track.lng != 0.0:
                x, y, _ = latlng_to_local(track.lat, track.lng)
                position = (x, y)
                pos_source = "radar"
                pos_conf = max(0.3, track.confidence * 0.9)
            else:
                position = (0.0, 0.0)
                pos_source = "radar"
                pos_conf = 0.1

            # Compute heading from azimuth + velocity direction
            heading = track.azimuth_deg if track.velocity_mps != 0.0 else 0.0

            with self._target_tracker._lock:
                if track.target_id in self._target_tracker._targets:
                    t = self._target_tracker._targets[track.target_id]
                    t.position = position
                    t.heading = heading
                    t.speed = abs(track.velocity_mps)
                    t.last_seen = time.monotonic()
                    t.position_confidence = pos_conf
                    t.classification = track.classification
                    t.status = (
                        f"radar:{track.range_m:.0f}m "
                        f"{track.azimuth_deg:.1f}deg "
                        f"{track.velocity_mps:.1f}m/s"
                    )
                    if "radar" not in t.confirming_sources:
                        t.confirming_sources.add("radar")
                else:
                    name = f"Radar: {track.classification} ({track.range_m:.0f}m)"
                    self._target_tracker._targets[track.target_id] = TrackedTarget(
                        target_id=track.target_id,
                        name=name,
                        alliance="unknown",
                        asset_type=track.classification,
                        position=position,
                        heading=heading,
                        speed=abs(track.velocity_mps),
                        last_seen=time.monotonic(),
                        source="radar",
                        position_source=pos_source,
                        position_confidence=pos_conf,
                        classification=track.classification,
                        classification_confidence=track.confidence,
                        status=(
                            f"radar:{track.range_m:.0f}m "
                            f"{track.azimuth_deg:.1f}deg "
                            f"{track.velocity_mps:.1f}m/s"
                        ),
                    )
        except Exception as exc:
            log.error("Failed to update radar target %s: %s", track.target_id, exc)

    # -- Track retrieval ---------------------------------------------------

    def get_tracks(self, radar_id: Optional[str] = None) -> list[dict]:
        """Get current live tracks, optionally filtered by radar."""
        with self._lock:
            if radar_id:
                tracks = [
                    t.to_dict() for t in self._tracks.values()
                    if t.radar_id == radar_id
                ]
            else:
                tracks = [t.to_dict() for t in self._tracks.values()]
        return sorted(tracks, key=lambda t: t["timestamp"], reverse=True)

    def get_ppi_data(self, radar_id: str) -> Optional[dict]:
        """Get PPI scope data for a specific radar."""
        with self._lock:
            radar = self._radars.get(radar_id)
            if radar is None:
                return None

            tracks = [
                {
                    "track_id": t.track_id,
                    "range_m": t.range_m,
                    "azimuth_deg": t.azimuth_deg,
                    "velocity_mps": t.velocity_mps,
                    "rcs_dbsm": t.rcs_dbsm,
                    "classification": t.classification,
                    "confidence": t.confidence,
                }
                for t in self._tracks.values()
                if t.radar_id == radar_id
            ]

            return {
                "radar_id": radar_id,
                "lat": radar.lat,
                "lng": radar.lng,
                "orientation_deg": radar.orientation_deg,
                "max_range_m": radar.max_range_m,
                "tracks": tracks,
                "sweep_angle_deg": 0.0,  # placeholder for antenna position
                "timestamp": time.time(),
            }

    # -- Maintenance -------------------------------------------------------

    def prune_stale(self) -> int:
        """Remove tracks older than TTL. Returns number pruned."""
        now = time.time()
        expired = []
        with self._lock:
            for tid, track in self._tracks.items():
                if now - track.timestamp > self._track_ttl:
                    expired.append(tid)
            for tid in expired:
                del self._tracks[tid]
                self._stats["tracks_expired"] += 1
            self._stats["tracks_active"] = len(self._tracks)

        # Also remove from target tracker
        if self._target_tracker and expired:
            try:
                with self._target_tracker._lock:
                    for tid in expired:
                        self._target_tracker._targets.pop(tid, None)
            except Exception:
                pass

        return len(expired)

    def get_stats(self) -> dict:
        """Return tracker statistics."""
        with self._lock:
            return {
                **self._stats,
                "track_ttl": self._track_ttl,
            }
