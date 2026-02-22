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

    def subscribe(self, _filter: str | None = None) -> queue.Queue:
        """Subscribe to events. Returns a Queue that receives all events.

        The optional ``_filter`` parameter is accepted for API compatibility
        but is currently ignored — the caller must filter events itself.
        """
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
                    # Drop oldest message to make room — ensures fresh events
                    # (game state changes, wave starts) are never silently lost
                    # when high-frequency telemetry fills the queue.
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        q.put_nowait(msg)
                    except queue.Full:
                        pass
