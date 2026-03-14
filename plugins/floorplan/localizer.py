# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Indoor target localizer — assigns targets to rooms/zones.

Uses BLE trilateration positions and WiFi fingerprint matching to
determine which room a target is in. Integrates with the existing
geofence engine for polygon containment checks.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from .store import FloorPlanStore

log = logging.getLogger("indoor-localizer")


class IndoorLocalizer:
    """Assigns tracked targets to rooms within floor plans.

    Takes position estimates from BLE trilateration or WiFi fingerprinting
    and determines room-level containment using the floor plan's room
    polygons.
    """

    def __init__(self, store: FloorPlanStore) -> None:
        self._store = store

    def localize_target(
        self,
        target_id: str,
        lat: float,
        lon: float,
        confidence: float = 0.5,
        method: str = "trilateration",
    ) -> Optional[dict]:
        """Localize a target to a room based on lat/lon position.

        Searches all active floor plans for a room containing the point.
        Updates the indoor position store.

        Returns the indoor position dict, or None if no containing room.
        """
        plans = self._store.list_plans(status="active")

        for plan in plans:
            bounds = plan.get("bounds")
            if bounds:
                # Quick bounds check before polygon test
                if not (
                    bounds.get("south", -90) <= lat <= bounds.get("north", 90)
                    and bounds.get("west", -180) <= lon <= bounds.get("east", 180)
                ):
                    continue

            # Check each room's polygon
            for room in plan.get("rooms", []):
                polygon = room.get("polygon", [])
                if len(polygon) < 3:
                    continue
                if _point_in_polygon(lat, lon, polygon):
                    position = {
                        "target_id": target_id,
                        "plan_id": plan["plan_id"],
                        "room_id": room["room_id"],
                        "floor_level": room.get(
                            "floor_level", plan.get("floor_level", 0)
                        ),
                        "lat": lat,
                        "lon": lon,
                        "confidence": confidence,
                        "method": method,
                    }
                    self._store.set_position(target_id, position)
                    log.debug(
                        "Target %s localized to room %s (%.6f, %.6f)",
                        target_id, room["room_id"], lat, lon,
                    )
                    return position

        # Not in any room — might be in a plan but not a defined room
        for plan in plans:
            bounds = plan.get("bounds")
            if bounds and (
                bounds.get("south", -90) <= lat <= bounds.get("north", 90)
                and bounds.get("west", -180) <= lon <= bounds.get("east", 180)
            ):
                position = {
                    "target_id": target_id,
                    "plan_id": plan["plan_id"],
                    "room_id": None,
                    "floor_level": plan.get("floor_level", 0),
                    "lat": lat,
                    "lon": lon,
                    "confidence": confidence,
                    "method": method,
                }
                self._store.set_position(target_id, position)
                return position

        return None

    def localize_from_fingerprint(
        self,
        target_id: str,
        rssi_map: dict[str, float],
        plan_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Localize a target using WiFi RSSI fingerprint matching.

        Compares observed RSSI values against the fingerprint database
        using nearest-neighbor matching (Euclidean distance in RSSI space).

        Returns the best-matching indoor position, or None.
        """
        fingerprints = self._store.get_fingerprints(plan_id=plan_id)
        if not fingerprints:
            return None

        best_match: Optional[dict] = None
        best_distance = float("inf")

        for fp in fingerprints:
            fp_rssi = fp.get("rssi_map", {})
            if not fp_rssi:
                continue

            # Compute Euclidean distance over common BSSIDs
            common = set(rssi_map.keys()) & set(fp_rssi.keys())
            if len(common) < 2:
                continue

            dist_sq = sum(
                (rssi_map[bssid] - fp_rssi[bssid]) ** 2 for bssid in common
            )
            # Normalize by number of common BSSIDs
            distance = math.sqrt(dist_sq / len(common))

            if distance < best_distance:
                best_distance = distance
                best_match = fp

        if best_match is None:
            return None

        # Convert distance to confidence (closer = higher confidence)
        # RSSI distance of 0 = perfect match (1.0), distance of 20+ = low (0.1)
        confidence = max(0.1, min(1.0, 1.0 - best_distance / 25.0))

        position = {
            "target_id": target_id,
            "plan_id": best_match.get("plan_id", ""),
            "room_id": best_match.get("room_id"),
            "floor_level": best_match.get("floor_level", 0),
            "lat": best_match.get("lat"),
            "lon": best_match.get("lon"),
            "confidence": round(confidence, 3),
            "method": "fingerprint",
        }
        self._store.set_position(target_id, position)
        log.debug(
            "Target %s fingerprint-matched to room %s (confidence=%.2f, dist=%.1f)",
            target_id, position.get("room_id"), confidence, best_distance,
        )
        return position


def _point_in_polygon(
    lat: float, lon: float, polygon: list[dict]
) -> bool:
    """Ray-casting point-in-polygon test.

    polygon is a list of dicts with 'lat' and 'lon' keys.
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1
    for i in range(n):
        pi_lat = polygon[i].get("lat", 0)
        pi_lon = polygon[i].get("lon", 0)
        pj_lat = polygon[j].get("lat", 0)
        pj_lon = polygon[j].get("lon", 0)

        if ((pi_lon > lon) != (pj_lon > lon)) and (
            lat < (pj_lat - pi_lat) * (lon - pi_lon) / (pj_lon - pi_lon) + pi_lat
        ):
            inside = not inside
        j = i
    return inside
