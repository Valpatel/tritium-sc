# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for fake YOLO detection generator — written BEFORE implementation (TDD)."""
import json
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDetectionFormat(unittest.TestCase):
    """Detection output must match TRITIUM standard format."""

    def test_generate_returns_dict(self):
        from detector import DetectionGenerator
        det = DetectionGenerator(camera_id="test-cam-01")
        result = det.generate(frame_id=1)
        self.assertIsInstance(result, dict)

    def test_has_required_keys(self):
        from detector import DetectionGenerator
        det = DetectionGenerator(camera_id="test-cam-01")
        result = det.generate(frame_id=42)
        self.assertIn("boxes", result)
        self.assertIn("camera_id", result)
        self.assertIn("timestamp", result)
        self.assertIn("frame_id", result)

    def test_camera_id_matches(self):
        from detector import DetectionGenerator
        det = DetectionGenerator(camera_id="my-cam")
        result = det.generate(frame_id=1)
        self.assertEqual(result["camera_id"], "my-cam")

    def test_frame_id_matches(self):
        from detector import DetectionGenerator
        det = DetectionGenerator(camera_id="test-cam")
        result = det.generate(frame_id=99)
        self.assertEqual(result["frame_id"], 99)

    def test_timestamp_is_iso8601_utc(self):
        from detector import DetectionGenerator
        det = DetectionGenerator(camera_id="test-cam")
        result = det.generate(frame_id=1)
        ts = result["timestamp"]
        self.assertIsInstance(ts, str)
        # Must end with Z (UTC)
        self.assertTrue(ts.endswith("Z"), f"Timestamp should end with Z: {ts}")
        # Must be parseable as ISO8601
        from datetime import datetime
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_boxes_is_list(self):
        from detector import DetectionGenerator
        det = DetectionGenerator(camera_id="test-cam")
        result = det.generate(frame_id=1)
        self.assertIsInstance(result["boxes"], list)

    def test_result_is_json_serializable(self):
        from detector import DetectionGenerator
        det = DetectionGenerator(camera_id="test-cam")
        result = det.generate(frame_id=1)
        serialized = json.dumps(result)
        self.assertIsInstance(serialized, str)


class TestBoxFormat(unittest.TestCase):
    """Individual detection boxes must match the spec."""

    def _get_boxes(self, count=10):
        """Generate many detections to ensure we get some boxes."""
        from detector import DetectionGenerator
        det = DetectionGenerator(camera_id="test-cam", detection_rate=1.0)
        boxes = []
        for i in range(count):
            result = det.generate(frame_id=i)
            boxes.extend(result["boxes"])
        return boxes

    def test_box_has_label(self):
        boxes = self._get_boxes()
        self.assertGreater(len(boxes), 0, "Should generate at least one box")
        for box in boxes:
            self.assertIn("label", box)
            self.assertIsInstance(box["label"], str)

    def test_box_label_in_valid_set(self):
        boxes = self._get_boxes(50)
        valid_labels = {"person", "vehicle", "animal"}
        for box in boxes:
            self.assertIn(box["label"], valid_labels,
                          f"Label '{box['label']}' not in {valid_labels}")

    def test_box_has_confidence(self):
        boxes = self._get_boxes()
        for box in boxes:
            self.assertIn("confidence", box)
            self.assertIsInstance(box["confidence"], float)

    def test_confidence_in_range(self):
        boxes = self._get_boxes(50)
        for box in boxes:
            self.assertGreaterEqual(box["confidence"], 0.0)
            self.assertLessEqual(box["confidence"], 1.0)

    def test_confidence_realistic_range(self):
        """Confidence should typically be 0.3-0.99 (not always 0.0 or 1.0)."""
        boxes = self._get_boxes(100)
        confidences = [b["confidence"] for b in boxes]
        self.assertTrue(any(0.3 <= c <= 0.99 for c in confidences),
                        "At least some confidences should be in realistic range")

    def test_box_has_center_coords(self):
        boxes = self._get_boxes()
        for box in boxes:
            self.assertIn("center_x", box)
            self.assertIn("center_y", box)
            self.assertIsInstance(box["center_x"], float)
            self.assertIsInstance(box["center_y"], float)

    def test_center_coords_normalized(self):
        """Center coordinates should be normalized 0.0-1.0."""
        boxes = self._get_boxes(50)
        for box in boxes:
            self.assertGreaterEqual(box["center_x"], 0.0)
            self.assertLessEqual(box["center_x"], 1.0)
            self.assertGreaterEqual(box["center_y"], 0.0)
            self.assertLessEqual(box["center_y"], 1.0)

    def test_box_has_bbox(self):
        boxes = self._get_boxes()
        for box in boxes:
            self.assertIn("bbox", box)
            self.assertIsInstance(box["bbox"], list)
            self.assertEqual(len(box["bbox"]), 4)

    def test_bbox_values_normalized(self):
        """bbox [x1, y1, x2, y2] all normalized 0.0-1.0."""
        boxes = self._get_boxes(50)
        for box in boxes:
            for val in box["bbox"]:
                self.assertGreaterEqual(val, 0.0)
                self.assertLessEqual(val, 1.0)

    def test_bbox_x1_less_than_x2(self):
        boxes = self._get_boxes(50)
        for box in boxes:
            x1, y1, x2, y2 = box["bbox"]
            self.assertLess(x1, x2)
            self.assertLess(y1, y2)

    def test_center_within_bbox(self):
        boxes = self._get_boxes(50)
        for box in boxes:
            x1, y1, x2, y2 = box["bbox"]
            cx, cy = box["center_x"], box["center_y"]
            self.assertGreaterEqual(cx, x1)
            self.assertLessEqual(cx, x2)
            self.assertGreaterEqual(cy, y1)
            self.assertLessEqual(cy, y2)


class TestDetectionRate(unittest.TestCase):
    """Detection rate should be configurable."""

    def test_zero_rate_produces_empty_boxes(self):
        from detector import DetectionGenerator
        det = DetectionGenerator(camera_id="test-cam", detection_rate=0.0)
        for i in range(20):
            result = det.generate(frame_id=i)
            self.assertEqual(len(result["boxes"]), 0)

    def test_full_rate_always_produces_boxes(self):
        from detector import DetectionGenerator
        det = DetectionGenerator(camera_id="test-cam", detection_rate=1.0)
        for i in range(20):
            result = det.generate(frame_id=i)
            self.assertGreater(len(result["boxes"]), 0)

    def test_label_variety(self):
        """Over many detections, we should see all 3 label types."""
        from detector import DetectionGenerator
        det = DetectionGenerator(camera_id="test-cam", detection_rate=1.0)
        all_labels = set()
        for i in range(200):
            result = det.generate(frame_id=i)
            for box in result["boxes"]:
                all_labels.add(box["label"])
        self.assertIn("person", all_labels)
        self.assertIn("vehicle", all_labels)
        self.assertIn("animal", all_labels)


if __name__ == "__main__":
    unittest.main()
