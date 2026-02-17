"""ActionRecorder -- captures all Amy actions during a scenario run."""

from __future__ import annotations

import queue
import threading
import time

from amy.commander import EventBus
from .schema import RecordedAction


class ActionRecorder:
    """Subscribes to EventBus, records all events with timestamps.

    Categorizes events into: speech, thought, detection, motor, event.
    """

    def __init__(self, event_bus: EventBus, start_time: float | None = None):
        self._event_bus = event_bus
        self._start_time = start_time or time.monotonic()
        self._queue: queue.Queue | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self.actions: list[RecordedAction] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        """Subscribe to EventBus and start recording."""
        self._queue = self._event_bus.subscribe()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop recording and unsubscribe."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._queue:
            self._event_bus.unsubscribe(self._queue)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._record(msg)

    def _record(self, msg: dict) -> None:
        timestamp = time.monotonic() - self._start_time
        event_type = msg.get("type", "")
        data = msg.get("data", {})

        action = None

        if event_type == "transcript":
            speaker = data.get("speaker", "")
            text = data.get("text", "")
            if speaker == "amy":
                action = RecordedAction(
                    timestamp=timestamp,
                    category="speech",
                    action_type="say",
                    text=text,
                )
            else:
                action = RecordedAction(
                    timestamp=timestamp,
                    category="event",
                    action_type="user_speech",
                    text=text,
                )

        elif event_type == "thought":
            action = RecordedAction(
                timestamp=timestamp,
                category="thought",
                action_type="think",
                text=data.get("text", ""),
            )

        elif event_type == "detections":
            people = data.get("people", 0)
            if people > 0:
                action = RecordedAction(
                    timestamp=timestamp,
                    category="detection",
                    action_type="detect_person",
                    text=data.get("summary", ""),
                    metadata={"people": people, "boxes": data.get("boxes", [])},
                )

        elif event_type == "state_change":
            state = data.get("state", "")
            action = RecordedAction(
                timestamp=timestamp,
                category="event",
                action_type="state_change",
                text=state,
            )

        elif event_type == "goal":
            action = RecordedAction(
                timestamp=timestamp,
                category="thought",
                action_type="goal",
                text=data.get("text", ""),
                metadata={"priority": data.get("priority", 3)},
            )

        elif event_type == "goal_completed":
            action = RecordedAction(
                timestamp=timestamp,
                category="thought",
                action_type="goal_completed",
                text=data.get("text", ""),
            )

        elif event_type == "event":
            text = data.get("text", "")
            # Classify specific event subtypes
            if "person" in text.lower() or "YOLO" in text:
                action = RecordedAction(
                    timestamp=timestamp,
                    category="detection",
                    action_type="person_event",
                    text=text,
                )
            elif "motor" in text.lower() or "scan" in text.lower() or "look" in text.lower():
                action = RecordedAction(
                    timestamp=timestamp,
                    category="motor",
                    action_type="motor_event",
                    text=text,
                )
            else:
                action = RecordedAction(
                    timestamp=timestamp,
                    category="event",
                    action_type="event",
                    text=text,
                )

        if action is not None:
            with self._lock:
                self.actions.append(action)

    @property
    def speech(self) -> list[RecordedAction]:
        with self._lock:
            return [a for a in self.actions if a.category == "speech"]

    @property
    def thoughts(self) -> list[RecordedAction]:
        with self._lock:
            return [a for a in self.actions if a.category == "thought"]

    @property
    def detections(self) -> list[RecordedAction]:
        with self._lock:
            return [a for a in self.actions if a.category == "detection"]

    @property
    def all_actions(self) -> list[RecordedAction]:
        with self._lock:
            return list(self.actions)
