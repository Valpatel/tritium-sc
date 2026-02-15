"""Long-term memory for Amy — persists observations across sessions.

Stores spatial observations (what Amy has seen at different camera angles),
event timelines, room understanding, and person profiles.  All data is
saved to a JSON file and reloaded on startup.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime


class Memory:
    """Amy's persistent long-term memory."""

    def __init__(self, path: str | None = None):
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "amy_memory.json")
        self.path = path
        self._lock = threading.Lock()

        self.spatial: dict[str, list[dict]] = {}
        self.events: list[dict] = []
        self.room_summary: str = ""
        self.people: list[dict] = []
        self.session_count: int = 0
        self.session_start: float = time.time()

        self._load()
        self.session_count += 1

    # --- Spatial memory ---

    @staticmethod
    def _pos_key(pan: float, tilt: float) -> str:
        pb = round(pan / 10) * 10
        tb = round(tilt / 10) * 10
        return f"{pb},{tb}"

    def add_observation(self, pan: float, tilt: float, observation: str) -> None:
        key = self._pos_key(pan, tilt)
        with self._lock:
            if key not in self.spatial:
                self.spatial[key] = []
            self.spatial[key].append({
                "time": time.time(),
                "text": observation,
            })
            self.spatial[key] = self.spatial[key][-5:]

    def get_nearby_observations(self, pan: float, tilt: float, radius: int = 1) -> list[str]:
        pb = round(pan / 10) * 10
        tb = round(tilt / 10) * 10
        results = []
        with self._lock:
            for dp in range(-radius, radius + 1):
                for dt in range(-radius, radius + 1):
                    key = f"{pb + dp * 10},{tb + dt * 10}"
                    if key in self.spatial:
                        latest = self.spatial[key][-1]
                        age_min = (time.time() - latest["time"]) / 60
                        if age_min < 60:
                            results.append(latest["text"])
        return results

    def get_spatial_summary(self) -> str:
        with self._lock:
            if not self.spatial:
                return "Haven't explored much yet."
            parts = []
            for key, obs_list in sorted(self.spatial.items()):
                if obs_list:
                    latest = obs_list[-1]
                    age_min = (time.time() - latest["time"]) / 60
                    age_str = f"{age_min:.0f}m ago" if age_min < 60 else f"{age_min / 60:.1f}h ago"
                    parts.append(f"  [{key}] ({age_str}): {latest['text']}")
            return "\n".join(parts[-10:])

    # --- Event timeline ---

    def add_event(self, event_type: str, data: str) -> None:
        with self._lock:
            self.events.append({
                "time": time.time(),
                "type": event_type,
                "data": data,
            })
            if len(self.events) > 200:
                self.events = self.events[-200:]

    def get_recent_events(self, count: int = 10) -> list[dict]:
        with self._lock:
            return list(self.events[-count:])

    def get_event_summary(self) -> str:
        recent = self.get_recent_events(10)
        if not recent:
            return "No recent events."
        parts = []
        for ev in recent:
            t = datetime.fromtimestamp(ev["time"]).strftime("%H:%M:%S")
            parts.append(f"  [{t}] {ev['type']}: {ev['data']}")
        return "\n".join(parts)

    # --- Room understanding ---

    def update_room_summary(self, summary: str) -> None:
        with self._lock:
            self.room_summary = summary

    # --- People ---

    def record_person(self, description: str) -> None:
        with self._lock:
            self.people.append({
                "time": time.time(),
                "description": description,
            })
            if len(self.people) > 50:
                self.people = self.people[-50:]

    # --- Build LLM context ---

    def build_context(self, pan: float = 0, tilt: float = 0) -> str:
        parts = []

        uptime_min = (time.time() - self.session_start) / 60
        parts.append(f"[Session #{self.session_count}, uptime: {uptime_min:.0f}m]")

        if self.room_summary:
            parts.append(f"[Room knowledge]: {self.room_summary}")

        nearby = self.get_nearby_observations(pan, tilt)
        if nearby:
            parts.append("[What you've seen nearby]: " + "; ".join(nearby))

        recent = self.get_recent_events(5)
        if recent:
            event_strs = []
            for ev in recent:
                age_sec = time.time() - ev["time"]
                if age_sec < 60:
                    age = f"{age_sec:.0f}s ago"
                else:
                    age = f"{age_sec / 60:.0f}m ago"
                event_strs.append(f"{ev['data']} ({age})")
            parts.append("[Recent events]: " + "; ".join(event_strs))

        return "\n".join(parts)

    # --- Dashboard data ---

    def get_dashboard_data(self) -> dict:
        uptime_min = (time.time() - self.session_start) / 60
        return {
            "session": self.session_count,
            "uptime_min": round(uptime_min, 1),
            "room_summary": self.room_summary,
            "spatial_summary": self.get_spatial_summary(),
            "events": self.get_event_summary(),
            "total_observations": sum(len(v) for v in self.spatial.values()),
            "total_events": len(self.events),
            "total_people": len(self.people),
        }

    # --- Persistence ---

    def save(self) -> None:
        with self._lock:
            data = {
                "version": 1,
                "session_count": self.session_count,
                "spatial": self.spatial,
                "events": self.events,
                "room_summary": self.room_summary,
                "people": self.people,
            }
        try:
            tmp_path = self.path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.path)
        except OSError as e:
            print(f"  [memory save error: {e}]")

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            self.session_count = data.get("session_count", 0)
            self.spatial = data.get("spatial", {})
            self.events = data.get("events", [])
            self.room_summary = data.get("room_summary", "")
            self.people = data.get("people", [])
            obs_count = sum(len(v) for v in self.spatial.values())
            print(f"  [memory loaded: {obs_count} observations, "
                  f"{len(self.events)} events, session #{self.session_count}]")
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [memory load error: {e}]")
