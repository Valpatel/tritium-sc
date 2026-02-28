# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""PerceptionEngine — translates TRITIUM-SC game state to graphling perception.

Reads from TargetTracker to find nearby entities, calculates danger level,
and builds PerceptionPacket dicts compatible with the Graphlings server
POST /deployment/{soul_id}/think endpoint.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any


class PerceptionEngine:
    """Builds perception packets from TRITIUM-SC TargetTracker state.

    Args:
        tracker: TargetTracker instance (or mock) with get_all() method.
        perception_radius: Max distance for entity inclusion.
        max_events: Max recent events to track.
    """

    def __init__(
        self,
        tracker: Any,
        perception_radius: float = 50.0,
        max_events: int = 20,
    ) -> None:
        self._tracker = tracker
        self._radius = perception_radius
        self._recent_events: deque[str] = deque(maxlen=max_events)

    def record_event(self, event_type: str) -> None:
        """Record a game event for inclusion in perception packets."""
        self._recent_events.append(event_type)

    def build_perception(
        self,
        graphling_id: str,
        own_position: tuple[float, float],
        own_heading: float,
    ) -> dict:
        """Build a perception packet for a graphling at the given position.

        Returns a dict matching the Graphlings server PerceptionPacket format:
        {
            "nearby_entities": [...],
            "own_position": [x, y],
            "own_heading": float,
            "danger_level": float,
            "noise_level": float,
            "nearby_friendlies": int,
            "nearby_hostiles": int,
            "recent_events": [str, ...],
        }
        """
        all_targets = self._tracker.get_all()

        nearby_entities = []
        nearby_friendlies = 0
        nearby_hostiles = 0
        max_danger = 0.0

        for target in all_targets:
            # Skip the graphling itself if it's in the tracker
            if target.target_id == graphling_id:
                continue

            # Calculate distance
            dx = target.position[0] - own_position[0]
            dy = target.position[1] - own_position[1]
            distance = math.hypot(dx, dy)

            # Skip if outside radius
            if distance > self._radius:
                continue

            # Determine if threat
            is_hostile = target.alliance == "hostile"
            is_threat = is_hostile

            # Build entity perception
            heading_to = math.degrees(math.atan2(dx, dy)) % 360.0

            entity = {
                "target_id": target.target_id,
                "name": target.name,
                "alliance": target.alliance,
                "asset_type": target.asset_type,
                "distance": distance,
                "heading_to": heading_to,
                "status": target.status,
                "is_threat": is_threat,
            }
            nearby_entities.append(entity)

            # Count by alliance
            if target.alliance == "friendly":
                nearby_friendlies += 1
            elif target.alliance == "hostile":
                nearby_hostiles += 1

                # Danger scales inversely with distance
                if distance > 0:
                    danger = max(0.0, 1.0 - (distance / self._radius))
                else:
                    danger = 1.0
                max_danger = max(max_danger, danger)

        return {
            "nearby_entities": nearby_entities,
            "own_position": [own_position[0], own_position[1]],
            "own_heading": own_heading,
            "danger_level": max_danger,
            "noise_level": min(1.0, nearby_hostiles * 0.3),
            "nearby_friendlies": nearby_friendlies,
            "nearby_hostiles": nearby_hostiles,
            "recent_events": list(self._recent_events),
        }
