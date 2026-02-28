# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for VisionBridge — YOLO detection to thinker target conversion."""

import time
import pytest

# Add parent to path for imports
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain.vision_bridge import VisionBridge


class TestVisionBridgePush:
    """VisionBridge.push_detections — accumulates YOLO detections."""

    def test_push_single_detection(self):
        bridge = VisionBridge()
        bridge.push_detections([{
            "label": "person", "confidence": 0.95,
            "center_x": 0.5, "center_y": 0.6,
        }])
        assert bridge.detection_count == 1

    def test_push_multiple_detections(self):
        bridge = VisionBridge()
        bridge.push_detections([
            {"label": "person", "confidence": 0.9, "center_x": 0.3, "center_y": 0.4},
            {"label": "car", "confidence": 0.8, "center_x": 0.7, "center_y": 0.5},
        ])
        assert bridge.detection_count == 2

    def test_push_empty_list(self):
        bridge = VisionBridge()
        bridge.push_detections([])
        assert bridge.detection_count == 0


class TestVisionBridgeTargets:
    """VisionBridge.get_nearby_targets — converts detections to thinker format."""

    def test_person_is_hostile(self):
        bridge = VisionBridge()
        bridge.push_detections([{
            "label": "person", "confidence": 0.95,
            "center_x": 0.5, "center_y": 0.5,
        }])
        targets = bridge.get_nearby_targets()
        assert len(targets) == 1
        assert targets[0]["alliance"] == "hostile"

    def test_car_is_friendly(self):
        bridge = VisionBridge()
        bridge.push_detections([{
            "label": "car", "confidence": 0.8,
            "center_x": 0.5, "center_y": 0.5,
        }])
        targets = bridge.get_nearby_targets()
        assert len(targets) == 1
        assert targets[0]["alliance"] == "friendly"

    def test_unknown_label(self):
        bridge = VisionBridge()
        bridge.push_detections([{
            "label": "bicycle", "confidence": 0.7,
            "center_x": 0.5, "center_y": 0.5,
        }])
        targets = bridge.get_nearby_targets()
        assert len(targets) == 1
        assert targets[0]["alliance"] == "unknown"

    def test_target_has_position(self):
        bridge = VisionBridge()
        bridge.push_detections([{
            "label": "person", "confidence": 0.9,
            "center_x": 0.5, "center_y": 0.5,
        }])
        targets = bridge.get_nearby_targets(robot_position=(10.0, 5.0))
        assert len(targets) == 1
        pos = targets[0]["position"]
        assert "x" in pos
        assert "y" in pos

    def test_target_has_required_fields(self):
        bridge = VisionBridge()
        bridge.push_detections([{
            "label": "person", "confidence": 0.9,
            "center_x": 0.5, "center_y": 0.5,
        }])
        targets = bridge.get_nearby_targets()
        t = targets[0]
        assert "name" in t
        assert "alliance" in t
        assert "position" in t
        assert "label" in t
        assert "confidence" in t

    def test_max_targets_limit(self):
        bridge = VisionBridge({"max_targets": 3})
        bridge.push_detections([
            {"label": f"obj{i}", "confidence": 0.5, "center_x": 0.5, "center_y": 0.5}
            for i in range(10)
        ])
        targets = bridge.get_nearby_targets()
        assert len(targets) <= 3


class TestVisionBridgePruning:
    """VisionBridge — old detections get pruned."""

    def test_old_detections_pruned(self):
        bridge = VisionBridge({"max_detection_age": 0.1})
        bridge.push_detections([{
            "label": "person", "confidence": 0.9,
            "center_x": 0.5, "center_y": 0.5,
        }])
        assert bridge.detection_count == 1
        time.sleep(0.15)
        targets = bridge.get_nearby_targets()
        assert len(targets) == 0

    def test_dedup_same_label(self):
        """Multiple detections of same label keep only the latest."""
        bridge = VisionBridge()
        bridge.push_detections([{
            "label": "person", "confidence": 0.8,
            "center_x": 0.3, "center_y": 0.3,
        }])
        bridge.push_detections([{
            "label": "person", "confidence": 0.95,
            "center_x": 0.7, "center_y": 0.7,
        }])
        targets = bridge.get_nearby_targets()
        assert len(targets) == 1
        assert targets[0]["confidence"] == 0.95


class TestVisionBridgeIntegration:
    """VisionBridge + Thinker integration — detections feed into LLM context."""

    def test_targets_compatible_with_thinker(self):
        """Targets from bridge work with RobotThinker.build_context()."""
        from brain.thinker import RobotThinker
        bridge = VisionBridge()
        bridge.push_detections([{
            "label": "person", "confidence": 0.9,
            "center_x": 0.6, "center_y": 0.4,
        }])
        targets = bridge.get_nearby_targets(robot_position=(5.0, 3.0))

        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        ctx = thinker.build_context(
            telemetry={"position": {"x": 5.0, "y": 3.0}, "battery": 0.9, "status": "idle"},
            nearby_targets=targets,
        )
        assert "person" in ctx
        assert "hostile" in ctx
