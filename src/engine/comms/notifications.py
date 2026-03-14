# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""NotificationManager — collects and distributes alerts from all plugins.

Subscribes to EventBus events (ble:suspicious_device, geofence:enter,
threat_escalation, automation:alert) and auto-creates notifications.
Broadcasts new notifications over WebSocket for real-time UI updates.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Callable


@dataclass
class Notification:
    """A single notification from any plugin or subsystem."""
    id: str
    title: str
    message: str
    severity: str  # info, warning, critical
    source: str  # plugin name or subsystem
    timestamp: float
    read: bool = False
    entity_id: str | None = None  # optional link to target/dossier

    def to_dict(self) -> dict:
        return asdict(self)


class NotificationManager:
    """Collects notifications from all plugins and provides query/mark-read API.

    Optionally subscribes to an EventBus to auto-create notifications from
    well-known event types.  Optionally broadcasts new notifications via
    a WebSocket callback.
    """

    # EventBus event types to auto-subscribe to, with default severity/title
    AUTO_EVENTS: dict[str, dict] = {
        "ble:suspicious_device": {
            "severity": "warning",
            "title": "Suspicious BLE Device",
        },
        "geofence:enter": {
            "severity": "warning",
            "title": "Geofence Entry",
        },
        "threat_escalation": {
            "severity": "critical",
            "title": "Threat Escalation",
        },
        "automation:alert": {
            "severity": "info",
            "title": "Automation Alert",
        },
    }

    def __init__(
        self,
        event_bus=None,
        ws_broadcast: Callable[[dict], None] | None = None,
        max_notifications: int = 500,
    ) -> None:
        self._lock = threading.Lock()
        self._notifications: list[Notification] = []
        self._max = max_notifications
        self._ws_broadcast = ws_broadcast
        self._event_bus = event_bus
        self._event_thread: threading.Thread | None = None
        self._running = False
        self._event_queue: queue.Queue | None = None

        if event_bus is not None:
            self._start_event_listener()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        title: str,
        message: str,
        severity: str = "info",
        source: str = "system",
        entity_id: str | None = None,
    ) -> str:
        """Create and store a notification. Returns the notification id."""
        if severity not in ("info", "warning", "critical"):
            severity = "info"

        nid = uuid.uuid4().hex[:12]
        notif = Notification(
            id=nid,
            title=title,
            message=message,
            severity=severity,
            source=source,
            timestamp=time.time(),
            entity_id=entity_id,
        )

        with self._lock:
            self._notifications.insert(0, notif)
            if len(self._notifications) > self._max:
                self._notifications = self._notifications[: self._max]

        # Broadcast over WebSocket
        if self._ws_broadcast is not None:
            try:
                self._ws_broadcast({
                    "type": "notification:new",
                    "data": notif.to_dict(),
                })
            except Exception:
                pass  # Best-effort broadcast

        return nid

    def get_unread(self) -> list[dict]:
        """Return all unread notifications as dicts."""
        with self._lock:
            return [n.to_dict() for n in self._notifications if not n.read]

    def get_all(
        self, limit: int = 100, since: float | None = None
    ) -> list[dict]:
        """Return notifications as dicts, newest first."""
        with self._lock:
            result = self._notifications
            if since is not None:
                result = [n for n in result if n.timestamp >= since]
            return [n.to_dict() for n in result[:limit]]

    def mark_read(self, notification_id: str) -> bool:
        """Mark a single notification as read. Returns True if found."""
        with self._lock:
            for n in self._notifications:
                if n.id == notification_id:
                    n.read = True
                    return True
        return False

    def mark_all_read(self) -> int:
        """Mark all notifications as read. Returns count marked."""
        count = 0
        with self._lock:
            for n in self._notifications:
                if not n.read:
                    n.read = True
                    count += 1
        return count

    def count_unread(self) -> int:
        """Return the number of unread notifications."""
        with self._lock:
            return sum(1 for n in self._notifications if not n.read)

    def stop(self) -> None:
        """Stop the event listener thread."""
        self._running = False
        if self._event_queue is not None:
            try:
                self._event_bus.unsubscribe(self._event_queue)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # EventBus auto-subscription
    # ------------------------------------------------------------------

    def _start_event_listener(self) -> None:
        """Subscribe to the EventBus and process events in a daemon thread."""
        self._event_queue = self._event_bus.subscribe()
        self._running = True
        self._event_thread = threading.Thread(
            target=self._event_loop, daemon=True, name="notification-listener"
        )
        self._event_thread.start()

    def _event_loop(self) -> None:
        """Drain the EventBus queue and auto-create notifications."""
        while self._running:
            try:
                msg = self._event_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            except Exception:
                continue

            event_type = msg.get("type", "")
            data = msg.get("data") or {}

            if event_type not in self.AUTO_EVENTS:
                continue

            cfg = self.AUTO_EVENTS[event_type]
            title = data.get("title", cfg["title"])
            message = data.get("message", str(data))
            severity = data.get("severity", cfg["severity"])
            source = data.get("source", event_type)
            entity_id = data.get("entity_id") or data.get("target_id")

            self.add(
                title=title,
                message=message,
                severity=severity,
                source=source,
                entity_id=entity_id,
            )
