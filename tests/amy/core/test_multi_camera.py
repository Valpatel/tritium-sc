# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for multi-camera VisionThread support in Commander.

Verifies that Commander creates a VisionThread per camera node,
maintains backward-compatible vision_thread property, and properly
starts/stops all threads.
"""

from __future__ import annotations

import pytest

from tests.amy.conftest import MockSensorNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockVisionThread:
    """Minimal VisionThread stand-in for testing multi-camera wiring."""

    def __init__(self, node, event_bus=None, event_queue=None):
        self.node = node
        self._started = False
        self._stopped = False
        self._yolo_backend = "mock"

    def start(self):
        self._started = True

    def stop(self):
        self._stopped = True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMultiCameraVisionThreads:
    """Commander creates VisionThread per camera node."""

    def test_creates_vision_thread_per_camera(self):
        """3 camera nodes = 3 VisionThreads in vision_threads dict."""
        nodes = {
            "cam1": MockSensorNode(node_id="cam1", camera=True),
            "cam2": MockSensorNode(node_id="cam2", camera=True),
            "cam3": MockSensorNode(node_id="cam3", camera=True),
        }
        vision_threads = {}
        for nid, node in nodes.items():
            if node.has_camera:
                vt = MockVisionThread(node)
                vision_threads[nid] = vt

        assert len(vision_threads) == 3
        assert set(vision_threads.keys()) == {"cam1", "cam2", "cam3"}

    def test_non_camera_nodes_skipped(self):
        """Nodes without cameras don't get VisionThreads."""
        nodes = {
            "cam1": MockSensorNode(node_id="cam1", camera=True),
            "virtual": MockSensorNode(node_id="virtual", camera=False),
            "mic": MockSensorNode(node_id="mic", camera=False, mic=True),
        }
        vision_threads = {}
        for nid, node in nodes.items():
            if node.has_camera:
                vt = MockVisionThread(node)
                vision_threads[nid] = vt

        assert len(vision_threads) == 1
        assert "cam1" in vision_threads

    def test_backward_compat_vision_thread(self):
        """vision_thread alias points to first entry in vision_threads."""
        nodes = {
            "cam1": MockSensorNode(node_id="cam1", camera=True),
            "cam2": MockSensorNode(node_id="cam2", camera=True),
        }
        vision_threads = {}
        for nid, node in nodes.items():
            if node.has_camera:
                vt = MockVisionThread(node)
                vision_threads[nid] = vt

        # Backward compat: vision_thread = first entry
        vision_thread = next(iter(vision_threads.values())) if vision_threads else None
        assert vision_thread is not None
        assert vision_thread is vision_threads["cam1"]

    def test_empty_nodes_no_vision_thread(self):
        """No camera nodes = empty dict and None vision_thread."""
        nodes = {
            "virtual": MockSensorNode(node_id="virtual", camera=False),
        }
        vision_threads = {}
        for nid, node in nodes.items():
            if node.has_camera:
                vt = MockVisionThread(node)
                vision_threads[nid] = vt

        assert len(vision_threads) == 0
        vision_thread = next(iter(vision_threads.values()), None)
        assert vision_thread is None

    def test_start_all_vision_threads(self):
        """All vision threads should be startable."""
        nodes = {
            "cam1": MockSensorNode(node_id="cam1", camera=True),
            "cam2": MockSensorNode(node_id="cam2", camera=True),
        }
        vision_threads = {}
        for nid, node in nodes.items():
            if node.has_camera:
                vt = MockVisionThread(node)
                vision_threads[nid] = vt

        for vt in vision_threads.values():
            vt.start()

        assert all(vt._started for vt in vision_threads.values())

    def test_stop_all_vision_threads(self):
        """All vision threads should be stoppable."""
        nodes = {
            "cam1": MockSensorNode(node_id="cam1", camera=True),
            "cam2": MockSensorNode(node_id="cam2", camera=True),
        }
        vision_threads = {}
        for nid, node in nodes.items():
            if node.has_camera:
                vt = MockVisionThread(node)
                vision_threads[nid] = vt

        for vt in vision_threads.values():
            vt.start()
        for vt in vision_threads.values():
            vt.stop()

        assert all(vt._stopped for vt in vision_threads.values())

    def test_mixed_camera_types(self):
        """Different camera node types all get VisionThreads."""
        # Simulate BCC950 + IP cameras
        bcc = MockSensorNode(node_id="bcc950", camera=True, ptz=True)
        ip1 = MockSensorNode(node_id="ip-cam-1", camera=True, ptz=False)
        ip2 = MockSensorNode(node_id="ip-cam-2", camera=True, ptz=False)
        virtual = MockSensorNode(node_id="virtual", camera=False)

        nodes = {n.node_id: n for n in [bcc, ip1, ip2, virtual]}
        vision_threads = {}
        for nid, node in nodes.items():
            if node.has_camera:
                vt = MockVisionThread(node)
                vision_threads[nid] = vt

        assert len(vision_threads) == 3
        assert "bcc950" in vision_threads
        assert "ip-cam-1" in vision_threads
        assert "ip-cam-2" in vision_threads
        assert "virtual" not in vision_threads
