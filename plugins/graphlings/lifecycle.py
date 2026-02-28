# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SimulationLifecycleHandler — auto-deploy graphlings on countdown, recall on game over.

Listens for game_state_change events from the EventBus and orchestrates
batch deploy/recall of graphlings via the AgentBridge.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_bridge import AgentBridge
    from .config import GraphlingsConfig
    from .entity_factory import EntityFactory

log = logging.getLogger(__name__)


class SimulationLifecycleHandler:
    """Auto-deploys graphlings on simulation countdown, recalls on game over."""

    def __init__(
        self,
        bridge: AgentBridge,
        entity_factory: EntityFactory,
        config: GraphlingsConfig,
    ) -> None:
        self._bridge = bridge
        self._factory = entity_factory
        self._config = config
        self._deployed = False
        self._deployed_souls: list[str] = []

    def on_game_state_change(self, event: dict) -> None:
        """Handle game state change events from EventBus."""
        state = event.get("data", {}).get("state", "")
        if state == "countdown" and not self._deployed:
            self._deploy_all()
        elif state in ("victory", "defeat", "game_over"):
            self._recall_all(reason=state)

    def _deploy_all(self) -> None:
        """Deploy all available graphlings via batch endpoint."""
        config = {
            "context": self._config.default_context,
            "role_name": "civilian",
            "service_name": self._config.default_service_name,
            "consciousness_layer_min": self._config.default_consciousness_min,
            "consciousness_layer_max": self._config.default_consciousness_max,
            "allowed_actions": ["say", "move_to", "observe", "flee", "emote"],
        }
        result = self._bridge.batch_deploy(
            {"config": config, "max_agents": self._config.max_agents}
        )
        if result is None:
            return  # Server unreachable

        deployed = result.get("deployed", [])
        points = list(self._config.spawn_points.values())
        for i, entry in enumerate(deployed):
            soul_id = entry["soul_id"]
            name = entry.get("name", soul_id)
            # First graphling is drone_operator (combatant), rest are civilians
            is_combatant = i == 0
            spawn_point = points[i % len(points)] if points else (0.0, 0.0)
            self._factory.spawn(
                soul_id, name, spawn_point, is_combatant=is_combatant
            )
            self._deployed_souls.append(soul_id)

        self._deployed = True

    def _recall_all(self, reason: str) -> None:
        """Recall all deployed graphlings."""
        if not self._deployed:
            return
        self._bridge.batch_recall(self._config.default_service_name, reason)
        self._factory.despawn_all()
        self._deployed_souls.clear()
        self._deployed = False
