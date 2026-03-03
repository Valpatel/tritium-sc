# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Graphling Battle Mode — deploys creature agents for a skirmish scenario.

Usage:
    POST /api/graphlings/battle/start
    GET  /api/graphlings/battle/status
    POST /api/graphlings/battle/stop
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("graphlings.battle")


@dataclass
class BattleParticipant:
    """A creature deployed for the battle."""
    soul_id: str
    target_id: str
    role_name: str
    alliance: str
    is_combatant: bool
    last_think: float = 0.0
    think_count: int = 0
    last_action: str = ""
    status: str = "active"


@dataclass
class BattleState:
    """Tracks the state of a creature battle."""
    participants: dict[str, BattleParticipant] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    running: bool = False
    events: list[dict] = field(default_factory=list)

    @property
    def duration(self) -> float:
        if self.end_time > 0:
            return self.end_time - self.start_time
        if self.start_time > 0:
            return time.monotonic() - self.start_time
        return 0.0

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "duration_seconds": round(self.duration, 1),
            "participants": {
                sid: {
                    "role": p.role_name,
                    "alliance": p.alliance,
                    "target_id": p.target_id,
                    "think_count": p.think_count,
                    "last_action": p.last_action,
                    "status": p.status,
                }
                for sid, p in self.participants.items()
            },
            "event_count": len(self.events),
            "recent_events": self.events[-5:] if self.events else [],
        }


class GraphlingBattleMode:
    """Manages a creature battle scenario in tritium-sc.

    Deploys creatures from an external server, runs think cycles,
    and recalls them when the battle ends.
    """

    def __init__(
        self,
        bridge: Any,
        factory: Any,
        config: Any,
        available_soul_ids: Optional[list[str]] = None,
    ) -> None:
        self._bridge = bridge
        self._factory = factory
        self._config = config
        self._state = BattleState()
        self._available_souls = available_soul_ids or []

    @property
    def state(self) -> BattleState:
        return self._state

    @property
    def running(self) -> bool:
        return self._state.running

    def start(
        self,
        soul_ids: Optional[list[str]] = None,
        roles: Optional[list[dict]] = None,
    ) -> bool:
        """Start a battle by deploying creatures.

        Args:
            soul_ids: Soul IDs to deploy.
            roles: List of role dicts with keys: role_name, alliance,
                   is_combatant, spawn_point, deploy_config.
                   If not provided, all are deployed as friendly combatants.
        """
        if self._state.running:
            log.warning("Battle already running")
            return False

        ids = soul_ids or self._available_souls[:4]
        if not ids:
            active = self._bridge.list_active()
            if active:
                ids = [d.get("soul_id", "") for d in active][:4]

        if len(ids) < 2:
            log.error("Need at least 2 soul IDs for battle, got %d", len(ids))
            return False

        self._state = BattleState(start_time=time.monotonic(), running=True)

        deployed = 0
        for i, soul_id in enumerate(ids):
            role = (roles[i] if roles and i < len(roles)
                    else {"role_name": "combatant", "alliance": "friendly",
                          "is_combatant": True, "spawn_point": "center"})

            deploy_config = role.get("deploy_config", {
                "context": "npc_game",
                "role_name": role.get("role_name", "combatant"),
                "service_name": self._config.default_service_name,
            })

            result = self._bridge.deploy(soul_id, deploy_config)
            if result is None:
                log.warning("Failed to deploy %s", soul_id)
                continue

            position = self._config.spawn_points.get(
                role.get("spawn_point", "center"), (0.0, 0.0)
            )
            target_id = self._factory.spawn(
                soul_id=soul_id,
                name=role.get("role_name", "combatant"),
                position=position,
                is_combatant=role.get("is_combatant", True),
            )

            self._state.participants[soul_id] = BattleParticipant(
                soul_id=soul_id,
                target_id=target_id,
                role_name=role.get("role_name", "combatant"),
                alliance=role.get("alliance", "friendly"),
                is_combatant=role.get("is_combatant", True),
            )
            deployed += 1

        if deployed < 2:
            log.error("Only %d deployed, need at least 2", deployed)
            self.stop(reason="insufficient_participants")
            return False

        log.info("Battle started with %d creatures", deployed)
        return True

    def stop(self, reason: str = "manual") -> dict:
        if not self._state.running:
            return self._state.to_dict()

        self._state.end_time = time.monotonic()
        self._state.running = False

        for soul_id, p in list(self._state.participants.items()):
            self._factory.despawn(soul_id)
            self._bridge.recall(soul_id, f"battle_ended:{reason}")
            p.status = "recalled"

        return self._state.to_dict()

    def tick(self, perception_engine: Any, tracker: Any, motor: Any) -> None:
        """Run one tick of the battle — think cycle for each participant."""
        if not self._state.running:
            return

        now = time.monotonic()
        for soul_id, p in self._state.participants.items():
            if p.status != "active":
                continue
            if now - p.last_think < 3.0:
                continue

            target = tracker.get_target(p.target_id) if tracker else None
            if target:
                position = tuple(target.position[:2])
                heading = getattr(target, "heading", 0.0)
                status = getattr(target, "status", "idle")
            else:
                position, heading, status = (0.0, 0.0), 0.0, "idle"

            perception = {}
            if perception_engine:
                perception = perception_engine.build_perception(
                    p.target_id, position, heading
                )

            urgency = perception.get("danger_level", 0.2)

            response = self._bridge.think(
                soul_id=soul_id,
                perception=perception,
                current_state=status,
                available_actions=["say", "move_to", "observe", "flee", "emote"],
                urgency=urgency,
            )
            p.last_think = now
            p.think_count += 1

            if response is None:
                continue

            action = response.get("action", "")
            if action and motor:
                motor.execute(p.target_id, action)
                p.last_action = action

    def register_routes(self, app: Any) -> None:
        if not app:
            return
        mode = self

        @app.post("/api/graphlings/battle/start")
        async def battle_start(request: dict = {}):
            ok = mode.start(soul_ids=request.get("soul_ids"))
            return {"success": ok, "state": mode.state.to_dict()}

        @app.get("/api/graphlings/battle/status")
        async def battle_status():
            return mode.state.to_dict()

        @app.post("/api/graphlings/battle/stop")
        async def battle_stop(request: dict = {}):
            summary = mode.stop(reason=request.get("reason", "api_stop"))
            return {"success": True, "summary": summary}
