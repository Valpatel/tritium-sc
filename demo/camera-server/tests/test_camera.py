# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for camera frame generation — written BEFORE implementation (TDD)."""
import io
import sys
import os
import unittest

# Add parent dir to path so we can import camera module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image


class TestProceduralMode(unittest.TestCase):
    """Procedural mode: colored rectangles on dark background."""

    def test_generate_frame_returns_pil_image(self):
        from camera import FrameGenerator
        gen = FrameGenerator(mode="procedural", width=640, height=480)
        frame = gen.generate()
        self.assertIsInstance(frame, Image.Image)

    def test_frame_has_correct_resolution(self):
        from camera import FrameGenerator
        gen = FrameGenerator(mode="procedural", width=320, height=240)
        frame = gen.generate()
        self.assertEqual(frame.size, (320, 240))

    def test_frame_has_correct_resolution_custom(self):
        from camera import FrameGenerator
        gen = FrameGenerator(mode="procedural", width=1280, height=720)
        frame = gen.generate()
        self.assertEqual(frame.size, (1280, 720))

    def test_frame_is_rgb(self):
        from camera import FrameGenerator
        gen = FrameGenerator(mode="procedural", width=640, height=480)
        frame = gen.generate()
        self.assertEqual(frame.mode, "RGB")

    def test_consecutive_frames_differ(self):
        """Procedural frames should animate (not be identical)."""
        from camera import FrameGenerator
        gen = FrameGenerator(mode="procedural", width=640, height=480)
        f1 = gen.generate()
        f2 = gen.generate()
        # Convert to bytes and compare
        b1 = f1.tobytes()
        b2 = f2.tobytes()
        self.assertNotEqual(b1, b2)

    def test_frame_counter_increments(self):
        from camera import FrameGenerator
        gen = FrameGenerator(mode="procedural", width=640, height=480)
        self.assertEqual(gen.frame_count, 0)
        gen.generate()
        self.assertEqual(gen.frame_count, 1)
        gen.generate()
        self.assertEqual(gen.frame_count, 2)


class TestNoiseMode(unittest.TestCase):
    """Noise mode: random pixel data (stress test)."""

    def test_noise_frame_returns_image(self):
        from camera import FrameGenerator
        gen = FrameGenerator(mode="noise", width=640, height=480)
        frame = gen.generate()
        self.assertIsInstance(frame, Image.Image)

    def test_noise_frame_correct_resolution(self):
        from camera import FrameGenerator
        gen = FrameGenerator(mode="noise", width=320, height=240)
        frame = gen.generate()
        self.assertEqual(frame.size, (320, 240))

    def test_noise_frames_differ(self):
        from camera import FrameGenerator
        gen = FrameGenerator(mode="noise", width=64, height=64)
        f1 = gen.generate()
        f2 = gen.generate()
        self.assertNotEqual(f1.tobytes(), f2.tobytes())


class TestVideoMode(unittest.TestCase):
    """Video file mode: stub that raises if file not found."""

    def test_video_mode_raises_without_file(self):
        from camera import FrameGenerator
        with self.assertRaises((FileNotFoundError, ValueError)):
            FrameGenerator(mode="video", width=640, height=480, video_file="/nonexistent.mp4")


class TestJPEGEncoding(unittest.TestCase):
    """Frame to JPEG encoding."""

    def test_encode_jpeg_returns_bytes(self):
        from camera import FrameGenerator
        gen = FrameGenerator(mode="procedural", width=640, height=480)
        jpeg_data = gen.encode_jpeg()
        self.assertIsInstance(jpeg_data, bytes)

    def test_jpeg_starts_with_marker(self):
        from camera import FrameGenerator
        gen = FrameGenerator(mode="procedural", width=640, height=480)
        jpeg_data = gen.encode_jpeg()
        # JPEG files start with FF D8 FF
        self.assertTrue(jpeg_data[:2] == b'\xff\xd8')

    def test_jpeg_is_valid_image(self):
        from camera import FrameGenerator
        gen = FrameGenerator(mode="procedural", width=640, height=480)
        jpeg_data = gen.encode_jpeg()
        img = Image.open(io.BytesIO(jpeg_data))
        self.assertEqual(img.format, "JPEG")
        self.assertEqual(img.size, (640, 480))

    def test_encode_jpeg_quality(self):
        """Higher quality should produce larger file."""
        from camera import FrameGenerator
        gen = FrameGenerator(mode="procedural", width=640, height=480)
        gen.generate()  # Generate a frame first
        low_q = gen.encode_jpeg(quality=10)
        high_q = gen.encode_jpeg(quality=95)
        self.assertGreater(len(high_q), len(low_q))


if __name__ == "__main__":
    unittest.main()
