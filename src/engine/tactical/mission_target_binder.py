# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Mission-Target Binding — auto-assign targets to active missions.

When a mission is active and has a geofence zone, any target detected
within that zone is automatically bound as a mission-relevant target.
This enables the mission panel to show which targets are inside the
mission's area of operations.

The MissionTargetBinder runs as a periodic check (every 2 seconds),
scanning active missions for geofence zones and comparing target
positions against those zones.

Supports both circle geofences (center + radius) and polygon geofences
(vertex list with point-in-polygon test).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("mission_target_binder")


def _point_in_circle(
    lat: float, lng: float,
    center_lat: float, center_lng: float, radius_m: float,
) -> bool:
    """Check if a lat/lng point is within a circle.

    Uses haversine approximation for short distances.
    """
    dlat = math.radians(lat - center_lat)
    dlng = math.radians(lng - center_lng)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(center_lat))
        * math.cos(math.radians(lat))
        * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance_m = 6371000 * c
    return distance_m <= radius_m


def _point_in_polygon(
    lat: float, lng: float,
    vertices: list[tuple[float, float]],
) -> bool:
    """Ray-casting point-in-polygon test.

    Vertices are (lat, lng) tuples forming a closed polygon.
    """
    n = len(vertices)
    if n < 3:
        return False

    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = vertices[i]
        yj, xj = vertices[j]
        if ((yi > lng) != (yj > lng)) and (lat < (xj - xi) * (lng - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


class MissionTargetBinder:
    """Binds detected targets to active missions based on geofence zones.

    Periodically checks all active missions for geofence zones and
    determines which tracked targets fall within those zones.

    Parameters
    ----------
    missions_store:
        Dict mapping mission_id -> Mission (the in-memory missions store).
    target_tracker:
        TargetTracker or equivalent with get_all_targets() method.
    event_bus:
        Optional EventBus for publishing binding events.
    check_interval:
        Seconds between binding checks.
    """

    def __init__(
        self,
        missions_store: dict,
        target_tracker: Any = None,
        event_bus: Any = None,
        check_interval: float = 2.0,
    ) -> None:
        self._missions = missions_store
        self._tracker = target_tracker
        self._event_bus = event_bus
        self._check_interval = check_interval

        # mission_id -> set of bound target_ids
        self._bindings: dict[str, set[str]] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the periodic binding check."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._binding_loop,
            name="mission-target-binder",
            daemon=True,
        )
        self._thread.start()
        logger.info("MissionTargetBinder started (interval=%.1fs)", self._check_interval)

    def stop(self) -> None:
        """Stop the binding check."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("MissionTargetBinder stopped")

    def _binding_loop(self) -> None:
        """Periodically check and bind targets to missions."""
        while self._running:
            try:
                self._check_bindings()
            except Exception as exc:
                logger.debug("Binding check error: %s", exc)
            time.sleep(self._check_interval)

    def _check_bindings(self) -> None:
        """Check all active missions and bind nearby targets."""
        if self._tracker is None:
            return

        # Get all tracked targets
        try:
            all_targets = self._tracker.get_all_targets()
        except Exception:
            try:
                all_targets = self._tracker.targets
            except Exception:
                return

        if not all_targets:
            return

        for mission_id, mission in list(self._missions.items()):
            # Only check active missions with geofence zones
            if hasattr(mission, "status"):
                status = mission.status
                if hasattr(status, "value"):
                    status = status.value
                if status != "active":
                    continue
            else:
                continue

            geofence = getattr(mission, "geofence_zone", None)
            if geofence is None:
                continue

            bound_targets = set()

            for target in all_targets:
                # Get target position
                pos = self._get_target_position(target)
                if pos is None:
                    continue

                lat, lng = pos

                # Check if target is inside the geofence
                inside = False
                if hasattr(geofence, "is_circle") and geofence.is_circle:
                    inside = _point_in_circle(
                        lat, lng,
                        geofence.center_lat, geofence.center_lng,
                        geofence.radius_m,
                    )
                elif hasattr(geofence, "vertices") and geofence.vertices:
                    inside = _point_in_polygon(lat, lng, geofence.vertices)

                if inside:
                    target_id = self._get_target_id(target)
                    if target_id:
                        bound_targets.add(target_id)

            # Update bindings and publish changes
            with self._lock:
                old_bound = self._bindings.get(mission_id, set())
                new_entries = bound_targets - old_bound
                removed_entries = old_bound - bound_targets
                self._bindings[mission_id] = bound_targets

            if new_entries and self._event_bus is not None:
                self._event_bus.publish("mission_targets_bound", {
                    "mission_id": mission_id,
                    "mission_title": getattr(mission, "title", ""),
                    "new_targets": sorted(new_entries),
                    "total_bound": len(bound_targets),
                })

            if removed_entries and self._event_bus is not None:
                self._event_bus.publish("mission_targets_unbound", {
                    "mission_id": mission_id,
                    "removed_targets": sorted(removed_entries),
                    "total_bound": len(bound_targets),
                })

    def _get_target_position(self, target: Any) -> Optional[tuple[float, float]]:
        """Extract lat/lng position from a target object."""
        if isinstance(target, dict):
            pos = target.get("position")
            if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                return (float(pos[0]), float(pos[1]))
            lat = target.get("lat")
            lng = target.get("lng") or target.get("lon")
            if lat is not None and lng is not None:
                return (float(lat), float(lng))
            return None

        # Object with attributes
        if hasattr(target, "lat") and hasattr(target, "lng"):
            lat = getattr(target, "lat", None)
            lng = getattr(target, "lng", None)
            if lat is not None and lng is not None:
                return (float(lat), float(lng))

        if hasattr(target, "position"):
            pos = target.position
            if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                return (float(pos[0]), float(pos[1]))

        return None

    def _get_target_id(self, target: Any) -> str:
        """Extract target ID from a target object."""
        if isinstance(target, dict):
            return str(target.get("target_id", target.get("id", "")))
        return str(getattr(target, "target_id", getattr(target, "id", "")))

    def get_mission_targets(self, mission_id: str) -> list[str]:
        """Get the list of target IDs bound to a specific mission.

        Args:
            mission_id: The mission to query.

        Returns:
            Sorted list of bound target IDs.
        """
        with self._lock:
            return sorted(self._bindings.get(mission_id, set()))

    def get_all_bindings(self) -> dict[str, list[str]]:
        """Get all mission-target bindings.

        Returns:
            Dict mapping mission_id -> sorted list of bound target IDs.
        """
        with self._lock:
            return {
                mid: sorted(tids)
                for mid, tids in self._bindings.items()
                if tids
            }

    def bind_target_manually(self, mission_id: str, target_id: str) -> bool:
        """Manually bind a target to a mission.

        Args:
            mission_id: Mission to bind to.
            target_id: Target to bind.

        Returns:
            True if the target was newly bound (not already bound).
        """
        with self._lock:
            if mission_id not in self._bindings:
                self._bindings[mission_id] = set()
            was_new = target_id not in self._bindings[mission_id]
            self._bindings[mission_id].add(target_id)
            return was_new

    def unbind_target(self, mission_id: str, target_id: str) -> bool:
        """Remove a target binding from a mission.

        Returns:
            True if the target was actually bound and removed.
        """
        with self._lock:
            bound = self._bindings.get(mission_id, set())
            if target_id in bound:
                bound.discard(target_id)
                return True
            return False


# ---------------------------------------------------------------------------
# Singleton for API access
# ---------------------------------------------------------------------------

_binder: Optional[MissionTargetBinder] = None


def get_mission_target_binder(
    missions_store: Optional[dict] = None,
    target_tracker: Any = None,
    event_bus: Any = None,
) -> Optional[MissionTargetBinder]:
    """Get or create the singleton MissionTargetBinder.

    Returns None if missions_store is not provided and no binder exists.
    """
    global _binder
    if _binder is None and missions_store is not None:
        _binder = MissionTargetBinder(
            missions_store=missions_store,
            target_tracker=target_tracker,
            event_bus=event_bus,
        )
    return _binder
