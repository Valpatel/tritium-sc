"""Sensorium — Amy's L3 AWARENESS layer.

Fuses data from all sensor threads (YOLO, deep vision, audio, motor,
thinking) into a temporal narrative that higher layers can read.

This is a passive data structure — no thread of its own.  Other threads
push events in, and the thinking thread reads the narrative out.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class SceneEvent:
    """A single timestamped event in Amy's awareness."""

    timestamp: float        # monotonic time
    source: str             # "yolo", "deep", "audio", "motor", "thought"
    text: str               # human-readable description
    importance: float = 0.5 # 0.0-1.0
    source_node: str = ""   # which sensor node generated this

    @property
    def age(self) -> float:
        """Seconds since this event."""
        return time.monotonic() - self.timestamp


# Source display labels for the narrative
_SOURCE_LABELS = {
    "yolo": "Vision",
    "deep": "Observation",
    "audio": "Audio",
    "motor": "Movement",
    "thought": "Thought",
}


class Sensorium:
    """Sensor fusion layer — maintains a sliding window of scene events.

    Thread-safe: any thread can push events, any thread can read
    the narrative.
    """

    def __init__(self, max_events: int = 30, window_seconds: float = 120.0):
        self._events: deque[SceneEvent] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._window = window_seconds
        self._people_present: bool = False
        self._people_count: int = 0
        self._last_speech_time: float = 0.0
        self._last_silence_push: float = 0.0

    def push(self, source: str, text: str, importance: float = 0.5,
             source_node: str = "") -> None:
        """Add a scene event (called from any thread).

        Deduplicates consecutive identical events from the same source.
        """
        now = time.monotonic()

        # Debounce silence events (at most once per 30 seconds)
        if source == "audio" and "silence" in text.lower():
            if now - self._last_silence_push < 30.0:
                return
            self._last_silence_push = now

        with self._lock:
            # Skip if identical to the most recent event from same source
            if self._events:
                last = self._events[-1]
                if last.source == source and last.text == text and last.age < 5.0:
                    return

            event = SceneEvent(
                timestamp=now,
                source=source,
                text=text,
                importance=importance,
                source_node=source_node,
            )
            self._events.append(event)

            # Track people presence from YOLO events
            if source == "yolo":
                text_lower = text.lower()
                if "person" in text_lower or "people" in text_lower:
                    if "left" in text_lower and "entered" not in text_lower:
                        self._people_present = False
                        self._people_count = 0
                    else:
                        self._people_present = True
                elif "everyone left" in text_lower or "empty" in text_lower:
                    self._people_present = False
                    self._people_count = 0

            # Track speech timing
            if source == "audio" and "said" in text.lower():
                self._last_speech_time = now

    def narrative(self) -> str:
        """Build a temporal narrative for LLM context."""
        now = time.monotonic()
        with self._lock:
            events = [e for e in self._events if e.age < self._window]

        if not events:
            return "No recent observations."

        lines = []
        for event in events:
            age = now - event.timestamp
            if age < 3:
                time_str = "Now"
            elif age < 60:
                time_str = f"{int(age)}s ago"
            elif age < 3600:
                time_str = f"{int(age / 60)}m ago"
            else:
                time_str = f"{int(age / 3600)}h ago"

            lines.append(f"{time_str}: {event.text}")

        return "\n".join(lines)

    def summary(self) -> str:
        """One-line current state for the dashboard."""
        with self._lock:
            if not self._events:
                return "Quiet. No observations yet."

            latest: dict[str, SceneEvent] = {}
            for event in reversed(list(self._events)):
                if event.source not in latest and event.age < self._window:
                    latest[event.source] = event
                if len(latest) >= 4:
                    break

        parts = []
        if "yolo" in latest:
            parts.append(latest["yolo"].text)
        if "deep" in latest:
            parts.append(latest["deep"].text)
        if "audio" in latest:
            parts.append(latest["audio"].text)

        return " | ".join(parts) if parts else "Quiet."

    @property
    def people_present(self) -> bool:
        with self._lock:
            return self._people_present

    @property
    def seconds_since_speech(self) -> float:
        with self._lock:
            if self._last_speech_time == 0:
                return float("inf")
            return time.monotonic() - self._last_speech_time

    @property
    def mood(self) -> str:
        """Amy's inferred mood based on recent events."""
        with self._lock:
            if not self._events:
                return "neutral"
            recent = [e for e in self._events if e.age < 60]

        if not recent:
            return "neutral"

        texts = " ".join(e.text.lower() for e in recent)
        sources = [e.source for e in recent]

        if "speech" in texts or "said" in texts:
            return "engaged"
        if self.people_present:
            return "attentive"
        if sources.count("thought") > 2:
            return "contemplative"
        if "quiet" in texts or "silence" in texts:
            return "calm"
        if "entered" in texts or "appeared" in texts:
            return "curious"

        return "neutral"

    @property
    def recent_thoughts(self) -> list[str]:
        """Get the last few internal thoughts for the thinking prompt."""
        with self._lock:
            thoughts = [
                e.text for e in self._events
                if e.source == "thought" and e.age < 120
            ]
        return thoughts[-3:]

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self._events)
