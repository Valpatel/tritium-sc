# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for IP camera auto-discovery from database.

Verifies that create_amy discovers IP cameras from SQLite Camera records
and creates IPCameraNode instances merged into the nodes dict.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from engine.nodes.ip_camera import IPCameraNode


# ---------------------------------------------------------------------------
# Helper: create a test SQLite database with Camera rows
# ---------------------------------------------------------------------------

def _create_test_db(db_path: str, cameras: list[dict]) -> None:
    """Create a cameras table with test data."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE cameras (
            id INTEGER PRIMARY KEY,
            channel INTEGER UNIQUE,
            name TEXT,
            rtsp_url TEXT,
            substream_url TEXT,
            enabled BOOLEAN DEFAULT 1,
            position_x REAL,
            position_y REAL,
            heading REAL,
            fov REAL,
            mount_height REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for cam in cameras:
        conn.execute(
            "INSERT INTO cameras (channel, name, rtsp_url, enabled) VALUES (?, ?, ?, ?)",
            (cam["channel"], cam["name"], cam.get("rtsp_url"), cam.get("enabled", 1)),
        )
    conn.commit()
    conn.close()


def _discover_ip_cameras_from_db(db_path: str) -> dict[str, IPCameraNode]:
    """Standalone discovery function for testing (mirrors amy/__init__.py logic)."""
    from amy import _discover_ip_cameras
    return _discover_ip_cameras(db_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestIPCameraDiscovery:
    """IP cameras auto-discovered from SQLite Camera table."""

    def test_discovers_cameras_with_rtsp_url(self, tmp_path):
        """Cameras with rtsp_url create IPCameraNode instances."""
        db = str(tmp_path / "test.db")
        _create_test_db(db, [
            {"channel": 1, "name": "Front Door", "rtsp_url": "rtsp://10.0.0.5:554/1"},
            {"channel": 2, "name": "Back Yard", "rtsp_url": "rtsp://10.0.0.5:554/2"},
        ])

        from amy import _discover_ip_cameras
        nodes = _discover_ip_cameras(db)

        assert len(nodes) == 2
        assert "ip-cam-1" in nodes
        assert "ip-cam-2" in nodes
        assert isinstance(nodes["ip-cam-1"], IPCameraNode)
        assert nodes["ip-cam-1"].rtsp_url == "rtsp://10.0.0.5:554/1"
        assert nodes["ip-cam-2"].name == "Back Yard"

    def test_disabled_cameras_skipped(self, tmp_path):
        """Cameras with enabled=False are not discovered."""
        db = str(tmp_path / "test.db")
        _create_test_db(db, [
            {"channel": 1, "name": "Active", "rtsp_url": "rtsp://x/1", "enabled": 1},
            {"channel": 2, "name": "Disabled", "rtsp_url": "rtsp://x/2", "enabled": 0},
        ])

        from amy import _discover_ip_cameras
        nodes = _discover_ip_cameras(db)

        assert len(nodes) == 1
        assert "ip-cam-1" in nodes
        assert "ip-cam-2" not in nodes

    def test_cameras_without_rtsp_skipped(self, tmp_path):
        """Cameras with NULL rtsp_url are not discovered."""
        db = str(tmp_path / "test.db")
        _create_test_db(db, [
            {"channel": 1, "name": "Has RTSP", "rtsp_url": "rtsp://x/1"},
            {"channel": 3, "name": "No RTSP", "rtsp_url": None},
        ])

        from amy import _discover_ip_cameras
        nodes = _discover_ip_cameras(db)

        assert len(nodes) == 1
        assert "ip-cam-1" in nodes

    def test_empty_database(self, tmp_path):
        """No cameras in database returns empty dict."""
        db = str(tmp_path / "test.db")
        _create_test_db(db, [])

        from amy import _discover_ip_cameras
        nodes = _discover_ip_cameras(db)

        assert nodes == {}

    def test_missing_database_returns_empty(self, tmp_path):
        """Non-existent database file returns empty dict (no crash)."""
        db = str(tmp_path / "nonexistent.db")

        from amy import _discover_ip_cameras
        nodes = _discover_ip_cameras(db)

        assert nodes == {}

    def test_node_ids_use_channel_number(self, tmp_path):
        """Node IDs are formatted as ip-cam-{channel}."""
        db = str(tmp_path / "test.db")
        _create_test_db(db, [
            {"channel": 5, "name": "Cam 5", "rtsp_url": "rtsp://x/5"},
            {"channel": 12, "name": "Cam 12", "rtsp_url": "rtsp://x/12"},
        ])

        from amy import _discover_ip_cameras
        nodes = _discover_ip_cameras(db)

        assert "ip-cam-5" in nodes
        assert "ip-cam-12" in nodes

    def test_cameras_have_correct_properties(self, tmp_path):
        """Discovered IPCameraNodes have camera=True, ptz=False."""
        db = str(tmp_path / "test.db")
        _create_test_db(db, [
            {"channel": 1, "name": "Test", "rtsp_url": "rtsp://x/1"},
        ])

        from amy import _discover_ip_cameras
        nodes = _discover_ip_cameras(db)

        node = nodes["ip-cam-1"]
        assert node.has_camera is True
        assert node.has_ptz is False
        assert node.has_mic is False
        assert node.has_speaker is False
