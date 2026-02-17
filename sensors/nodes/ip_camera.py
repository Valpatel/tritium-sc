"""RTSP/NVR IP camera sensor node (view-only).

Phase 2 stub — reads RTSP streams via OpenCV.  No PTZ, no audio.
"""

from __future__ import annotations

from .base import SensorNode


class IPCameraNode(SensorNode):
    """IP camera connected via RTSP — view-only, no PTZ or audio.

    TODO Phase 2: Implement RTSP stream reading via OpenCV or go2rtc.
    """

    def __init__(
        self,
        node_id: str,
        name: str,
        rtsp_url: str,
    ):
        super().__init__(node_id, name)
        self.rtsp_url = rtsp_url

    @property
    def has_camera(self) -> bool:
        return True
