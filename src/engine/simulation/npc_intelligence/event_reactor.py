# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""EventReactor — distributes EventBus events to nearby NPC brains.

Subscribes to the EventBus for combat, wave, and sensor events, then
distributes them to NPCs within a type-specific radius. Sets danger/interest
context and records events in NPC memory.
"""

from __future__ import annotations

import math
import queue
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from engine.simulation.npc_intelligence.brain import NPCBrain


# Event type -> max radius in meters (float('inf') = global)
_EVENT_RADII: dict[str, float] = {
    "weapon_fired": 50.0,
    "target_eliminated": 80.0,
    "unit_destroyed": 80.0,
    "explosion": 100.0,
    "wave_start": float("inf"),
    "wave_complete": float("inf"),
    "escalation_change": float("inf"),
}

# Event types that set danger on affected NPCs
_DANGER_EVENTS: set[str] = {
    "weapon_fired",
    "target_eliminated",
    "unit_destroyed",
    "explosion",
}

# Event types that set interest on affected NPCs
_INTEREST_EVENTS: set[str] = {
    "wave_start",
    "wave_complete",
    "escalation_change",
}


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class EventReactor:
    """Distributes EventBus events to nearby NPC brains based on distance."""

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._queue: queue.Queue | None = None

    def start(self) -> None:
        """Subscribe to the EventBus."""
        if self._queue is not None:
            return  # already started
        self._queue = self._bus.subscribe()

    def stop(self) -> None:
        """Unsubscribe from the EventBus."""
        if self._queue is None:
            return
        self._bus.unsubscribe(self._queue)
        self._queue = None

    def process_event(
        self,
        event: dict,
        brains_with_positions: list[tuple[NPCBrain, tuple[float, float]]],
    ) -> None:
        """Process a single event and distribute to nearby NPCs.

        Args:
            event: Event dict with "type" and optional "data" keys.
            brains_with_positions: List of (NPCBrain, (x, y)) tuples.
        """
        if not brains_with_positions:
            return

        event_type = event.get("type", "")
        data = event.get("data", {})

        # Determine radius for this event type
        radius = _EVENT_RADII.get(event_type)
        if radius is None:
            # Unknown event type — ignore silently
            return

        # Extract event position (if any)
        pos_data = data.get("position")
        if pos_data and len(pos_data) >= 2:
            event_pos: tuple[float, float] | None = (float(pos_data[0]), float(pos_data[1]))
        else:
            event_pos = None

        # For infinite-radius events or events without position, affect all NPCs
        is_global = radius == float("inf") or event_pos is None

        is_danger = event_type in _DANGER_EVENTS
        is_interest = event_type in _INTEREST_EVENTS

        for brain, npc_pos in brains_with_positions:
            # Skip bound NPCs
            if brain.is_bound:
                continue

            # Compute distance
            if is_global:
                dist = 0.0
                in_range = True
            else:
                assert event_pos is not None
                dist = _distance(event_pos, npc_pos)
                in_range = dist <= radius

            if not in_range:
                continue

            # Record in memory (with distance)
            event_data = dict(data)
            event_data["distance"] = dist
            brain.memory.add_event(event_type, event_data)

            # Set danger context
            if is_danger:
                brain.set_danger(dist)

            # Set interest context
            if is_interest:
                brain.set_interest(dist)
