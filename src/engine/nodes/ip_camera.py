# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""RTSP/NVR IP camera sensor node (view-only).

Reads RTSP streams via OpenCV with automatic reconnection.
No PTZ, no audio -- view-only camera for YOLO detection pipeline.
"""

from __future__ import annotations

import numpy as np

from .base import SensorNode
from .frame_buffer import ReconnectingFrameBuffer


class IPCameraNode(SensorNode):
    """IP camera connected via RTSP -- view-only, no PTZ or audio.

    Uses ReconnectingFrameBuffer for automatic RTSP stream recovery.
    Frames are available via get_frame()/get_jpeg() for YOLO and MJPEG.
    """

    def __init__(
        self,
        node_id: str,
        name: str,
        rtsp_url: str,
    ):
        super().__init__(node_id, name)
        self.rtsp_url = rtsp_url
        self._buffer: ReconnectingFrameBuffer | None = None

    @property
    def has_camera(self) -> bool:
        return True

    @property
    def has_ptz(self) -> bool:
        return False

    def start(self) -> None:
        self._buffer = ReconnectingFrameBuffer(self.rtsp_url)
        self._buffer.start()

    def stop(self) -> None:
        if self._buffer is not None:
            self._buffer.stop()
            self._buffer = None

    def get_frame(self) -> np.ndarray | None:
        if self._buffer is None:
            return None
        return self._buffer.frame

    def get_jpeg(self) -> bytes | None:
        if self._buffer is None:
            return None
        return self._buffer.jpeg

    @property
    def frame_id(self) -> int:
        if self._buffer is None:
            return 0
        return self._buffer.frame_id

    @property
    def frame_age(self) -> float:
        if self._buffer is None:
            return float("inf")
        return self._buffer.frame_age
