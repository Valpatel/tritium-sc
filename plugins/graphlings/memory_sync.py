# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MemorySync — experience recording and batch sync to Graphling server.

Queues in-game experiences per soul_id and flushes them in batch to the
Graphling home server via AgentBridge.record_experiences().
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any

log = logging.getLogger(__name__)

# Map tritium-sc event types to graphling experience categories
_EVENT_CATEGORY_MAP: dict[str, str] = {
    "projectile_fired": "COMBAT_WITNESS",
    "target_eliminated": "COMBAT_WITNESS",
    "explosion": "COMBAT_WITNESS",
    "combat_damage": "COMBAT_WITNESS",
    "npc_thought": "SOCIAL_INTERACTION",
    "npc_dialogue": "SOCIAL_INTERACTION",
    "greeting": "SOCIAL_INTERACTION",
    "target_spawned": "ENVIRONMENT_CHANGE",
    "target_despawned": "ENVIRONMENT_CHANGE",
    "zone_entered": "ENVIRONMENT_CHANGE",
    "zone_exited": "ENVIRONMENT_CHANGE",
}

_DEFAULT_CATEGORY = "GENERAL"


class MemorySync:
    """Queues experiences and flushes them to the Graphling server in batch."""

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge
        self._lock = threading.Lock()
        # soul_id -> list of experience dicts
        self._queues: dict[str, list[dict]] = defaultdict(list)

    def record_event(
        self,
        soul_id: str,
        event_type: str,
        description: str,
        confidence: float = 0.5,
    ) -> None:
        """Queue an experience for a graphling.

        Thread-safe: can be called from any thread.
        """
        category = _EVENT_CATEGORY_MAP.get(event_type, _DEFAULT_CATEGORY)
        experience = {
            "event_type": event_type,
            "description": description,
            "confidence": confidence,
            "category": category,
        }

        with self._lock:
            self._queues[soul_id].append(experience)

    def flush(self, soul_id: str) -> int:
        """Flush queued experiences for a soul to the server.

        Returns the number of experiences successfully recorded.
        If the bridge call fails (returns 0), experiences are kept
        in the queue for retry.
        """
        with self._lock:
            pending = self._queues.get(soul_id, [])
            if not pending:
                return 0
            # Take a snapshot for sending
            batch = list(pending)

        count = self._bridge.record_experiences(soul_id, batch)

        if count > 0:
            # Only clear on success
            with self._lock:
                current = self._queues.get(soul_id, [])
                # Remove only the items we successfully sent
                # (new items may have been added during the flush)
                self._queues[soul_id] = current[len(batch):]
                if not self._queues[soul_id]:
                    # Clean up empty list
                    del self._queues[soul_id]

        return count

    def pending_count(self, soul_id: str) -> int:
        """Return the number of pending experiences for a soul."""
        with self._lock:
            return len(self._queues.get(soul_id, []))

    def flush_all(self) -> dict[str, int]:
        """Flush all queued experiences for all souls.

        Returns a dict of soul_id -> count synced.
        """
        with self._lock:
            soul_ids = list(self._queues.keys())

        results: dict[str, int] = {}
        for soul_id in soul_ids:
            results[soul_id] = self.flush(soul_id)
        return results
