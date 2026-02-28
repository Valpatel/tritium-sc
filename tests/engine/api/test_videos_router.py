# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the videos router — filename parsing, directory scanning,
channel detection, and stream validation.

Tests pure utility functions and API endpoints with mock filesystems.
"""
from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.videos import (
    parse_video_timestamp,
    parse_channel_number,
    find_channel_dir,
    find_date_dir,
    get_channel_dirs,
    get_date_dirs,
    VideoFile,
    DateFolder,
    ChannelInfo,
    router,
)


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestVideoModels:
    """Video file, date folder, and channel info models."""

    def test_video_file_required_fields(self):
        vf = VideoFile(
            channel=1, filename="test.mp4", path="ch01/2026-01-01/test.mp4",
            size=1024, date="2026-01-01",
        )
        assert vf.channel == 1
        assert vf.duration_seconds is None
        assert vf.timestamp is None

    def test_video_file_with_timestamp(self):
        vf = VideoFile(
            channel=1, filename="test.mp4", path="ch01/2026-01-01/test.mp4",
            size=1024, date="2026-01-01",
            timestamp=datetime(2026, 1, 1, 12, 0),
        )
        assert vf.timestamp.hour == 12

    def test_date_folder(self):
        df = DateFolder(channel=1, date="2026-01-15", video_count=5)
        assert df.video_count == 5

    def test_channel_info(self):
        ci = ChannelInfo(
            channel=1, name="Channel 1", path="/recordings/channel_01",
            date_count=30, total_videos=150,
        )
        assert ci.date_count == 30


# ---------------------------------------------------------------------------
# parse_video_timestamp
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestParseVideoTimestamp:
    """Parse timestamps from video filenames."""

    def test_fragment_format(self):
        ts = parse_video_timestamp("fragment_01_20260115120000.mp4")
        assert ts is not None
        assert ts.year == 2026
        assert ts.month == 1
        assert ts.day == 15
        assert ts.hour == 12

    def test_plain_timestamp(self):
        ts = parse_video_timestamp("20260215143022.mp4")
        assert ts is not None
        assert ts.hour == 14
        assert ts.minute == 30
        assert ts.second == 22

    def test_no_timestamp(self):
        ts = parse_video_timestamp("video.mp4")
        assert ts is None

    def test_short_number_no_match(self):
        ts = parse_video_timestamp("video_123456.mp4")
        assert ts is None  # Only 6 digits, need 14

    def test_invalid_timestamp_values(self):
        # 99991399999999 — month 13 is invalid
        ts = parse_video_timestamp("fragment_99991399999999.mp4")
        assert ts is None  # ValueError from strptime


# ---------------------------------------------------------------------------
# parse_channel_number
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestParseChannelNumber:
    """Extract channel numbers from directory names."""

    def test_channel_01(self):
        assert parse_channel_number("channel_01") == 1

    def test_channel_12(self):
        assert parse_channel_number("channel_12") == 12

    def test_ch1(self):
        assert parse_channel_number("ch1") == 1

    def test_channel1(self):
        assert parse_channel_number("channel1") == 1

    def test_no_number(self):
        assert parse_channel_number("recordings") == 0


# ---------------------------------------------------------------------------
# Directory Scanning Functions
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDirectoryScanning:
    """Test channel and date directory discovery with temp filesystems."""

    def test_get_channel_dirs_empty(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                result = get_channel_dirs()
                assert result == []

    def test_get_channel_dirs_with_channels(self):
        with tempfile.TemporaryDirectory() as td:
            # Create channel directories
            (Path(td) / "channel_01").mkdir()
            (Path(td) / "channel_02").mkdir()
            (Path(td) / "not_a_channel").mkdir()
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                result = get_channel_dirs()
                assert len(result) == 2
                assert result[0].name == "channel_01"
                assert result[1].name == "channel_02"

    def test_get_channel_dirs_various_formats(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "channel_01").mkdir()
            (Path(td) / "ch2").mkdir()
            (Path(td) / "channel3").mkdir()
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                result = get_channel_dirs()
                assert len(result) == 3

    def test_get_channel_dirs_nonexistent_path(self):
        with patch("app.routers.videos.settings") as mock_settings:
            mock_settings.recordings_path = Path("/tmp/nonexistent_recordings_dir")
            result = get_channel_dirs()
            assert result == []

    def test_find_channel_dir_found(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "channel_01").mkdir()
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                result = find_channel_dir(1)
                assert result is not None
                assert result.name == "channel_01"

    def test_find_channel_dir_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                result = find_channel_dir(99)
                assert result is None

    def test_get_date_dirs_flat(self):
        with tempfile.TemporaryDirectory() as td:
            ch = Path(td) / "channel_01"
            ch.mkdir()
            (ch / "2026-01-15").mkdir()
            (ch / "2026-01-16").mkdir()
            (ch / "not_a_date").mkdir()
            result = get_date_dirs(ch)
            assert len(result) == 2
            # Sorted reverse
            assert result[0][0] == "2026-01-16"
            assert result[1][0] == "2026-01-15"

    def test_get_date_dirs_nested(self):
        with tempfile.TemporaryDirectory() as td:
            ch = Path(td) / "channel_01"
            ch.mkdir()
            (ch / "2026" / "01" / "15").mkdir(parents=True)
            (ch / "2026" / "01" / "16").mkdir(parents=True)
            result = get_date_dirs(ch)
            assert len(result) == 2
            assert result[0][0] == "2026-01-16"

    def test_find_date_dir_flat(self):
        with tempfile.TemporaryDirectory() as td:
            ch = Path(td)
            (ch / "2026-01-15").mkdir()
            result = find_date_dir(ch, "2026-01-15")
            assert result is not None

    def test_find_date_dir_nested(self):
        with tempfile.TemporaryDirectory() as td:
            ch = Path(td)
            (ch / "2026" / "01" / "15").mkdir(parents=True)
            result = find_date_dir(ch, "2026-01-15")
            assert result is not None

    def test_find_date_dir_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            result = find_date_dir(Path(td), "2026-01-15")
            assert result is None


# ---------------------------------------------------------------------------
# Stream Validation (Security)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestStreamValidation:
    """Test directory traversal prevention and input validation."""

    def test_invalid_date_format(self):
        client = TestClient(_make_app())
        resp = client.get("/api/videos/stream/1/not-a-date/video.mp4")
        assert resp.status_code == 400
        assert "Invalid date format" in resp.json()["detail"]

    def test_invalid_file_type(self):
        with tempfile.TemporaryDirectory() as td:
            ch = Path(td) / "channel_01"
            ch.mkdir()
            date_dir = ch / "2026-01-15"
            date_dir.mkdir()
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                client = TestClient(_make_app())
                resp = client.get("/api/videos/stream/1/2026-01-15/video.exe")
                assert resp.status_code == 400
                assert "Invalid file type" in resp.json()["detail"]

    def test_directory_traversal_slash(self):
        client = TestClient(_make_app())
        # FastAPI won't even route this due to path params, but test the concept
        resp = client.get("/api/videos/stream/1/2026-01-15/..%2F..%2Fetc%2Fpasswd.mp4")
        # Should get 400 or 404, never 200
        assert resp.status_code in (400, 404, 422)

    def test_channel_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                client = TestClient(_make_app())
                resp = client.get("/api/videos/stream/99/2026-01-15/video.mp4")
                assert resp.status_code == 404


# ---------------------------------------------------------------------------
# List Videos API
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestListVideosAPI:
    """GET /api/videos/channels/{channel}/dates/{date}."""

    def test_list_videos_invalid_date(self):
        client = TestClient(_make_app())
        resp = client.get("/api/videos/channels/1/dates/invalid")
        assert resp.status_code == 400

    def test_list_videos_channel_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                client = TestClient(_make_app())
                resp = client.get("/api/videos/channels/99/dates/2026-01-15")
                assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Channels API
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestChannelsAPI:
    """GET /api/videos/channels."""

    def test_list_channels_empty(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                client = TestClient(_make_app())
                resp = client.get("/api/videos/channels")
                assert resp.status_code == 200
                assert resp.json() == []

    def test_list_channels_with_videos(self):
        with tempfile.TemporaryDirectory() as td:
            ch = Path(td) / "channel_01"
            ch.mkdir()
            date_dir = ch / "2026-01-15"
            date_dir.mkdir()
            (date_dir / "test_20260115120000.mp4").write_bytes(b"\x00" * 100)
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                client = TestClient(_make_app())
                resp = client.get("/api/videos/channels")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data) == 1
                assert data[0]["channel"] == 1
                assert data[0]["total_videos"] == 1


# ---------------------------------------------------------------------------
# Dates API
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDatesAPI:
    """GET /api/videos/channels/{channel}/dates."""

    def test_list_dates_channel_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                client = TestClient(_make_app())
                resp = client.get("/api/videos/channels/99/dates")
                assert resp.status_code == 404

    def test_list_dates_with_videos(self):
        with tempfile.TemporaryDirectory() as td:
            ch = Path(td) / "channel_01"
            ch.mkdir()
            d1 = ch / "2026-01-15"
            d1.mkdir()
            (d1 / "video.mp4").write_bytes(b"\x00" * 100)
            d2 = ch / "2026-01-16"
            d2.mkdir()
            # Empty date dir — no videos, should be excluded
            with patch("app.routers.videos.settings") as mock_settings:
                mock_settings.recordings_path = Path(td)
                client = TestClient(_make_app())
                resp = client.get("/api/videos/channels/1/dates")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data) == 1  # Only the one with videos
                assert data[0]["date"] == "2026-01-15"
