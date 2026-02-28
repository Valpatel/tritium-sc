"""CrowdDynamics — panic and curiosity contagion between nearby NPCs.

Simulates social effects: fleeing pedestrians cause panic in bystanders,
curious observers attract social NPCs. Vehicles and bound NPCs are excluded
from these effects.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.simulation.npc_intelligence.brain import NPCBrain

# Radius within which panic spreads from fleeing/panicking NPCs
_PANIC_RADIUS = 15.0

# Radius within which curiosity spreads from curious/observing NPCs
_CURIOSITY_RADIUS = 20.0

# Minimum sociability for an NPC to be attracted by curiosity
_SOCIABILITY_THRESHOLD = 0.4

# FSM states that indicate panic (source of contagion)
_PANIC_STATES = frozenset({"fleeing", "panicking"})

# FSM states that indicate curiosity (source of attraction)
_CURIOSITY_STATES = frozenset({"curious", "observing"})


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class CrowdDynamics:
    """Spreads panic and curiosity between nearby NPCs."""

    def update(
        self,
        brains_with_positions: list[tuple[NPCBrain, tuple[float, float]]],
    ) -> None:
        """Process crowd effects for all NPCs.

        For each NPC pair, check if one is fleeing/panicking (panic source)
        or curious/observing (curiosity source) and affect nearby NPCs.

        Args:
            brains_with_positions: List of (NPCBrain, (x, y)) tuples.
        """
        if len(brains_with_positions) < 2:
            return

        # Identify panic and curiosity sources (skip bound NPCs)
        panic_sources: list[tuple[NPCBrain, tuple[float, float]]] = []
        curiosity_sources: list[tuple[NPCBrain, tuple[float, float]]] = []

        for brain, pos in brains_with_positions:
            if brain.is_bound:
                continue
            state = brain.fsm_state
            if state in _PANIC_STATES:
                panic_sources.append((brain, pos))
            elif state in _CURIOSITY_STATES:
                curiosity_sources.append((brain, pos))

        # Spread panic
        for source_brain, source_pos in panic_sources:
            for target_brain, target_pos in brains_with_positions:
                if target_brain is source_brain:
                    continue
                if target_brain.is_bound:
                    continue
                # Vehicles are excluded from panic spreading
                if target_brain.asset_type == "vehicle":
                    continue

                dist = _distance(source_pos, target_pos)
                if dist <= _PANIC_RADIUS:
                    target_brain.set_danger(dist)

        # Spread curiosity
        for source_brain, source_pos in curiosity_sources:
            for target_brain, target_pos in brains_with_positions:
                if target_brain is source_brain:
                    continue
                if target_brain.is_bound:
                    continue

                # Only social NPCs are attracted
                if target_brain.personality.sociability < _SOCIABILITY_THRESHOLD:
                    continue

                dist = _distance(source_pos, target_pos)
                if dist <= _CURIOSITY_RADIUS:
                    target_brain.set_interest(dist)
