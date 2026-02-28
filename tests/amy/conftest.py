# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shared fixtures for Amy tests."""

from __future__ import annotations

import os
import tempfile

# Force CPU for tests — GB10 sm_121 is incompatible with current PyTorch (sm_80-90)
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import numpy as np
import pytest

from engine.nodes.base import SensorNode, Position


class MockSensorNode(SensorNode):
    """In-memory sensor node for unit testing.

    Provides controllable camera frames, PTZ position, and audio recording
    without any real hardware.
    """

    def __init__(
        self,
        node_id: str = "mock",
        name: str = "Mock Node",
        camera: bool = True,
        ptz: bool = True,
        mic: bool = True,
        speaker: bool = True,
    ):
        super().__init__(node_id, name)
        self._has_camera = camera
        self._has_ptz = ptz
        self._has_mic = mic
        self._has_speaker = speaker

        # Controllable state
        self._position = Position(
            pan=0.0, tilt=0.0, zoom=100.0,
            pan_min=-170.0, pan_max=170.0,
            tilt_min=-30.0, tilt_max=30.0,
        )
        self._frame: np.ndarray | None = np.zeros((480, 640, 3), dtype=np.uint8)
        self._frame_id: int = 0
        self._move_log: list[tuple[int, int, float]] = []
        self._reset_count: int = 0
        self._audio_data: np.ndarray | None = None
        self._played_audio: list[tuple[bytes, int]] = []

    @property
    def has_camera(self) -> bool:
        return self._has_camera

    @property
    def has_ptz(self) -> bool:
        return self._has_ptz

    @property
    def has_mic(self) -> bool:
        return self._has_mic

    @property
    def has_speaker(self) -> bool:
        return self._has_speaker

    def get_frame(self) -> np.ndarray | None:
        if self._frame is not None:
            self._frame_id += 1
        return self._frame.copy() if self._frame is not None else None

    def get_jpeg(self) -> bytes | None:
        if self._frame is None:
            return None
        import cv2
        _, buf = cv2.imencode(".jpg", self._frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes()

    @property
    def frame_id(self) -> int:
        return self._frame_id

    def move(self, pan_dir: int, tilt_dir: int, duration: float) -> tuple[bool, bool]:
        self._move_log.append((pan_dir, tilt_dir, duration))
        pan_moved = False
        tilt_moved = False

        if pan_dir != 0:
            new_pan = self._position.pan + pan_dir * duration * 50
            if self._position.pan_min is not None:
                new_pan = max(new_pan, self._position.pan_min)
            if self._position.pan_max is not None:
                new_pan = min(new_pan, self._position.pan_max)
            if new_pan != self._position.pan:
                self._position.pan = new_pan
                pan_moved = True

        if tilt_dir != 0:
            new_tilt = self._position.tilt + tilt_dir * duration * 50
            if self._position.tilt_min is not None:
                new_tilt = max(new_tilt, self._position.tilt_min)
            if self._position.tilt_max is not None:
                new_tilt = min(new_tilt, self._position.tilt_max)
            if new_tilt != self._position.tilt:
                self._position.tilt = new_tilt
                tilt_moved = True

        return (pan_moved, tilt_moved)

    def get_position(self) -> Position:
        return Position(
            pan=self._position.pan,
            tilt=self._position.tilt,
            zoom=self._position.zoom,
            pan_min=self._position.pan_min,
            pan_max=self._position.pan_max,
            tilt_min=self._position.tilt_min,
            tilt_max=self._position.tilt_max,
        )

    def reset_position(self) -> None:
        self._position.pan = 0.0
        self._position.tilt = 0.0
        self._reset_count += 1

    def record_audio(self, duration: float) -> np.ndarray | None:
        if self._audio_data is not None:
            return self._audio_data
        return np.zeros(int(duration * 16000), dtype=np.float32)

    def play_audio(self, raw_pcm: bytes, sample_rate: int = 22050) -> None:
        self._played_audio.append((raw_pcm, sample_rate))


@pytest.fixture
def mock_node():
    """A MockSensorNode with all capabilities."""
    return MockSensorNode()


@pytest.fixture
def mock_node_no_camera():
    """A MockSensorNode without camera."""
    return MockSensorNode(camera=False, ptz=False)


@pytest.fixture
def memory_tmpdir(tmp_path):
    """A temporary directory path for Memory persistence tests."""
    return str(tmp_path / "amy_memory.json")


@pytest.fixture
def sensorium():
    """A fresh Sensorium instance."""
    from amy.brain.sensorium import Sensorium
    return Sensorium()


@pytest.fixture
def synthetic_video_lib(tmp_path):
    """A SyntheticVideoLibrary using a temp directory."""
    from engine.synthetic.video_library import SyntheticVideoLibrary
    return SyntheticVideoLibrary(library_path=str(tmp_path / "synthetic_video"))


@pytest.fixture(scope="module")
def perf_results():
    """Collect performance metrics across tests in a module.

    After the module completes, writes a JSON report to
    tests/.test-results/perf-report.json.
    """
    import json
    from pathlib import Path

    results: dict[str, dict] = {}
    yield results

    results_dir = Path(__file__).parent.parent / ".test-results"
    results_dir.mkdir(parents=True, exist_ok=True)
    report_path = results_dir / "perf-report.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
