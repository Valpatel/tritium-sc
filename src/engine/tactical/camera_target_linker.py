# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""CameraTargetLinker — auto-link camera detections to targets via FOV geometry.

When a YOLO detection occurs, this module checks if any registered camera's
FOV cone covers the detection position.  If so, it creates a
CameraDetectionLink associating the detection with that camera and the
matching target.

Uses camera placement data (position, FOV degrees, rotation) from the
camera_feeds plugin and detection data from the yolo_detector plugin.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from tritium_lib.geo import haversine_distance as _haversine_m

logger = logging.getLogger("camera-target-linker")


@dataclass
class CameraPlacement:
    """Camera position and FOV geometry for link matching."""
    camera_id: str
    lat: float = 0.0
    lng: float = 0.0
    fov_degrees: float = 90.0
    rotation_degrees: float = 0.0  # clockwise from north
    max_range_m: float = 50.0  # max detection range in meters


@dataclass
class DetectionLinkRecord:
    """Record of a camera-detection-target link."""
    link_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    detection_id: str = ""
    camera_id: str = ""
    target_id: str = ""
    class_name: str = ""
    position_in_frame_x: float = 0.0
    position_in_frame_y: float = 0.0
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)
    bbox_area: float = 0.0

    def to_dict(self) -> dict:
        return {
            "link_id": self.link_id,
            "detection_id": self.detection_id,
            "camera_id": self.camera_id,
            "target_id": self.target_id,
            "class_name": self.class_name,
            "position_in_frame": {
                "x": self.position_in_frame_x,
                "y": self.position_in_frame_y,
            },
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "bbox_area": self.bbox_area,
        }



def _bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Bearing in degrees (0=north, clockwise) from point 1 to point 2."""
    dlng = math.radians(lng2 - lng1)
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    x = math.sin(dlng) * math.cos(lat2r)
    y = (math.cos(lat1r) * math.sin(lat2r) -
         math.sin(lat1r) * math.cos(lat2r) * math.cos(dlng))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _angle_diff(a: float, b: float) -> float:
    """Smallest angle difference between two bearings (0-180)."""
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


class CameraTargetLinker:
    """Auto-links YOLO detections to cameras based on FOV geometry.

    Maintains a registry of camera placements and processes detection
    events to create links when a detection falls within a camera's FOV.

    Parameters
    ----------
    event_bus:
        Optional EventBus for publishing link events.
    max_links:
        Maximum stored link records (FIFO eviction).
    """

    def __init__(
        self,
        event_bus: Any = None,
        max_links: int = 5000,
    ) -> None:
        self._cameras: dict[str, CameraPlacement] = {}
        self._links: list[DetectionLinkRecord] = []
        self._max_links = max_links
        self._event_bus = event_bus
        self._total_checked = 0
        self._total_linked = 0

    def register_camera(self, placement: CameraPlacement) -> None:
        """Register or update a camera placement."""
        self._cameras[placement.camera_id] = placement
        logger.debug(
            "Camera registered: %s (%.4f, %.4f, FOV=%.0f, rot=%.0f)",
            placement.camera_id, placement.lat, placement.lng,
            placement.fov_degrees, placement.rotation_degrees,
        )

    def remove_camera(self, camera_id: str) -> None:
        """Remove a camera from the registry."""
        self._cameras.pop(camera_id, None)

    def get_cameras(self) -> list[CameraPlacement]:
        """Return all registered camera placements."""
        return list(self._cameras.values())

    def process_detection(
        self,
        detection_id: str,
        class_name: str,
        confidence: float,
        target_lat: float,
        target_lng: float,
        target_id: str = "",
        bbox_center: tuple[float, float] = (0.5, 0.5),
        bbox_area: float = 0.0,
    ) -> list[DetectionLinkRecord]:
        """Check if a detection falls within any camera's FOV and create links.

        Parameters
        ----------
        detection_id:
            Unique detection event ID.
        class_name:
            Detected object class (person, vehicle, etc.).
        confidence:
            Detection confidence (0.0-1.0).
        target_lat, target_lng:
            Geo position of the detected target.
        target_id:
            Target tracker ID (if known).
        bbox_center:
            Normalized bounding box center (x, y) in frame coordinates.
        bbox_area:
            Normalized bounding box area.

        Returns
        -------
        list[DetectionLinkRecord]:
            Links created for cameras whose FOV covers this detection.
        """
        self._total_checked += 1
        created_links: list[DetectionLinkRecord] = []

        for cam in self._cameras.values():
            if cam.lat == 0.0 and cam.lng == 0.0:
                continue

            # Distance check
            dist = _haversine_m(cam.lat, cam.lng, target_lat, target_lng)
            if dist > cam.max_range_m:
                continue

            # Bearing check — is the target within the camera's FOV cone?
            bearing = _bearing_deg(cam.lat, cam.lng, target_lat, target_lng)
            angle_from_center = _angle_diff(bearing, cam.rotation_degrees)
            half_fov = cam.fov_degrees / 2.0

            if angle_from_center > half_fov:
                continue

            # Target is within this camera's FOV
            link = DetectionLinkRecord(
                detection_id=detection_id,
                camera_id=cam.camera_id,
                target_id=target_id,
                class_name=class_name,
                position_in_frame_x=bbox_center[0],
                position_in_frame_y=bbox_center[1],
                confidence=confidence,
                bbox_area=bbox_area,
            )

            self._links.append(link)
            created_links.append(link)
            self._total_linked += 1

            # Evict oldest if over limit
            if len(self._links) > self._max_links:
                self._links = self._links[-self._max_links:]

            logger.info(
                "Camera link: %s -> %s (cam=%s, dist=%.1fm, angle=%.1f)",
                detection_id, target_id, cam.camera_id, dist, angle_from_center,
            )

        # Publish link events
        if created_links and self._event_bus is not None:
            for link in created_links:
                self._event_bus.publish("camera:detection_link", data=link.to_dict())

        return created_links

    def get_links_for_target(self, target_id: str, limit: int = 50) -> list[dict]:
        """Get all camera links for a specific target."""
        return [
            link.to_dict()
            for link in reversed(self._links)
            if link.target_id == target_id
        ][:limit]

    def get_links_for_camera(self, camera_id: str, limit: int = 50) -> list[dict]:
        """Get all detection links for a specific camera."""
        return [
            link.to_dict()
            for link in reversed(self._links)
            if link.camera_id == camera_id
        ][:limit]

    def get_recent_links(self, limit: int = 100) -> list[dict]:
        """Get most recent links across all cameras."""
        return [link.to_dict() for link in reversed(self._links)][:limit]

    @property
    def stats(self) -> dict:
        """Return linker statistics."""
        return {
            "cameras_registered": len(self._cameras),
            "total_links": len(self._links),
            "total_checked": self._total_checked,
            "total_linked": self._total_linked,
            "link_rate": (
                self._total_linked / self._total_checked
                if self._total_checked > 0 else 0.0
            ),
        }
