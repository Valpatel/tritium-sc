# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Fake YOLO detection generator.

Produces detection payloads in TRITIUM standard format:
  {
    "boxes": [ { "label", "confidence", "center_x", "center_y", "bbox" } ],
    "camera_id": "...",
    "timestamp": "2026-02-27T12:00:00Z",
    "frame_id": 1234
  }
"""
import random
from datetime import datetime, timezone


# Labels with relative frequency weights
_LABELS = [
    ("person", 5),
    ("vehicle", 3),
    ("animal", 2),
]
_LABEL_NAMES = [l[0] for l in _LABELS]
_LABEL_WEIGHTS = [l[1] for l in _LABELS]


class DetectionGenerator:
    """Generates fake YOLO-style detections with configurable rate."""

    def __init__(
        self,
        camera_id: str = "demo-cam-01",
        detection_rate: float = 0.3,
        max_boxes: int = 5,
    ):
        """
        Args:
            camera_id: Camera identifier for the payload.
            detection_rate: Probability (0.0-1.0) that any given frame
                            contains detections.
            max_boxes: Maximum number of boxes per frame when detections occur.
        """
        self.camera_id = camera_id
        self.detection_rate = max(0.0, min(1.0, detection_rate))
        self.max_boxes = max(1, max_boxes)

    def generate(self, frame_id: int) -> dict:
        """Generate a detection payload for one frame.

        Args:
            frame_id: Sequential frame number.

        Returns:
            Detection dict matching TRITIUM standard format.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        boxes = []
        if random.random() < self.detection_rate:
            n_boxes = random.randint(1, self.max_boxes)
            for _ in range(n_boxes):
                boxes.append(self._random_box())

        return {
            "boxes": boxes,
            "camera_id": self.camera_id,
            "timestamp": timestamp,
            "frame_id": frame_id,
        }

    def _random_box(self) -> dict:
        """Generate a single random detection box."""
        label = random.choices(_LABEL_NAMES, weights=_LABEL_WEIGHTS, k=1)[0]

        # Confidence in realistic range (0.3 - 0.99)
        confidence = round(random.uniform(0.3, 0.99), 2)

        # Random box position and size (normalized 0-1)
        box_w = random.uniform(0.05, 0.35)
        box_h = random.uniform(0.05, 0.40)
        x1 = random.uniform(0.0, 1.0 - box_w)
        y1 = random.uniform(0.0, 1.0 - box_h)
        x2 = x1 + box_w
        y2 = y1 + box_h

        center_x = round((x1 + x2) / 2, 4)
        center_y = round((y1 + y2) / 2, 4)

        return {
            "label": label,
            "confidence": confidence,
            "center_x": center_x,
            "center_y": center_y,
            "bbox": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
        }
