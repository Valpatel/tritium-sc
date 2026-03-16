# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ADS-B track processor — aircraft tracking via dump1090 integration.

Processes ADS-B messages from dump1090 (or compatible decoders like
readsb, dump1090-mutability, dump1090-fa) and maintains an in-memory
registry of tracked aircraft.

Each aircraft is identified by its ICAO 24-bit hex address and
registered as a TrackedTarget with source='adsb' and target_id
prefix 'adsb_{icao}'.

Data sources:
    - MQTT topic: tritium/{site}/sdr/{id}/adsb
    - REST API: POST /api/sdr/ingest/adsb
    - EventBus: event type 'adsb:message' or 'dump1090:message'
    - Direct dump1090 TCP JSON stream (via HackRFPlugin)

Message format (dump1090 JSON):
    {
        "hex": "A1B2C3",
        "flight": "UAL2145",
        "lat": 30.27,
        "lon": -97.74,
        "altitude": 12000,
        "speed": 250,
        "track": 135,
        "squawk": "1200",
        "vert_rate": 500,
        "ground": false
    }
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

log = logging.getLogger("sdr_monitor.adsb")

# Default time before an aircraft track goes stale
DEFAULT_ADSB_TTL_S = 60.0

# Emergency squawk codes
EMERGENCY_SQUAWKS = {
    "7500": "hijack",
    "7600": "radio_failure",
    "7700": "emergency",
}


class ADSBTrack:
    """An ADS-B aircraft track.

    Maintains the latest position, altitude, speed, heading, and
    identification for a single aircraft identified by its ICAO hex.
    """

    __slots__ = (
        "icao_hex",
        "callsign",
        "lat",
        "lng",
        "altitude_ft",
        "speed_kts",
        "heading",
        "vertical_rate",
        "squawk",
        "first_seen",
        "last_seen",
        "message_count",
        "on_ground",
    )

    def __init__(
        self,
        icao_hex: str,
        callsign: str = "",
        lat: float = 0.0,
        lng: float = 0.0,
        altitude_ft: int = 0,
        speed_kts: float = 0.0,
        heading: float = 0.0,
        vertical_rate: int = 0,
        squawk: str = "",
    ) -> None:
        self.icao_hex = icao_hex
        self.callsign = callsign
        self.lat = lat
        self.lng = lng
        self.altitude_ft = altitude_ft
        self.speed_kts = speed_kts
        self.heading = heading
        self.vertical_rate = vertical_rate
        self.squawk = squawk
        now = time.time()
        self.first_seen = now
        self.last_seen = now
        self.message_count = 1
        self.on_ground = False

    def update(self, msg: dict) -> None:
        """Update track from a dump1090-style message."""
        self.last_seen = time.time()
        self.message_count += 1
        flight = msg.get("flight", "").strip()
        if flight:
            self.callsign = flight
        lat = msg.get("lat", 0.0)
        lon = msg.get("lon", 0.0)
        if lat and lon:
            self.lat = lat
            self.lng = lon
        alt = msg.get("altitude", msg.get("alt_baro", 0))
        if alt:
            self.altitude_ft = int(alt)
        speed = msg.get("speed", msg.get("gs", 0.0))
        if speed:
            self.speed_kts = float(speed)
        track = msg.get("track", 0.0)
        if track:
            self.heading = float(track)
        vr = msg.get("vert_rate", msg.get("baro_rate", 0))
        if vr:
            self.vertical_rate = int(vr)
        squawk = msg.get("squawk", "")
        if squawk:
            self.squawk = squawk
        self.on_ground = bool(msg.get("ground", False))

    @property
    def is_emergency(self) -> bool:
        """Check if this aircraft is squawking an emergency code."""
        return self.squawk in EMERGENCY_SQUAWKS

    @property
    def emergency_type(self) -> Optional[str]:
        """Return the emergency type if squawking emergency, else None."""
        return EMERGENCY_SQUAWKS.get(self.squawk)

    @property
    def label(self) -> str:
        """Human-readable label: callsign if available, else ICAO hex."""
        return self.callsign if self.callsign else self.icao_hex

    @property
    def flight_level(self) -> str:
        """Flight level string (e.g., 'FL350' for 35000 ft)."""
        return f"FL{self.altitude_ft // 100}"

    def to_dict(self) -> dict:
        return {
            "icao_hex": self.icao_hex,
            "callsign": self.callsign,
            "lat": self.lat,
            "lng": self.lng,
            "altitude_ft": self.altitude_ft,
            "speed_kts": self.speed_kts,
            "heading": self.heading,
            "vertical_rate": self.vertical_rate,
            "squawk": self.squawk,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "message_count": self.message_count,
            "on_ground": self.on_ground,
            "is_emergency": self.is_emergency,
            "label": self.label,
            "flight_level": self.flight_level,
        }


class ADSBProcessor:
    """ADS-B message processor and aircraft track registry.

    Maintains an in-memory registry of aircraft tracks. Handles:
    - Track creation and update from dump1090-style JSON messages
    - Stale track expiry based on configurable TTL
    - Emergency squawk detection
    - TrackedTarget registration in the target tracker

    Usage::

        processor = ADSBProcessor(ttl_s=60.0)
        track_dict = processor.ingest(adsb_message)
        active = processor.get_active_tracks()
        processor.expire_stale()
    """

    def __init__(self, ttl_s: float = DEFAULT_ADSB_TTL_S) -> None:
        self._tracks: dict[str, ADSBTrack] = {}
        self._ttl_s = ttl_s
        self._messages_received = 0

    def ingest(self, msg: dict) -> Optional[dict]:
        """Process an ADS-B message and return the updated track dict.

        Args:
            msg: dump1090-style JSON message with at minimum a 'hex' field.

        Returns:
            Track dict if valid, None if the message lacks an ICAO hex.
        """
        icao = msg.get("hex", "").strip()
        if not icao:
            return None

        self._messages_received += 1

        if icao in self._tracks:
            track = self._tracks[icao]
            track.update(msg)
        else:
            flight = msg.get("flight", "").strip()
            lat = msg.get("lat", 0.0)
            lon = msg.get("lon", 0.0)
            alt = int(msg.get("altitude", msg.get("alt_baro", 0)))
            speed = float(msg.get("speed", msg.get("gs", 0.0)))
            heading = float(msg.get("track", 0.0))
            squawk = msg.get("squawk", "")

            track = ADSBTrack(
                icao_hex=icao,
                callsign=flight,
                lat=lat,
                lng=lon,
                altitude_ft=alt,
                speed_kts=speed,
                heading=heading,
                squawk=squawk,
            )
            self._tracks[icao] = track

        return track.to_dict()

    def get_active_tracks(self) -> list[dict]:
        """Return all tracks that are not stale (within TTL)."""
        now = time.time()
        return [
            t.to_dict()
            for t in self._tracks.values()
            if now - t.last_seen < self._ttl_s
        ]

    def get_track(self, icao: str) -> Optional[dict]:
        """Get a specific track by ICAO hex, or None if not found."""
        track = self._tracks.get(icao)
        return track.to_dict() if track else None

    def get_emergency_tracks(self) -> list[dict]:
        """Return tracks currently squawking emergency codes."""
        now = time.time()
        return [
            t.to_dict()
            for t in self._tracks.values()
            if t.is_emergency and now - t.last_seen < self._ttl_s
        ]

    def expire_stale(self) -> list[str]:
        """Remove stale tracks and return list of expired ICAO hex codes."""
        now = time.time()
        expired = [
            icao
            for icao, track in self._tracks.items()
            if now - track.last_seen > self._ttl_s
        ]
        for icao in expired:
            del self._tracks[icao]
        return expired

    @property
    def track_count(self) -> int:
        """Number of tracks in the registry (including stale)."""
        return len(self._tracks)

    @property
    def messages_received(self) -> int:
        return self._messages_received

    def get_stats(self) -> dict:
        """Return processor statistics."""
        now = time.time()
        active = sum(1 for t in self._tracks.values() if now - t.last_seen < self._ttl_s)
        return {
            "messages_received": self._messages_received,
            "tracks_total": len(self._tracks),
            "tracks_active": active,
            "ttl_s": self._ttl_s,
        }
