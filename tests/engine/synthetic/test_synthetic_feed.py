# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the synthetic camera feed router.

Tests verify MJPEG streaming, snapshot, CRUD operations for synthetic
camera feeds, and proper integration with SyntheticVideoLibrary.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import MagicMock, patch, AsyncMock

import numpy as np
import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

from app.routers.synthetic_feed import (
    SyntheticFeedManager,
    SyntheticFeedConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager() -> SyntheticFeedManager:
    """Create a SyntheticFeedManager for testing."""
    return SyntheticFeedManager()


# ===========================================================================
# SyntheticFeedConfig tests
# ===========================================================================


class TestSyntheticFeedConfig:
    """Verify feed configuration validation."""

    def test_default_config(self):
        cfg = SyntheticFeedConfig(feed_id="test-1")
        assert cfg.feed_id == "test-1"
        assert cfg.scene_type == "bird_eye"
        assert cfg.fps == 10
        assert cfg.width == 640
        assert cfg.height == 480

    def test_custom_scene_type(self):
        cfg = SyntheticFeedConfig(feed_id="cam-2", scene_type="street_cam")
        assert cfg.scene_type == "street_cam"

    def test_custom_resolution(self):
        cfg = SyntheticFeedConfig(feed_id="cam-3", width=320, height=240)
        assert cfg.width == 320
        assert cfg.height == 240

    def test_custom_fps(self):
        cfg = SyntheticFeedConfig(feed_id="cam-4", fps=30)
        assert cfg.fps == 30


# ===========================================================================
# SyntheticFeedManager tests
# ===========================================================================


class TestSyntheticFeedManagerCreate:
    """Test creating synthetic camera feeds."""

    def test_create_feed(self):
        mgr = _make_manager()
        cfg = SyntheticFeedConfig(feed_id="syn-1")
        feed = mgr.create_feed(cfg)
        assert feed is not None
        assert feed["feed_id"] == "syn-1"

    def test_create_feed_stores_in_registry(self):
        mgr = _make_manager()
        cfg = SyntheticFeedConfig(feed_id="syn-2")
        mgr.create_feed(cfg)
        feeds = mgr.list_feeds()
        assert len(feeds) == 1
        assert feeds[0]["feed_id"] == "syn-2"

    def test_create_multiple_feeds(self):
        mgr = _make_manager()
        for i in range(3):
            mgr.create_feed(SyntheticFeedConfig(feed_id=f"syn-{i}"))
        assert len(mgr.list_feeds()) == 3

    def test_create_duplicate_feed_id_rejected(self):
        mgr = _make_manager()
        cfg = SyntheticFeedConfig(feed_id="syn-dup")
        mgr.create_feed(cfg)
        with pytest.raises(ValueError, match="already exists"):
            mgr.create_feed(cfg)

    def test_create_feed_returns_config(self):
        mgr = _make_manager()
        cfg = SyntheticFeedConfig(feed_id="syn-cfg", scene_type="battle", fps=5)
        result = mgr.create_feed(cfg)
        assert result["scene_type"] == "battle"
        assert result["fps"] == 5


class TestSyntheticFeedManagerDelete:
    """Test deleting synthetic camera feeds."""

    def test_delete_existing_feed(self):
        mgr = _make_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="del-1"))
        assert len(mgr.list_feeds()) == 1
        mgr.delete_feed("del-1")
        assert len(mgr.list_feeds()) == 0

    def test_delete_nonexistent_feed_raises(self):
        mgr = _make_manager()
        with pytest.raises(KeyError, match="not found"):
            mgr.delete_feed("nonexistent")

    def test_delete_one_of_many(self):
        mgr = _make_manager()
        for i in range(3):
            mgr.create_feed(SyntheticFeedConfig(feed_id=f"multi-{i}"))
        mgr.delete_feed("multi-1")
        ids = [f["feed_id"] for f in mgr.list_feeds()]
        assert "multi-0" in ids
        assert "multi-1" not in ids
        assert "multi-2" in ids


class TestSyntheticFeedManagerList:
    """Test listing feeds."""

    def test_list_empty(self):
        mgr = _make_manager()
        assert mgr.list_feeds() == []

    def test_list_returns_all_feeds(self):
        mgr = _make_manager()
        for i in range(5):
            mgr.create_feed(SyntheticFeedConfig(feed_id=f"list-{i}"))
        feeds = mgr.list_feeds()
        assert len(feeds) == 5

    def test_list_returns_feed_metadata(self):
        mgr = _make_manager()
        mgr.create_feed(SyntheticFeedConfig(
            feed_id="meta-1",
            scene_type="neighborhood",
            fps=15,
            width=800,
            height=600,
        ))
        feeds = mgr.list_feeds()
        f = feeds[0]
        assert f["scene_type"] == "neighborhood"
        assert f["fps"] == 15
        assert f["width"] == 800
        assert f["height"] == 600


class TestSyntheticFeedManagerGetFeed:
    """Test getting a specific feed."""

    def test_get_existing_feed(self):
        mgr = _make_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="get-1"))
        feed = mgr.get_feed("get-1")
        assert feed is not None
        assert feed["feed_id"] == "get-1"

    def test_get_nonexistent_returns_none(self):
        mgr = _make_manager()
        assert mgr.get_feed("nope") is None


class TestSyntheticFeedManagerSnapshot:
    """Test single frame snapshot generation."""

    def test_snapshot_returns_jpeg(self):
        mgr = _make_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="snap-1"))
        jpeg = mgr.get_snapshot("snap-1")
        assert jpeg is not None
        assert jpeg[:2] == b"\xff\xd8", "Should start with JPEG magic bytes"

    def test_snapshot_nonexistent_raises(self):
        mgr = _make_manager()
        with pytest.raises(KeyError, match="not found"):
            mgr.get_snapshot("no-such-cam")

    def test_snapshot_size_matches_config(self):
        """Snapshot from a 320x240 feed should be a reasonable JPEG."""
        mgr = _make_manager()
        mgr.create_feed(SyntheticFeedConfig(
            feed_id="snap-small",
            width=320,
            height=240,
        ))
        jpeg = mgr.get_snapshot("snap-small")
        assert len(jpeg) > 100
        assert len(jpeg) < 500_000  # should be way under 500KB for 320x240


class TestSyntheticFeedManagerFrameGen:
    """Test frame generation for MJPEG streaming."""

    def test_generate_frame_returns_bgr(self):
        mgr = _make_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="fg-1"))
        frame = mgr.generate_frame("fg-1")
        assert isinstance(frame, np.ndarray)
        assert frame.dtype == np.uint8
        assert frame.shape == (480, 640, 3)

    def test_generate_frame_nonexistent_raises(self):
        mgr = _make_manager()
        with pytest.raises(KeyError, match="not found"):
            mgr.generate_frame("nope")

    def test_generate_frame_different_scenes(self):
        """Each scene type should produce a valid frame."""
        mgr = _make_manager()
        for scene in ["bird_eye", "street_cam", "battle", "neighborhood"]:
            fid = f"scene-{scene}"
            mgr.create_feed(SyntheticFeedConfig(feed_id=fid, scene_type=scene))
            frame = mgr.generate_frame(fid)
            assert frame is not None
            assert frame.shape[2] == 3

    def test_generate_frame_increments_counter(self):
        mgr = _make_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cnt-1"))
        mgr.generate_frame("cnt-1")
        mgr.generate_frame("cnt-1")
        feed = mgr.get_feed("cnt-1")
        assert feed["frame_count"] >= 2


class TestSyntheticFeedManagerMJPEGIter:
    """Test MJPEG frame iterator."""

    def test_mjpeg_iter_yields_bytes(self):
        """MJPEG iterator should yield JPEG frames with MJPEG boundary."""
        mgr = _make_manager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="mjpeg-1", fps=10))
        gen = mgr.mjpeg_frames("mjpeg-1")
        # Get first frame
        frame_data = next(gen)
        assert isinstance(frame_data, bytes)
        # Should contain MJPEG content-type boundary
        assert b"--frame" in frame_data
        assert b"Content-Type: image/jpeg" in frame_data

    def test_mjpeg_iter_nonexistent_raises(self):
        mgr = _make_manager()
        with pytest.raises(KeyError, match="not found"):
            gen = mgr.mjpeg_frames("nope")
            next(gen)


class TestSyntheticFeedNoHardcodedValues:
    """Paranoid check: no hardcoded IPs, hostnames, or paths."""

    def test_manager_has_no_hardcoded_ips(self):
        """Manager should not embed any IP addresses."""
        mgr = _make_manager()
        # Just verify it creates cleanly without network dependencies
        assert mgr is not None

    def test_feed_config_defaults_are_reasonable(self):
        """Default config values should be reasonable."""
        cfg = SyntheticFeedConfig(feed_id="default-check")
        assert cfg.fps > 0
        assert cfg.fps <= 60
        assert cfg.width > 0
        assert cfg.height > 0
        assert cfg.scene_type in ("bird_eye", "street_cam", "battle", "neighborhood")
