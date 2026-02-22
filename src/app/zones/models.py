"""Zone and ZoneEvent models for area-based monitoring."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import json


class ZoneType(str, Enum):
    """Types of monitoring zones."""
    ENTRY_EXIT = "entry_exit"       # Track who enters/exits
    ACTIVITY = "activity"           # Track all activity in area
    TRIPWIRE = "tripwire"           # Line crossing detection
    OBJECT_MONITOR = "object_monitor"  # Monitor specific object (dumpster, car, etc.)


class ZoneEventType(str, Enum):
    """Types of zone events."""
    ENTER = "enter"
    EXIT = "exit"
    ACTIVITY = "activity"
    STATE_CHANGE = "state_change"   # For object_monitor (opened/closed)
    LINGER = "linger"               # Target stayed too long


@dataclass
class Zone:
    """A monitoring zone on a camera view."""

    zone_id: str
    camera_id: int
    name: str
    polygon: list[tuple[int, int]]  # List of (x, y) points
    zone_type: ZoneType
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)

    # For object_monitor type
    monitored_object: Optional[str] = None  # "dumpster", "garage_door", etc.
    baseline_state: Optional[str] = None    # "closed", "empty", etc.

    # Alert settings
    alert_on_enter: bool = True
    alert_on_exit: bool = False
    alert_on_linger: bool = False
    linger_threshold_seconds: int = 60
    cooldown_seconds: int = 30

    # Statistics
    total_events: int = 0
    last_event_at: Optional[datetime] = None

    def contains_point(self, x: int, y: int) -> bool:
        """Check if a point is inside this zone polygon."""
        n = len(self.polygon)
        if n < 3:
            return False

        inside = False
        j = n - 1

        for i in range(n):
            xi, yi = self.polygon[i]
            xj, yj = self.polygon[j]

            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i

        return inside

    def contains_bbox(self, bbox: tuple[int, int, int, int], threshold: float = 0.5) -> bool:
        """Check if a bounding box overlaps with this zone.

        Args:
            bbox: (x1, y1, x2, y2) bounding box
            threshold: Fraction of bbox that must be inside zone

        Returns:
            True if bbox overlaps zone above threshold
        """
        x1, y1, x2, y2 = bbox
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2

        # Quick check: is center inside?
        if self.contains_point(center_x, center_y):
            return True

        # Check corners
        corners = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]
        inside_count = sum(1 for cx, cy in corners if self.contains_point(cx, cy))

        return inside_count / 4 >= threshold

    def to_dict(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "camera_id": self.camera_id,
            "name": self.name,
            "polygon": self.polygon,
            "zone_type": self.zone_type.value,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "monitored_object": self.monitored_object,
            "baseline_state": self.baseline_state,
            "alert_on_enter": self.alert_on_enter,
            "alert_on_exit": self.alert_on_exit,
            "alert_on_linger": self.alert_on_linger,
            "linger_threshold_seconds": self.linger_threshold_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "total_events": self.total_events,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Zone":
        return cls(
            zone_id=data["zone_id"],
            camera_id=data["camera_id"],
            name=data["name"],
            polygon=[tuple(p) for p in data["polygon"]],
            zone_type=ZoneType(data["zone_type"]),
            enabled=data.get("enabled", True),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            monitored_object=data.get("monitored_object"),
            baseline_state=data.get("baseline_state"),
            alert_on_enter=data.get("alert_on_enter", True),
            alert_on_exit=data.get("alert_on_exit", False),
            alert_on_linger=data.get("alert_on_linger", False),
            linger_threshold_seconds=data.get("linger_threshold_seconds", 60),
            cooldown_seconds=data.get("cooldown_seconds", 30),
            total_events=data.get("total_events", 0),
            last_event_at=datetime.fromisoformat(data["last_event_at"]) if data.get("last_event_at") else None,
        )


@dataclass
class ZoneEvent:
    """An event that occurred in a zone."""

    event_id: str
    zone_id: str
    zone_name: str
    event_type: ZoneEventType
    timestamp: datetime
    camera_id: int

    # Target that triggered the event
    target_id: Optional[str] = None
    target_type: Optional[str] = None  # person, vehicle, etc.
    target_thumbnail_id: Optional[str] = None

    # Event details
    duration_seconds: Optional[float] = None  # For linger events
    state_before: Optional[str] = None  # For state_change
    state_after: Optional[str] = None   # For state_change

    # Media
    video_path: Optional[str] = None
    frame_number: Optional[int] = None
    thumbnail_path: Optional[str] = None
    clip_path: Optional[str] = None  # Short clip of event

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "camera_id": self.camera_id,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "target_thumbnail_id": self.target_thumbnail_id,
            "duration_seconds": self.duration_seconds,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "video_path": self.video_path,
            "frame_number": self.frame_number,
            "thumbnail_path": self.thumbnail_path,
            "clip_path": self.clip_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ZoneEvent":
        return cls(
            event_id=data["event_id"],
            zone_id=data["zone_id"],
            zone_name=data["zone_name"],
            event_type=ZoneEventType(data["event_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            camera_id=data["camera_id"],
            target_id=data.get("target_id"),
            target_type=data.get("target_type"),
            target_thumbnail_id=data.get("target_thumbnail_id"),
            duration_seconds=data.get("duration_seconds"),
            state_before=data.get("state_before"),
            state_after=data.get("state_after"),
            video_path=data.get("video_path"),
            frame_number=data.get("frame_number"),
            thumbnail_path=data.get("thumbnail_path"),
            clip_path=data.get("clip_path"),
        )
