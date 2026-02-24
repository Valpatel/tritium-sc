"""Unit tests for SyntheticFeedManager and feed dataclasses.

Tests feed CRUD, config dataclass, Pydantic models. Frame generation
tests require OpenCV + video_gen which are available in the venv.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.routers.synthetic_feed import (
    SyntheticFeedConfig,
    SyntheticFeedManager,
    CreateFeedRequest,
    FeedResponse,
)


# ===========================================================================
# SyntheticFeedConfig Dataclass
# ===========================================================================

@pytest.mark.unit
class TestSyntheticFeedConfig:
    """SyntheticFeedConfig — feed configuration dataclass."""

    def test_construction(self):
        cfg = SyntheticFeedConfig(feed_id="test-1")
        assert cfg.feed_id == "test-1"

    def test_defaults(self):
        cfg = SyntheticFeedConfig(feed_id="t")
        assert cfg.scene_type == "bird_eye"
        assert cfg.fps == 10
        assert cfg.width == 640
        assert cfg.height == 480

    def test_custom(self):
        cfg = SyntheticFeedConfig(
            feed_id="custom", scene_type="battle", fps=30,
            width=1280, height=720,
        )
        assert cfg.scene_type == "battle"
        assert cfg.fps == 30
        assert cfg.width == 1280

    def test_to_dict(self):
        cfg = SyntheticFeedConfig(feed_id="t")
        d = cfg.to_dict()
        assert d["feed_id"] == "t"
        assert d["scene_type"] == "bird_eye"
        assert isinstance(d, dict)


# ===========================================================================
# CreateFeedRequest Pydantic Model
# ===========================================================================

@pytest.mark.unit
class TestCreateFeedRequest:
    """CreateFeedRequest — Pydantic request model."""

    def test_minimal(self):
        r = CreateFeedRequest(feed_id="cam-1")
        assert r.feed_id == "cam-1"
        assert r.scene_type == "bird_eye"

    def test_full(self):
        r = CreateFeedRequest(
            feed_id="cam-1", scene_type="street_cam",
            fps=15, width=800, height=600,
        )
        assert r.scene_type == "street_cam"
        assert r.fps == 15

    def test_missing_feed_id_raises(self):
        with pytest.raises(ValidationError):
            CreateFeedRequest()


# ===========================================================================
# FeedResponse Pydantic Model
# ===========================================================================

@pytest.mark.unit
class TestFeedResponse:
    """FeedResponse — Pydantic response model."""

    def test_construction(self):
        r = FeedResponse(
            feed_id="cam-1", scene_type="bird_eye", fps=10,
            width=640, height=480, frame_count=0, created_at="2026-02-20T00:00:00",
        )
        assert r.feed_id == "cam-1"
        assert r.frame_count == 0


# ===========================================================================
# SyntheticFeedManager — CRUD
# ===========================================================================

@pytest.mark.unit
class TestSyntheticFeedManagerCRUD:
    """SyntheticFeedManager — create, list, get, delete."""

    def test_starts_empty(self):
        mgr = SyntheticFeedManager()
        assert mgr.list_feeds() == []

    def test_create_feed(self):
        mgr = SyntheticFeedManager()
        cfg = SyntheticFeedConfig(feed_id="cam-1")
        result = mgr.create_feed(cfg)
        assert result["feed_id"] == "cam-1"
        assert result["frame_count"] == 0

    def test_create_duplicate_raises(self):
        mgr = SyntheticFeedManager()
        cfg = SyntheticFeedConfig(feed_id="cam-1")
        mgr.create_feed(cfg)
        with pytest.raises(ValueError, match="already exists"):
            mgr.create_feed(cfg)

    def test_list_feeds(self):
        mgr = SyntheticFeedManager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam-1"))
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam-2"))
        feeds = mgr.list_feeds()
        assert len(feeds) == 2
        ids = {f["feed_id"] for f in feeds}
        assert "cam-1" in ids
        assert "cam-2" in ids

    def test_get_feed_exists(self):
        mgr = SyntheticFeedManager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam-1"))
        feed = mgr.get_feed("cam-1")
        assert feed is not None
        assert feed["feed_id"] == "cam-1"

    def test_get_feed_missing(self):
        mgr = SyntheticFeedManager()
        assert mgr.get_feed("nonexistent") is None

    def test_delete_feed(self):
        mgr = SyntheticFeedManager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam-1"))
        mgr.delete_feed("cam-1")
        assert mgr.list_feeds() == []

    def test_delete_missing_raises(self):
        mgr = SyntheticFeedManager()
        with pytest.raises(KeyError, match="not found"):
            mgr.delete_feed("nonexistent")

    def test_create_invalid_scene_type_defaults(self):
        mgr = SyntheticFeedManager()
        cfg = SyntheticFeedConfig(feed_id="cam-1", scene_type="invalid_scene")
        result = mgr.create_feed(cfg)
        assert result["scene_type"] == "bird_eye"

    def test_feed_has_created_at(self):
        mgr = SyntheticFeedManager()
        result = mgr.create_feed(SyntheticFeedConfig(feed_id="cam-1"))
        assert "created_at" in result
        assert len(result["created_at"]) > 0

    def test_feed_metadata_fields(self):
        mgr = SyntheticFeedManager()
        cfg = SyntheticFeedConfig(feed_id="cam-1", fps=15, width=800, height=600)
        result = mgr.create_feed(cfg)
        assert result["fps"] == 15
        assert result["width"] == 800
        assert result["height"] == 600


# ===========================================================================
# SyntheticFeedManager — Frame Generation
# ===========================================================================

@pytest.mark.unit
class TestSyntheticFeedManagerFrames:
    """SyntheticFeedManager — frame generation and snapshots."""

    def test_generate_frame(self):
        import numpy as np
        mgr = SyntheticFeedManager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam-1", width=320, height=240))
        frame = mgr.generate_frame("cam-1")
        assert isinstance(frame, np.ndarray)
        assert frame.shape == (240, 320, 3)
        assert frame.dtype == np.uint8

    def test_generate_frame_increments_count(self):
        mgr = SyntheticFeedManager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam-1"))
        mgr.generate_frame("cam-1")
        mgr.generate_frame("cam-1")
        feed = mgr.get_feed("cam-1")
        assert feed["frame_count"] == 2

    def test_generate_frame_missing_raises(self):
        mgr = SyntheticFeedManager()
        with pytest.raises(KeyError):
            mgr.generate_frame("nonexistent")

    def test_get_snapshot_returns_jpeg(self):
        mgr = SyntheticFeedManager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam-1", width=320, height=240))
        jpeg = mgr.get_snapshot("cam-1")
        assert isinstance(jpeg, bytes)
        assert len(jpeg) > 100
        assert jpeg[:2] == b"\xff\xd8"  # JPEG magic bytes

    def test_get_snapshot_missing_raises(self):
        mgr = SyntheticFeedManager()
        with pytest.raises(KeyError):
            mgr.get_snapshot("nonexistent")

    def test_different_scene_types(self):
        import numpy as np
        mgr = SyntheticFeedManager()
        for scene in ["bird_eye", "street_cam", "battle", "neighborhood"]:
            mgr.create_feed(SyntheticFeedConfig(feed_id=f"cam-{scene}", scene_type=scene, width=320, height=240))
            frame = mgr.generate_frame(f"cam-{scene}")
            assert isinstance(frame, np.ndarray)
            assert frame.shape == (240, 320, 3)

    def test_mjpeg_frames_generator(self):
        mgr = SyntheticFeedManager()
        mgr.create_feed(SyntheticFeedConfig(feed_id="cam-1", width=160, height=120, fps=10))
        gen = mgr.mjpeg_frames("cam-1")
        frame_bytes = next(gen)
        assert b"--frame" in frame_bytes
        assert b"Content-Type: image/jpeg" in frame_bytes

    def test_mjpeg_missing_raises(self):
        mgr = SyntheticFeedManager()
        with pytest.raises(KeyError):
            gen = mgr.mjpeg_frames("nonexistent")
            next(gen)
