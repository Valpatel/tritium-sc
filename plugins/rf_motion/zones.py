# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""RF motion zones — monitored areas defined by radio pairs.

An RFZone groups multiple radio pairs into a named area. Motion detected
in any pair within the zone triggers zone-level occupancy. Occupancy
tracking maintains a history of when the zone was occupied.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from .detector import RSSIMotionDetector, MotionEvent

log = logging.getLogger("rf-motion-zones")


@dataclass
class OccupancyRecord:
    """A period of zone occupancy."""
    start_time: float
    end_time: float = 0.0
    peak_confidence: float = 0.0
    event_count: int = 0

    @property
    def duration(self) -> float:
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time

    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": round(self.duration, 1),
            "peak_confidence": round(self.peak_confidence, 3),
            "event_count": self.event_count,
        }


@dataclass
class RFZone:
    """A monitored area defined by 2+ radio pairs."""

    zone_id: str
    name: str
    pair_ids: list[str] = field(default_factory=list)
    occupied: bool = False
    last_motion_time: float = 0.0
    occupancy_history: list[OccupancyRecord] = field(default_factory=list)
    _current_occupancy: OccupancyRecord | None = field(default=None, repr=False)

    # How long after last motion before zone is considered vacant (seconds)
    vacancy_timeout: float = 30.0

    # Max occupancy history records to keep
    max_history: int = 100

    def check_motion(self, events: list[MotionEvent], now: float | None = None) -> bool:
        """Check if any motion events match this zone's pairs.

        Returns True if zone state changed (occupied <-> vacant).
        """
        if now is None:
            now = time.time()

        zone_events = [e for e in events if e.pair_id in self.pair_ids]
        was_occupied = self.occupied

        if zone_events:
            self.last_motion_time = now
            best = max(zone_events, key=lambda e: e.confidence)

            if not self.occupied:
                # Zone just became occupied
                self.occupied = True
                self._current_occupancy = OccupancyRecord(
                    start_time=now,
                    peak_confidence=best.confidence,
                    event_count=1,
                )
            else:
                # Zone still occupied — update current record
                if self._current_occupancy is not None:
                    self._current_occupancy.event_count += len(zone_events)
                    if best.confidence > self._current_occupancy.peak_confidence:
                        self._current_occupancy.peak_confidence = best.confidence
        else:
            # No motion events for this zone
            if self.occupied and (now - self.last_motion_time) > self.vacancy_timeout:
                # Zone became vacant
                self.occupied = False
                if self._current_occupancy is not None:
                    self._current_occupancy.end_time = now
                    self.occupancy_history.append(self._current_occupancy)
                    # Trim history
                    if len(self.occupancy_history) > self.max_history:
                        self.occupancy_history = self.occupancy_history[-self.max_history:]
                    self._current_occupancy = None

        return self.occupied != was_occupied

    def to_dict(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "name": self.name,
            "pair_ids": self.pair_ids,
            "occupied": self.occupied,
            "last_motion_time": self.last_motion_time,
            "vacancy_timeout": self.vacancy_timeout,
            "occupancy_history": [r.to_dict() for r in self.occupancy_history[-10:]],
            "current_occupancy": (
                self._current_occupancy.to_dict()
                if self._current_occupancy is not None
                else None
            ),
        }


class ZoneManager:
    """Manages a collection of RF motion zones."""

    def __init__(self, detector: RSSIMotionDetector) -> None:
        self._detector = detector
        self._zones: dict[str, RFZone] = {}
        self._lock = threading.Lock()

    def add_zone(
        self,
        zone_id: str,
        name: str,
        pair_ids: list[str],
        vacancy_timeout: float = 30.0,
    ) -> RFZone:
        zone = RFZone(
            zone_id=zone_id,
            name=name,
            pair_ids=list(pair_ids),
            vacancy_timeout=vacancy_timeout,
        )
        with self._lock:
            self._zones[zone_id] = zone
        return zone

    def remove_zone(self, zone_id: str) -> bool:
        with self._lock:
            return self._zones.pop(zone_id, None) is not None

    def get_zone(self, zone_id: str) -> RFZone | None:
        with self._lock:
            return self._zones.get(zone_id)

    def list_zones(self) -> list[RFZone]:
        with self._lock:
            return list(self._zones.values())

    def check_all(self, events: list[MotionEvent] | None = None) -> list[RFZone]:
        """Check all zones against motion events. Returns zones that changed state."""
        if events is None:
            events = self._detector.detect()

        now = time.time()
        changed: list[RFZone] = []
        with self._lock:
            for zone in self._zones.values():
                if zone.check_motion(events, now):
                    changed.append(zone)
        return changed

    def get_occupied_zones(self) -> list[RFZone]:
        with self._lock:
            return [z for z in self._zones.values() if z.occupied]
