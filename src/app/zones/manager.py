"""Zone manager for CRUD operations and event detection."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from app.zones.models import Zone, ZoneEvent, ZoneType, ZoneEventType


class ZoneManager:
    """Manages zones and zone events."""

    def __init__(self, storage_path: Path):
        """Initialize zone manager.

        Args:
            storage_path: Directory to store zone data
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.zones_file = self.storage_path / "zones.json"
        self.events_file = self.storage_path / "zone_events.json"

        self._zones: dict[str, Zone] = {}
        self._events: list[ZoneEvent] = []
        self._load()

    def _load(self):
        """Load zones and events from disk."""
        if self.zones_file.exists():
            try:
                with open(self.zones_file) as f:
                    data = json.load(f)
                    self._zones = {z["zone_id"]: Zone.from_dict(z) for z in data}
                logger.info(f"Loaded {len(self._zones)} zones")
            except Exception as e:
                logger.error(f"Failed to load zones: {e}")
                self._zones = {}

        if self.events_file.exists():
            try:
                with open(self.events_file) as f:
                    data = json.load(f)
                    self._events = [ZoneEvent.from_dict(e) for e in data]
                logger.info(f"Loaded {len(self._events)} zone events")
            except Exception as e:
                logger.error(f"Failed to load events: {e}")
                self._events = []

    def _save_zones(self):
        """Save zones to disk."""
        with open(self.zones_file, "w") as f:
            json.dump([z.to_dict() for z in self._zones.values()], f, indent=2)

    def _save_events(self):
        """Save events to disk."""
        # Keep last 10000 events
        recent_events = self._events[-10000:]
        with open(self.events_file, "w") as f:
            json.dump([e.to_dict() for e in recent_events], f, indent=2)

    # ==================
    # Zone CRUD
    # ==================

    def create_zone(
        self,
        camera_id: int,
        name: str,
        polygon: list[tuple[int, int]],
        zone_type: ZoneType,
        **kwargs,
    ) -> Zone:
        """Create a new zone.

        Args:
            camera_id: Camera this zone belongs to
            name: Human-readable name
            polygon: List of (x, y) vertices
            zone_type: Type of zone monitoring
            **kwargs: Additional zone settings

        Returns:
            Created Zone object
        """
        zone_id = f"zone_{uuid.uuid4().hex[:8]}"

        zone = Zone(
            zone_id=zone_id,
            camera_id=camera_id,
            name=name,
            polygon=polygon,
            zone_type=zone_type,
            **kwargs,
        )

        self._zones[zone_id] = zone
        self._save_zones()

        logger.info(f"Created zone '{name}' ({zone_type.value}) on camera {camera_id}")
        return zone

    def get_zone(self, zone_id: str) -> Optional[Zone]:
        """Get a zone by ID."""
        return self._zones.get(zone_id)

    def get_zones_for_camera(self, camera_id: int) -> list[Zone]:
        """Get all zones for a camera."""
        return [z for z in self._zones.values() if z.camera_id == camera_id]

    def get_all_zones(self) -> list[Zone]:
        """Get all zones."""
        return list(self._zones.values())

    def update_zone(self, zone_id: str, **updates) -> Optional[Zone]:
        """Update a zone.

        Args:
            zone_id: Zone to update
            **updates: Fields to update

        Returns:
            Updated zone or None if not found
        """
        zone = self._zones.get(zone_id)
        if not zone:
            return None

        for key, value in updates.items():
            if hasattr(zone, key):
                setattr(zone, key, value)

        self._save_zones()
        logger.info(f"Updated zone {zone_id}")
        return zone

    def delete_zone(self, zone_id: str) -> bool:
        """Delete a zone.

        Args:
            zone_id: Zone to delete

        Returns:
            True if deleted
        """
        if zone_id in self._zones:
            del self._zones[zone_id]
            self._save_zones()
            logger.info(f"Deleted zone {zone_id}")
            return True
        return False

    # ==================
    # Event Detection
    # ==================

    def check_detections(
        self,
        camera_id: int,
        detections: list[dict],
        timestamp: datetime,
        video_path: str,
        frame_number: int,
    ) -> list[ZoneEvent]:
        """Check if any detections trigger zone events.

        Args:
            camera_id: Camera the detections are from
            detections: List of detection dicts with bbox, class_name, etc.
            timestamp: Frame timestamp
            video_path: Source video path
            frame_number: Frame number in video

        Returns:
            List of triggered ZoneEvent objects
        """
        zones = self.get_zones_for_camera(camera_id)
        if not zones:
            return []

        triggered_events = []

        for zone in zones:
            if not zone.enabled:
                continue

            for det in detections:
                bbox = det.get("bbox", (0, 0, 0, 0))

                if zone.contains_bbox(bbox):
                    # Target is in zone
                    event = self._create_zone_event(
                        zone=zone,
                        detection=det,
                        timestamp=timestamp,
                        video_path=video_path,
                        frame_number=frame_number,
                    )

                    if event:
                        triggered_events.append(event)

        return triggered_events

    def _create_zone_event(
        self,
        zone: Zone,
        detection: dict,
        timestamp: datetime,
        video_path: str,
        frame_number: int,
    ) -> Optional[ZoneEvent]:
        """Create a zone event for a detection.

        Args:
            zone: Zone that was triggered
            detection: Detection that triggered it
            timestamp: When it happened
            video_path: Source video
            frame_number: Frame in video

        Returns:
            ZoneEvent or None if event should be suppressed
        """
        # Check cooldown
        if zone.last_event_at:
            elapsed = (timestamp - zone.last_event_at).total_seconds()
            if elapsed < zone.cooldown_seconds:
                return None  # Still in cooldown

        event_id = f"evt_{uuid.uuid4().hex[:8]}"

        event = ZoneEvent(
            event_id=event_id,
            zone_id=zone.zone_id,
            zone_name=zone.name,
            event_type=ZoneEventType.ACTIVITY,  # Default to activity
            timestamp=timestamp,
            camera_id=zone.camera_id,
            target_type=detection.get("class_name"),
            target_thumbnail_id=detection.get("thumbnail_id"),
            video_path=video_path,
            frame_number=frame_number,
        )

        # Update zone stats
        zone.total_events += 1
        zone.last_event_at = timestamp

        # Store event
        self._events.append(event)
        self._save_events()
        self._save_zones()

        logger.info(f"Zone event: {zone.name} - {detection.get('class_name')} at {timestamp}")

        return event

    # ==================
    # Event Queries
    # ==================

    def get_events_for_zone(
        self,
        zone_id: str,
        limit: int = 100,
        offset: int = 0,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[ZoneEvent]:
        """Get events for a specific zone.

        Args:
            zone_id: Zone to query
            limit: Max events to return
            offset: Skip first N events
            date_from: Start date filter (YYYY-MM-DD)
            date_to: End date filter (YYYY-MM-DD)

        Returns:
            List of ZoneEvent objects
        """
        events = [e for e in self._events if e.zone_id == zone_id]

        if date_from:
            events = [e for e in events if e.timestamp.strftime("%Y-%m-%d") >= date_from]
        if date_to:
            events = [e for e in events if e.timestamp.strftime("%Y-%m-%d") <= date_to]

        # Sort by timestamp descending (most recent first)
        events.sort(key=lambda e: e.timestamp, reverse=True)

        return events[offset:offset + limit]

    def get_events_by_target(
        self,
        target_type: Optional[str] = None,
        zone_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[ZoneEvent]:
        """Get events filtered by target type.

        Args:
            target_type: Filter by type (person, vehicle, etc.)
            zone_id: Filter by zone
            limit: Max events

        Returns:
            List of ZoneEvent objects
        """
        events = self._events

        if target_type:
            events = [e for e in events if e.target_type == target_type]
        if zone_id:
            events = [e for e in events if e.zone_id == zone_id]

        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    def get_zone_summary(self, zone_id: str) -> dict:
        """Get activity summary for a zone.

        Args:
            zone_id: Zone to summarize

        Returns:
            Summary dict with event counts, last activity, etc.
        """
        zone = self.get_zone(zone_id)
        if not zone:
            return {}

        events = self.get_events_for_zone(zone_id, limit=1000)

        # Count by target type
        type_counts = {}
        for e in events:
            t = e.target_type or "unknown"
            type_counts[t] = type_counts.get(t, 0) + 1

        # Count by hour
        hourly_counts = [0] * 24
        for e in events:
            hourly_counts[e.timestamp.hour] += 1

        peak_hour = hourly_counts.index(max(hourly_counts)) if any(hourly_counts) else None

        return {
            "zone_id": zone_id,
            "zone_name": zone.name,
            "zone_type": zone.zone_type.value,
            "total_events": zone.total_events,
            "last_event_at": zone.last_event_at.isoformat() if zone.last_event_at else None,
            "events_by_type": type_counts,
            "hourly_distribution": hourly_counts,
            "peak_hour": peak_hour,
            "recent_events": [e.to_dict() for e in events[:10]],
        }
