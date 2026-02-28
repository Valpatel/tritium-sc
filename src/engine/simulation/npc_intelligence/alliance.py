"""AllianceManager — handles NPC radicalization (neutral -> hostile).

Radicalization conditions (ALL must be true):
1. 3+ target_eliminated events in NPC memory within 60s
2. Global escalation level is "amber" or "red"
3. No friendly units within 30m of the NPC
4. NPC aggression trait > 0.7
5. Global cooldown: 120s since last radicalization

On radicalization the target gains hostile combat stats, a hostile FSM,
and a MovementController for smooth movement.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus

from engine.simulation.npc_intelligence.brain import NPCBrain
from engine.simulation.target import SimulationTarget
from engine.simulation.unit_states import create_hostile_fsm
from engine.simulation.movement import MovementController


# Radicalization thresholds
_MIN_ELIMINATIONS = 3
_ELIMINATION_WINDOW = 60.0  # seconds
_VALID_ESCALATION_LEVELS = {"amber", "red"}
_FRIENDLY_EXCLUSION_RADIUS = 30.0  # meters
_MIN_AGGRESSION = 0.7  # strictly greater than

# Hostile combat profile applied on radicalization
_HOSTILE_HEALTH = 80.0
_HOSTILE_WEAPON_RANGE = 40.0
_HOSTILE_WEAPON_COOLDOWN = 2.5
_HOSTILE_WEAPON_DAMAGE = 10.0


class AllianceManager:
    """Manages NPC alliance transitions (radicalization)."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus
        self._last_radicalization_time: float = 0.0
        self._radicalization_cooldown: float = 120.0

    def check_radicalization(
        self,
        brain: NPCBrain,
        target: SimulationTarget,
        escalation_level: str,
        friendly_positions: list[tuple[float, float]],
    ) -> str | None:
        """Check if an NPC should radicalize. Returns target_id if radicalized, None otherwise."""

        # Already hostile -- nothing to do
        if target.alliance == "hostile":
            return None

        # Bound NPCs are controlled by live tracking data, not AI
        if brain.is_bound:
            return None

        # Condition 5: Global cooldown
        now = time.time()
        if (now - self._last_radicalization_time) < self._radicalization_cooldown:
            return None

        # Condition 4: Aggression must be strictly > 0.7
        if brain.personality.aggression <= _MIN_AGGRESSION:
            return None

        # Condition 2: Escalation level must be amber or red
        if escalation_level not in _VALID_ESCALATION_LEVELS:
            return None

        # Condition 1: 3+ target_eliminated events within 60s
        elim_count = self._count_eliminations(brain, _ELIMINATION_WINDOW)
        if elim_count < _MIN_ELIMINATIONS:
            return None

        # Condition 3: No friendly within 30m
        if self._friendly_nearby(target.position, friendly_positions):
            return None

        # All conditions met -- radicalize
        self._apply_radicalization(brain, target)
        self._last_radicalization_time = time.time()
        return target.target_id

    def _apply_radicalization(self, brain: NPCBrain, target: SimulationTarget) -> None:
        """Apply radicalization changes to the target."""
        old_alliance = target.alliance

        # Change alliance
        target.alliance = "hostile"
        target.is_combatant = True

        # Apply hostile combat profile
        target.health = _HOSTILE_HEALTH
        target.max_health = _HOSTILE_HEALTH
        target.weapon_range = _HOSTILE_WEAPON_RANGE
        target.weapon_cooldown = _HOSTILE_WEAPON_COOLDOWN
        target.weapon_damage = _HOSTILE_WEAPON_DAMAGE

        # Swap FSM to hostile behavior
        hostile_fsm = create_hostile_fsm()
        target.fsm_state = hostile_fsm.current_state

        # Create MovementController for smooth movement
        mc_heading = (90.0 - target.heading) % 360.0
        target.movement = MovementController(
            max_speed=target.speed,
            turn_rate=max(180.0, target.speed * 90.0),
            acceleration=max(4.0, target.speed * 2.0),
            deceleration=max(6.0, target.speed * 3.0),
            x=target.position[0],
            y=target.position[1],
            heading=mc_heading,
        )

        # Publish alliance change event
        if self._event_bus is not None:
            self._event_bus.publish("npc_alliance_change", {
                "target_id": target.target_id,
                "old_alliance": old_alliance,
                "new_alliance": "hostile",
            })

    @staticmethod
    def _count_eliminations(brain: NPCBrain, window_seconds: float) -> int:
        """Count target_eliminated events within the time window."""
        cutoff = time.time() - window_seconds
        return sum(
            1 for e in brain.memory.events
            if e["type"] == "target_eliminated" and e["timestamp"] >= cutoff
        )

    @staticmethod
    def _friendly_nearby(
        npc_position: tuple[float, float],
        friendly_positions: list[tuple[float, float]],
    ) -> bool:
        """Check if any friendly unit is within the exclusion radius."""
        nx, ny = npc_position
        for fx, fy in friendly_positions:
            dist = math.hypot(fx - nx, fy - ny)
            if dist <= _FRIENDLY_EXCLUSION_RADIUS:
                return True
        return False
