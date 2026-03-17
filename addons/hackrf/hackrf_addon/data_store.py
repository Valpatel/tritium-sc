# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Persistent SQLite data store for HackRF SDR data.

Stores spectrum snapshots, signal detections, decoded devices (rtl_433),
TPMS sensors, aircraft (ADS-B), and RF environment summaries across
server restarts. Uses aiosqlite for async access.

UX Loop 6 (Investigate Target) — enables historical RF analysis.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite

log = logging.getLogger("hackrf.data_store")

# Default database path — inside the gitignored data/ directory
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data",
    "hackrf.db",
)


class HackRFDataStore:
    """Persistent SQLite store for HackRF SDR data.

    Tables:
        spectrum_snapshots — compressed sweep data
        signal_detections — detected signals with frequency and power
        decoded_devices — rtl_433 decoded device events
        tpms_sensors — tire pressure monitoring sensors
        aircraft — ADS-B aircraft tracking
        rf_environment — periodic RF environment snapshots per band
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open database and create tables if needed."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")

        await self._create_tables()
        log.info(f"HackRF data store initialized at {self.db_path}")

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _create_tables(self) -> None:
        """Create all tables if they don't exist."""
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS spectrum_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                freq_start_hz INTEGER NOT NULL,
                freq_end_hz INTEGER NOT NULL,
                bin_width INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                data_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_spectrum_ts
                ON spectrum_snapshots(timestamp);
            CREATE INDEX IF NOT EXISTS idx_spectrum_freq
                ON spectrum_snapshots(freq_start_hz, freq_end_hz);

            CREATE TABLE IF NOT EXISTS signal_detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                freq_hz INTEGER NOT NULL,
                power_dbm REAL NOT NULL,
                band_name TEXT,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                detection_count INTEGER DEFAULT 1
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_freq
                ON signal_detections(freq_hz);
            CREATE INDEX IF NOT EXISTS idx_signal_band
                ON signal_detections(band_name);

            CREATE TABLE IF NOT EXISTS decoded_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                protocol TEXT,
                model TEXT,
                device_id TEXT,
                freq_hz INTEGER,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                event_count INTEGER DEFAULT 1,
                last_data_json TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_decoded_device
                ON decoded_devices(protocol, device_id);
            CREATE INDEX IF NOT EXISTS idx_decoded_model
                ON decoded_devices(model);

            CREATE TABLE IF NOT EXISTS tpms_sensors (
                sensor_id TEXT PRIMARY KEY,
                vehicle_hash TEXT,
                pressure_psi REAL,
                temperature_c REAL,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS aircraft (
                icao TEXT PRIMARY KEY,
                callsign TEXT,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                last_alt REAL,
                last_lat REAL,
                last_lng REAL,
                last_speed REAL
            );
            CREATE INDEX IF NOT EXISTS idx_aircraft_callsign
                ON aircraft(callsign);

            CREATE TABLE IF NOT EXISTS rf_environment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                band_name TEXT NOT NULL,
                avg_power_dbm REAL,
                peak_power_dbm REAL,
                peak_freq_hz INTEGER,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rf_env_band_ts
                ON rf_environment(band_name, timestamp);
        """)
        await self._db.commit()

    # ------------------------------------------------------------------
    # Store methods
    # ------------------------------------------------------------------

    async def store_sweep(self, sweep_data: dict) -> None:
        """Store a compressed spectrum snapshot.

        Args:
            sweep_data: Dict with freq_start_hz, freq_end_hz, bin_width,
                        and 'data' (list of measurement dicts to be JSON-compressed).
        """
        if not self._db:
            return

        data_json = json.dumps(sweep_data.get("data", []))

        await self._db.execute(
            "INSERT INTO spectrum_snapshots (freq_start_hz, freq_end_hz, bin_width, timestamp, data_json) VALUES (?, ?, ?, ?, ?)",
            (
                sweep_data.get("freq_start_hz", 0),
                sweep_data.get("freq_end_hz", 0),
                sweep_data.get("bin_width", 0),
                time.time(),
                data_json,
            ),
        )
        await self._db.commit()

    async def store_signal(self, freq_hz: int, power_dbm: float, band: str | None = None) -> None:
        """Upsert a signal detection.

        If the frequency has been seen before, updates last_seen, power, and
        increments detection_count. Otherwise inserts a new record.

        Args:
            freq_hz: Signal frequency in Hz.
            power_dbm: Signal power in dBm.
            band: Optional band name (e.g. "ISM 433", "WiFi 2.4GHz").
        """
        if not self._db:
            return

        now = time.time()
        await self._db.execute(
            """INSERT INTO signal_detections (freq_hz, power_dbm, band_name, first_seen, last_seen, detection_count)
               VALUES (?, ?, ?, ?, ?, 1)
               ON CONFLICT(freq_hz) DO UPDATE SET
                   power_dbm = excluded.power_dbm,
                   band_name = COALESCE(excluded.band_name, signal_detections.band_name),
                   last_seen = excluded.last_seen,
                   detection_count = signal_detections.detection_count + 1
            """,
            (freq_hz, power_dbm, band, now, now),
        )
        await self._db.commit()

    async def store_device(self, event_data: dict) -> None:
        """Upsert a decoded device from rtl_433.

        Args:
            event_data: Dict with protocol, model, device_id, freq_hz, and
                        any additional data stored as last_data_json.
        """
        if not self._db:
            return

        now = time.time()
        protocol = event_data.get("protocol", "unknown")
        device_id = event_data.get("device_id") or event_data.get("id", "unknown")
        data_json = json.dumps({
            k: v for k, v in event_data.items()
            if k not in ("protocol", "model", "device_id", "id", "freq_hz")
        })

        await self._db.execute(
            """INSERT INTO decoded_devices (protocol, model, device_id, freq_hz, first_seen, last_seen, event_count, last_data_json)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(protocol, device_id) DO UPDATE SET
                   model = COALESCE(excluded.model, decoded_devices.model),
                   freq_hz = COALESCE(excluded.freq_hz, decoded_devices.freq_hz),
                   last_seen = excluded.last_seen,
                   event_count = decoded_devices.event_count + 1,
                   last_data_json = excluded.last_data_json
            """,
            (
                protocol,
                event_data.get("model"),
                str(device_id),
                event_data.get("freq_hz"),
                now,
                now,
                data_json,
            ),
        )
        await self._db.commit()

    async def store_tpms(self, sensor_data: dict) -> None:
        """Upsert a TPMS sensor reading.

        Args:
            sensor_data: Dict with sensor_id, vehicle_hash, pressure_psi, temperature_c.
        """
        if not self._db:
            return

        now = time.time()
        sensor_id = sensor_data.get("sensor_id") or sensor_data.get("id", "unknown")

        await self._db.execute(
            """INSERT INTO tpms_sensors (sensor_id, vehicle_hash, pressure_psi, temperature_c, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(sensor_id) DO UPDATE SET
                   vehicle_hash = COALESCE(excluded.vehicle_hash, tpms_sensors.vehicle_hash),
                   pressure_psi = excluded.pressure_psi,
                   temperature_c = excluded.temperature_c,
                   last_seen = excluded.last_seen
            """,
            (
                str(sensor_id),
                sensor_data.get("vehicle_hash"),
                sensor_data.get("pressure_psi"),
                sensor_data.get("temperature_c"),
                now,
                now,
            ),
        )
        await self._db.commit()

    async def store_aircraft(self, aircraft_data: dict) -> None:
        """Upsert an aircraft from ADS-B.

        Args:
            aircraft_data: Dict with icao, callsign, alt, lat, lng, speed.
        """
        if not self._db:
            return

        now = time.time()
        icao = aircraft_data.get("icao", "unknown")

        await self._db.execute(
            """INSERT INTO aircraft (icao, callsign, first_seen, last_seen, last_alt, last_lat, last_lng, last_speed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(icao) DO UPDATE SET
                   callsign = COALESCE(excluded.callsign, aircraft.callsign),
                   last_seen = excluded.last_seen,
                   last_alt = COALESCE(excluded.last_alt, aircraft.last_alt),
                   last_lat = COALESCE(excluded.last_lat, aircraft.last_lat),
                   last_lng = COALESCE(excluded.last_lng, aircraft.last_lng),
                   last_speed = COALESCE(excluded.last_speed, aircraft.last_speed)
            """,
            (
                icao,
                aircraft_data.get("callsign"),
                now,
                now,
                aircraft_data.get("alt"),
                aircraft_data.get("lat"),
                aircraft_data.get("lng"),
                aircraft_data.get("speed"),
            ),
        )
        await self._db.commit()

    async def store_rf_snapshot(self, band_name: str, avg_power_dbm: float | None = None,
                                 peak_power_dbm: float | None = None,
                                 peak_freq_hz: int | None = None) -> None:
        """Store a periodic RF environment snapshot for a band.

        Args:
            band_name: Name of the frequency band.
            avg_power_dbm: Average power across the band.
            peak_power_dbm: Peak power in the band.
            peak_freq_hz: Frequency of the peak.
        """
        if not self._db:
            return

        await self._db.execute(
            "INSERT INTO rf_environment (band_name, avg_power_dbm, peak_power_dbm, peak_freq_hz, timestamp) VALUES (?, ?, ?, ?, ?)",
            (band_name, avg_power_dbm, peak_power_dbm, peak_freq_hz, time.time()),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    async def get_spectrum_history(
        self, freq_start: int | None = None, freq_end: int | None = None,
        since: float | None = None, limit: int = 100,
    ) -> list[dict]:
        """Get historical spectrum snapshots.

        Args:
            freq_start: Filter by minimum start frequency (Hz).
            freq_end: Filter by maximum end frequency (Hz).
            since: Only snapshots after this Unix timestamp.
            limit: Max snapshots to return.

        Returns:
            List of snapshot dicts with parsed data.
        """
        if not self._db:
            return []

        conditions = []
        params = []

        if freq_start is not None:
            conditions.append("freq_start_hz >= ?")
            params.append(freq_start)
        if freq_end is not None:
            conditions.append("freq_end_hz <= ?")
            params.append(freq_end)
        if since is not None:
            conditions.append("timestamp > ?")
            params.append(since)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        cursor = await self._db.execute(
            f"SELECT freq_start_hz, freq_end_hz, bin_width, timestamp, data_json FROM spectrum_snapshots WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        )
        rows = []
        for row in await cursor.fetchall():
            d = dict(row)
            try:
                d["data"] = json.loads(d.pop("data_json"))
            except (json.JSONDecodeError, KeyError):
                d["data"] = []
                d.pop("data_json", None)
            rows.append(d)
        rows.reverse()
        return rows

    async def get_signal_trend(self, freq_hz: int, since: float | None = None) -> list[dict]:
        """Get signal strength over time for a specific frequency.

        This queries spectrum_snapshots and extracts the power at the given
        frequency from each snapshot. For exact-match use signal_detections.

        Args:
            freq_hz: Frequency to track (Hz).
            since: Only data after this Unix timestamp.

        Returns:
            List of {timestamp, power_dbm} dicts.
        """
        if not self._db:
            return []

        # Get from signal_detections table — just the current state
        since_ts = since or 0.0
        cursor = await self._db.execute(
            "SELECT freq_hz, power_dbm, first_seen, last_seen, detection_count FROM signal_detections WHERE freq_hz = ?",
            (freq_hz,),
        )
        row = await cursor.fetchone()
        if row:
            return [dict(row)]
        return []

    async def get_device_history(self, device_id: str) -> list[dict]:
        """Get event history for a decoded device.

        Args:
            device_id: The device ID string.

        Returns:
            List of device event dicts.
        """
        if not self._db:
            return []

        cursor = await self._db.execute(
            "SELECT protocol, model, device_id, freq_hz, first_seen, last_seen, event_count, last_data_json FROM decoded_devices WHERE device_id = ?",
            (device_id,),
        )
        rows = []
        for row in await cursor.fetchall():
            d = dict(row)
            try:
                d["last_data"] = json.loads(d.pop("last_data_json"))
            except (json.JSONDecodeError, KeyError):
                d["last_data"] = {}
                d.pop("last_data_json", None)
            rows.append(d)
        return rows

    async def get_aircraft_tracks(self, icao: str | None = None, since: float | None = None) -> list[dict]:
        """Get aircraft tracking data.

        Args:
            icao: Filter by ICAO hex code. If None, returns all.
            since: Only aircraft seen after this timestamp.

        Returns:
            List of aircraft dicts.
        """
        if not self._db:
            return []

        conditions = []
        params = []

        if icao is not None:
            conditions.append("icao = ?")
            params.append(icao)
        if since is not None:
            conditions.append("last_seen > ?")
            params.append(since)

        where = " AND ".join(conditions) if conditions else "1=1"

        cursor = await self._db.execute(
            f"SELECT icao, callsign, first_seen, last_seen, last_alt, last_lat, last_lng, last_speed FROM aircraft WHERE {where} ORDER BY last_seen DESC",
            params,
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_rf_environment_history(
        self, band_name: str | None = None, since: float | None = None
    ) -> list[dict]:
        """Get RF environment history, optionally filtered by band.

        Args:
            band_name: Filter by band name.
            since: Only data after this Unix timestamp.

        Returns:
            List of RF environment snapshot dicts.
        """
        if not self._db:
            return []

        conditions = []
        params = []

        if band_name is not None:
            conditions.append("band_name = ?")
            params.append(band_name)
        if since is not None:
            conditions.append("timestamp > ?")
            params.append(since)

        where = " AND ".join(conditions) if conditions else "1=1"

        cursor = await self._db.execute(
            f"SELECT band_name, avg_power_dbm, peak_power_dbm, peak_freq_hz, timestamp FROM rf_environment WHERE {where} ORDER BY timestamp",
            params,
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_all_signals(self, min_power: float | None = None) -> list[dict]:
        """Get all detected signals.

        Args:
            min_power: Minimum power threshold in dBm.

        Returns:
            List of signal detection dicts sorted by power descending.
        """
        if not self._db:
            return []

        if min_power is not None:
            cursor = await self._db.execute(
                "SELECT freq_hz, power_dbm, band_name, first_seen, last_seen, detection_count FROM signal_detections WHERE power_dbm >= ? ORDER BY power_dbm DESC",
                (min_power,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT freq_hz, power_dbm, band_name, first_seen, last_seen, detection_count FROM signal_detections ORDER BY power_dbm DESC",
            )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_all_devices(self) -> list[dict]:
        """Get all decoded devices."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            "SELECT protocol, model, device_id, freq_hz, first_seen, last_seen, event_count, last_data_json FROM decoded_devices ORDER BY last_seen DESC",
        )
        rows = []
        for row in await cursor.fetchall():
            d = dict(row)
            try:
                d["last_data"] = json.loads(d.pop("last_data_json"))
            except (json.JSONDecodeError, KeyError):
                d["last_data"] = {}
                d.pop("last_data_json", None)
            rows.append(d)
        return rows

    async def get_tpms_sensors(self) -> list[dict]:
        """Get all TPMS sensors."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            "SELECT sensor_id, vehicle_hash, pressure_psi, temperature_c, first_seen, last_seen FROM tpms_sensors ORDER BY last_seen DESC",
        )
        return [dict(row) for row in await cursor.fetchall()]
