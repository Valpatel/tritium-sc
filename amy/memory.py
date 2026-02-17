"""Long-term memory for Amy — persists observations across sessions.

Stores spatial observations (what Amy has seen at different camera angles),
event timelines, room understanding, and person profiles.  All data is
saved to a JSON file and reloaded on startup.
"""

from __future__ import annotations

import json
import os
import re
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
        self.zones: list[dict] = []
        self.patterns: list[dict] = []
        self.session_summaries: list[dict] = []
        self.session_count: int = 0
        self.session_start: float = time.time()

        # --- V3: People, Facts, Self-Model ---
        self.known_people: dict[str, dict] = {}  # keyed by lowercased name
        self.facts: list[dict] = []              # max 100
        self.self_model: dict = {
            "personality_notes": [],              # max 5
            "preferences": {"likes": [], "dislikes": []},
            "behavioral_stats": {},
        }

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

    # --- Person identity (V3) ---

    def link_person(self, name: str, appearance: str = "", zone: str = "") -> None:
        """Create or update a known_people entry."""
        key = name.lower().strip()
        if not key:
            return
        with self._lock:
            now = time.time()
            if key in self.known_people:
                p = self.known_people[key]
                p["last_seen"] = now
                if self.session_count not in p["sessions_seen"]:
                    p["sessions_seen"].append(self.session_count)
                if appearance:
                    p["appearance"] = appearance
                if zone:
                    p["last_location"] = zone
                p["interaction_count"] = p.get("interaction_count", 0) + 1
            else:
                self.known_people[key] = {
                    "name": name,
                    "first_seen": now,
                    "last_seen": now,
                    "sessions_seen": [self.session_count],
                    "appearance": appearance,
                    "traits": [],
                    "relationship": "",
                    "last_location": zone,
                    "interaction_count": 1,
                }
            # Cap at 20 known people (evict least recently seen)
            if len(self.known_people) > 20:
                oldest_key = min(self.known_people, key=lambda k: self.known_people[k]["last_seen"])
                del self.known_people[oldest_key]

    def identify_person(self, zone: str = "", people_count: int = 1) -> str | None:
        """Heuristic: if exactly 1 known person's last_location matches zone, return name."""
        if people_count != 1 or not zone:
            return None
        with self._lock:
            matches = [
                p["name"] for p in self.known_people.values()
                if p.get("last_location", "").lower() == zone.lower()
            ]
        return matches[0] if len(matches) == 1 else None

    def update_person_seen(self, name: str, zone: str = "") -> None:
        """Update last_seen and last_location for a known person."""
        key = name.lower().strip()
        with self._lock:
            if key in self.known_people:
                self.known_people[key]["last_seen"] = time.time()
                if zone:
                    self.known_people[key]["last_location"] = zone

    # --- Facts (V3) ---

    def add_fact(self, text: str, tags: list[str] | None = None, person: str | None = None) -> None:
        """Append a fact. Enforces cap at 100 (FIFO eviction)."""
        with self._lock:
            self.facts.append({
                "time": time.time(),
                "source": "conversation",
                "text": text[:200],
                "tags": (tags or [])[:5],
                "person": person,
            })
            if len(self.facts) > 100:
                self.facts = self.facts[-100:]

    def add_preference(self, category: str, text: str) -> None:
        """Add a preference (likes/dislikes). Deduped, capped at 10 per list."""
        if category not in ("likes", "dislikes"):
            return
        text = text.strip()[:100]
        if not text:
            return
        with self._lock:
            prefs = self.self_model.get("preferences", {"likes": [], "dislikes": []})
            lst = prefs.get(category, [])
            # Deduplicate (case-insensitive)
            if text.lower() not in [p.lower() for p in lst]:
                lst.append(text)
                if len(lst) > 10:
                    lst = lst[-10:]
                prefs[category] = lst
            self.self_model["preferences"] = prefs

    def add_self_note(self, text: str) -> None:
        """Append to self_model personality_notes, cap at 5."""
        with self._lock:
            notes = self.self_model.get("personality_notes", [])
            notes.append(text[:200])
            if len(notes) > 5:
                notes = notes[-5:]
            self.self_model["personality_notes"] = notes

    # --- Recall (V3) ---

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """Keyword search across facts, known_people traits, events, session_summaries.

        Scoring: +1 per keyword match in text, +0.5 per tag match,
        recency bonus decaying over 24h.
        """
        keywords = [w.lower() for w in query.split() if len(w) > 2]
        if not keywords:
            return []

        now = time.time()
        candidates: list[tuple[float, dict]] = []

        with self._lock:
            # Search facts
            for fact in self.facts:
                score = self._score_item(fact.get("text", ""), fact.get("tags", []),
                                         fact.get("time", 0), keywords, now)
                if score > 0:
                    candidates.append((score, {"type": "fact", "text": fact["text"],
                                               "time": fact["time"], "person": fact.get("person")}))

            # Search known_people traits
            for key, person in self.known_people.items():
                text = f"{person['name']} {person.get('appearance', '')} {' '.join(person.get('traits', []))}"
                score = self._score_item(text, [], person.get("last_seen", 0), keywords, now)
                if score > 0:
                    candidates.append((score, {"type": "person", "text": f"{person['name']}: {person.get('appearance', '')}",
                                               "time": person.get("last_seen", 0), "person": person["name"]}))

            # Search events
            for ev in self.events[-50:]:  # Only recent events
                score = self._score_item(ev.get("data", ""), [], ev.get("time", 0), keywords, now)
                if score > 0:
                    candidates.append((score, {"type": "event", "text": ev["data"],
                                               "time": ev["time"]}))

            # Search session summaries
            for ss in self.session_summaries:
                score = self._score_item(ss.get("summary", ""), [], ss.get("time", 0), keywords, now)
                if score > 0:
                    candidates.append((score, {"type": "summary", "text": ss["summary"],
                                               "time": ss["time"]}))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [c[1] for c in candidates[:limit]]

    @staticmethod
    def _score_item(text: str, tags: list[str], timestamp: float, keywords: list[str], now: float) -> float:
        """Score an item for recall relevance."""
        text_lower = text.lower()
        score = sum(1.0 for kw in keywords if kw in text_lower)
        score += sum(0.5 for kw in keywords for tag in tags if kw in tag.lower())

        # Recency bonus: decays from 1.0 to 0.0 over 24 hours
        if timestamp > 0:
            age_hours = (now - timestamp) / 3600
            recency = max(0.0, 1.0 - age_hours / 24.0)
            score += recency * 0.5

        return score

    def recall_for_person(self, name: str, limit: int = 3) -> list[dict]:
        """Facts and events linked to a specific person."""
        key = name.lower().strip()
        results: list[dict] = []
        with self._lock:
            for fact in self.facts:
                if fact.get("person", "").lower() == key:
                    results.append({"type": "fact", "text": fact["text"], "time": fact["time"]})
            for ev in self.events:
                if key in ev.get("data", "").lower():
                    results.append({"type": "event", "text": ev["data"], "time": ev["time"]})
        results.sort(key=lambda x: x.get("time", 0), reverse=True)
        return results[:limit]

    def recall_for_zone(self, zone: str, limit: int = 3) -> list[dict]:
        """Facts and observations associated with a zone."""
        zone_lower = zone.lower()
        results: list[dict] = []
        with self._lock:
            for fact in self.facts:
                if zone_lower in fact.get("text", "").lower() or zone_lower in " ".join(fact.get("tags", [])).lower():
                    results.append({"type": "fact", "text": fact["text"], "time": fact["time"]})
            # Also check spatial observations for zones
            for key, obs_list in self.spatial.items():
                for obs in obs_list:
                    if zone_lower in obs.get("text", "").lower():
                        results.append({"type": "observation", "text": obs["text"], "time": obs["time"]})
        results.sort(key=lambda x: x.get("time", 0), reverse=True)
        return results[:limit]

    # --- Zones ---

    def register_zone(self, name: str, pan: float, tilt: float,
                      description: str = "") -> None:
        """Register a named zone at a camera angle."""
        with self._lock:
            for z in self.zones:
                if z["name"] == name:
                    z["pan"] = pan
                    z["tilt"] = tilt
                    z["description"] = description
                    return
            self.zones.append({
                "name": name,
                "pan": pan,
                "tilt": tilt,
                "description": description,
            })

    def get_zone_at(self, pan: float, tilt: float,
                    threshold: float = 20.0) -> dict | None:
        """Find the zone closest to given pan/tilt within threshold."""
        with self._lock:
            best = None
            best_dist = threshold
            for z in self.zones:
                dist = ((z["pan"] - pan) ** 2 + (z["tilt"] - tilt) ** 2) ** 0.5
                if dist < best_dist:
                    best = dict(z)
                    best_dist = dist
            return best

    def get_zone_context(self) -> str:
        """Build zone context string for LLM prompt."""
        with self._lock:
            if not self.zones:
                return ""
            parts = []
            for z in self.zones:
                desc = f": {z['description']}" if z["description"] else ""
                parts.append(f"  {z['name']} (pan={z['pan']:.0f}, tilt={z['tilt']:.0f}){desc}")
            return "[Known zones]:\n" + "\n".join(parts)

    # --- Patterns ---

    def detect_patterns(self) -> list[dict]:
        """Analyze event timeline for recurring events by hour-of-day."""
        with self._lock:
            events = list(self.events)

        if len(events) < 10:
            return self.patterns

        hour_counts: dict[int, dict[str, int]] = {}
        for ev in events:
            h = datetime.fromtimestamp(ev["time"]).hour
            et = ev["type"]
            if h not in hour_counts:
                hour_counts[h] = {}
            hour_counts[h][et] = hour_counts[h].get(et, 0) + 1

        new_patterns = []
        for hour, types in sorted(hour_counts.items()):
            for etype, count in types.items():
                if count >= 3:
                    new_patterns.append({
                        "hour": hour,
                        "type": etype,
                        "count": count,
                        "description": f"{etype} typically occurs around {hour}:00 ({count} times)",
                    })

        with self._lock:
            self.patterns = new_patterns
        return new_patterns

    def get_pattern_context(self) -> str:
        """Build pattern context for LLM prompt."""
        with self._lock:
            if not self.patterns:
                return ""
            parts = [p["description"] for p in self.patterns[:5]]
            return "[Observed patterns]:\n  " + "\n  ".join(parts)

    # --- Session summaries ---

    def generate_session_summary(self) -> str:
        """Summarize the current session for persistence."""
        with self._lock:
            events = list(self.events)
            spatial = dict(self.spatial)

        uptime_min = (time.time() - self.session_start) / 60
        event_types: dict[str, int] = {}
        for ev in events:
            et = ev["type"]
            event_types[et] = event_types.get(et, 0) + 1

        obs_count = sum(len(v) for v in spatial.values())
        type_summary = ", ".join(f"{k}:{v}" for k, v in sorted(event_types.items()))

        summary = (
            f"Session #{self.session_count}: {uptime_min:.0f}min uptime, "
            f"{len(events)} events ({type_summary}), "
            f"{obs_count} observations"
        )

        with self._lock:
            self.session_summaries.append({
                "session": self.session_count,
                "time": time.time(),
                "summary": summary,
            })
            self.session_summaries = self.session_summaries[-10:]

        return summary

    # --- Context builders (V3) ---

    def build_people_context(self) -> str:
        """Format known_people for LLM prompt."""
        with self._lock:
            if not self.known_people:
                return ""
            now = time.time()
            parts = []
            for p in sorted(self.known_people.values(), key=lambda x: x.get("last_seen", 0), reverse=True):
                age = now - p.get("last_seen", now)
                if age < 3600:
                    ago = f"{int(age/60)}m ago"
                elif age < 86400:
                    ago = f"{int(age/3600)}h ago"
                else:
                    ago = f"{int(age/86400)}d ago"

                traits_str = ", ".join(p.get("traits", [])[:3])
                desc = f"{p['name']} (last seen {ago}"
                if traits_str:
                    desc += f", {traits_str}"
                if p.get("relationship"):
                    desc += f", {p['relationship']}"
                desc += ")"
                parts.append(f"  {desc}")
            return "[People you know]:\n" + "\n".join(parts[:10])

    def build_self_context(self) -> str:
        """Format self_model for LLM prompt."""
        with self._lock:
            notes = self.self_model.get("personality_notes", [])
            prefs = self.self_model.get("preferences", {"likes": [], "dislikes": []})
            likes = prefs.get("likes", [])
            dislikes = prefs.get("dislikes", [])

        parts: list[str] = []
        if notes:
            parts.append("[Self-awareness]:\n  " + "\n  ".join(notes[-3:]))
        if likes or dislikes:
            pref_lines: list[str] = []
            if likes:
                pref_lines.append(f"Things I enjoy: {', '.join(likes[-5:])}")
            if dislikes:
                pref_lines.append(f"Things I dislike: {', '.join(dislikes[-5:])}")
            parts.append("[Preferences]:\n  " + "\n  ".join(pref_lines))

        return "\n".join(parts)

    # --- Build LLM context ---

    def build_context(self, pan: float = 0, tilt: float = 0) -> str:
        parts = []

        uptime_min = (time.time() - self.session_start) / 60
        parts.append(f"[Session #{self.session_count}, uptime: {uptime_min:.0f}m]")

        if self.room_summary:
            parts.append(f"[Room knowledge]: {self.room_summary}")

        zone = self.get_zone_at(pan, tilt)
        if zone:
            desc = f" — {zone['description']}" if zone["description"] else ""
            parts.append(f"[Current zone]: {zone['name']}{desc}")

        zone_ctx = self.get_zone_context()
        if zone_ctx:
            parts.append(zone_ctx)

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

        pattern_ctx = self.get_pattern_context()
        if pattern_ctx:
            parts.append(pattern_ctx)

        people_ctx = self.build_people_context()
        if people_ctx:
            parts.append(people_ctx)

        self_ctx = self.build_self_context()
        if self_ctx:
            parts.append(self_ctx)

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
                "version": 3,
                "session_count": self.session_count,
                "spatial": self.spatial,
                "events": self.events,
                "room_summary": self.room_summary,
                "people": self.people,
                "zones": self.zones,
                "patterns": self.patterns,
                "session_summaries": self.session_summaries,
                "known_people": self.known_people,
                "facts": self.facts,
                "self_model": self.self_model,
            }
        try:
            tmp_path = self.path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.path)
        except OSError as e:
            print(f"  [memory save error: {e}]")

    def _load(self) -> None:
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            self.session_count = data.get("session_count", 0)
            self.spatial = data.get("spatial", {})
            self.events = data.get("events", [])
            self.room_summary = data.get("room_summary", "")
            self.people = data.get("people", [])
            self.zones = data.get("zones", [])
            self.patterns = data.get("patterns", [])
            self.session_summaries = data.get("session_summaries", [])

            # V3 fields
            self.known_people = data.get("known_people", {})
            self.facts = data.get("facts", [])
            self.self_model = data.get("self_model", {
                "personality_notes": [],
                "preferences": {"likes": [], "dislikes": []},
                "behavioral_stats": {},
            })

            version = data.get("version", 1)
            if version < 3:
                self._migrate_v2_to_v3()

            obs_count = sum(len(v) for v in self.spatial.values())
            print(f"  [memory loaded: {obs_count} observations, "
                  f"{len(self.events)} events, session #{self.session_count}]")
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [memory load error: {e}]")

    def _migrate_v2_to_v3(self) -> None:
        """Auto-migrate v2 memory to v3."""
        # Extract named people from existing people descriptions
        for p in self.people:
            desc = p.get("description", "")
            names = re.findall(r'\b([A-Z][a-z]{2,15})\b', desc)
            for name in names:
                if name.lower() not in {"the", "and", "person", "someone", "unknown",
                                         "tall", "short", "wearing", "shirt", "hoodie",
                                         "room", "desk", "door", "left", "right"}:
                    key = name.lower()
                    if key not in self.known_people:
                        self.known_people[key] = {
                            "name": name,
                            "first_seen": p.get("time", time.time()),
                            "last_seen": p.get("time", time.time()),
                            "sessions_seen": [self.session_count],
                            "appearance": desc[:100],
                            "traits": [],
                            "relationship": "",
                            "last_location": "",
                            "interaction_count": 1,
                        }

        # Convert conversation events to facts
        for ev in self.events:
            if "conversation" in ev.get("type", ""):
                self.facts.append({
                    "time": ev.get("time", time.time()),
                    "source": "migration",
                    "text": ev.get("data", "")[:200],
                    "tags": ["conversation", "migrated"],
                    "person": None,
                })
        # Cap facts
        if len(self.facts) > 100:
            self.facts = self.facts[-100:]

        print(f"  [memory migrated v2->v3: {len(self.known_people)} people, {len(self.facts)} facts]")
