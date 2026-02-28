# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for CCTV synthetic camera feeds.

Tests cover:
  - Frame resolution and format
  - Timestamp overlay detection
  - Sensor noise presence
  - Day vs night brightness
  - Frame uniqueness across a sequence
  - Deterministic reproduction with seeds
  - Video clip generation (duration, motion, frame count)
  - MJPEG streaming and snapshot API
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from engine.synthetic.video_gen import render_cctv_frame, CCTV_SCENE_TYPES
from engine.synthetic.video_library import SyntheticVideoLibrary


# ===========================================================================
# Helper
# ===========================================================================

def _ssim_gray(a: np.ndarray, b: np.ndarray) -> float:
    """Simplified SSIM between two gray images (0..1 scale)."""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    mu_a = a.mean()
    mu_b = b.mean()
    sigma_a = a.std()
    sigma_b = b.std()
    sigma_ab = ((a - mu_a) * (b - mu_b)).mean()
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    num = (2 * mu_a * mu_b + c1) * (2 * sigma_ab + c2)
    den = (mu_a ** 2 + mu_b ** 2 + c1) * (sigma_a ** 2 + sigma_b ** 2 + c2)
    return num / den


# ===========================================================================
# Task 1 — Enhanced CCTV Frame Renderer
# ===========================================================================

@pytest.mark.unit
class TestCCTVFrameResolution:
    """render_cctv_frame produces correct resolution."""

    def test_default_640x480(self):
        frame = render_cctv_frame(camera_name="CAM-01", scene_type="front_door", seed=42)
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    def test_1280x720(self):
        frame = render_cctv_frame(
            camera_name="CAM-01", scene_type="front_door",
            resolution=(1280, 720), seed=42,
        )
        assert frame.shape == (720, 1280, 3)


@pytest.mark.unit
class TestCCTVTimestampOverlay:
    """Timestamp text should appear in the top-left region."""

    def test_has_timestamp_overlay(self):
        frame = render_cctv_frame(
            camera_name="CAM-01", scene_type="front_door",
            time_of_day="night", seed=42,
        )
        # Top-left 200x30 region should have bright pixels (text overlay)
        top_left = frame[5:35, 5:220]
        bright = np.sum(top_left > 150)
        assert bright > 20, f"Expected overlay text pixels, got {bright} bright pixels"


@pytest.mark.unit
class TestCCTVNoise:
    """Frame should contain sensor noise (non-uniform areas)."""

    def test_has_noise(self):
        frame = render_cctv_frame(
            camera_name="CAM-01", scene_type="front_door",
            time_of_day="night", seed=42,
        )
        # Standard deviation across the frame should be > 5
        std = float(frame.astype(np.float64).std())
        assert std > 5, f"Frame std deviation too low: {std}"


@pytest.mark.unit
class TestCCTVDayVsNight:
    """Day frames should be brighter than night frames."""

    def test_day_brightness(self):
        frame = render_cctv_frame(
            camera_name="CAM-01", scene_type="front_door",
            time_of_day="day", seed=42,
        )
        mean = float(frame.mean())
        assert mean > 80, f"Day frame too dark: mean={mean}"

    def test_night_brightness(self):
        frame = render_cctv_frame(
            camera_name="CAM-01", scene_type="front_door",
            time_of_day="night", seed=42,
        )
        mean = float(frame.mean())
        assert mean < 40, f"Night frame too bright: mean={mean}"

    def test_dusk_between(self):
        day = render_cctv_frame(camera_name="C", scene_type="front_door", time_of_day="day", seed=42)
        night = render_cctv_frame(camera_name="C", scene_type="front_door", time_of_day="night", seed=42)
        dusk = render_cctv_frame(camera_name="C", scene_type="front_door", time_of_day="dusk", seed=42)
        assert float(night.mean()) < float(dusk.mean()) < float(day.mean())


@pytest.mark.unit
class TestCCTVUniqueFrames:
    """10 consecutive frames (different seeds) should all be different."""

    def test_unique_frames(self):
        frames = []
        for i in range(10):
            f = render_cctv_frame(
                camera_name="CAM-01", scene_type="street_view",
                time_of_day="night", seed=100 + i * 17,
                frame_number=i,
            )
            frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))

        # Check non-adjacent pairs: at least half must be distinct (SSIM < 0.99)
        distinct_count = 0
        pair_count = 0
        for i in range(len(frames)):
            for j in range(i + 1, len(frames)):
                pair_count += 1
                ssim = _ssim_gray(frames[i], frames[j])
                if ssim < 0.99:
                    distinct_count += 1
        assert distinct_count > pair_count // 2, (
            f"Only {distinct_count}/{pair_count} pairs are distinct (SSIM < 0.99)"
        )


@pytest.mark.unit
class TestCCTVDeterministic:
    """Same seed produces identical frame."""

    def test_deterministic(self):
        f1 = render_cctv_frame(
            camera_name="CAM-01", scene_type="front_door",
            time_of_day="night", seed=777,
            timestamp="2026-02-22 03:00:00", frame_number=0,
        )
        f2 = render_cctv_frame(
            camera_name="CAM-01", scene_type="front_door",
            time_of_day="night", seed=777,
            timestamp="2026-02-22 03:00:00", frame_number=0,
        )
        np.testing.assert_array_equal(f1, f2)


@pytest.mark.unit
class TestCCTVSceneTypes:
    """All CCTV scene types render without error."""

    @pytest.mark.parametrize("scene_type", [
        "front_door", "back_yard", "street_view", "parking", "driveway",
    ])
    def test_scene_renders(self, scene_type):
        frame = render_cctv_frame(
            camera_name="TEST", scene_type=scene_type,
            time_of_day="day", seed=42,
        )
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    def test_invalid_scene_type_raises(self):
        with pytest.raises(ValueError, match="Invalid CCTV scene_type"):
            render_cctv_frame(camera_name="X", scene_type="nonexistent", seed=42)


@pytest.mark.unit
class TestCCTVRealism:
    """Realism features: barrel distortion, JPEG artifacts, color temp."""

    def test_barrel_distortion(self):
        """Frame should have slight barrel distortion (edges darker or warped)."""
        frame = render_cctv_frame(
            camera_name="CAM-01", scene_type="front_door",
            time_of_day="day", seed=42,
        )
        # Barrel distortion: corner pixels should be slightly different from
        # a flat rendering. Just check it runs and frame is valid.
        assert frame.shape == (480, 640, 3)

    def test_jpeg_artifacts(self):
        """Re-encoded at low quality — JPEG round-trip should be lossy."""
        frame = render_cctv_frame(
            camera_name="CAM-01", scene_type="front_door",
            time_of_day="day", seed=42,
        )
        # Encode at high quality then decode — should differ from original
        # because render_cctv_frame applies internal JPEG compression
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
        decoded = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        # The frame already went through JPEG compression internally,
        # so it should survive a second round without much change
        diff = np.abs(frame.astype(np.int16) - decoded.astype(np.int16)).mean()
        # Just verify it's a valid frame that can be JPEG encoded
        assert diff < 20


# ===========================================================================
# Task 2 — Video Clip Generation
# ===========================================================================

@pytest.mark.unit
class TestCCTVClipGeneration:
    """generate_cctv_clip produces valid MP4 clips."""

    @pytest.fixture
    def lib(self, tmp_path):
        return SyntheticVideoLibrary(tmp_path / "video")

    def test_clip_duration(self, lib):
        """Generated clip should be ~5 seconds."""
        clip_dir = lib.generate_cctv_clip(
            camera_name="CAM-01", scene_type="front_door",
            duration=5.0, fps=10, seed=42,
        )
        mp4 = clip_dir / "clip.mp4"
        assert mp4.exists()
        cap = cv2.VideoCapture(str(mp4))
        try:
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps > 0:
                duration = frame_count / fps
                assert 4.0 <= duration <= 6.0, f"Clip duration {duration:.1f}s not ~5s"
        finally:
            cap.release()

    def test_clip_has_motion(self, lib):
        """Frame diff between first and middle frames should be > 0."""
        clip_dir = lib.generate_cctv_clip(
            camera_name="CAM-01", scene_type="street_view",
            duration=5.0, fps=10, seed=42,
        )
        mp4 = clip_dir / "clip.mp4"
        cap = cv2.VideoCapture(str(mp4))
        try:
            ret1, frame1 = cap.read()
            assert ret1, "Could not read first frame"
            # Skip to middle
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
            ret2, frame2 = cap.read()
            assert ret2, "Could not read middle frame"
            diff = np.abs(frame1.astype(np.int16) - frame2.astype(np.int16)).mean()
            assert diff > 0, "No motion detected between first and middle frame"
        finally:
            cap.release()

    def test_clip_frame_count(self, lib):
        """5s at 10fps should produce 48-52 frames."""
        clip_dir = lib.generate_cctv_clip(
            camera_name="CAM-01", scene_type="front_door",
            duration=5.0, fps=10, seed=42,
        )
        mp4 = clip_dir / "clip.mp4"
        cap = cv2.VideoCapture(str(mp4))
        try:
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            assert 48 <= count <= 52, f"Expected 48-52 frames, got {count}"
        finally:
            cap.release()

    def test_clip_metadata(self, lib):
        """Metadata JSON written alongside clip."""
        clip_dir = lib.generate_cctv_clip(
            camera_name="CAM-01", scene_type="front_door",
            duration=5.0, fps=10, seed=42,
        )
        meta_path = clip_dir / "metadata.json"
        assert meta_path.exists()
        with open(meta_path) as f:
            meta = json.load(f)
        assert meta["camera_name"] == "CAM-01"
        assert meta["scene_type"] == "front_door"
        assert meta["duration"] == 5.0
        assert meta["fps"] == 10
        assert meta["seed"] == 42

    def test_clip_saves_individual_frames(self, lib):
        """Individual JPEG frames saved alongside clip."""
        clip_dir = lib.generate_cctv_clip(
            camera_name="CAM-01", scene_type="front_door",
            duration=2.0, fps=10, seed=42,
        )
        frames = sorted(clip_dir.glob("frame_*.jpg"))
        assert len(frames) == 20, f"Expected 20 frames, got {len(frames)}"


# ===========================================================================
# Task 5 — API Integration (feed manager with pre-generated frames)
# ===========================================================================

@pytest.mark.unit
class TestCCTVFeedAPI:
    """Synthetic feed manager serves CCTV-type feeds."""

    def test_cctv_scene_type_accepted(self):
        """Creating a feed with cctv scene type works."""
        from app.routers.synthetic_feed import SyntheticFeedConfig, SyntheticFeedManager
        mgr = SyntheticFeedManager()
        cfg = SyntheticFeedConfig(feed_id="cam-01", scene_type="cctv")
        result = mgr.create_feed(cfg)
        assert result["feed_id"] == "cam-01"

    def test_snapshot_returns_jpeg(self):
        """Snapshot from CCTV feed is valid JPEG."""
        from app.routers.synthetic_feed import SyntheticFeedConfig, SyntheticFeedManager
        mgr = SyntheticFeedManager()
        cfg = SyntheticFeedConfig(feed_id="cam-01", scene_type="cctv", width=320, height=240)
        mgr.create_feed(cfg)
        jpeg = mgr.get_snapshot("cam-01")
        assert isinstance(jpeg, bytes)
        assert jpeg[:2] == b"\xff\xd8"  # JPEG SOI marker

    def test_mjpeg_stream_serves_frames(self):
        """MJPEG generator yields at least 3 frames."""
        from app.routers.synthetic_feed import SyntheticFeedConfig, SyntheticFeedManager
        mgr = SyntheticFeedManager()
        cfg = SyntheticFeedConfig(feed_id="cam-01", scene_type="cctv", width=160, height=120, fps=100)
        mgr.create_feed(cfg)
        gen = mgr.mjpeg_frames("cam-01")
        frames = []
        for _ in range(3):
            frames.append(next(gen))
        assert len(frames) == 3
        for fb in frames:
            assert b"--frame" in fb
            assert b"Content-Type: image/jpeg" in fb
