"""Layered perception — cheap OpenCV frame analysis before expensive ML.

L0: Quality gate (sharpness, brightness) — reject blurred/dark frames
L1: Complexity (edge density) — novelty score for interesting areas
L2: Motion (frame diff) — reflex tracking, event trigger

Pure OpenCV/numpy — no ML models, no heavy imports.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2
import numpy as np

from .nodes.base import Position


@dataclass
class CameraPose:
    """Estimated camera pose from raw position + discovered limits."""

    pan_normalized: float | None    # 0.0 (left limit) to 1.0 (right limit)
    tilt_normalized: float | None   # 0.0 (down limit) to 1.0 (up limit)
    pan_degrees: float | None       # Estimated degrees from center
    tilt_degrees: float | None      # Estimated degrees from center
    pan_raw: float                  # Raw position value (arbitrary units)
    tilt_raw: float                 # Raw position value
    pan_limits: tuple[float, float] | None   # (min, max) if both discovered
    tilt_limits: tuple[float, float] | None
    calibrated: bool                # True when both axes have both limits


class PoseEstimator:
    """Normalize raw PTZ position to 0.0-1.0 and estimate degrees."""

    def __init__(self, pan_range_deg: float = 180.0, tilt_range_deg: float = 72.0) -> None:
        self._pan_range_deg = pan_range_deg
        self._tilt_range_deg = tilt_range_deg
        self._lock = threading.Lock()
        self._pose: CameraPose | None = None

    @property
    def pose(self) -> CameraPose | None:
        with self._lock:
            return self._pose

    def update(self, position: Position) -> CameraPose:
        """Convert raw Position into estimated CameraPose."""
        pan_limits = None
        tilt_limits = None
        pan_norm: float | None = None
        tilt_norm: float | None = None
        pan_deg: float | None = None
        tilt_deg: float | None = None

        if position.pan_min is not None and position.pan_max is not None:
            pan_limits = (position.pan_min, position.pan_max)
            span = position.pan_max - position.pan_min
            if span > 0:
                pan_norm = (position.pan - position.pan_min) / span
                pan_norm = max(0.0, min(1.0, pan_norm))
                pan_deg = (pan_norm - 0.5) * self._pan_range_deg

        if position.tilt_min is not None and position.tilt_max is not None:
            tilt_limits = (position.tilt_min, position.tilt_max)
            span = position.tilt_max - position.tilt_min
            if span > 0:
                tilt_norm = (position.tilt - position.tilt_min) / span
                tilt_norm = max(0.0, min(1.0, tilt_norm))
                tilt_deg = (tilt_norm - 0.5) * self._tilt_range_deg

        calibrated = pan_limits is not None and tilt_limits is not None

        pose = CameraPose(
            pan_normalized=pan_norm,
            tilt_normalized=tilt_norm,
            pan_degrees=pan_deg,
            tilt_degrees=tilt_deg,
            pan_raw=position.pan,
            tilt_raw=position.tilt,
            pan_limits=pan_limits,
            tilt_limits=tilt_limits,
            calibrated=calibrated,
        )
        with self._lock:
            self._pose = pose
        return pose


@dataclass
class FrameMetrics:
    """Results from L0-L2 frame analysis."""

    sharpness: float            # Laplacian variance (>50 sharp, <20 blurred)
    brightness: float           # Mean pixel intensity (0-255)
    complexity: float           # Edge density (0.0-1.0, wall ~0.02, busy ~0.15+)
    motion_score: float         # Fraction of pixels changed (0.0-1.0)
    motion_center: tuple[float, float] | None  # Normalized (cx, cy) of motion
    is_usable: bool             # Quick composite: sharp + bright enough


class FrameAnalyzer:
    """Runs L0-L2 perception in a single analyze() call (~5ms total)."""

    # L0 thresholds
    MIN_SHARPNESS = 25.0
    MIN_BRIGHTNESS = 15.0

    # L2 motion diff threshold (pixel intensity change to count as motion)
    MOTION_THRESH = 30

    def __init__(self) -> None:
        self._prev_gray: np.ndarray | None = None

    def analyze(self, frame: np.ndarray) -> FrameMetrics:
        """Run all L0-L2 analysis on a BGR frame.

        Returns FrameMetrics with sharpness, brightness, complexity,
        motion score, motion centroid, and usability flag.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # L0: Quality — sharpness (Laplacian variance) + brightness
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(np.mean(gray))

        # L1: Complexity — Canny edge pixel ratio
        edges = cv2.Canny(gray, 50, 150)
        complexity = float(np.count_nonzero(edges)) / edges.size

        # L2: Motion — absdiff against previous frame
        motion_score = 0.0
        motion_center: tuple[float, float] | None = None

        if self._prev_gray is not None and self._prev_gray.shape == gray.shape:
            diff = cv2.absdiff(gray, self._prev_gray)
            _, motion_mask = cv2.threshold(diff, self.MOTION_THRESH, 255, cv2.THRESH_BINARY)
            motion_pixels = np.count_nonzero(motion_mask)
            motion_score = motion_pixels / motion_mask.size

            if motion_pixels > 0:
                ys, xs = np.nonzero(motion_mask)
                h, w = gray.shape
                cx = float(np.mean(xs)) / w
                cy = float(np.mean(ys)) / h
                motion_center = (cx, cy)

        self._prev_gray = gray

        is_usable = sharpness >= self.MIN_SHARPNESS and brightness >= self.MIN_BRIGHTNESS

        return FrameMetrics(
            sharpness=sharpness,
            brightness=brightness,
            complexity=complexity,
            motion_score=motion_score,
            motion_center=motion_center,
            is_usable=is_usable,
        )
