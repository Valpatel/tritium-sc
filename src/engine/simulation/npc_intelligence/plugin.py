"""NPCIntelligencePlugin — PluginInterface implementation.

Ties together NPCBrain, EventReactor, CrowdDynamics, AllianceManager,
LLMThinkScheduler, and BehaviorTreeFallback into a single plugin that
observes the simulation via EventBus and adds behavioral AI to NPCs.
"""

from __future__ import annotations

import logging
from typing import Any

from engine.plugins.base import PluginContext, PluginInterface
from .brain import NPCBrain
from .event_reactor import EventReactor
from .crowd import CrowdDynamics
from .alliance import AllianceManager
from .think_scheduler import LLMThinkScheduler
from .thought_registry import ThoughtRegistry
from .fallback import BehaviorTreeFallback

log = logging.getLogger(__name__)


class NPCIntelligencePlugin(PluginInterface):
    """Behavioral AI for neutral NPCs (pedestrians, vehicles, animals).

    Implements PluginInterface. Observes via EventBus, mutates NPCs
    by directly accessing SimulationTarget objects.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._engine: Any = None
        self._brains: dict[str, NPCBrain] = {}
        self._reactor: EventReactor | None = None
        self._crowd: CrowdDynamics = CrowdDynamics()
        self._alliance_mgr: AllianceManager | None = None
        self._scheduler: LLMThinkScheduler | None = None
        self._fallback: BehaviorTreeFallback = BehaviorTreeFallback()
        self._thought_registry: ThoughtRegistry | None = None
        self._started: bool = False

    # -- PluginInterface identity --

    @property
    def plugin_id(self) -> str:
        return "tritium.npc-intelligence"

    @property
    def name(self) -> str:
        return "NPC Intelligence"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"ai", "data_source", "background"}

    # -- PluginInterface lifecycle --

    def configure(self, ctx: PluginContext) -> None:
        """Store references to shared services."""
        self._event_bus = ctx.event_bus
        self._engine = ctx.simulation_engine
        self._reactor = EventReactor(ctx.event_bus)
        self._alliance_mgr = AllianceManager(event_bus=ctx.event_bus)
        self._scheduler = LLMThinkScheduler()
        self._thought_registry = ThoughtRegistry(event_bus=ctx.event_bus, plugin=self)

    def start(self) -> None:
        """Start event reactor and think scheduler."""
        if self._started:
            return
        if self._reactor is not None:
            self._reactor.start()
        if self._scheduler is not None:
            self._scheduler.start()
        if self._thought_registry is not None:
            self._thought_registry.start()
        self._started = True
        log.info("NPC Intelligence plugin started (%d brains)", len(self._brains))

    def stop(self) -> None:
        """Stop event reactor and think scheduler."""
        if not self._started:
            return
        if self._reactor is not None:
            self._reactor.stop()
        if self._scheduler is not None:
            self._scheduler.stop()
        if self._thought_registry is not None:
            self._thought_registry.stop()
        self._started = False
        log.info("NPC Intelligence plugin stopped")

    @property
    def healthy(self) -> bool:
        """Health check."""
        if not self._started:
            return True  # not started yet is OK
        if self._scheduler is not None and not self._scheduler.healthy:
            return False
        return True

    @property
    def thought_registry(self) -> ThoughtRegistry | None:
        """Access the thought registry."""
        return self._thought_registry

    # -- Brain management --

    def attach_brain(
        self,
        target_id: str,
        asset_type: str,
        alliance: str,
    ) -> NPCBrain:
        """Create and attach a brain for an NPC target."""
        brain = NPCBrain(target_id, asset_type, alliance)
        self._brains[target_id] = brain
        return brain

    def detach_brain(self, target_id: str) -> bool:
        """Remove a brain. Returns True if found."""
        return self._brains.pop(target_id, None) is not None

    def get_brain(self, target_id: str) -> NPCBrain | None:
        """Get a brain by target ID."""
        return self._brains.get(target_id)

    @property
    def brain_count(self) -> int:
        """Number of attached brains."""
        return len(self._brains)

    # -- Tick (called by brain_manager or externally) --

    def tick(self, dt: float, targets_with_positions: list[tuple[str, tuple[float, float]]] | None = None) -> None:
        """Tick all brains, process crowd dynamics, check alliance transitions.

        Args:
            dt: Time delta.
            targets_with_positions: Optional list of (target_id, (x, y)) for position context.
        """
        if not self._started:
            return

        # Build brains-with-positions list
        bwp = []
        pos_map: dict[str, tuple[float, float]] = {}
        if targets_with_positions:
            pos_map = {tid: pos for tid, pos in targets_with_positions}

        for tid, brain in self._brains.items():
            pos = pos_map.get(tid, (0.0, 0.0))
            bwp.append((brain, pos))

        # Tick FSMs
        for brain, _ in bwp:
            brain.tick(dt)

        # Crowd dynamics
        self._crowd.update(bwp)

        # Check for LLM thinking needs (schedule or fallback)
        for brain, _ in bwp:
            if brain.is_bound:
                continue
            if brain._needs_fallback:
                action = self._fallback.decide(
                    brain, brain.memory.danger_level(), brain.memory.interest_level()
                )
                brain.apply_action(action)
                brain._needs_fallback = False
                brain.mark_thought()
                # Publish thought bubble for fallback action
                if self._thought_registry is not None:
                    self._thought_registry.set_thought(
                        brain.target_id,
                        action.capitalize(),
                        duration=3.0,
                    )

    def _on_think_result(self, target_id: str, action: str) -> None:
        """Callback from LLMThinkScheduler."""
        brain = self._brains.get(target_id)
        if brain is not None:
            brain.apply_action(action)
