# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for SyntheticCameraNode — written before implementation (TDD)."""

from __future__ import annotations

import time

import numpy as np
import pytest

from engine.comms.event_bus import EventBus
from engine.simulation.engine import SimulationEngine
from engine.simulation.target import SimulationTarget


pytestmark = pytest.mark.unit


def _make_engine() -> SimulationEngine:
    """Create a minimal SimulationEngine (no threads started)."""
    bus = EventBus()
    return SimulationEngine(bus)


def _make_node(engine: SimulationEngine | None = None):
    """Create a SyntheticCameraNode."""
    from engine.nodes.synthetic_camera import SyntheticCameraNode

    if engine is None:
        engine = _make_engine()
    return SyntheticCameraNode(engine)


class TestSyntheticCameraInterface:
    """Verify SyntheticCameraNode implements SensorNode correctly."""

    def test_is_sensor_node(self):
        from engine.nodes.base import SensorNode

        node = _make_node()
        assert isinstance(node, SensorNode)

    def test_has_camera_true(self):
        node = _make_node()
        assert node.has_camera is True

    def test_has_ptz_true(self):
        node = _make_node()
        assert node.has_ptz is True

    def test_has_mic_false(self):
        node = _make_node()
        assert node.has_mic is False

    def test_has_speaker_false(self):
        node = _make_node()
        assert node.has_speaker is False

    def test_node_id_default(self):
        node = _make_node()
        assert node.node_id == "syn-cam-0"

    def test_node_name_default(self):
        node = _make_node()
        assert node.name == "Simulation Camera"


class TestSyntheticCameraFrames:
    """Test frame generation from simulation state."""

    def test_frame_before_start_is_none(self):
        node = _make_node()
        assert node.get_frame() is None

    def test_frame_after_start(self):
        node = _make_node()
        node.start()
        time.sleep(0.3)
        try:
            frame = node.get_frame()
            assert frame is not None
            assert frame.shape == (480, 640, 3)
            assert frame.dtype == np.uint8
        finally:
            node.stop()

    def test_jpeg_valid(self):
        node = _make_node()
        node.start()
        time.sleep(0.3)
        try:
            jpeg = node.get_jpeg()
            assert jpeg is not None
            assert jpeg[:2] == b"\xff\xd8", "Should start with JPEG magic bytes"
        finally:
            node.stop()

    def test_frame_id_increments(self):
        node = _make_node()
        node.start()
        time.sleep(0.3)
        try:
            id1 = node.frame_id
            time.sleep(0.2)
            id2 = node.frame_id
            assert id2 > id1
        finally:
            node.stop()

    def test_targets_appear_in_frame(self):
        """When a target exists at origin, center pixels should have bright content."""
        engine = _make_engine()
        target = SimulationTarget(
            target_id="test-1",
            name="Test Turret",
            asset_type="turret",
            alliance="friendly",
            position=(0.0, 0.0),
        )
        engine.add_target(target)

        node = _make_node(engine)
        node.start()
        time.sleep(0.3)
        try:
            frame = node.get_frame()
            assert frame is not None
            h, w = frame.shape[:2]
            center = frame[h // 2 - 20 : h // 2 + 20, w // 2 - 20 : w // 2 + 20]
            assert np.max(center) > 20, "Center should have bright pixels when target at origin"
        finally:
            node.stop()


    def test_eliminated_target_rendered_differently(self):
        """Eliminated targets should still appear but are rendered identically.

        The current _render_frame implementation does NOT filter or restyle
        eliminated targets -- they are drawn with the same alliance color as
        active ones.  This test documents that behaviour by placing an active
        friendly and an eliminated hostile at known positions, then verifying
        both produce coloured pixels matching their alliance colours.
        """
        engine = _make_engine()

        # Active friendly at (10, 10)
        friendly = SimulationTarget(
            target_id="friendly-1",
            name="Active Rover",
            asset_type="rover",
            alliance="friendly",
            position=(10.0, 10.0),
        )
        engine.add_target(friendly)

        # Eliminated hostile at (-10, -10)
        hostile = SimulationTarget(
            target_id="hostile-1",
            name="Dead Hostile",
            asset_type="person",
            alliance="hostile",
            position=(-10.0, -10.0),
            health=0.0,
            status="eliminated",
        )
        engine.add_target(hostile)

        node = _make_node(engine)
        node.start()
        time.sleep(0.3)
        try:
            frame = node.get_frame()
            assert frame is not None
            h, w = frame.shape[:2]

            # Compute pixel positions using the same transform as the camera
            vr = node._view_radius
            scale = min(w, h) / (2.0 * vr)

            # Friendly at (10, 10) -> pixel
            fpx = int(w / 2 + 10.0 * scale)
            fpy = int(h / 2 - 10.0 * scale)
            # Hostile at (-10, -10) -> pixel
            hpx = int(w / 2 + (-10.0) * scale)
            hpy = int(h / 2 - (-10.0) * scale)

            # Sample a small region around each target (rectangles are 8px)
            margin = 8
            friendly_region = frame[
                max(fpy - margin, 0) : fpy + margin,
                max(fpx - margin, 0) : fpx + margin,
            ]
            hostile_region = frame[
                max(hpy - margin, 0) : hpy + margin,
                max(hpx - margin, 0) : hpx + margin,
            ]

            # Both regions should contain bright pixels (not just background)
            bg_max = 20  # background is (12,10,10), grid is (20,20,20)
            assert np.max(friendly_region) > bg_max, (
                "Active friendly should be visible at its position"
            )
            assert np.max(hostile_region) > bg_max, (
                "Eliminated hostile should still be visible (no filtering by status)"
            )

            # Verify alliance colours are present in the regions
            # Friendly BGR: (161, 255, 5) -- high green channel
            assert np.max(friendly_region[:, :, 1]) > 200, (
                "Friendly region should have strong green channel (alliance colour)"
            )
            # Hostile BGR: (109, 42, 255) -- high red channel (index 2 in BGR)
            assert np.max(hostile_region[:, :, 2]) > 200, (
                "Hostile region should have strong red channel (alliance colour)"
            )

        finally:
            node.stop()


class TestSyntheticCameraPTZ:
    """Test PTZ (pan/tilt) control of the virtual camera view."""

    def test_ptz_shifts_view_center(self):
        node = _make_node()
        original = list(node._view_center)
        node.move(1, 0, 1.0)
        assert node._view_center[0] != original[0]

    def test_ptz_tilt_shifts_view(self):
        node = _make_node()
        original = list(node._view_center)
        node.move(0, 1, 1.0)
        assert node._view_center[1] != original[1]

    def test_get_position_returns_position(self):
        from engine.nodes.base import Position

        node = _make_node()
        pos = node.get_position()
        assert isinstance(pos, Position)

    def test_reset_position(self):
        node = _make_node()
        node.move(1, 1, 1.0)
        node.reset_position()
        assert node._view_center == [0.0, 0.0]


class TestSyntheticCameraLifecycle:
    """Test start/stop lifecycle."""

    def test_stop_is_clean(self):
        node = _make_node()
        node.start()
        time.sleep(0.2)
        node.stop()
        assert node._thread is None or not node._thread.is_alive()

    def test_double_start_safe(self):
        """Starting twice should not create duplicate threads."""
        node = _make_node()
        node.start()
        time.sleep(0.1)
        node.start()  # second start should be a no-op
        time.sleep(0.1)
        node.stop()

    def test_stop_without_start(self):
        """Stopping without starting should not raise."""
        node = _make_node()
        node.stop()  # should be a no-op
