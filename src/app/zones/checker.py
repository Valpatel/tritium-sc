"""Zone detection checker for integration with video analysis pipeline."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from app.zones.manager import ZoneManager
from app.zones.models import Zone, ZoneEvent


class ZoneChecker:
    """Checks detections against defined zones and triggers events."""

    def __init__(self, zone_manager: ZoneManager):
        """Initialize zone checker.

        Args:
            zone_manager: ZoneManager instance to use
        """
        self.manager = zone_manager
        self._camera_zones_cache: dict[int, list[Zone]] = {}

    def get_zones_for_camera(self, camera_id: int) -> list[Zone]:
        """Get cached zones for a camera."""
        if camera_id not in self._camera_zones_cache:
            self._camera_zones_cache[camera_id] = self.manager.get_zones_for_camera(camera_id)
        return self._camera_zones_cache[camera_id]

    def clear_cache(self):
        """Clear the zone cache (call when zones are modified)."""
        self._camera_zones_cache.clear()

    def check_frame_detections(
        self,
        camera_id: int,
        detections: list,  # List of Detection objects from detector
        timestamp: datetime,
        video_path: str,
        frame_number: int,
    ) -> list[ZoneEvent]:
        """Check if any detections in a frame trigger zone events.

        Args:
            camera_id: Camera ID
            detections: List of Detection objects with bbox, class_name, etc.
            timestamp: Frame timestamp
            video_path: Source video path
            frame_number: Frame number in video

        Returns:
            List of triggered ZoneEvent objects
        """
        zones = self.get_zones_for_camera(camera_id)
        if not zones:
            return []

        # Convert detections to dict format for manager
        detection_dicts = []
        for det in detections:
            detection_dicts.append({
                "bbox": det.bbox,
                "class_name": det.class_name,
                "confidence": det.confidence,
                "center": det.center,
                "track_id": getattr(det, 'track_id', None),
            })

        return self.manager.check_detections(
            camera_id=camera_id,
            detections=detection_dicts,
            timestamp=timestamp,
            video_path=video_path,
            frame_number=frame_number,
        )


def get_zone_checker() -> Optional[ZoneChecker]:
    """Get a zone checker instance if zones are configured.

    Returns:
        ZoneChecker instance or None if zones module not available
    """
    try:
        from app.config import settings
        storage_path = settings.recordings_path / ".cache" / "zones"
        manager = ZoneManager(storage_path)
        return ZoneChecker(manager)
    except Exception as e:
        logger.warning(f"Could not initialize zone checker: {e}")
        return None
