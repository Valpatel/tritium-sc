# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""NPC Context-Aware Thought Bubble Plugin — reference implementation.

Demonstrates the ThoughtRegistry + PluginInterface end-to-end:
  EventBus events -> brain state analysis -> template thought -> ThoughtRegistry
  -> EventBus("npc_thought") -> WebSocket bridge -> frontend speech bubble

This plugin reads each NPC's FSM state, personality, and memory (danger/interest
levels) and selects a contextual thought from template tables. No LLM needed —
pure template-based for predictability and zero latency.

Use this as a reference for building external thought providers (Graphlings, etc.).
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from engine.plugins.base import PluginContext, PluginInterface

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thought template tables
# ---------------------------------------------------------------------------
# Keyed by (fsm_state, situation) -> list of (text, emotion, weight)
# Situation: "danger" | "tense" | "interest" | "calm"
# Emotion:   "neutral" | "curious" | "afraid" | "angry" | "happy"

_PEDESTRIAN_THOUGHTS: dict[tuple[str, str], list[tuple[str, str, int]]] = {
    # -- calm states --
    ("walking", "calm"): [
        ("Nice day for a walk", "happy", 2),
        ("Where was that coffee shop?", "curious", 1),
        ("I wonder what's for dinner", "neutral", 1),
        ("Almost there", "neutral", 1),
        ("La la la...", "happy", 1),
    ],
    ("pausing", "calm"): [
        ("Let me check my phone", "neutral", 2),
        ("Nice view from here", "happy", 1),
        ("Which way was it again?", "curious", 1),
    ],
    # -- tense states --
    ("walking", "tense"): [
        ("Something feels off...", "afraid", 2),
        ("I should get home", "neutral", 1),
        ("Was that a gunshot?", "afraid", 1),
        ("I don't like this", "afraid", 1),
    ],
    ("pausing", "tense"): [
        ("Maybe I should turn around", "afraid", 2),
        ("What was that noise?", "afraid", 1),
    ],
    # -- interest states --
    ("walking", "interest"): [
        ("What's happening over there?", "curious", 2),
        ("Is that a robot?!", "curious", 2),
        ("Let me go see", "curious", 1),
    ],
    ("observing", "interest"): [
        ("What's going on over there?", "curious", 2),
        ("Is that a robot?", "curious", 2),
        ("Whoa, cool!", "happy", 1),
        ("I should record this", "curious", 1),
    ],
    ("observing", "calm"): [
        ("Interesting...", "curious", 2),
        ("Hmm, what's that about?", "curious", 1),
    ],
    ("curious", "interest"): [
        ("I wonder what that is", "curious", 2),
        ("Let me get a closer look", "curious", 1),
        ("That looks interesting!", "curious", 1),
    ],
    ("curious", "calm"): [
        ("What's over here?", "curious", 2),
        ("Ooh, what's that?", "curious", 1),
    ],
    # -- danger states --
    ("fleeing", "danger"): [
        ("Run!", "afraid", 3),
        ("I need to get out of here!", "afraid", 2),
        ("Go go go!", "afraid", 2),
        ("Not today!", "afraid", 1),
    ],
    ("fleeing", "tense"): [
        ("Better safe than sorry", "afraid", 2),
        ("I'm outta here", "afraid", 1),
    ],
    ("hiding", "danger"): [
        ("Stay quiet...", "afraid", 2),
        ("Please don't find me", "afraid", 1),
        ("...", "afraid", 1),
    ],
    ("hiding", "tense"): [
        ("I'll just wait here", "afraid", 1),
        ("Is it safe yet?", "afraid", 1),
    ],
    ("panicking", "danger"): [
        ("HELP!", "afraid", 3),
        ("Oh no oh no oh no", "afraid", 2),
        ("AHHH!", "afraid", 2),
        ("Somebody help!", "afraid", 1),
    ],
    ("panicking", "tense"): [
        ("This is bad!", "afraid", 2),
        ("What do I do?!", "afraid", 1),
    ],
}

_VEHICLE_THOUGHTS: dict[tuple[str, str], list[tuple[str, str, int]]] = {
    ("driving", "calm"): [
        ("Traffic's moving well", "neutral", 1),
        ("Almost there", "neutral", 1),
        ("Nice day for a drive", "happy", 1),
    ],
    ("driving", "tense"): [
        ("What's happening up ahead?", "afraid", 1),
        ("I should be careful", "neutral", 1),
    ],
    ("driving", "interest"): [
        ("What's that on the road?", "curious", 1),
        ("Is that a drone?", "curious", 1),
    ],
    ("stopped", "calm"): [
        ("Red light I guess", "neutral", 1),
        ("Come on, come on...", "neutral", 1),
    ],
    ("stopped", "tense"): [
        ("Why is everyone stopped?", "afraid", 1),
        ("Something's wrong", "afraid", 1),
    ],
    ("yielding", "calm"): [
        ("After you", "neutral", 1),
        ("Go ahead", "neutral", 1),
    ],
    ("evading", "danger"): [
        ("Get out of the way!", "angry", 2),
        ("Swerve!", "afraid", 1),
        ("Move move move!", "afraid", 2),
    ],
    ("evading", "tense"): [
        ("Gotta go around", "afraid", 1),
        ("Watch out!", "afraid", 1),
    ],
    ("parked", "calm"): [
        ("Finally parked", "neutral", 1),
        ("Time for a break", "happy", 1),
    ],
}

_ANIMAL_THOUGHTS: dict[tuple[str, str], list[tuple[str, str, int]]] = {
    ("wandering", "calm"): [
        ("Sniff sniff", "curious", 2),
        ("...", "neutral", 1),
        ("*tail wag*", "happy", 1),
    ],
    ("wandering", "interest"): [
        ("What's that smell?", "curious", 2),
        ("Ooh!", "curious", 1),
    ],
    ("resting", "calm"): [
        ("Zzz...", "neutral", 2),
        ("*yawn*", "neutral", 1),
    ],
    ("startled", "danger"): [
        ("!", "afraid", 3),
        ("BARK!", "afraid", 2),
    ],
    ("startled", "tense"): [
        ("Huh?", "afraid", 1),
        ("*ears perk up*", "curious", 1),
    ],
    ("fleeing", "danger"): [
        ("*whimper*", "afraid", 2),
        ("YELP!", "afraid", 1),
    ],
    ("following", "calm"): [
        ("*happy panting*", "happy", 2),
        ("Where are we going?", "curious", 1),
    ],
}

# Generic fallback for any unknown state/situation combo
_FALLBACK_THOUGHTS: list[tuple[str, str, int]] = [
    ("...", "neutral", 3),
    ("Hmm", "neutral", 1),
    ("Huh", "curious", 1),
]

# Table selection by asset type
_THOUGHT_TABLES: dict[str, dict] = {
    "person": _PEDESTRIAN_THOUGHTS,
    "vehicle": _VEHICLE_THOUGHTS,
    "animal": _ANIMAL_THOUGHTS,
}

# ---------------------------------------------------------------------------
# Interval constants
# ---------------------------------------------------------------------------

_THINK_MIN = 8.0   # min seconds between thoughts
_THINK_MAX = 15.0  # max seconds between thoughts
_DURATION_MIN = 4.0  # thought bubble visible for 4-8s
_DURATION_MAX = 8.0

# Situation thresholds
_DANGER_THRESHOLD = 0.3
_TENSE_THRESHOLD = 0.1
_INTEREST_THRESHOLD = 0.3


# ===========================================================================
# Plugin
# ===========================================================================


class NPCContextThoughts(PluginInterface):
    """Generates context-aware thought bubbles for NPCs.

    Reads each NPC's brain state (FSM state, personality, danger/interest)
    and publishes a contextual thought from template tables via ThoughtRegistry.
    """

    def __init__(self) -> None:
        self._npc_plugin: Any = None
        self._thought_registry: Any = None
        self._event_bus: Any = None
        self._started: bool = False
        self._next_think: dict[str, float] = {}  # unit_id -> monotonic time

    # -- PluginInterface identity --

    @property
    def plugin_id(self) -> str:
        return "tritium.npc-context-thoughts"

    @property
    def name(self) -> str:
        return "NPC Context Thoughts"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"ai"}

    @property
    def dependencies(self) -> list[str]:
        return ["tritium.npc-intelligence"]

    # -- PluginInterface lifecycle --

    def configure(self, ctx: PluginContext) -> None:
        """Store references to NPC intelligence plugin and thought registry."""
        self._event_bus = ctx.event_bus
        self._npc_plugin = ctx.plugin_manager.get_plugin("tritium.npc-intelligence")
        if self._npc_plugin is not None:
            self._thought_registry = self._npc_plugin.thought_registry
        log.info(
            "NPC Context Thoughts configured (intelligence=%s, registry=%s)",
            self._npc_plugin is not None,
            self._thought_registry is not None,
        )

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        log.info("NPC Context Thoughts started")

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self._next_think.clear()
        log.info("NPC Context Thoughts stopped")

    # -- Core logic --

    def tick(self, dt: float) -> None:
        """Called each simulation tick. Checks each NPC for thought readiness."""
        if not self._started or self._npc_plugin is None or self._thought_registry is None:
            return

        now = time.monotonic()
        brains: dict = self._npc_plugin._brains

        for target_id, brain in brains.items():
            # Skip bound (externally controlled) NPCs
            if brain.is_bound:
                continue

            # Check if it's time to think
            deadline = self._next_think.get(target_id)
            if deadline is not None and now < deadline:
                continue

            # Classify situation from brain memory
            danger = brain.memory.danger_level()
            interest = brain.memory.interest_level()
            situation = self._classify_situation(danger, interest)

            # Get FSM state
            fsm_state = brain.fsm_state or "walking"

            # Pick a thought
            text, emotion = self._pick_thought(brain.asset_type, fsm_state, situation)

            # Publish
            duration = random.uniform(_DURATION_MIN, _DURATION_MAX)
            self._thought_registry.set_thought(
                target_id,
                text,
                emotion=emotion,
                duration=duration,
            )

            # Schedule next thought (staggered)
            self._next_think[target_id] = now + random.uniform(_THINK_MIN, _THINK_MAX)

    # -- Helpers (static for testability) --

    @staticmethod
    def _classify_situation(danger: float, interest: float) -> str:
        """Classify the NPC's current situation from memory levels.

        Returns: "danger" | "tense" | "interest" | "calm"
        """
        if danger >= _DANGER_THRESHOLD:
            return "danger"
        if danger >= _TENSE_THRESHOLD:
            return "tense"
        if interest >= _INTEREST_THRESHOLD:
            return "interest"
        return "calm"

    @staticmethod
    def _pick_thought(
        asset_type: str, fsm_state: str, situation: str
    ) -> tuple[str, str]:
        """Pick a weighted-random thought for the given context.

        Returns: (text, emotion)
        """
        table = _THOUGHT_TABLES.get(asset_type, _PEDESTRIAN_THOUGHTS)

        # Try exact match first
        options = table.get((fsm_state, situation))

        # Fallback: try same state with "calm"
        if not options:
            options = table.get((fsm_state, "calm"))

        # Fallback: try default state for this situation
        if not options:
            defaults = {
                "person": "walking",
                "vehicle": "driving",
                "animal": "wandering",
            }
            default_state = defaults.get(asset_type, "walking")
            options = table.get((default_state, situation))

        # Fallback: try default state with "calm"
        if not options:
            defaults = {
                "person": "walking",
                "vehicle": "driving",
                "animal": "wandering",
            }
            default_state = defaults.get(asset_type, "walking")
            options = table.get((default_state, "calm"))

        # Final fallback
        if not options:
            options = _FALLBACK_THOUGHTS

        # Weighted random selection
        texts, emotions, weights = zip(*options)
        chosen = random.choices(list(zip(texts, emotions)), weights=weights, k=1)[0]
        return chosen
