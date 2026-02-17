"""EventBus — thread-safe pub/sub for internal event passing.

This is the core messaging primitive used by Commander, SimulationEngine,
ThreatClassifier, AutoDispatcher, MQTTBridge, and the WebSocket bridge.
Extracted from commander.py so that infrastructure modules do not need
to import the full Commander module.
"""

from __future__ import annotations

import queue
import threading


class EventBus:
    """Simple thread-safe pub/sub for pushing events to subscribers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue] = []

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def publish(self, event_type: str, data: dict | None = None) -> None:
        msg = {"type": event_type}
        if data is not None:
            msg["data"] = data
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass
