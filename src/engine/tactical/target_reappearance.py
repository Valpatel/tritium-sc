# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TargetReappearanceMonitor — detect when lost targets return.

Tracks targets that go stale (pruned from the tracker) and notifies
operators when they reappear.  Useful for understanding movement
patterns and identifying surveillance-relevant behavior.

"Target ble_aabbcc returned after 15 minutes."
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("target-reappearance")


@dataclass
class DepartureRecord:
    """Record of a target that was last seen and then lost."""
    target_id: str
    name: str = ""
    source: str = ""
    asset_type: str = ""
    last_seen: float = 0.0  # monotonic time of last sighting
    departed_at: float = 0.0  # monotonic time when marked as departed
    last_position: tuple[float, float] = (0.0, 0.0)


@dataclass
class ReappearanceEvent:
    """Event emitted when a previously-departed target reappears."""
    target_id: str
    name: str = ""
    source: str = ""
    asset_type: str = ""
    absence_seconds: float = 0.0
    last_position: tuple[float, float] = (0.0, 0.0)
    return_position: tuple[float, float] = (0.0, 0.0)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "name": self.name,
            "source": self.source,
            "asset_type": self.asset_type,
            "absence_seconds": round(self.absence_seconds, 1),
            "absence_human": _format_duration(self.absence_seconds),
            "last_position": {"x": self.last_position[0], "y": self.last_position[1]},
            "return_position": {"x": self.return_position[0], "y": self.return_position[1]},
            "timestamp": self.timestamp,
            "message": (
                f"Target {self.name or self.target_id} returned after "
                f"{_format_duration(self.absence_seconds)}"
            ),
        }


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s" if secs else f"{mins}m"
    else:
        hours = int(seconds / 3600)
        mins = int((seconds % 3600) / 60)
        return f"{hours}h {mins}m" if mins else f"{hours}h"


class TargetReappearanceMonitor:
    """Monitors target departures and reappearances.

    Call ``check()`` periodically (e.g., every 5-10 seconds) with the
    current set of tracked target IDs and previously-tracked IDs.

    Parameters
    ----------
    event_bus:
        Optional EventBus for publishing reappearance notifications.
    min_absence_seconds:
        Minimum absence duration before a reappearance is noteworthy.
        Default 60 seconds (1 minute) to avoid noise from brief drops.
    max_tracked_departures:
        Maximum number of departed targets to remember. FIFO eviction.
    """

    def __init__(
        self,
        event_bus: Any = None,
        min_absence_seconds: float = 60.0,
        max_tracked_departures: int = 1000,
    ) -> None:
        self._event_bus = event_bus
        self._min_absence = min_absence_seconds
        self._max_departures = max_tracked_departures
        self._departed: dict[str, DepartureRecord] = {}
        self._known_ids: set[str] = set()  # IDs seen on last check
        self._total_departures = 0
        self._total_reappearances = 0
        self._recent_events: list[ReappearanceEvent] = []
        self._max_recent = 100

    def record_departure(
        self,
        target_id: str,
        name: str = "",
        source: str = "",
        asset_type: str = "",
        last_position: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        """Record that a target has departed (gone stale/pruned).

        Called when the TargetTracker prunes a stale target.
        """
        now = time.monotonic()
        self._departed[target_id] = DepartureRecord(
            target_id=target_id,
            name=name,
            source=source,
            asset_type=asset_type,
            last_seen=now,
            departed_at=now,
            last_position=last_position,
        )
        self._total_departures += 1

        # Evict oldest if over limit
        if len(self._departed) > self._max_departures:
            oldest_key = min(self._departed, key=lambda k: self._departed[k].departed_at)
            del self._departed[oldest_key]

        logger.debug("Target departed: %s (%s)", target_id, name)

    def check_reappearance(
        self,
        target_id: str,
        name: str = "",
        source: str = "",
        asset_type: str = "",
        position: tuple[float, float] = (0.0, 0.0),
    ) -> ReappearanceEvent | None:
        """Check if a target that just appeared was previously departed.

        Call this when a new target is added to the tracker.

        Returns
        -------
        ReappearanceEvent or None:
            Event if the target was previously departed and absence exceeds
            the minimum threshold.
        """
        if target_id not in self._departed:
            return None

        record = self._departed.pop(target_id)
        now = time.monotonic()
        absence = now - record.departed_at

        if absence < self._min_absence:
            return None

        event = ReappearanceEvent(
            target_id=target_id,
            name=name or record.name,
            source=source or record.source,
            asset_type=asset_type or record.asset_type,
            absence_seconds=absence,
            last_position=record.last_position,
            return_position=position,
        )

        self._total_reappearances += 1
        self._recent_events.append(event)
        if len(self._recent_events) > self._max_recent:
            self._recent_events = self._recent_events[-self._max_recent:]

        logger.info(
            "Target reappeared: %s after %s",
            target_id, _format_duration(absence),
        )

        # Publish to event bus
        if self._event_bus is not None:
            self._event_bus.publish(
                "target:reappearance",
                data=event.to_dict(),
            )

        return event

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        """Return recent reappearance events."""
        return [e.to_dict() for e in reversed(self._recent_events)][:limit]

    def get_departed(self) -> list[dict]:
        """Return currently departed targets."""
        now = time.monotonic()
        return [
            {
                "target_id": r.target_id,
                "name": r.name,
                "source": r.source,
                "asset_type": r.asset_type,
                "absent_seconds": round(now - r.departed_at, 1),
                "absent_human": _format_duration(now - r.departed_at),
                "last_position": {"x": r.last_position[0], "y": r.last_position[1]},
            }
            for r in self._departed.values()
        ]

    @property
    def stats(self) -> dict:
        """Return monitor statistics."""
        return {
            "total_departures": self._total_departures,
            "total_reappearances": self._total_reappearances,
            "currently_departed": len(self._departed),
            "recent_events": len(self._recent_events),
        }
