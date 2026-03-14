# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""WiFi BSSID geolocation enrichment provider.

Estimates the real-world location of WiFi access points by looking up their
BSSID (MAC address) in a local SQLite cache.  In production this cache would
be populated from services like WiGLE or the Mozilla Location Service; for
now we ship a stub database of ~50 sample BSSIDs covering common scenarios
(home routers, coffee shops, enterprise APs, mobile hotspots).

The provider registers itself into the EnrichmentPipeline and auto-enriches
any target whose identifiers include a ``bssid`` key.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from .enrichment import EnrichmentPipeline, EnrichmentResult

logger = logging.getLogger("wifi_geolocation")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeoResult:
    """Geolocation estimate for a single BSSID."""

    lat: float
    lng: float
    accuracy_meters: float
    source: str  # e.g. "wigle", "mls", "stub"


# ---------------------------------------------------------------------------
# Stub BSSID database — 50 sample entries
# ---------------------------------------------------------------------------

_STUB_BSSIDS: list[tuple[str, float, float, float, str]] = [
    # (bssid, lat, lng, accuracy_m, source)
    # --- Bay Area residential ---
    ("00:1A:2B:3C:4D:5E", 37.7749, -122.4194, 50.0, "stub"),
    ("00:1A:2B:3C:4D:5F", 37.7750, -122.4195, 45.0, "stub"),
    ("00:1A:2B:3C:4D:60", 37.7751, -122.4196, 55.0, "stub"),
    ("AA:BB:CC:DD:EE:01", 37.7752, -122.4180, 30.0, "stub"),
    ("AA:BB:CC:DD:EE:02", 37.7760, -122.4170, 40.0, "stub"),
    # --- Bay Area commercial ---
    ("11:22:33:44:55:01", 37.7850, -122.4090, 25.0, "stub"),
    ("11:22:33:44:55:02", 37.7855, -122.4085, 20.0, "stub"),
    ("11:22:33:44:55:03", 37.7860, -122.4080, 35.0, "stub"),
    # --- San Jose ---
    ("22:33:44:55:66:01", 37.3382, -121.8863, 60.0, "stub"),
    ("22:33:44:55:66:02", 37.3390, -121.8870, 50.0, "stub"),
    ("22:33:44:55:66:03", 37.3400, -121.8880, 45.0, "stub"),
    # --- Los Angeles ---
    ("33:44:55:66:77:01", 34.0522, -118.2437, 40.0, "stub"),
    ("33:44:55:66:77:02", 34.0530, -118.2440, 35.0, "stub"),
    ("33:44:55:66:77:03", 34.0540, -118.2445, 50.0, "stub"),
    ("33:44:55:66:77:04", 34.0550, -118.2450, 55.0, "stub"),
    ("33:44:55:66:77:05", 34.0560, -118.2455, 30.0, "stub"),
    # --- New York ---
    ("44:55:66:77:88:01", 40.7128, -74.0060, 20.0, "stub"),
    ("44:55:66:77:88:02", 40.7130, -74.0062, 25.0, "stub"),
    ("44:55:66:77:88:03", 40.7135, -74.0065, 30.0, "stub"),
    ("44:55:66:77:88:04", 40.7140, -74.0070, 35.0, "stub"),
    # --- Chicago ---
    ("55:66:77:88:99:01", 41.8781, -87.6298, 40.0, "stub"),
    ("55:66:77:88:99:02", 41.8790, -87.6300, 45.0, "stub"),
    ("55:66:77:88:99:03", 41.8800, -87.6305, 50.0, "stub"),
    # --- Seattle ---
    ("66:77:88:99:AA:01", 47.6062, -122.3321, 25.0, "stub"),
    ("66:77:88:99:AA:02", 47.6070, -122.3330, 30.0, "stub"),
    ("66:77:88:99:AA:03", 47.6080, -122.3340, 35.0, "stub"),
    # --- Denver ---
    ("77:88:99:AA:BB:01", 39.7392, -104.9903, 50.0, "stub"),
    ("77:88:99:AA:BB:02", 39.7400, -104.9910, 55.0, "stub"),
    # --- Austin ---
    ("88:99:AA:BB:CC:01", 30.2672, -97.7431, 30.0, "stub"),
    ("88:99:AA:BB:CC:02", 30.2680, -97.7440, 35.0, "stub"),
    ("88:99:AA:BB:CC:03", 30.2690, -97.7450, 40.0, "stub"),
    # --- Miami ---
    ("99:AA:BB:CC:DD:01", 25.7617, -80.1918, 25.0, "stub"),
    ("99:AA:BB:CC:DD:02", 25.7620, -80.1920, 30.0, "stub"),
    # --- Portland ---
    ("AA:11:22:33:44:01", 45.5152, -122.6784, 35.0, "stub"),
    ("AA:11:22:33:44:02", 45.5160, -122.6790, 40.0, "stub"),
    # --- Coffee shops / enterprise ---
    ("BB:11:22:33:44:01", 37.7900, -122.4000, 15.0, "stub"),
    ("BB:11:22:33:44:02", 37.7905, -122.4005, 10.0, "stub"),
    ("BB:11:22:33:44:03", 37.7910, -122.4010, 12.0, "stub"),
    # --- Mobile hotspots (low accuracy) ---
    ("CC:11:22:33:44:01", 37.8000, -122.4100, 200.0, "stub"),
    ("CC:11:22:33:44:02", 34.0600, -118.2500, 250.0, "stub"),
    ("CC:11:22:33:44:03", 40.7200, -74.0100, 180.0, "stub"),
    # --- Espressif dev boards (common in IoT) ---
    ("24:0A:C4:00:01:01", 37.4220, -122.0841, 100.0, "stub"),
    ("24:0A:C4:00:01:02", 37.4225, -122.0845, 90.0, "stub"),
    ("30:AE:A4:00:01:01", 37.4230, -122.0850, 110.0, "stub"),
    # --- Raspberry Pi APs ---
    ("B8:27:EB:00:01:01", 51.5074, -0.1278, 40.0, "stub"),
    ("DC:A6:32:00:01:01", 51.5080, -0.1280, 35.0, "stub"),
    # --- Airport / transit ---
    ("DD:11:22:33:44:01", 37.6213, -122.3790, 75.0, "stub"),
    ("DD:11:22:33:44:02", 40.6413, -73.7781, 80.0, "stub"),
    ("DD:11:22:33:44:03", 33.9425, -118.4081, 70.0, "stub"),
    # --- University campus ---
    ("EE:11:22:33:44:01", 37.8719, -122.2585, 20.0, "stub"),
]

assert len(_STUB_BSSIDS) == 50, f"Expected 50 stub BSSIDs, got {len(_STUB_BSSIDS)}"


# ---------------------------------------------------------------------------
# WiFiGeolocationProvider
# ---------------------------------------------------------------------------


class WiFiGeolocationProvider:
    """Look up WiFi BSSID to estimate access point location.

    Maintains a local SQLite cache (in-memory by default, or on disk if
    *db_path* is provided).  The cache is seeded with stub data on first use.

    Parameters
    ----------
    db_path:
        Path to SQLite database file.  Use ``":memory:"`` (the default) for
        an ephemeral in-memory cache.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._ensure_db()

    # -- Public API ---------------------------------------------------------

    def query(self, bssid: str) -> GeoResult | None:
        """Look up a BSSID and return its geolocation, or None if unknown.

        The BSSID is normalized to uppercase colon-separated format before
        lookup.
        """
        bssid_norm = self._normalize_bssid(bssid)
        if not bssid_norm:
            return None

        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT lat, lng, accuracy_meters, source FROM bssid_geo WHERE bssid = ?",
                (bssid_norm,),
            ).fetchone()

        if row is None:
            return None

        return GeoResult(
            lat=row[0],
            lng=row[1],
            accuracy_meters=row[2],
            source=row[3],
        )

    def insert(
        self,
        bssid: str,
        lat: float,
        lng: float,
        accuracy_meters: float,
        source: str = "external",
    ) -> None:
        """Insert or update a BSSID geolocation record."""
        bssid_norm = self._normalize_bssid(bssid)
        if not bssid_norm:
            raise ValueError(f"Invalid BSSID: {bssid!r}")

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO bssid_geo
                   (bssid, lat, lng, accuracy_meters, source)
                   VALUES (?, ?, ?, ?, ?)""",
                (bssid_norm, lat, lng, accuracy_meters, source),
            )
            conn.commit()

    def count(self) -> int:
        """Return number of BSSIDs in the cache."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT COUNT(*) FROM bssid_geo").fetchone()
            return row[0] if row else 0

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # -- Enrichment callback ------------------------------------------------

    async def enrich(
        self, target_id: str, identifiers: dict
    ) -> EnrichmentResult | None:
        """Enrichment pipeline callback.

        Looks for ``bssid`` in *identifiers*.  If found and a geolocation is
        available, returns an EnrichmentResult with the position data.
        """
        bssid = identifiers.get("bssid", "")
        if not bssid:
            return None

        result = self.query(bssid)
        if result is None:
            return None

        return EnrichmentResult(
            provider="wifi_geolocation",
            enrichment_type="geolocation",
            data={
                "bssid": self._normalize_bssid(bssid),
                "lat": result.lat,
                "lng": result.lng,
                "accuracy_meters": result.accuracy_meters,
                "source": result.source,
            },
            confidence=self._accuracy_to_confidence(result.accuracy_meters),
        )

    # -- Internal -----------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Return the database connection, creating it if needed."""
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        return self._conn

    def _ensure_db(self) -> None:
        """Create the table and seed stub data if the table is empty."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """CREATE TABLE IF NOT EXISTS bssid_geo (
                    bssid TEXT PRIMARY KEY,
                    lat REAL NOT NULL,
                    lng REAL NOT NULL,
                    accuracy_meters REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'stub'
                )"""
            )
            # Seed stub data only if table is empty
            row = conn.execute("SELECT COUNT(*) FROM bssid_geo").fetchone()
            if row and row[0] == 0:
                conn.executemany(
                    """INSERT OR IGNORE INTO bssid_geo
                       (bssid, lat, lng, accuracy_meters, source)
                       VALUES (?, ?, ?, ?, ?)""",
                    _STUB_BSSIDS,
                )
                conn.commit()
                logger.info("Seeded %d stub BSSID geolocations", len(_STUB_BSSIDS))

    @staticmethod
    def _normalize_bssid(bssid: str) -> str | None:
        """Normalize a BSSID to uppercase colon-separated format.

        Returns None if the input is not a valid 6-octet MAC.
        """
        if not bssid:
            return None

        # Strip whitespace, uppercase, replace separators
        clean = bssid.strip().upper().replace("-", ":").replace(".", ":")

        # Handle formats without separators: AABBCCDDEEFF
        if len(clean) == 12 and ":" not in clean:
            clean = ":".join(clean[i : i + 2] for i in range(0, 12, 2))

        # Validate: must be AA:BB:CC:DD:EE:FF
        parts = clean.split(":")
        if len(parts) != 6:
            return None
        for part in parts:
            if len(part) != 2:
                return None
            try:
                int(part, 16)
            except ValueError:
                return None

        return clean

    @staticmethod
    def _accuracy_to_confidence(accuracy_meters: float) -> float:
        """Convert accuracy in meters to a confidence score (0.0-1.0).

        < 25m  -> 0.9
        25-50m -> 0.8
        50-100m -> 0.7
        100-200m -> 0.5
        > 200m -> 0.3
        """
        if accuracy_meters <= 25:
            return 0.9
        elif accuracy_meters <= 50:
            return 0.8
        elif accuracy_meters <= 100:
            return 0.7
        elif accuracy_meters <= 200:
            return 0.5
        else:
            return 0.3


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def register_wifi_geolocation(
    pipeline: EnrichmentPipeline,
    db_path: str = ":memory:",
) -> WiFiGeolocationProvider:
    """Create a WiFiGeolocationProvider and register it with the pipeline.

    Returns the provider instance so callers can insert additional BSSIDs
    or close the database when done.
    """
    provider = WiFiGeolocationProvider(db_path=db_path)
    pipeline.register_provider("wifi_geolocation", provider.enrich)
    logger.info(
        "Registered wifi_geolocation provider with %d cached BSSIDs",
        provider.count(),
    )
    return provider
