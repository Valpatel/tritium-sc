# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""BehaviorTreeFallback — weighted-random NPC decision making.

When the LLM is unavailable or a brain doesn't need a full think cycle,
this fallback makes quick behavioral decisions based on personality traits,
danger level, and interest level.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.simulation.npc_intelligence.brain import NPCBrain


# Danger threshold above which danger-based actions dominate
_DANGER_THRESHOLD = 0.3

# Interest threshold above which interest-based actions are considered
_INTEREST_THRESHOLD = 0.3

# Default actions per asset type (no danger, no interest)
_DEFAULT_ACTIONS: dict[str, list[tuple[str, float]]] = {
    "person": [("WALK", 0.7), ("PAUSE", 0.3)],
    "vehicle": [("DRIVE", 0.9), ("PAUSE", 0.1)],
    "animal": [("WANDER", 0.8), ("PAUSE", 0.2)],
}


def _weighted_choice(options: list[tuple[str, float]]) -> str:
    """Pick a random action from weighted options."""
    total = sum(w for _, w in options)
    if total <= 0:
        return options[0][0] if options else "WALK"
    r = random.uniform(0, total)
    cumulative = 0.0
    for action, weight in options:
        cumulative += weight
        if r <= cumulative:
            return action
    return options[-1][0]


class BehaviorTreeFallback:
    """Makes quick weighted-random decisions for NPCs without LLM thinking."""

    def decide(
        self,
        brain: NPCBrain,
        danger_level: float,
        interest_level: float,
    ) -> str:
        """Decide an action based on brain personality, danger, and interest.

        Returns one of: WALK, FLEE, HIDE, OBSERVE, APPROACH, PAUSE, IGNORE,
        DRIVE, WANDER.
        """
        caution = brain.personality.caution
        curiosity = brain.personality.curiosity
        asset_type = brain.asset_type

        # Danger takes priority over interest
        if danger_level >= _DANGER_THRESHOLD:
            return self._danger_decision(danger_level, caution, asset_type)

        if interest_level >= _INTEREST_THRESHOLD:
            return self._interest_decision(interest_level, curiosity, asset_type)

        return self._normal_decision(asset_type)

    def _danger_decision(
        self,
        danger_level: float,
        caution: float,
        asset_type: str,
    ) -> str:
        """Decide when danger is present."""
        # Combined urgency: danger * (0.5 + 0.5 * caution)
        # High caution amplifies danger response
        urgency = danger_level * (0.5 + 0.5 * caution)

        if asset_type == "vehicle":
            # Vehicles evade (mapped to FLEE in action map)
            return "FLEE"

        if asset_type == "animal":
            return "FLEE"

        # Pedestrian: FLEE vs HIDE weighted by caution and danger
        flee_weight = urgency * 1.5
        hide_weight = urgency * caution
        return _weighted_choice([("FLEE", flee_weight), ("HIDE", hide_weight)])

    def _interest_decision(
        self,
        interest_level: float,
        curiosity: float,
        asset_type: str,
    ) -> str:
        """Decide when something interesting is happening."""
        # Combined pull: interest * curiosity
        pull = interest_level * curiosity

        if asset_type == "vehicle":
            # Vehicles mostly keep driving; high pull might make them pause
            if pull > 0.5:
                return _weighted_choice([("DRIVE", 0.6), ("PAUSE", 0.4)])
            return "DRIVE"

        if asset_type == "animal":
            if pull > 0.4:
                return _weighted_choice([("WANDER", 0.6), ("PAUSE", 0.4)])
            return "WANDER"

        # Pedestrian: curiosity determines approach vs observe vs walk
        if pull > 0.4:
            approach_weight = pull * 1.0
            observe_weight = pull * 0.8
            walk_weight = (1.0 - pull) * 0.5
            pause_weight = (1.0 - pull) * 0.3
            return _weighted_choice([
                ("APPROACH", approach_weight),
                ("OBSERVE", observe_weight),
                ("WALK", walk_weight),
                ("PAUSE", pause_weight),
            ])

        # Low pull: mostly walk/pause with slight chance of approach
        return _weighted_choice([
            ("WALK", 0.6),
            ("PAUSE", 0.3),
            ("APPROACH", 0.1),
        ])

    def _normal_decision(self, asset_type: str) -> str:
        """Decide under normal conditions (no danger, no interest)."""
        options = _DEFAULT_ACTIONS.get(asset_type, _DEFAULT_ACTIONS["person"])
        return _weighted_choice(options)
