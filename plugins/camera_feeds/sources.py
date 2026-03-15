# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Camera source ABC and concrete implementations.

Each source type implements CameraSourceBase which provides a uniform
interface for getting frames, regardless of whether the camera is
synthetic, RTSP, MJPEG, MQTT, or USB.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator

import cv2
import numpy as np

log = logging.getLogger("camera-feeds")


@dataclass
class CameraSourceConfig:
    """Configuration for a camera source."""

    source_id: str
    source_type: str  # synthetic, rtsp, mjpeg, mqtt, usb
    name: str = ""
    width: int = 640
    height: int = 480
    fps: int = 10
    uri: str = ""  # RTSP/MJPEG URL, MQTT topic, USB device index
    extra: dict = field(default_factory=dict)


class CameraSourceBase(ABC):
    """Abstract base class for camera sources."""

    def __init__(self, config: CameraSourceConfig) -> None:
        self.config = config
        self._running = False
        self._last_frame: np.ndarray | None = None
        self._frame_count = 0
        self._created_at = datetime.now(timezone.utc).isoformat()
        self._lock = threading.Lock()

    @property
    def source_id(self) -> str:
        return self.config.source_id

    @property
    def source_type(self) -> str:
        return self.config.source_type

    @abstractmethod
    def start(self) -> None:
        """Start capturing frames."""

    @abstractmethod
    def stop(self) -> None:
        """Stop capturing frames."""

    @abstractmethod
    def get_frame(self) -> np.ndarray | None:
        """Return the latest BGR frame, or None if unavailable."""

    @property
    def is_running(self) -> bool:
        return self._running

    def get_snapshot(self, quality: int = 80) -> bytes | None:
        """Return a JPEG-encoded snapshot."""
        frame = self.get_frame()
        if frame is None:
            return None
        _, jpeg_buf = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality],
        )
        return jpeg_buf.tobytes()

    def mjpeg_frames(self) -> Generator[bytes, None, None]:
        """Yield MJPEG-formatted frames for streaming."""
        fps = max(1, self.config.fps)
        interval = 1.0 / fps
        while self._running:
            jpeg = self.get_snapshot()
            if jpeg is None:
                time.sleep(interval)
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                b"\r\n" + jpeg + b"\r\n"
            )
            time.sleep(interval)

    def to_dict(self) -> dict:
        """Serializable metadata dict."""
        return {
            "source_id": self.config.source_id,
            "source_type": self.config.source_type,
            "name": self.config.name or self.config.source_id,
            "width": self.config.width,
            "height": self.config.height,
            "fps": self.config.fps,
            "uri": self.config.uri,
            "running": self._running,
            "frame_count": self._frame_count,
            "created_at": self._created_at,
        }


class SyntheticSource(CameraSourceBase):
    """Wraps the existing synthetic video_gen renderers."""

    def __init__(self, config: CameraSourceConfig) -> None:
        super().__init__(config)
        self._seed = int(time.time() * 1000) % (2**31)
        self._renderer: Any = None
        self._scene_type = config.extra.get("scene_type", "bird_eye")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._load_renderer()

    def stop(self) -> None:
        self._running = False

    def _load_renderer(self) -> None:
        """Load the renderer function for the configured scene type."""
        try:
            from engine.synthetic.video_gen import (
                render_bird_eye,
                render_cctv_frame,
                render_street_cam,
                render_battle_scene,
                render_neighborhood,
            )
            renderers = {
                "bird_eye": render_bird_eye,
                "street_cam": render_street_cam,
                "battle": render_battle_scene,
                "neighborhood": render_neighborhood,
                "cctv": render_cctv_frame,
            }
            self._renderer = renderers.get(self._scene_type, render_bird_eye)
        except ImportError:
            log.warning("Synthetic video_gen not available")
            self._renderer = None

    def get_frame(self) -> np.ndarray | None:
        if self._renderer is None:
            return None

        kwargs: dict[str, Any] = {
            "resolution": (self.config.width, self.config.height),
            "seed": self._seed + self._frame_count,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }

        if self._scene_type in ("street_cam", "neighborhood", "cctv"):
            kwargs["camera_name"] = f"CAM-{self.config.source_id}"
        if self._scene_type == "cctv":
            kwargs["scene_type"] = "front_door"
            kwargs["frame_number"] = self._frame_count

        frame = self._renderer(**kwargs)
        self._frame_count += 1
        with self._lock:
            self._last_frame = frame
        return frame


class MQTTSource(CameraSourceBase):
    """Receives JPEG frames and detection events from MQTT cameras.

    Subscribes to the configured URI as an MQTT topic
    (e.g. ``tritium/{site}/cameras/{cam_id}/frame``) and decodes incoming
    JPEG payloads into BGR frames.  When wired to an MQTTBridge, also
    receives detection events and forwards them to the TargetTracker.
    """

    def __init__(self, config: CameraSourceConfig) -> None:
        super().__init__(config)
        self._topic = config.uri or f"tritium/+/camera"
        self._event_bus: Any = None
        self._mqtt_bridge: Any = None
        self._target_tracker: Any = None
        # Camera ID extracted from config for MQTT topic matching
        self._cam_id: str = config.extra.get("cam_id", config.source_id)
        # Detection stats
        self._detection_count: int = 0

    def set_event_bus(self, event_bus: Any) -> None:
        """Inject the EventBus for receiving MQTT-bridged frames."""
        self._event_bus = event_bus

    def set_mqtt_bridge(self, mqtt_bridge: Any) -> None:
        """Wire this source to an MQTTBridge to receive camera frames."""
        self._mqtt_bridge = mqtt_bridge
        mqtt_bridge.register_camera_callback(self._cam_id, self.on_frame)

    def set_target_tracker(self, tracker: Any) -> None:
        """Set the TargetTracker for detection -> target creation."""
        self._target_tracker = tracker

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        log.info("MQTTSource started, cam_id=%s topic=%s", self._cam_id, self._topic)

    def stop(self) -> None:
        self._running = False

    def on_frame(self, jpeg_bytes: bytes) -> None:
        """Called when a JPEG frame arrives from MQTT."""
        if not self._running:
            return
        try:
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                with self._lock:
                    self._last_frame = frame
                    self._frame_count += 1
        except Exception as exc:
            log.error("MQTTSource decode error: %s", exc)

    def on_detection(self, detection: dict) -> None:
        """Process a YOLO detection and create/update a TrackedTarget.

        Args:
            detection: Dict with keys: label, confidence, center_x, center_y.
        """
        self._detection_count += 1
        if self._target_tracker is not None:
            self._target_tracker.update_from_detection({
                "class_name": detection.get("label", "unknown"),
                "confidence": detection.get("confidence", 0.5),
                "center_x": detection.get("center_x", 0.5),
                "center_y": detection.get("center_y", 0.5),
                "source_camera": self._cam_id,
            })

    def get_frame(self) -> np.ndarray | None:
        with self._lock:
            return self._last_frame

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["cam_id"] = self._cam_id
        d["detection_count"] = self._detection_count
        return d


class RTSPSource(CameraSourceBase):
    """Captures frames from an RTSP stream via OpenCV.

    Uses a background thread with a 3-second timeout for the initial
    RTSP probe so unreachable cameras never block server startup.
    """

    OPEN_TIMEOUT = 3.0  # seconds — max time for RTSP probe

    def __init__(self, config: CameraSourceConfig) -> None:
        super().__init__(config)
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True,
            name=f"rtsp-{self.config.source_id}",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _open_capture(self) -> cv2.VideoCapture | None:
        """Open RTSP capture with a timeout to avoid blocking.

        Runs cv2.VideoCapture in a helper thread with a 3-second
        deadline.  Returns the capture if opened in time, else None.
        """
        result: list[cv2.VideoCapture | None] = [None]

        def _do_open():
            cap = cv2.VideoCapture(self.config.uri)
            result[0] = cap

        opener = threading.Thread(target=_do_open, daemon=True, name="rtsp-open")
        opener.start()
        opener.join(timeout=self.OPEN_TIMEOUT)

        if opener.is_alive():
            log.warning(
                "RTSP probe timed out after %.1fs: %s",
                self.OPEN_TIMEOUT, self.config.uri,
            )
            # Thread will finish eventually and the capture will be
            # garbage-collected; we just don't use it.
            return None

        cap = result[0]
        if cap is not None and cap.isOpened():
            return cap

        # Capture failed to open within timeout
        if cap is not None:
            cap.release()
        return None

    def _capture_loop(self) -> None:
        self._cap = self._open_capture()
        fps = max(1, self.config.fps)
        interval = 1.0 / fps
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                log.warning("RTSP stream not open: %s", self.config.uri)
                time.sleep(2.0)
                self._cap = self._open_capture()
                continue
            ret, frame = self._cap.read()
            if ret and frame is not None:
                if (frame.shape[1], frame.shape[0]) != (self.config.width, self.config.height):
                    frame = cv2.resize(frame, (self.config.width, self.config.height))
                with self._lock:
                    self._last_frame = frame
                    self._frame_count += 1
            time.sleep(interval)

    def get_frame(self) -> np.ndarray | None:
        with self._lock:
            return self._last_frame


class MJPEGSource(CameraSourceBase):
    """Captures frames from an MJPEG HTTP stream."""

    def __init__(self, config: CameraSourceConfig) -> None:
        super().__init__(config)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True,
            name=f"mjpeg-{self.config.source_id}",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def _capture_loop(self) -> None:
        import urllib.request
        while self._running:
            try:
                stream = urllib.request.urlopen(self.config.uri, timeout=10)
                buf = b""
                while self._running:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    # Find JPEG boundaries
                    start = buf.find(b"\xff\xd8")
                    end = buf.find(b"\xff\xd9")
                    if start != -1 and end != -1 and end > start:
                        jpg = buf[start:end + 2]
                        buf = buf[end + 2:]
                        arr = np.frombuffer(jpg, dtype=np.uint8)
                        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if frame is not None:
                            with self._lock:
                                self._last_frame = frame
                                self._frame_count += 1
            except Exception as exc:
                log.warning("MJPEG stream error (%s): %s", self.config.uri, exc)
                time.sleep(2.0)

    def get_frame(self) -> np.ndarray | None:
        with self._lock:
            return self._last_frame


class USBSource(CameraSourceBase):
    """Captures frames from a USB camera via OpenCV."""

    def __init__(self, config: CameraSourceConfig) -> None:
        super().__init__(config)
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        try:
            self._device_index = int(config.uri) if config.uri else 0
        except ValueError:
            self._device_index = 0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True,
            name=f"usb-{self.config.source_id}",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _capture_loop(self) -> None:
        self._cap = cv2.VideoCapture(self._device_index)
        if self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        fps = max(1, self.config.fps)
        interval = 1.0 / fps
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                log.warning("USB camera %d not available", self._device_index)
                time.sleep(2.0)
                continue
            ret, frame = self._cap.read()
            if ret and frame is not None:
                with self._lock:
                    self._last_frame = frame
                    self._frame_count += 1
            time.sleep(interval)

    def get_frame(self) -> np.ndarray | None:
        with self._lock:
            return self._last_frame


# Registry of source type -> class
SOURCE_TYPES: dict[str, type[CameraSourceBase]] = {
    "synthetic": SyntheticSource,
    "mqtt": MQTTSource,
    "rtsp": RTSPSource,
    "mjpeg": MJPEGSource,
    "usb": USBSource,
}
