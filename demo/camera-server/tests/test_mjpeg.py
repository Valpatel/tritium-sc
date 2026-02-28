# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for MJPEG HTTP server — written BEFORE implementation (TDD)."""
import io
import json
import sys
import os
import threading
import time
import unittest
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _find_free_port():
    """Find a free TCP port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestMJPEGServerEndpoints(unittest.TestCase):
    """HTTP server must serve /mjpeg, /snapshot, /status."""

    @classmethod
    def setUpClass(cls):
        from camera import FrameGenerator
        from mjpeg_server import MJPEGServer
        cls.port = _find_free_port()
        cls.gen = FrameGenerator(mode="procedural", width=320, height=240)
        cls.server = MJPEGServer(
            frame_generator=cls.gen,
            port=cls.port,
            camera_id="test-cam-01",
            fps=10,
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        # Wait for server to be ready
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://localhost:{cls.port}/status", timeout=1)
                break
            except (urllib.error.URLError, ConnectionRefusedError):
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_snapshot_returns_jpeg(self):
        resp = urllib.request.urlopen(f"http://localhost:{self.port}/snapshot")
        content_type = resp.headers.get("Content-Type", "")
        self.assertIn("image/jpeg", content_type)
        data = resp.read()
        # JPEG marker
        self.assertTrue(data[:2] == b'\xff\xd8')

    def test_status_returns_json(self):
        resp = urllib.request.urlopen(f"http://localhost:{self.port}/status")
        content_type = resp.headers.get("Content-Type", "")
        self.assertIn("application/json", content_type)
        data = json.loads(resp.read().decode())
        self.assertIn("camera_id", data)
        self.assertIn("fps", data)
        self.assertIn("resolution", data)
        self.assertIn("uptime", data)

    def test_status_camera_id(self):
        resp = urllib.request.urlopen(f"http://localhost:{self.port}/status")
        data = json.loads(resp.read().decode())
        self.assertEqual(data["camera_id"], "test-cam-01")

    def test_status_resolution_format(self):
        resp = urllib.request.urlopen(f"http://localhost:{self.port}/status")
        data = json.loads(resp.read().decode())
        # Should be "WIDTHxHEIGHT" string
        self.assertEqual(data["resolution"], "320x240")

    def test_status_uptime_is_number(self):
        resp = urllib.request.urlopen(f"http://localhost:{self.port}/status")
        data = json.loads(resp.read().decode())
        self.assertIsInstance(data["uptime"], (int, float))
        self.assertGreaterEqual(data["uptime"], 0)

    def test_mjpeg_content_type(self):
        req = urllib.request.Request(f"http://localhost:{self.port}/mjpeg")
        resp = urllib.request.urlopen(req, timeout=2)
        content_type = resp.headers.get("Content-Type", "")
        self.assertIn("multipart/x-mixed-replace", content_type)
        # Should contain boundary
        self.assertIn("boundary=", content_type)

    def test_mjpeg_delivers_frames(self):
        """Read a few bytes from the MJPEG stream to verify frames arrive."""
        req = urllib.request.Request(f"http://localhost:{self.port}/mjpeg")
        resp = urllib.request.urlopen(req, timeout=3)
        # Read first chunk — should contain boundary and JPEG data
        data = resp.read(8192)
        self.assertGreater(len(data), 0)
        # Should contain JPEG start marker somewhere
        self.assertIn(b'\xff\xd8', data)
        resp.close()

    def test_404_on_unknown_path(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://localhost:{self.port}/nonexistent")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
