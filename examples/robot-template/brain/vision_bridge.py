# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Vision Bridge — converts YOLO detections into thinker-compatible targets.

YOLO runs fast (~10fps) for reactive tracking. The LLM thinker runs slow
(~5s cycles) for strategic decisions. This bridge accumulates YOLO detections
and converts them into the target format the thinker understands.

Pipeline:
    Camera (YOLO) → VisionBridge → Thinker (LLM)
    [10 fps detect]  [accumulate]   [5s think cycle]
"""
from __future__ import annotations

import threading
import time
from typing import Any


# Detection to target alliance mapping
_HOSTILE_LABELS = {"person"}  # In a nerf war, detected people are targets
_FRIENDLY_LABELS = {"robot", "car"}  # Our own units


class VisionBridge:
    """Accumulates YOLO detections and presents them as nearby targets.

    Thread-safe. Camera thread pushes detections, thinker thread reads targets.
    """

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self._detections: list[dict] = []
        self._lock = threading.Lock()
        self._max_age = config.get("max_detection_age", 5.0)
        self._max_targets = config.get("max_targets", 10)
        # Map from label to game coords requires camera-to-world calibration.
        # For now, we use normalized image coords as rough position.
        self._field_of_view = config.get("camera_fov", 60.0)  # degrees

    def push_detections(self, detections: list[dict]) -> None:
        """Push new YOLO detections (called from camera thread)."""
        now = time.monotonic()
        with self._lock:
            for det in detections:
                det["_timestamp"] = now
                self._detections.append(det)
            # Prune old and excess
            self._prune()

    def get_nearby_targets(
        self,
        robot_position: tuple[float, float] = (0.0, 0.0),
    ) -> list[dict]:
        """Get current targets for the thinker context.

        Returns list of dicts compatible with thinker.build_context(nearby_targets=...).
        """
        with self._lock:
            self._prune()
            targets = []
            for det in self._detections:
                label = det.get("label", "object")
                conf = det.get("confidence", 0.0)
                cx = det.get("center_x", 0.5)
                cy = det.get("center_y", 0.5)

                # Classify alliance based on label
                if label in _HOSTILE_LABELS:
                    alliance = "hostile"
                elif label in _FRIENDLY_LABELS:
                    alliance = "friendly"
                else:
                    alliance = "unknown"

                # Convert image coordinates to approximate world offset
                # center_x/center_y are 0.0-1.0 normalized image coords
                # Map to rough position relative to robot
                dx = (cx - 0.5) * self._field_of_view * 0.1  # rough meters
                dy = (0.5 - cy) * self._field_of_view * 0.1  # y is inverted

                targets.append({
                    "name": f"{label}-{len(targets)+1}",
                    "alliance": alliance,
                    "position": {
                        "x": robot_position[0] + dx,
                        "y": robot_position[1] + dy,
                    },
                    "label": label,
                    "confidence": conf,
                })

            return targets[:self._max_targets]

    @property
    def detection_count(self) -> int:
        with self._lock:
            return len(self._detections)

    def _prune(self) -> None:
        """Remove stale detections."""
        now = time.monotonic()
        self._detections = [
            d for d in self._detections
            if (now - d.get("_timestamp", 0)) < self._max_age
        ]
        # Keep only the most recent per label
        seen: dict[str, dict] = {}
        for det in reversed(self._detections):
            key = det.get("label", "object")
            if key not in seen:
                seen[key] = det
        self._detections = list(seen.values())
