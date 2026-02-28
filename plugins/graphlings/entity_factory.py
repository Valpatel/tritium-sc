# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""EntityFactory — spawn and manage graphling SimulationTargets.

Creates SimulationTarget instances for graphlings deployed into the
tritium-sc world. Tracks the soul_id -> target_id mapping.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from engine.simulation.target import SimulationTarget

log = logging.getLogger(__name__)


class EntityFactory:
    """Creates and manages graphling entities in the simulation."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        # soul_id -> target_id
        self._soul_to_target: dict[str, str] = {}

    def spawn(
        self,
        soul_id: str,
        name: str,
        position: tuple[float, float],
        role_config: Optional[dict] = None,
        is_combatant: bool = False,
    ) -> str:
        """Spawn a graphling as a SimulationTarget.

        Returns the target_id of the created entity.
        """
        target_id = f"graphling_{soul_id}_{uuid.uuid4().hex[:8]}"

        target = SimulationTarget(
            target_id=target_id,
            name=name,
            alliance="friendly",
            asset_type="graphling",
            position=position,
            speed=1.0,
            battery=1.0,
            is_combatant=is_combatant,
            health=50.0,
            max_health=50.0,
            weapon_range=0.0,
            weapon_cooldown=0.0,
            weapon_damage=0.0,
        )

        self._engine.add_target(target)
        self._soul_to_target[soul_id] = target_id

        log.info("Spawned graphling %s (%s) at %s as %s", name, soul_id, position, target_id)
        return target_id

    def despawn(self, soul_id: str) -> bool:
        """Remove a graphling from the simulation.

        Returns True if the graphling was found and removed, False otherwise.
        """
        target_id = self._soul_to_target.pop(soul_id, None)
        if target_id is None:
            return False

        self._engine.remove_target(target_id)
        log.info("Despawned graphling %s (target %s)", soul_id, target_id)
        return True

    def despawn_all(self) -> None:
        """Remove all graphlings from the simulation."""
        for soul_id, target_id in list(self._soul_to_target.items()):
            self._engine.remove_target(target_id)
            log.info("Despawned graphling %s (target %s)", soul_id, target_id)
        self._soul_to_target.clear()

    def get_target_id(self, soul_id: str) -> Optional[str]:
        """Get the target_id for a deployed graphling, or None."""
        return self._soul_to_target.get(soul_id)

    def list_active(self) -> list[str]:
        """List all currently spawned soul_ids."""
        return list(self._soul_to_target.keys())
