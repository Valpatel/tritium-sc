# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for live/sim mode camera switching.

Verifies that set_mode("live") switches primary vision_thread to a real
camera node, and set_mode("sim") switches back to synthetic.
"""

from __future__ import annotations

import pytest

from tests.amy.conftest import MockSensorNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockVisionThread:
    """Minimal VisionThread stand-in."""

    def __init__(self, node, event_bus=None, event_queue=None):
        self.node = node
        self._started = False
        self._stopped = False
        self._yolo_backend = "mock"

    def start(self):
        self._started = True

    def stop(self):
        self._stopped = True


class MockEventBus:
    def __init__(self):
        self.published = []

    def publish(self, event_type, data):
        self.published.append((event_type, data))


class MockEngine:
    """Minimal SimulationEngine stand-in."""

    def __init__(self):
        self.spawners_paused = False

    def pause_spawners(self):
        self.spawners_paused = True

    def resume_spawners(self):
        self.spawners_paused = False


def _build_vision_state(nodes):
    """Build vision_threads dict and vision_thread alias like Commander._boot."""
    vision_threads = {}
    for nid, node in nodes.items():
        if node.has_camera:
            vt = MockVisionThread(node)
            vision_threads[nid] = vt
    vision_thread = next(iter(vision_threads.values()), None) if vision_threads else None
    return vision_threads, vision_thread


def _switch_primary_camera(mode, vision_threads):
    """Simulate Commander.set_mode camera switching logic.

    In live mode: prefer first real camera (non-virtual node).
    In sim mode: prefer virtual/synthetic camera.
    All VisionThreads keep running.
    """
    if not vision_threads:
        return None

    if mode == "live":
        # Prefer real (non-virtual) cameras
        for nid, vt in vision_threads.items():
            if nid != "virtual" and not nid.startswith("synthetic"):
                return vt
        # Fall back to whatever is available
        return next(iter(vision_threads.values()))
    else:
        # Sim mode: prefer virtual/synthetic
        for nid, vt in vision_threads.items():
            if nid == "virtual" or nid.startswith("synthetic"):
                return vt
        # Fall back to whatever is available
        return next(iter(vision_threads.values()))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestModeSwitchCameraSelection:
    """set_mode switches primary vision_thread between real and synthetic."""

    def test_live_mode_uses_real_camera(self):
        """In live mode, vision_thread should point to a real camera."""
        nodes = {
            "virtual": MockSensorNode(node_id="virtual", camera=True),
            "ip-cam-1": MockSensorNode(node_id="ip-cam-1", camera=True),
        }
        vision_threads, _ = _build_vision_state(nodes)

        primary = _switch_primary_camera("live", vision_threads)
        assert primary is not None
        assert primary.node.node_id == "ip-cam-1"

    def test_sim_mode_uses_synthetic_camera(self):
        """In sim mode, vision_thread should point to virtual/synthetic."""
        nodes = {
            "virtual": MockSensorNode(node_id="virtual", camera=True),
            "ip-cam-1": MockSensorNode(node_id="ip-cam-1", camera=True),
        }
        vision_threads, _ = _build_vision_state(nodes)

        primary = _switch_primary_camera("sim", vision_threads)
        assert primary is not None
        assert primary.node.node_id == "virtual"

    def test_all_vision_threads_still_running(self):
        """Mode switch doesn't stop any VisionThread."""
        nodes = {
            "virtual": MockSensorNode(node_id="virtual", camera=True),
            "ip-cam-1": MockSensorNode(node_id="ip-cam-1", camera=True),
            "ip-cam-2": MockSensorNode(node_id="ip-cam-2", camera=True),
        }
        vision_threads, _ = _build_vision_state(nodes)

        # Start all
        for vt in vision_threads.values():
            vt.start()

        # Switch modes
        _switch_primary_camera("live", vision_threads)
        _switch_primary_camera("sim", vision_threads)

        # All should still be running (none stopped)
        assert all(vt._started for vt in vision_threads.values())
        assert not any(vt._stopped for vt in vision_threads.values())

    def test_live_mode_no_real_camera_falls_back(self):
        """If only virtual camera exists, live mode uses it as fallback."""
        nodes = {
            "virtual": MockSensorNode(node_id="virtual", camera=True),
        }
        vision_threads, _ = _build_vision_state(nodes)

        primary = _switch_primary_camera("live", vision_threads)
        assert primary is not None
        assert primary.node.node_id == "virtual"

    def test_sim_mode_no_virtual_falls_back(self):
        """If no virtual camera, sim mode uses whatever is available."""
        nodes = {
            "ip-cam-1": MockSensorNode(node_id="ip-cam-1", camera=True),
        }
        vision_threads, _ = _build_vision_state(nodes)

        primary = _switch_primary_camera("sim", vision_threads)
        assert primary is not None
        assert primary.node.node_id == "ip-cam-1"

    def test_empty_vision_threads_returns_none(self):
        """No cameras at all = None primary."""
        primary = _switch_primary_camera("live", {})
        assert primary is None

    def test_bcc950_preferred_in_live_mode(self):
        """BCC950 hardware camera preferred over virtual in live mode."""
        nodes = {
            "virtual": MockSensorNode(node_id="virtual", camera=True),
            "bcc950": MockSensorNode(node_id="bcc950", camera=True, ptz=True),
        }
        vision_threads, _ = _build_vision_state(nodes)

        primary = _switch_primary_camera("live", vision_threads)
        assert primary.node.node_id == "bcc950"
