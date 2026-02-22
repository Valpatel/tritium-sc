"""ML integration tests for YOLO object detection."""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture(scope="module")
def yolo_model():
    """Load YOLO model once for the module (slow)."""
    from ultralytics import YOLO

    return YOLO("yolo11n.pt")


class TestYOLODetection:
    """Tests for YOLO model loading and inference."""

    def test_model_loads(self, yolo_model):
        """YOLO model loads successfully."""
        assert yolo_model is not None

    def test_detect_on_synthetic_frame(self, yolo_model):
        """Model runs inference on a blank 480x640 frame without error."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        results = yolo_model(frame, verbose=False)
        assert results is not None
        assert len(results) > 0

    def test_detection_result_structure(self, yolo_model):
        """Detection results have the expected boxes attribute."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        results = yolo_model(frame, verbose=False)
        # results[0].boxes exists even if 0 detections
        boxes = results[0].boxes
        assert hasattr(boxes, "cls")
        assert hasattr(boxes, "conf")
        assert hasattr(boxes, "xyxy")

    def test_vision_thread_tracked_classes(self):
        """VisionThread.TRACKED_CLASSES contains expected COCO class IDs."""
        from amy.commander import VisionThread

        tc = VisionThread.TRACKED_CLASSES
        assert tc[0] == "person"
        assert tc[15] == "cat"
        assert tc[16] == "dog"
        assert tc[62] == "tv"
        assert tc[63] == "laptop"
        assert tc[67] == "cell phone"
