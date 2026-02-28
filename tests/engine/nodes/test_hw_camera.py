# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Hardware tests for BCC950Node camera functionality.

Requires a physical BCC950 ConferenceCam connected via USB.
Run with: pytest tests/amy/test_hw_camera.py -m hardware
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

bcc950_mod = pytest.importorskip("engine.nodes.bcc950", reason="bcc950 deps not installed")
BCC950Node = bcc950_mod.BCC950Node

pytestmark = [pytest.mark.hardware, pytest.mark.slow]


@pytest.fixture(scope="module")
def bcc950_node():
    """Create, start, yield, and stop a BCC950Node for the test module."""
    node = BCC950Node()
    try:
        node.start()
    except RuntimeError as e:
        pytest.skip(f"BCC950 not available: {e}")
    # Let the frame buffer warm up
    time.sleep(1.0)
    yield node
    node.stop()


class TestBCC950Camera:
    def test_node_starts(self, bcc950_node: BCC950Node):
        """Node starts without error (confirmed by fixture reaching here)."""
        assert bcc950_node.has_camera

    def test_get_frame_returns_bgr_uint8(self, bcc950_node: BCC950Node):
        """get_frame() returns a numpy array with dtype uint8 and 3 channels."""
        frame = bcc950_node.get_frame()
        assert frame is not None, "get_frame() returned None"
        assert isinstance(frame, np.ndarray)
        assert frame.dtype == np.uint8
        assert frame.ndim == 3
        assert frame.shape[2] == 3, f"Expected 3 channels (BGR), got {frame.shape[2]}"

    def test_get_frame_reasonable_dimensions(self, bcc950_node: BCC950Node):
        """get_frame() returns a frame with reasonable dimensions."""
        frame = bcc950_node.get_frame()
        assert frame is not None
        height, width = frame.shape[:2]
        assert height > 100, f"Frame height {height} too small"
        assert width > 100, f"Frame width {width} too small"

    def test_get_jpeg_returns_valid_jpeg(self, bcc950_node: BCC950Node):
        """get_jpeg() returns bytes starting with the JPEG header."""
        jpeg = bcc950_node.get_jpeg()
        assert jpeg is not None, "get_jpeg() returned None"
        assert isinstance(jpeg, bytes)
        assert jpeg[:3] == b"\xff\xd8\xff", (
            f"Expected JPEG header ff d8 ff, got {jpeg[:3].hex()}"
        )

    def test_frame_ids_increment(self, bcc950_node: BCC950Node):
        """Frame IDs increment between successive get_frame() calls."""
        _ = bcc950_node.get_frame()
        id1 = bcc950_node.frame_id
        # Wait for at least one new frame
        time.sleep(0.1)
        _ = bcc950_node.get_frame()
        id2 = bcc950_node.frame_id
        assert id2 > id1, f"Frame ID did not increment: {id1} -> {id2}"

    def test_concurrent_frame_access(self, bcc950_node: BCC950Node):
        """Concurrent frame access from multiple threads is safe."""
        def grab_frame(_):
            return bcc950_node.get_frame()

        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(grab_frame, range(5)))

        for i, frame in enumerate(results):
            assert frame is not None, f"Thread {i} got None frame"
            assert frame.dtype == np.uint8
            assert frame.ndim == 3


def test_camera_report(bcc950_node: BCC950Node):
    """Print a summary report of camera capabilities."""
    frame = bcc950_node.get_frame()
    assert frame is not None
    height, width = frame.shape[:2]

    # Estimate FPS by timing 30 frame reads
    n_frames = 30
    start = time.monotonic()
    for _ in range(n_frames):
        bcc950_node.get_frame()
        time.sleep(0.033)
    elapsed = time.monotonic() - start
    fps = n_frames / elapsed if elapsed > 0 else 0

    jpeg = bcc950_node.get_jpeg()
    jpeg_size = len(jpeg) if jpeg else 0

    print("\n" + "=" * 50)
    print("BCC950 Camera Report")
    print("=" * 50)
    print(f"  Frame dimensions : {width}x{height}")
    print(f"  Estimated FPS    : {fps:.1f}")
    print(f"  JPEG size        : {jpeg_size:,} bytes")
    print("=" * 50)
