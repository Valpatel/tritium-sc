"""SyntheticCameraNode — generates MJPEG from simulation state.

Provides a bird's-eye view of the battlespace as if from a virtual overhead
camera. Each target is rendered as a colored rectangle with label. Implements
the SensorNode interface so Amy can treat it like any other camera.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

from amy.nodes.base import Position, SensorNode

if TYPE_CHECKING:
    from amy.simulation.engine import SimulationEngine


# Alliance -> BGR color map
_ALLIANCE_COLORS = {
    "friendly": (161, 255, 5),   # Green
    "hostile": (109, 42, 255),   # Red
    "neutral": (255, 160, 0),    # Blue
    "unknown": (10, 238, 252),   # Yellow
}


class SyntheticCameraNode(SensorNode):
    """Renders simulation state as camera frames at configurable FPS."""

    def __init__(
        self,
        engine: SimulationEngine,
        node_id: str = "syn-cam-0",
        name: str = "Simulation Camera",
        fps: int = 10,
        width: int = 640,
        height: int = 480,
    ) -> None:
        super().__init__(node_id, name)
        self._engine = engine
        self._fps = fps
        self._width = width
        self._height = height
        self._view_center = [0.0, 0.0]
        self._view_radius = 35.0
        self._frame: np.ndarray | None = None
        self._jpeg: bytes | None = None
        self._frame_lock = threading.Lock()
        self._frame_count = 0
        self._running = False
        self._thread: threading.Thread | None = None

    # -- SensorNode properties -----------------------------------------------

    @property
    def has_camera(self) -> bool:
        return True

    @property
    def has_ptz(self) -> bool:
        return True

    @property
    def frame_id(self) -> int:
        return self._frame_count

    # -- Camera interface ----------------------------------------------------

    def get_frame(self) -> np.ndarray | None:
        with self._frame_lock:
            return self._frame.copy() if self._frame is not None else None

    def get_jpeg(self) -> bytes | None:
        with self._frame_lock:
            return self._jpeg

    # -- PTZ interface -------------------------------------------------------

    def move(self, pan_dir: int, tilt_dir: int, duration: float) -> tuple[bool, bool]:
        self._view_center[0] += pan_dir * 5.0
        self._view_center[1] += tilt_dir * 5.0
        return (pan_dir != 0, tilt_dir != 0)

    def get_position(self) -> Position:
        return Position(pan=self._view_center[0], tilt=self._view_center[1])

    def reset_position(self) -> None:
        self._view_center = [0.0, 0.0]

    # -- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._render_loop, daemon=True, name="syn-cam",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # -- Rendering -----------------------------------------------------------

    def _render_loop(self) -> None:
        interval = 1.0 / self._fps
        while self._running:
            try:
                frame = self._render_frame()
                _, jpeg_buf = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80],
                )
                with self._frame_lock:
                    self._frame = frame
                    self._jpeg = jpeg_buf.tobytes()
                    self._frame_count += 1
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug("SyntheticCameraNode render error: %s", e)
            time.sleep(interval)

    def _world_to_pixel(self, wx: float, wy: float) -> tuple[int, int]:
        """Convert world coordinates to pixel coordinates."""
        cx, cy = self._view_center
        scale = min(self._width, self._height) / (2.0 * self._view_radius)
        px = int(self._width / 2 + (wx - cx) * scale)
        py = int(self._height / 2 - (wy - cy) * scale)  # Y inverted
        return px, py

    def _render_frame(self) -> np.ndarray:
        """Render current simulation state to a BGR frame."""
        frame = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        frame[:] = (12, 10, 10)  # Dark background

        # Grid lines every 5 world-units
        for g in range(-30, 31, 5):
            px, _ = self._world_to_pixel(g, 0)
            if 0 <= px < self._width:
                cv2.line(frame, (px, 0), (px, self._height), (20, 20, 20), 1)
            _, py = self._world_to_pixel(0, g)
            if 0 <= py < self._height:
                cv2.line(frame, (0, py), (self._width, py), (20, 20, 20), 1)

        # Draw targets from engine
        targets = self._engine.get_targets()
        for t in targets:
            px, py = self._world_to_pixel(t.position[0], t.position[1])
            if not (0 <= px < self._width and 0 <= py < self._height):
                continue

            color = _ALLIANCE_COLORS.get(t.alliance, _ALLIANCE_COLORS["unknown"])
            size = 8
            cv2.rectangle(
                frame, (px - size, py - size), (px + size, py + size), color, -1,
            )
            cv2.rectangle(
                frame, (px - size, py - size), (px + size, py + size), (255, 255, 255), 1,
            )

            label = t.target_id[:12]
            cv2.putText(
                frame, label, (px - size, py - size - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1,
            )

        # Timestamp overlay
        ts = time.strftime("%H:%M:%S")
        cv2.putText(
            frame, f"SYN-CAM | {ts} | {len(targets)} targets",
            (10, self._height - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1,
        )

        return frame
