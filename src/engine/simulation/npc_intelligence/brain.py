"""NPCBrain, NPCPersonality, NPCMemory — per-NPC intelligence state.

Each NPC gets one NPCBrain that holds:
- A StateMachine (from npc_fsm.py)
- A NPCPersonality (random traits)
- A NPCMemory (short-term event buffer)

The brain ticks the FSM with context derived from personality + memory,
tracks when LLM thinking is needed, and applies LLM/fallback decisions.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any

from engine.simulation.state_machine import StateMachine
from .npc_fsm import create_npc_fsm


# ============================================================================
# Personality
# ============================================================================

@dataclass
class NPCPersonality:
    """Four personality traits (0.0-1.0) that influence NPC behavior."""

    curiosity: float = 0.5
    caution: float = 0.5
    sociability: float = 0.5
    aggression: float = 0.1

    @classmethod
    def random(cls) -> NPCPersonality:
        """Create a personality with fully random traits."""
        return cls(
            curiosity=random.uniform(0.0, 1.0),
            caution=random.uniform(0.0, 1.0),
            sociability=random.uniform(0.0, 1.0),
            aggression=random.uniform(0.0, 1.0),
        )

    @classmethod
    def for_asset_type(cls, asset_type: str) -> NPCPersonality:
        """Create a personality with type-appropriate trait ranges."""
        if asset_type == "person":
            return cls(
                curiosity=random.uniform(0.3, 0.7),
                caution=random.uniform(0.3, 0.7),
                sociability=random.uniform(0.4, 0.8),
                aggression=random.uniform(0.0, 0.3),
            )
        elif asset_type == "vehicle":
            return cls(
                curiosity=random.uniform(0.1, 0.3),
                caution=random.uniform(0.5, 0.9),
                sociability=random.uniform(0.1, 0.3),
                aggression=random.uniform(0.0, 0.1),
            )
        elif asset_type == "animal":
            return cls(
                curiosity=random.uniform(0.2, 0.5),
                caution=random.uniform(0.6, 0.9),
                sociability=random.uniform(0.1, 0.4),
                aggression=random.uniform(0.0, 0.1),
            )
        else:
            return cls.random()

    def to_dict(self) -> dict[str, float]:
        return {
            "curiosity": self.curiosity,
            "caution": self.caution,
            "sociability": self.sociability,
            "aggression": self.aggression,
        }


# ============================================================================
# Memory
# ============================================================================

# Event types that count as "combat" for radicalization checks
_COMBAT_EVENT_TYPES = {"target_eliminated", "weapon_fired", "unit_destroyed"}

# Danger weights by event type
_DANGER_WEIGHTS: dict[str, float] = {
    "weapon_fired": 0.6,
    "target_eliminated": 0.8,
    "unit_destroyed": 0.7,
    "explosion": 1.0,
    "wave_start": 0.3,
    "escalation_change": 0.4,
}

# Interest weights by event type
_INTEREST_WEIGHTS: dict[str, float] = {
    "wave_start": 0.5,
    "wave_complete": 0.4,
    "escalation_change": 0.3,
    "weapon_fired": 0.2,
    "target_eliminated": 0.3,
    "npc_alliance_change": 0.6,
}


class NPCMemory:
    """Short-term event buffer for an NPC. Tracks recent events with timestamps."""

    def __init__(self, max_events: int = 20) -> None:
        self.max_events = max_events
        self.events: list[dict] = []

    def add_event(self, event_type: str, data: dict | None = None) -> None:
        """Record an event."""
        entry = {
            "type": event_type,
            "timestamp": time.time(),
            "data": data or {},
        }
        self.events.append(entry)
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

    def recent(self, count: int) -> list[dict]:
        """Return the N most recent events."""
        return self.events[-count:]

    def danger_level(self) -> float:
        """Compute a danger level (0.0-1.0) from recent events.

        Danger decays with event age. Events within 10s are full weight,
        events older than 60s contribute almost nothing.
        """
        if not self.events:
            return 0.0

        now = time.time()
        total = 0.0
        for event in self.events:
            weight = _DANGER_WEIGHTS.get(event["type"], 0.0)
            if weight <= 0:
                continue
            age = now - event["timestamp"]
            # Exponential decay: half-life ~15s
            decay = 2.0 ** (-age / 15.0)
            # Distance factor: closer events are more dangerous
            dist = event.get("data", {}).get("distance", 50.0)
            dist_factor = max(0.0, 1.0 - dist / 100.0)
            total += weight * decay * dist_factor

        return min(1.0, total)

    def interest_level(self) -> float:
        """Compute an interest level (0.0-1.0) from recent events."""
        if not self.events:
            return 0.0

        now = time.time()
        total = 0.0
        for event in self.events:
            weight = _INTEREST_WEIGHTS.get(event["type"], 0.0)
            if weight <= 0:
                continue
            age = now - event["timestamp"]
            decay = 2.0 ** (-age / 30.0)
            total += weight * decay

        return min(1.0, total)

    def combat_events_in_window(self, window_seconds: float) -> int:
        """Count combat events within the time window."""
        cutoff = time.time() - window_seconds
        return sum(
            1 for e in self.events
            if e["type"] in _COMBAT_EVENT_TYPES and e["timestamp"] >= cutoff
        )

    def format_for_prompt(self) -> str:
        """Format recent events as text for LLM prompt."""
        if not self.events:
            return "(none)"
        lines = []
        for event in self.events[-10:]:
            etype = event["type"]
            dist = event.get("data", {}).get("distance")
            if dist is not None:
                lines.append(f"- {etype} (distance: {dist:.0f}m)")
            else:
                lines.append(f"- {etype}")
        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all events."""
        self.events.clear()


# ============================================================================
# Action -> FSM State mapping
# ============================================================================

# Maps LLM action words to FSM state names per NPC type
_PEDESTRIAN_ACTION_MAP: dict[str, str] = {
    "WALK": "walking",
    "PAUSE": "pausing",
    "OBSERVE": "observing",
    "FLEE": "fleeing",
    "HIDE": "hiding",
    "APPROACH": "curious",
    "IGNORE": "walking",
    "PANIC": "panicking",
}

_VEHICLE_ACTION_MAP: dict[str, str] = {
    "DRIVE": "driving",
    "STOP": "stopped",
    "YIELD": "yielding",
    "EVADE": "evading",
    "PARK": "parked",
    "WALK": "driving",
    "FLEE": "evading",
    "IGNORE": "driving",
}

_ANIMAL_ACTION_MAP: dict[str, str] = {
    "WANDER": "wandering",
    "REST": "resting",
    "FLEE": "fleeing",
    "FOLLOW": "following",
    "WALK": "wandering",
    "IGNORE": "wandering",
}


def _action_map_for_type(asset_type: str) -> dict[str, str]:
    if asset_type == "vehicle":
        return _VEHICLE_ACTION_MAP
    if asset_type == "animal":
        return _ANIMAL_ACTION_MAP
    return _PEDESTRIAN_ACTION_MAP


# ============================================================================
# NPCBrain
# ============================================================================

# Think interval range (seconds) — staggered per NPC
_THINK_MIN = 5.0
_THINK_MAX = 10.0


class NPCBrain:
    """Per-NPC brain: FSM + personality + memory + think scheduling."""

    def __init__(
        self,
        target_id: str,
        asset_type: str,
        alliance: str,
        personality: NPCPersonality | None = None,
    ) -> None:
        self.target_id = target_id
        self.asset_type = asset_type
        self.alliance = alliance
        self.personality = personality or NPCPersonality.for_asset_type(asset_type)
        self.memory = NPCMemory()
        self.fsm: StateMachine | None = create_npc_fsm(asset_type, alliance)

        # Think scheduling
        self._think_interval = random.uniform(_THINK_MIN, _THINK_MAX)
        self._last_think_time: float = 0.0

        # Binding (sim-to-live switching)
        self._bound: bool = False

        # Fallback flag — set by LLMThinkScheduler on LLM failure
        self._needs_fallback: bool = False

        # Current context overrides (set by EventReactor / CrowdDynamics)
        self._danger_nearby: bool = False
        self._danger_distance: float = 999.0
        self._interest_nearby: bool = False
        self._interest_distance: float = 999.0
        self._cover_available: bool = False

        # Action map for this type
        self._action_map = _action_map_for_type(asset_type)

    @property
    def fsm_state(self) -> str | None:
        """Current FSM state name."""
        if self.fsm is None:
            return None
        return self.fsm.current_state

    @property
    def is_bound(self) -> bool:
        """Whether this NPC is bound to real tracking data."""
        return self._bound

    def bind(self) -> None:
        """Suspend AI when NPC is bound to real data."""
        self._bound = True

    def unbind(self) -> None:
        """Resume AI when NPC is unbound."""
        self._bound = False

    def needs_think(self) -> bool:
        """Check if this NPC needs an LLM think cycle."""
        if self._bound:
            return False
        if self.fsm is None:
            return False
        elapsed = time.monotonic() - self._last_think_time
        return elapsed >= self._think_interval

    def mark_thought(self) -> None:
        """Mark that a think cycle was just completed."""
        self._last_think_time = time.monotonic()
        # Randomize next interval slightly
        self._think_interval = random.uniform(_THINK_MIN, _THINK_MAX)

    def tick(self, dt: float) -> None:
        """Tick the FSM with current context."""
        if self._bound or self.fsm is None:
            return
        ctx = self.build_fsm_context()
        self.fsm.tick(dt, ctx)

    def build_fsm_context(
        self,
        danger_nearby: bool | None = None,
        danger_distance: float | None = None,
        interest_nearby: bool | None = None,
        interest_distance: float | None = None,
        cover_available: bool | None = None,
        **extra: Any,
    ) -> dict:
        """Build the context dict for FSM tick."""
        ctx = {
            "danger_nearby": danger_nearby if danger_nearby is not None else self._danger_nearby,
            "danger_distance": danger_distance if danger_distance is not None else self._danger_distance,
            "interest_nearby": interest_nearby if interest_nearby is not None else self._interest_nearby,
            "interest_distance": interest_distance if interest_distance is not None else self._interest_distance,
            "cover_available": cover_available if cover_available is not None else self._cover_available,
            "curiosity": self.personality.curiosity,
            "caution": self.personality.caution,
            # Animal-specific
            "loud_noise": self._danger_nearby,
            "is_dog": self.asset_type == "animal",  # simplified: all animals can follow
            "person_nearby": False,  # set externally
            # Vehicle-specific
            "obstacle_ahead": False,
            "emergency_nearby": False,
        }
        ctx.update(extra)
        return ctx

    def apply_action(self, action: str) -> None:
        """Apply an LLM/fallback action to the FSM."""
        if self.fsm is None:
            return
        action_upper = action.upper().strip()
        target_state = self._action_map.get(action_upper)
        if target_state is not None and target_state in self.fsm.state_names:
            self.fsm.force_state(target_state)

    def force_state(self, state_name: str) -> None:
        """Force the FSM to a specific state."""
        if self.fsm is not None and state_name in self.fsm.state_names:
            self.fsm.force_state(state_name)

    def set_danger(self, distance: float = 10.0) -> None:
        """Set danger context."""
        self._danger_nearby = True
        self._danger_distance = distance

    def clear_danger(self) -> None:
        """Clear danger context."""
        self._danger_nearby = False
        self._danger_distance = 999.0

    def set_interest(self, distance: float = 20.0) -> None:
        """Set interest context."""
        self._interest_nearby = True
        self._interest_distance = distance

    def clear_interest(self) -> None:
        """Clear interest context."""
        self._interest_nearby = False
        self._interest_distance = 999.0

    def get_state(self) -> dict:
        """Get the brain state as a dict (for API/debugging)."""
        return {
            "target_id": self.target_id,
            "asset_type": self.asset_type,
            "alliance": self.alliance,
            "fsm_state": self.fsm_state,
            "personality": self.personality.to_dict(),
            "memory_count": len(self.memory.events),
            "danger_level": self.memory.danger_level(),
            "interest_level": self.memory.interest_level(),
            "is_bound": self._bound,
        }
