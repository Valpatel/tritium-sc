"""Unit tests for FrameAnalyzer — layered perception L0-L2."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from amy.perception import FrameAnalyzer, FrameMetrics, CameraPose, PoseEstimator
from amy.nodes.base import Position


@pytest.mark.unit
class TestFrameAnalyzer:
    """Tests for FrameAnalyzer.analyze() — pure OpenCV frame metrics."""

    def test_blank_image_low_complexity(self):
        """A solid-color image has near-zero edge complexity."""
        analyzer = FrameAnalyzer()
        blank = np.zeros((100, 100, 3), dtype=np.uint8)
        m = analyzer.analyze(blank)
        assert m.complexity < 0.01

    def test_blank_image_low_sharpness(self):
        """A solid-color image has near-zero sharpness."""
        analyzer = FrameAnalyzer()
        blank = np.zeros((100, 100, 3), dtype=np.uint8)
        m = analyzer.analyze(blank)
        assert m.sharpness < 1.0

    def test_patterned_image_high_sharpness(self):
        """Vertical stripes create strong edges — high sharpness."""
        analyzer = FrameAnalyzer()
        striped = np.zeros((100, 100, 3), dtype=np.uint8)
        striped[:, ::2] = 255
        m = analyzer.analyze(striped)
        assert m.sharpness > 100.0

    def test_patterned_image_high_complexity(self):
        """Wide stripes create many Canny edges — high complexity."""
        analyzer = FrameAnalyzer()
        striped = np.zeros((200, 200, 3), dtype=np.uint8)
        # 10px wide stripes — Canny detects the gradient transitions
        for i in range(0, 200, 20):
            striped[:, i:i+10] = 255
        m = analyzer.analyze(striped)
        assert m.complexity > 0.01

    def test_identical_frames_zero_motion(self):
        """Two identical frames produce zero motion score."""
        analyzer = FrameAnalyzer()
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        analyzer.analyze(frame)  # First frame — sets baseline
        m = analyzer.analyze(frame)  # Second — same content
        assert m.motion_score == 0.0
        assert m.motion_center is None

    def test_shifted_frame_positive_motion(self):
        """Shifted content between frames produces positive motion + centroid."""
        analyzer = FrameAnalyzer()
        frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
        frame1[20:40, 20:40] = 200  # White square top-left

        frame2 = np.zeros((100, 100, 3), dtype=np.uint8)
        frame2[60:80, 60:80] = 200  # White square bottom-right

        analyzer.analyze(frame1)
        m = analyzer.analyze(frame2)
        assert m.motion_score > 0.0
        assert m.motion_center is not None
        cx, cy = m.motion_center
        assert 0.0 <= cx <= 1.0
        assert 0.0 <= cy <= 1.0

    def test_dark_image_not_usable(self):
        """A nearly-black image fails the brightness usability check."""
        analyzer = FrameAnalyzer()
        dark = np.full((100, 100, 3), 5, dtype=np.uint8)
        m = analyzer.analyze(dark)
        assert m.brightness < 15.0
        assert m.is_usable is False

    def test_blurred_image_not_usable(self):
        """A heavily blurred image fails the sharpness usability check."""
        analyzer = FrameAnalyzer()
        # Start with a sharp image
        sharp = np.zeros((200, 200, 3), dtype=np.uint8)
        sharp[::4, :] = 255
        sharp[:, ::4] = 255
        # Blur very heavily — large kernel + high sigma
        blurred = cv2.GaussianBlur(sharp, (61, 61), 30)
        m = analyzer.analyze(blurred)
        assert m.sharpness < 25.0
        assert m.is_usable is False

    def test_bright_sharp_image_is_usable(self):
        """A bright, sharp image passes the usability check."""
        analyzer = FrameAnalyzer()
        img = np.full((100, 100, 3), 128, dtype=np.uint8)
        img[::2, :] = 200  # Add some edge content
        m = analyzer.analyze(img)
        assert m.brightness > 15.0
        assert m.sharpness > 25.0
        assert m.is_usable is True

    def test_first_frame_zero_motion(self):
        """First frame has no previous — motion is always zero."""
        analyzer = FrameAnalyzer()
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        m = analyzer.analyze(frame)
        assert m.motion_score == 0.0
        assert m.motion_center is None

    def test_returns_frame_metrics_dataclass(self):
        """analyze() returns a FrameMetrics dataclass with all fields."""
        analyzer = FrameAnalyzer()
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        m = analyzer.analyze(frame)
        assert isinstance(m, FrameMetrics)
        assert isinstance(m.sharpness, float)
        assert isinstance(m.brightness, float)
        assert isinstance(m.complexity, float)
        assert isinstance(m.motion_score, float)
        assert isinstance(m.is_usable, bool)


@pytest.mark.unit
class TestPoseEstimator:
    """Tests for PoseEstimator — PTZ position normalization + degree estimation."""

    def test_no_limits_returns_none_normalized(self):
        """Position without limits produces None for normalized values."""
        est = PoseEstimator()
        pos = Position(pan=50.0, tilt=10.0)
        pose = est.update(pos)
        assert pose.pan_normalized is None
        assert pose.tilt_normalized is None
        assert pose.pan_degrees is None
        assert pose.tilt_degrees is None
        assert pose.calibrated is False

    def test_pan_limits_normalize(self):
        """Position with pan limits produces normalized 0.0-1.0 value."""
        est = PoseEstimator()
        pos = Position(pan=50.0, tilt=0.0, pan_min=0.0, pan_max=100.0)
        pose = est.update(pos)
        assert pose.pan_normalized == pytest.approx(0.5)
        assert pose.pan_degrees == pytest.approx(0.0)  # center = 0 degrees
        assert pose.tilt_normalized is None  # tilt has no limits
        assert pose.calibrated is False  # only pan calibrated

    def test_at_left_limit(self):
        """At left limit: pan_normalized ~0.0, pan_degrees ~ -90."""
        est = PoseEstimator()
        pos = Position(pan=0.0, tilt=0.0, pan_min=0.0, pan_max=100.0)
        pose = est.update(pos)
        assert pose.pan_normalized == pytest.approx(0.0)
        assert pose.pan_degrees == pytest.approx(-90.0)

    def test_at_right_limit(self):
        """At right limit: pan_normalized ~1.0, pan_degrees ~ +90."""
        est = PoseEstimator()
        pos = Position(pan=100.0, tilt=0.0, pan_min=0.0, pan_max=100.0)
        pose = est.update(pos)
        assert pose.pan_normalized == pytest.approx(1.0)
        assert pose.pan_degrees == pytest.approx(90.0)

    def test_full_calibration(self):
        """Both axes with limits gives calibrated=True."""
        est = PoseEstimator()
        pos = Position(
            pan=50.0, tilt=25.0,
            pan_min=0.0, pan_max=100.0,
            tilt_min=0.0, tilt_max=50.0,
        )
        pose = est.update(pos)
        assert pose.calibrated is True
        assert pose.pan_normalized == pytest.approx(0.5)
        assert pose.tilt_normalized == pytest.approx(0.5)
        assert pose.pan_degrees == pytest.approx(0.0)
        assert pose.tilt_degrees == pytest.approx(0.0)

    def test_custom_degree_range(self):
        """Custom degree range is used for conversion."""
        est = PoseEstimator(pan_range_deg=360.0, tilt_range_deg=90.0)
        pos = Position(
            pan=100.0, tilt=50.0,
            pan_min=0.0, pan_max=100.0,
            tilt_min=0.0, tilt_max=50.0,
        )
        pose = est.update(pos)
        assert pose.pan_degrees == pytest.approx(180.0)  # (1.0 - 0.5) * 360
        assert pose.tilt_degrees == pytest.approx(45.0)   # (1.0 - 0.5) * 90

    def test_raw_values_always_present(self):
        """Raw pan/tilt values are always present regardless of calibration."""
        est = PoseEstimator()
        pos = Position(pan=42.0, tilt=7.5)
        pose = est.update(pos)
        assert pose.pan_raw == 42.0
        assert pose.tilt_raw == 7.5

    def test_pose_property_returns_latest(self):
        """The pose property returns the last computed CameraPose."""
        est = PoseEstimator()
        assert est.pose is None
        pos = Position(pan=10.0, tilt=5.0)
        est.update(pos)
        assert est.pose is not None
        assert est.pose.pan_raw == 10.0

    def test_clamps_to_zero_one(self):
        """Out-of-range position gets clamped to 0.0-1.0."""
        est = PoseEstimator()
        pos = Position(pan=-10.0, tilt=0.0, pan_min=0.0, pan_max=100.0)
        pose = est.update(pos)
        assert pose.pan_normalized == 0.0
