"""Abstract SensorNode — the interface Amy uses to interact with hardware.

Each node is a physical or virtual endpoint that may provide:
- Camera (video frames, JPEG stream)
- PTZ (pan/tilt/zoom motor control)
- Microphone (audio input)
- Speaker (audio output)

Amy's Commander manages a dict of nodes.  Any mic can trigger wake word.
Each camera feeds YOLO detections into the sensorium with a source tag.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Position:
    """Camera PTZ position with limit awareness."""

    pan: float = 0.0
    tilt: float = 0.0
    zoom: float = 100.0
    pan_min: float | None = None
    pan_max: float | None = None
    tilt_min: float | None = None
    tilt_max: float | None = None

    @property
    def can_pan_left(self) -> bool:
        return self.pan_min is None or self.pan > self.pan_min

    @property
    def can_pan_right(self) -> bool:
        return self.pan_max is None or self.pan < self.pan_max

    @property
    def can_tilt_up(self) -> bool:
        return self.tilt_max is None or self.tilt < self.tilt_max

    @property
    def can_tilt_down(self) -> bool:
        return self.tilt_min is None or self.tilt > self.tilt_min


class SensorNode(ABC):
    """A sensor endpoint Amy can see/hear/speak through."""

    def __init__(self, node_id: str, name: str):
        self.node_id = node_id
        self.name = name

    @property
    def has_camera(self) -> bool:
        return False

    @property
    def has_ptz(self) -> bool:
        return False

    @property
    def has_mic(self) -> bool:
        return False

    @property
    def has_speaker(self) -> bool:
        return False

    # --- Camera ---

    def get_frame(self) -> np.ndarray | None:
        """Get the latest BGR frame (thread-safe copy)."""
        return None

    def get_jpeg(self) -> bytes | None:
        """Get the latest JPEG-encoded frame."""
        return None

    @property
    def frame_id(self) -> int:
        """Monotonic frame counter for dedup."""
        return 0

    # --- PTZ ---

    def move(self, pan_dir: int, tilt_dir: int, duration: float) -> tuple[bool, bool]:
        """Move camera. Returns (pan_moved, tilt_moved)."""
        return (False, False)

    def get_position(self) -> Position:
        """Get current PTZ position."""
        return Position()

    def reset_position(self) -> None:
        """Reset to default center position."""
        pass

    # --- Audio ---

    def record_audio(self, duration: float) -> np.ndarray | None:
        """Record audio from mic. Returns 16kHz float32 mono."""
        return None

    def play_audio(self, raw_pcm: bytes, sample_rate: int = 22050) -> None:
        """Play raw PCM audio through speaker."""
        pass

    # --- Lifecycle ---

    def start(self) -> None:
        """Start background threads (frame capture, etc.)."""
        pass

    def stop(self) -> None:
        """Stop and release resources."""
        pass
