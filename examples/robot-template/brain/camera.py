"""Camera module — optional YOLO detection on onboard camera."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mqtt_client import RobotMQTTClient


class RobotCamera:
    """Onboard camera with optional YOLO detection.

    When enabled, captures frames and runs YOLO locally, publishing
    detections to MQTT so TRITIUM-SC can track what this robot sees.
    """

    def __init__(self, mqtt_client: RobotMQTTClient, config: dict) -> None:
        self._mqtt = mqtt_client
        cam_cfg = config.get("camera", {})
        self._enabled = cam_cfg.get("enabled", False)
        self._device = cam_cfg.get("device", 0)
        self._model_name = cam_cfg.get("yolo_model", "yolov8n.pt")
        self._interval = cam_cfg.get("detection_interval", 1.0)
        self._publish_frames = cam_cfg.get("publish_frames", False)
        self._running = False
        self._thread: threading.Thread | None = None
        self._cap = None
        self._model = None

    def start(self) -> None:
        if not self._enabled or self._running:
            return
        try:
            import cv2
            self._cap = cv2.VideoCapture(self._device)
            if not self._cap.isOpened():
                print(f"  Camera {self._device} failed to open")
                return
            print(f"  Camera {self._device} opened")
        except ImportError:
            print("  opencv-python not installed — camera disabled")
            return

        try:
            from ultralytics import YOLO
            self._model = YOLO(self._model_name)
            print(f"  YOLO model loaded: {self._model_name}")
        except ImportError:
            print("  ultralytics not installed — detection disabled")
            self._model = None

        self._running = True
        self._thread = threading.Thread(target=self._detect_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._cap:
            self._cap.release()

    def _detect_loop(self) -> None:
        import cv2
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            if self._model is not None:
                results = self._model(frame, verbose=False, conf=0.5)
                if results and len(results[0].boxes) > 0:
                    h, w = frame.shape[:2]
                    detections = []
                    boxes = results[0].boxes
                    for i in range(len(boxes)):
                        cls_id = int(boxes.cls[i])
                        cls_name = results[0].names.get(cls_id, "object")
                        conf = float(boxes.conf[i])
                        x1, y1, x2, y2 = boxes.xyxy[i].tolist()
                        detections.append({
                            "label": cls_name,
                            "confidence": round(conf, 3),
                            "center_x": round((x1 + x2) / 2 / w, 3),
                            "center_y": round((y1 + y2) / 2 / h, 3),
                            "bbox": [x1/w, y1/h, x2/w, y2/h],
                        })
                    if detections:
                        self._mqtt.publish_detection(detections)

            time.sleep(self._interval)
