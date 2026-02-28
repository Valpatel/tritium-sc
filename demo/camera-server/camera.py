# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Frame generator for the demo camera server.

Modes:
  - procedural: colored rectangles on dark background (Pillow only)
  - noise: random pixel data (stress test)
  - video: loop a video file (stub -- raises if file not found)
"""
import io
import math
import os
import random
import time

from PIL import Image, ImageDraw


class FrameGenerator:
    """Generates camera frames using Pillow (no OpenCV)."""

    def __init__(
        self,
        mode: str = "procedural",
        width: int = 640,
        height: int = 480,
        video_file: str | None = None,
    ):
        self.mode = mode
        self.width = width
        self.height = height
        self.frame_count: int = 0
        self._current_frame: Image.Image | None = None
        self._start_time = time.monotonic()

        # Validate video mode
        if mode == "video":
            if not video_file or not os.path.isfile(video_file):
                raise FileNotFoundError(
                    f"Video file not found: {video_file}"
                )
            self._video_file = video_file

        # Pre-generate some random rectangles for procedural mode
        self._rects = self._init_procedural_rects()

    def _init_procedural_rects(self, count: int = 8) -> list[dict]:
        """Create a set of animated rectangles with velocities."""
        rects = []
        for _ in range(count):
            w = random.randint(20, max(30, self.width // 5))
            h = random.randint(20, max(30, self.height // 5))
            rects.append({
                "x": random.randint(0, max(1, self.width - w)),
                "y": random.randint(0, max(1, self.height - h)),
                "w": w,
                "h": h,
                "vx": random.uniform(-2, 2),
                "vy": random.uniform(-2, 2),
                "color": (
                    random.randint(30, 255),
                    random.randint(30, 255),
                    random.randint(30, 255),
                ),
            })
        return rects

    def generate(self) -> Image.Image:
        """Generate one frame. Returns a PIL Image in RGB mode."""
        if self.mode == "procedural":
            frame = self._generate_procedural()
        elif self.mode == "noise":
            frame = self._generate_noise()
        elif self.mode == "video":
            frame = self._generate_video()
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

        self._current_frame = frame
        self.frame_count += 1
        return frame

    def _generate_procedural(self) -> Image.Image:
        """Colored rectangles on a dark background, animated."""
        img = Image.new("RGB", (self.width, self.height), (15, 15, 25))
        draw = ImageDraw.Draw(img)

        # Animate rectangles
        for rect in self._rects:
            rect["x"] += rect["vx"]
            rect["y"] += rect["vy"]

            # Bounce off walls
            if rect["x"] < 0 or rect["x"] + rect["w"] > self.width:
                rect["vx"] *= -1
                rect["x"] = max(0, min(rect["x"], self.width - rect["w"]))
            if rect["y"] < 0 or rect["y"] + rect["h"] > self.height:
                rect["vy"] *= -1
                rect["y"] = max(0, min(rect["y"], self.height - rect["h"]))

            x1, y1 = int(rect["x"]), int(rect["y"])
            x2, y2 = x1 + rect["w"], y1 + rect["h"]
            draw.rectangle([x1, y1, x2, y2], fill=rect["color"])

        # Add timestamp text
        elapsed = time.monotonic() - self._start_time
        ts_text = f"F:{self.frame_count} T:{elapsed:.1f}s"
        draw.text((5, 5), ts_text, fill=(0, 240, 255))

        return img

    def _generate_noise(self) -> Image.Image:
        """Random noise pixels."""
        data = bytes(random.getrandbits(8) for _ in range(self.width * self.height * 3))
        img = Image.frombytes("RGB", (self.width, self.height), data)
        return img

    def _generate_video(self) -> Image.Image:
        """Loop frames from a video file. Stub for now."""
        # This would use imageio or similar to extract frames
        raise NotImplementedError("Video mode requires additional dependencies")

    def encode_jpeg(self, quality: int = 70) -> bytes:
        """Encode current (or newly generated) frame as JPEG bytes."""
        if self._current_frame is None:
            self.generate()
        buf = io.BytesIO()
        self._current_frame.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
