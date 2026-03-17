# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Persistent SQLite data store for Meshtastic mesh network data.

Stores node state, position history, telemetry, messages, and network stats
across server restarts. Uses aiosqlite for async access.

UX Loop 6 (Investigate Target) — enables historical analysis of mesh nodes.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite

log = logging.getLogger("meshtastic.data_store")

# Default database path — inside the gitignored data/ directory
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data",
    "meshtastic.db",
)


class MeshtasticDataStore:
    """Persistent SQLite store for Meshtastic mesh network data.

    Tables:
        nodes — node metadata (upserted on each poll)
        node_positions — GPS position history
        node_telemetry — battery, voltage, SNR, channel util, env sensors
        messages — text, position, telemetry messages
        mesh_stats — periodic network-level snapshots
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open database and create tables if needed."""
        # Ensure data directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        # Enable WAL mode for better concurrent read performance
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")

        await self._create_tables()
        log.info(f"Meshtastic data store initialized at {self.db_path}")

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _create_tables(self) -> None:
        """Create all tables if they don't exist."""
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                long_name TEXT,
                short_name TEXT,
                hw_model TEXT,
                role TEXT,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS node_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                altitude REAL,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_node_positions_node_ts
                ON node_positions(node_id, timestamp);

            CREATE TABLE IF NOT EXISTS node_telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                battery REAL,
                voltage REAL,
                snr REAL,
                channel_util REAL,
                temperature REAL,
                humidity REAL,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_node_telemetry_node_ts
                ON node_telemetry(node_id, timestamp);

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                sender_name TEXT,
                text TEXT,
                channel INTEGER DEFAULT 0,
                type TEXT DEFAULT 'text',
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_ts
                ON messages(timestamp);
            CREATE INDEX IF NOT EXISTS idx_messages_type
                ON messages(type);

            CREATE TABLE IF NOT EXISTS mesh_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_nodes INTEGER NOT NULL,
                online_nodes INTEGER NOT NULL,
                with_gps INTEGER NOT NULL,
                avg_snr REAL,
                avg_battery REAL,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mesh_stats_ts
                ON mesh_stats(timestamp);
        """)
        await self._db.commit()

    # ------------------------------------------------------------------
    # Store methods
    # ------------------------------------------------------------------

    async def store_node(self, node_data: dict) -> None:
        """Upsert a node, optionally storing position and telemetry history.

        Args:
            node_data: Dict with at minimum 'node_id'. May include
                       lat, lng, altitude, battery, voltage, snr,
                       channel_util, temperature, humidity, etc.
        """
        if not self._db:
            return

        node_id = node_data.get("node_id")
        if not node_id:
            return

        now = time.time()

        # Upsert node metadata
        await self._db.execute(
            """INSERT INTO nodes (node_id, long_name, short_name, hw_model, role, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(node_id) DO UPDATE SET
                   long_name = COALESCE(excluded.long_name, nodes.long_name),
                   short_name = COALESCE(excluded.short_name, nodes.short_name),
                   hw_model = COALESCE(excluded.hw_model, nodes.hw_model),
                   role = COALESCE(excluded.role, nodes.role),
                   last_seen = excluded.last_seen
            """,
            (
                node_id,
                node_data.get("long_name"),
                node_data.get("short_name"),
                node_data.get("hw_model"),
                node_data.get("role"),
                now,
                now,
            ),
        )

        # Store position if GPS data present
        lat = node_data.get("lat")
        lng = node_data.get("lng")
        if lat is not None and lng is not None:
            await self._db.execute(
                "INSERT INTO node_positions (node_id, lat, lng, altitude, timestamp) VALUES (?, ?, ?, ?, ?)",
                (node_id, lat, lng, node_data.get("altitude"), now),
            )

        # Store telemetry if any metrics present
        has_telemetry = any(
            node_data.get(k) is not None
            for k in ("battery", "voltage", "snr", "channel_util", "temperature", "humidity")
        )
        if has_telemetry:
            await self._db.execute(
                """INSERT INTO node_telemetry
                   (node_id, battery, voltage, snr, channel_util, temperature, humidity, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    node_id,
                    node_data.get("battery"),
                    node_data.get("voltage"),
                    node_data.get("snr"),
                    node_data.get("channel_util"),
                    node_data.get("temperature"),
                    node_data.get("humidity"),
                    now,
                ),
            )

        await self._db.commit()

    async def store_message(self, msg_data: dict) -> None:
        """Store a mesh message.

        Args:
            msg_data: Dict with sender_id, sender_name, text, channel, type, timestamp.
        """
        if not self._db:
            return

        await self._db.execute(
            "INSERT INTO messages (sender_id, sender_name, text, channel, type, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (
                msg_data.get("sender_id", "unknown"),
                msg_data.get("sender_name"),
                msg_data.get("text"),
                msg_data.get("channel", 0),
                msg_data.get("type", "text"),
                msg_data.get("timestamp", time.time()),
            ),
        )
        await self._db.commit()

    async def store_stats_snapshot(self, stats: dict | None = None) -> None:
        """Store a periodic network stats snapshot.

        Args:
            stats: Dict with total_nodes, online_nodes, with_gps, avg_snr, avg_battery.
                   If None, stores zeros (caller should provide real stats).
        """
        if not self._db:
            return

        if stats is None:
            stats = {}

        await self._db.execute(
            "INSERT INTO mesh_stats (total_nodes, online_nodes, with_gps, avg_snr, avg_battery, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (
                stats.get("total_nodes", 0),
                stats.get("online_nodes", 0),
                stats.get("with_gps", 0),
                stats.get("avg_snr"),
                stats.get("avg_battery"),
                time.time(),
            ),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    async def get_node_history(
        self, node_id: str, since: float | None = None
    ) -> dict:
        """Get position and telemetry history for a node.

        Args:
            node_id: The mesh node ID.
            since: Unix timestamp — only return data after this time.

        Returns:
            Dict with 'positions' and 'telemetry' lists.
        """
        if not self._db:
            return {"positions": [], "telemetry": []}

        since_ts = since or 0.0

        cursor = await self._db.execute(
            "SELECT lat, lng, altitude, timestamp FROM node_positions WHERE node_id = ? AND timestamp > ? ORDER BY timestamp",
            (node_id, since_ts),
        )
        positions = [dict(row) for row in await cursor.fetchall()]

        cursor = await self._db.execute(
            "SELECT battery, voltage, snr, channel_util, temperature, humidity, timestamp FROM node_telemetry WHERE node_id = ? AND timestamp > ? ORDER BY timestamp",
            (node_id, since_ts),
        )
        telemetry = [dict(row) for row in await cursor.fetchall()]

        return {"positions": positions, "telemetry": telemetry}

    async def get_message_history(
        self,
        since: float | None = None,
        channel: int | None = None,
        msg_type: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Get message history with optional filters.

        Args:
            since: Only messages after this Unix timestamp.
            channel: Filter by channel number.
            msg_type: Filter by message type ('text', 'position', 'telemetry').
            limit: Max messages to return.

        Returns:
            List of message dicts, oldest first.
        """
        if not self._db:
            return []

        conditions = []
        params = []

        if since is not None:
            conditions.append("timestamp > ?")
            params.append(since)
        if channel is not None:
            conditions.append("channel = ?")
            params.append(channel)
        if msg_type is not None:
            conditions.append("type = ?")
            params.append(msg_type)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        cursor = await self._db.execute(
            f"SELECT sender_id, sender_name, text, channel, type, timestamp FROM messages WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        rows.reverse()  # Return oldest first
        return rows

    async def get_stats_history(
        self,
        since: float | None = None,
        interval: float | None = None,
    ) -> list[dict]:
        """Get network stats history, optionally sampled at an interval.

        Args:
            since: Only stats after this Unix timestamp.
            interval: If set, sample at this interval (seconds) using GROUP BY.

        Returns:
            List of stats dicts, oldest first.
        """
        if not self._db:
            return []

        since_ts = since or 0.0

        if interval and interval > 0:
            # Group by time buckets
            cursor = await self._db.execute(
                """SELECT
                       AVG(total_nodes) as total_nodes,
                       AVG(online_nodes) as online_nodes,
                       AVG(with_gps) as with_gps,
                       AVG(avg_snr) as avg_snr,
                       AVG(avg_battery) as avg_battery,
                       CAST(timestamp / ? AS INTEGER) * ? as timestamp
                   FROM mesh_stats
                   WHERE timestamp > ?
                   GROUP BY CAST(timestamp / ? AS INTEGER)
                   ORDER BY timestamp""",
                (interval, interval, since_ts, interval),
            )
        else:
            cursor = await self._db.execute(
                "SELECT total_nodes, online_nodes, with_gps, avg_snr, avg_battery, timestamp FROM mesh_stats WHERE timestamp > ? ORDER BY timestamp",
                (since_ts,),
            )

        return [dict(row) for row in await cursor.fetchall()]

    async def get_node_count_over_time(self, since: float | None = None) -> list[dict]:
        """Get node count trend from stats snapshots.

        Returns:
            List of {timestamp, total_nodes, online_nodes} dicts.
        """
        if not self._db:
            return []

        since_ts = since or 0.0
        cursor = await self._db.execute(
            "SELECT timestamp, total_nodes, online_nodes FROM mesh_stats WHERE timestamp > ? ORDER BY timestamp",
            (since_ts,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_signal_quality_trend(
        self, node_id: str, since: float | None = None
    ) -> list[dict]:
        """Get SNR trend for a specific node.

        Args:
            node_id: The mesh node ID.
            since: Only data after this Unix timestamp.

        Returns:
            List of {timestamp, snr} dicts.
        """
        if not self._db:
            return []

        since_ts = since or 0.0
        cursor = await self._db.execute(
            "SELECT timestamp, snr FROM node_telemetry WHERE node_id = ? AND snr IS NOT NULL AND timestamp > ? ORDER BY timestamp",
            (node_id, since_ts),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_all_nodes(self) -> list[dict]:
        """Get all known nodes with their metadata."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            "SELECT node_id, long_name, short_name, hw_model, role, first_seen, last_seen FROM nodes ORDER BY last_seen DESC"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_node_count(self) -> int:
        """Get total number of known nodes."""
        if not self._db:
            return 0

        cursor = await self._db.execute("SELECT COUNT(*) FROM nodes")
        row = await cursor.fetchone()
        return row[0] if row else 0
