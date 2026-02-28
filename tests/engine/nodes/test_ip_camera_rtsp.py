# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for IPCameraNode RTSP implementation and ReconnectingFrameBuffer.

Tests frame capture, reconnection with exponential backoff, thread safety,
and clean shutdown. All tests use mocked cv2.VideoCapture — no hardware needed.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from engine.nodes.frame_buffer import FrameBuffer, ReconnectingFrameBuffer
from engine.nodes.ip_camera import IPCameraNode
from engine.nodes.base import SensorNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_frame(width=640, height=480):
    """Create a synthetic BGR frame."""
    return np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)


class FakeVideoCapture:
    """Mock cv2.VideoCapture that returns synthetic frames."""

    def __init__(self, url_or_device=None):
        self._opened = True
        self._read_count = 0
        self._fail_after = None  # set to N to fail after N reads
        self._fail_count = 0     # how many failures to return

    def isOpened(self):
        return self._opened

    def read(self):
        self._read_count += 1
        if self._fail_after is not None and self._read_count > self._fail_after:
            self._fail_count += 1
            return False, None
        return True, _make_fake_frame()

    def set(self, prop, value):
        pass

    def release(self):
        self._opened = False


class FailingVideoCapture:
    """VideoCapture that always fails reads."""

    def __init__(self, url=None):
        self._opened = True
        self.read_count = 0

    def isOpened(self):
        return self._opened

    def read(self):
        self.read_count += 1
        return False, None

    def set(self, prop, value):
        pass

    def release(self):
        self._opened = False


# ---------------------------------------------------------------------------
# FrameBuffer tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFrameBuffer:
    """FrameBuffer — lock-protected shared frame reader."""

    def test_start_stop(self):
        cap = FakeVideoCapture()
        lock = threading.Lock()
        buf = FrameBuffer(cap, lock)
        buf.start()
        time.sleep(0.15)  # Let it grab a few frames
        buf.stop()
        assert buf.frame_id > 0

    def test_frame_returns_ndarray(self):
        cap = FakeVideoCapture()
        lock = threading.Lock()
        buf = FrameBuffer(cap, lock)
        buf.start()
        time.sleep(0.15)
        frame = buf.frame
        buf.stop()
        assert isinstance(frame, np.ndarray)
        assert frame.shape == (480, 640, 3)

    def test_jpeg_valid_bytes(self):
        cap = FakeVideoCapture()
        lock = threading.Lock()
        buf = FrameBuffer(cap, lock)
        buf.start()
        time.sleep(0.15)
        jpeg = buf.jpeg
        buf.stop()
        assert isinstance(jpeg, bytes)
        assert jpeg[:2] == b'\xff\xd8'  # JPEG SOI marker

    def test_frame_id_increments(self):
        cap = FakeVideoCapture()
        lock = threading.Lock()
        buf = FrameBuffer(cap, lock)
        buf.start()
        time.sleep(0.15)
        id1 = buf.frame_id
        time.sleep(0.1)
        id2 = buf.frame_id
        buf.stop()
        assert id2 > id1

    def test_frame_age(self):
        cap = FakeVideoCapture()
        lock = threading.Lock()
        buf = FrameBuffer(cap, lock)
        # Before start, age is inf
        assert buf.frame_age == float("inf")
        buf.start()
        time.sleep(0.15)
        age = buf.frame_age
        buf.stop()
        assert age < 1.0  # Should be very recent


# ---------------------------------------------------------------------------
# ReconnectingFrameBuffer tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestReconnectingFrameBuffer:
    """ReconnectingFrameBuffer — RTSP reconnection with exponential backoff."""

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_start_creates_capture(self):
        buf = ReconnectingFrameBuffer("rtsp://test/stream")
        buf.start()
        time.sleep(0.15)
        assert buf.frame_id > 0
        buf.stop()

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_get_frame_returns_ndarray(self):
        buf = ReconnectingFrameBuffer("rtsp://test/stream")
        buf.start()
        time.sleep(0.15)
        frame = buf.frame
        buf.stop()
        assert isinstance(frame, np.ndarray)
        assert frame.shape == (480, 640, 3)

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_jpeg_valid(self):
        buf = ReconnectingFrameBuffer("rtsp://test/stream")
        buf.start()
        time.sleep(0.15)
        jpeg = buf.jpeg
        buf.stop()
        assert jpeg is not None
        assert jpeg[:2] == b'\xff\xd8'

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_frame_age(self):
        buf = ReconnectingFrameBuffer("rtsp://test/stream")
        assert buf.frame_age == float("inf")
        buf.start()
        time.sleep(0.15)
        assert buf.frame_age < 1.0
        buf.stop()

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FailingVideoCapture)
    def test_reconnect_on_read_failure(self):
        """After FAILURE_THRESHOLD consecutive fails, should reconnect."""
        buf = ReconnectingFrameBuffer("rtsp://test/stream")
        buf.FAILURE_THRESHOLD = 3  # Lower threshold for faster test
        buf.BACKOFF_BASE = 0.01    # Fast backoff for testing
        buf.start()
        time.sleep(0.5)
        assert buf._reconnect_count > 0
        buf.stop()

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FailingVideoCapture)
    def test_reconnect_backoff_increases(self):
        """Backoff delay should increase with each reconnect."""
        buf = ReconnectingFrameBuffer("rtsp://test/stream")
        buf.FAILURE_THRESHOLD = 2
        buf.BACKOFF_BASE = 0.01
        buf.BACKOFF_MAX = 0.1
        buf.start()
        time.sleep(0.5)
        # Multiple reconnects should have happened
        assert buf._reconnect_count >= 2
        buf.stop()

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FailingVideoCapture)
    def test_stop_during_reconnect(self):
        """Stop should terminate even during reconnect backoff."""
        buf = ReconnectingFrameBuffer("rtsp://test/stream")
        buf.FAILURE_THRESHOLD = 1
        buf.BACKOFF_BASE = 10.0  # Long delay
        buf.start()
        time.sleep(0.2)  # Let it enter reconnect
        t0 = time.monotonic()
        buf.stop()
        elapsed = time.monotonic() - t0
        # Should stop quickly, not wait for full backoff
        assert elapsed < 2.0

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_concurrent_access(self):
        """Multiple threads reading frame/jpeg simultaneously."""
        buf = ReconnectingFrameBuffer("rtsp://test/stream")
        buf.start()
        time.sleep(0.15)

        errors = []

        def reader():
            try:
                for _ in range(20):
                    _ = buf.frame
                    _ = buf.jpeg
                    _ = buf.frame_id
                    _ = buf.frame_age
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        buf.stop()
        assert errors == [], f"Concurrent access errors: {errors}"


# ---------------------------------------------------------------------------
# IPCameraNode tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestIPCameraNodeRTSP:
    """IPCameraNode — full RTSP implementation via ReconnectingFrameBuffer."""

    def test_construction(self):
        node = IPCameraNode(
            node_id="cam-01", name="Front Door",
            rtsp_url="rtsp://10.0.0.5:554/stream1",
        )
        assert node.node_id == "cam-01"
        assert node.name == "Front Door"
        assert node.rtsp_url == "rtsp://10.0.0.5:554/stream1"

    def test_is_sensor_node(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://x")
        assert isinstance(node, SensorNode)

    def test_has_camera_true(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://x")
        assert node.has_camera is True

    def test_no_ptz(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://x")
        assert node.has_ptz is False

    def test_frame_none_before_start(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://x")
        assert node.get_frame() is None
        assert node.get_jpeg() is None
        assert node.frame_id == 0
        assert node.frame_age == float("inf")

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_start_creates_buffer(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://test")
        node.start()
        time.sleep(0.15)
        assert node._buffer is not None
        assert node.frame_id > 0
        node.stop()

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_get_frame_after_start(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://test")
        node.start()
        time.sleep(0.15)
        frame = node.get_frame()
        node.stop()
        assert isinstance(frame, np.ndarray)
        assert frame.shape == (480, 640, 3)

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_get_jpeg_after_start(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://test")
        node.start()
        time.sleep(0.15)
        jpeg = node.get_jpeg()
        node.stop()
        assert isinstance(jpeg, bytes)
        assert jpeg[:2] == b'\xff\xd8'

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_frame_age_after_start(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://test")
        node.start()
        time.sleep(0.15)
        assert node.frame_age < 1.0
        node.stop()

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_stop_cleans_up(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://test")
        node.start()
        time.sleep(0.1)
        node.stop()
        assert node._buffer is None
        assert node.get_frame() is None

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_double_stop_safe(self):
        node = IPCameraNode(node_id="c1", name="Test", rtsp_url="rtsp://test")
        node.start()
        time.sleep(0.1)
        node.stop()
        node.stop()  # Should not raise
