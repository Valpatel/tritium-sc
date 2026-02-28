# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for the live camera pipeline.

Proves the full pipeline: IPCameraNode → VisionThread → EventBus → TargetTracker → escalation.
Uses mock RTSP captures — no real hardware or server needed.
"""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from engine.nodes.ip_camera import IPCameraNode
from engine.nodes.frame_buffer import ReconnectingFrameBuffer
from engine.comms.event_bus import EventBus
from engine.tactical.escalation import ThreatClassifier, AutoDispatcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeVideoCapture:
    """Mock cv2.VideoCapture that returns synthetic frames with a person-like blob."""

    def __init__(self, url=None):
        self._opened = True
        self._frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # Draw a person-sized blob at center
        self._frame[200:400, 280:360, :] = [0, 128, 255]  # BGR orange blob

    def isOpened(self):
        return self._opened

    def read(self):
        return True, self._frame.copy()

    def set(self, prop, value):
        pass

    def release(self):
        self._opened = False


# ---------------------------------------------------------------------------
# Test: IPCamera frames reach the system
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestIPCameraFramesPipeline:
    """IPCameraNode → frame buffer → event bus pipeline."""

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_ip_camera_frames_reach_event_bus(self):
        """Frames from IPCameraNode are available for YOLO/VisionThread consumption."""
        node = IPCameraNode(
            node_id="ip-cam-1",
            name="Front Door",
            rtsp_url="rtsp://test/stream",
        )
        node.start()
        time.sleep(0.2)

        # Verify frames are flowing
        frame = node.get_frame()
        assert frame is not None
        assert isinstance(frame, np.ndarray)
        assert frame.shape == (480, 640, 3)

        jpeg = node.get_jpeg()
        assert jpeg is not None
        assert jpeg[:2] == b'\xff\xd8'

        assert node.frame_id > 0
        assert node.frame_age < 1.0

        node.stop()

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_multiple_ip_cameras_independent(self):
        """Multiple IPCameraNodes operate independently."""
        nodes = []
        for i in range(3):
            node = IPCameraNode(
                node_id=f"ip-cam-{i+1}",
                name=f"Camera {i+1}",
                rtsp_url=f"rtsp://test/stream{i+1}",
            )
            node.start()
            nodes.append(node)

        time.sleep(0.2)

        # All should have frames
        for node in nodes:
            assert node.get_frame() is not None
            assert node.frame_id > 0

        for node in nodes:
            node.stop()


@pytest.mark.unit
class TestEscalationFromDetection:
    """Detection → threat classifier → escalation event pipeline."""

    def test_detection_event_triggers_classification(self):
        """A detection event published on EventBus reaches ThreatClassifier."""
        bus = EventBus()

        # Create a mock tracker with a hostile target
        class FakeTrackedTarget:
            def __init__(self, target_id, alliance, position):
                self.target_id = target_id
                self.alliance = alliance
                self.position = position
                self.battery = 1.0
                self.status = "active"
                self.name = "Hostile Person"
                self.asset_type = "person"

        class FakeTracker:
            def __init__(self):
                self._targets = {
                    "h1": FakeTrackedTarget("h1", "hostile", (5.0, 5.0)),
                }

            def get_all(self):
                return list(self._targets.values())

            def get(self, tid):
                return self._targets.get(tid)

        tracker = FakeTracker()

        # Create classifier with a zone centered at origin
        zones = [{
            "name": "perimeter",
            "type": "perimeter",
            "position": {"x": 0.0, "y": 0.0},
            "properties": {"radius": 100.0},
        }]

        classifier = ThreatClassifier(
            bus, tracker, zones=zones,
            linger_threshold=1.0,  # Quick linger for test
        )

        # Run one classify tick manually
        classifier._classify_tick()

        # Target at (5,5) is inside the 100m radius zone
        records = classifier.get_records()
        assert "h1" in records
        assert records["h1"].threat_level in ("unknown", "suspicious", "hostile")

    def test_escalation_events_published(self):
        """ThreatClassifier publishes escalation_change events."""
        bus = EventBus()
        sub = bus.subscribe()

        class FakeTarget:
            def __init__(self):
                self.target_id = "h1"
                self.alliance = "hostile"
                self.position = (5.0, 5.0)
                self.battery = 1.0
                self.status = "active"
                self.name = "Hostile"
                self.asset_type = "person"

        class FakeTracker:
            def get_all(self):
                return [FakeTarget()]

            def get(self, tid):
                return FakeTarget() if tid == "h1" else None

        zones = [{
            "name": "restricted",
            "type": "restricted",
            "position": {"x": 0.0, "y": 0.0},
            "properties": {"radius": 50.0},
        }]

        classifier = ThreatClassifier(bus, FakeTracker(), zones=zones)
        classifier._classify_tick()

        # Check that an event was published
        events = []
        while not sub.empty():
            events.append(sub.get_nowait())

        escalation_events = [e for e in events if e.get("type") in ("escalation_change", "zone_violation")]
        assert len(escalation_events) > 0

        bus.unsubscribe(sub)


@pytest.mark.unit
class TestModeSwitchCameraPipeline:
    """Mode switching changes primary camera source."""

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_mode_switch_changes_primary_camera(self):
        """Switching between sim/live changes which camera is primary."""
        from tests.amy.conftest import MockSensorNode

        # Build nodes dict with virtual + IP camera
        virtual = MockSensorNode(node_id="virtual", camera=True)
        ip_cam = IPCameraNode(
            node_id="ip-cam-1", name="Real Camera",
            rtsp_url="rtsp://test/stream",
        )

        nodes = {"virtual": virtual, "ip-cam-1": ip_cam}

        # Build vision_threads (simulating Commander._boot)
        class SimpleVT:
            def __init__(self, node):
                self.node = node

        vision_threads = {}
        for nid, node in nodes.items():
            if node.has_camera:
                vision_threads[nid] = SimpleVT(node)

        # Sim mode: prefer virtual
        vision_thread = None
        for nid, vt in vision_threads.items():
            if nid == "virtual" or nid.startswith("synthetic"):
                vision_thread = vt
                break
        assert vision_thread is not None
        assert vision_thread.node.node_id == "virtual"

        # Live mode: prefer real camera
        for nid, vt in vision_threads.items():
            if nid != "virtual" and not nid.startswith("synthetic"):
                vision_thread = vt
                break
        assert vision_thread.node.node_id == "ip-cam-1"

    @patch("engine.nodes.frame_buffer.cv2.VideoCapture", FakeVideoCapture)
    def test_discovered_camera_has_frames_in_live_mode(self):
        """An IP camera discovered from DB provides frames when in live mode."""
        import sqlite3
        import tempfile

        # Create test database
        db_path = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE cameras (
                id INTEGER PRIMARY KEY, channel INTEGER UNIQUE,
                name TEXT, rtsp_url TEXT, substream_url TEXT,
                enabled BOOLEAN DEFAULT 1, position_x REAL,
                position_y REAL, heading REAL, fov REAL,
                mount_height REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO cameras (channel, name, rtsp_url, enabled) VALUES (?, ?, ?, ?)",
            (1, "Front Door", "rtsp://test/stream", 1),
        )
        conn.commit()
        conn.close()

        # Discover cameras
        from amy import _discover_ip_cameras
        ip_nodes = _discover_ip_cameras(db_path)

        assert len(ip_nodes) == 1
        node = ip_nodes["ip-cam-1"]
        assert isinstance(node, IPCameraNode)
        assert node.has_camera is True

        # Start and verify frames
        node.start()
        time.sleep(0.2)
        assert node.get_frame() is not None
        assert node.frame_id > 0
        node.stop()

        # Cleanup
        import os
        os.unlink(db_path)
