# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""GraphlingsPlugin — External creature agents living in the TRITIUM-SC world.

Thin adapter that wires an external creature server into tritium-sc's
plugin system, providing perception, motor output, entity spawning, and
lifecycle management.

All intelligence lives on the external server.  This plugin provides
only tritium-sc-specific integration: perceive surroundings, send to
server, execute returned actions.
"""
from __future__ import annotations

import logging
import queue as queue_mod
import threading
import time
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

from .agent_bridge import AgentBridge
from .config import GraphlingsConfig
from .entity_factory import EntityFactory
from .lifecycle import SimulationLifecycleHandler
from .motor import MotorOutput
from .perception import PerceptionEngine

log = logging.getLogger("graphlings")


class GraphlingsPlugin(PluginInterface):
    """External creature agents deployed as NPCs in TRITIUM-SC.

    Bridges an external creature server with tritium-sc's simulation
    world, allowing creatures to perceive, think, and act as NPCs
    alongside existing units.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._engine: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None
        self._config = GraphlingsConfig.from_env()

        self._bridge: Optional[AgentBridge] = None
        self._perception: Optional[PerceptionEngine] = None
        self._motor: Optional[MotorOutput] = None
        self._factory: Optional[EntityFactory] = None
        self._lifecycle: Optional[SimulationLifecycleHandler] = None

        # Deployed agent tracking
        self._deployed: dict[str, dict] = {}
        self._running = False

        # Agent loop
        self._agent_thread: Optional[threading.Thread] = None
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_running = False
        self._event_thread: Optional[threading.Thread] = None

        # Thought history (ring buffer)
        from collections import deque
        self._thought_history: deque = deque(maxlen=200)

    # ── PluginInterface identity ─────────────────────────────────

    @property
    def plugin_id(self) -> str:
        return "com.graphlings.agent"

    @property
    def name(self) -> str:
        return "Graphlings Agent Bridge"

    @property
    def version(self) -> str:
        return "0.3.0"

    @property
    def capabilities(self) -> set[str]:
        return {"ai", "data_source", "routes", "background"}

    # ── PluginInterface lifecycle ────────────────────────────────

    def configure(self, ctx: PluginContext) -> None:
        """Store references to game systems and initialize components."""
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._engine = ctx.simulation_engine
        self._app = ctx.app
        self._logger = ctx.logger or log

        self._bridge = AgentBridge(self._config)

        self._perception = PerceptionEngine(
            self._tracker, self._config.perception_radius
        )
        self._motor = MotorOutput(self._tracker, self._event_bus, self._logger)
        self._factory = EntityFactory(self._engine)

        self._lifecycle = SimulationLifecycleHandler(
            self._bridge, self._factory, self._config
        )

        self._register_routes()

        self._logger.info(
            "Graphlings plugin configured (server: %s, max agents: %d)",
            self._config.server_url,
            self._config.max_agents,
        )

    def start(self) -> None:
        """Start the agent loop."""
        self._running = True

        # Agent think loop
        self._agent_thread = threading.Thread(
            target=self._agent_loop, daemon=True, name="graphlings-agent"
        )
        self._agent_thread.start()

        # Subscribe to game events
        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_running = True
            self._event_thread = threading.Thread(
                target=self._event_drain_loop, daemon=True, name="graphlings-events"
            )
            self._event_thread.start()

        self._logger.info("Graphlings Agent Bridge started")

    def stop(self) -> None:
        """Gracefully stop all agents."""
        self._running = False
        self._event_running = False

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._agent_thread and self._agent_thread.is_alive():
            self._agent_thread.join(timeout=3.0)

        # Recall all deployed
        for soul_id in list(self._deployed):
            self._recall_agent(soul_id, "shutdown")

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        self._logger.info("Graphlings Agent Bridge stopped")

    @property
    def healthy(self) -> bool:
        return self._running or not self._deployed

    # ── Deploy / Recall ──────────────────────────────────────────

    def deploy_graphling(
        self,
        soul_id: str,
        role_name: str,
        role_description: str = "",
        spawn_point: str = "marketplace",
        consciousness_min: int | None = None,
        consciousness_max: int | None = None,
    ) -> bool:
        """Deploy a graphling into the tritium-sc world."""
        import random as _rng
        if not self._bridge:
            return False

        base = self._config.spawn_points.get(spawn_point, (100.0, 200.0))
        offset = 15.0
        position = (
            base[0] + _rng.uniform(-offset, offset),
            base[1] + _rng.uniform(-offset, offset),
        )

        deploy_config = {
            "context": self._config.default_context,
            "service_name": self._config.default_service_name,
            "role_name": role_name,
            "role_description": role_description,
        }
        if consciousness_min is not None:
            deploy_config["consciousness_layer_min"] = consciousness_min
        if consciousness_max is not None:
            deploy_config["consciousness_layer_max"] = consciousness_max

        result = self._bridge.deploy(soul_id, deploy_config)
        if result is None:
            return False

        # Spawn entity in simulation
        target_id = self._factory.spawn(soul_id, role_name, position)

        self._deployed[soul_id] = {
            "soul_id": soul_id,
            "target_id": target_id,
            "role_name": role_name,
            "position": position,
            "deployed_at": time.time(),
        }
        return True

    def _recall_agent(self, soul_id: str, reason: str = "manual") -> bool:
        if soul_id in self._deployed:
            self._factory.despawn(soul_id)
            del self._deployed[soul_id]
        if self._bridge:
            self._bridge.recall(soul_id, reason)
        return True

    # ── Agent loop ───────────────────────────────────────────────

    def _agent_loop(self) -> None:
        """Background loop: periodically think for each deployed agent."""
        while self._running:
            try:
                self._tick_agents()
            except Exception as e:
                log.error("Agent tick error: %s", e)
            time.sleep(self._config.think_interval_seconds)

    def _tick_agents(self) -> None:
        """One round of thinking for all deployed agents."""
        if not self._bridge or not self._deployed:
            return

        for soul_id, info in list(self._deployed.items()):
            target_id = info.get("target_id", "")
            target = self._tracker.get_target(target_id) if self._tracker else None

            if target:
                position = tuple(target.position[:2])
                heading = getattr(target, "heading", 0.0)
                status = getattr(target, "status", "idle")
            else:
                position = info.get("position", (0.0, 0.0))
                heading = 0.0
                status = "idle"

            # Build perception
            perception = {}
            if self._perception:
                perception = self._perception.build_perception(
                    target_id, position, heading
                )
            perception["current_state"] = status

            # Think
            response = self._bridge.think(
                soul_id=soul_id,
                perception=perception,
                current_state=status,
                available_actions=["say", "move_to", "observe", "flee", "emote"],
                urgency=perception.get("danger_level", 0.2),
            )
            if response is None:
                continue

            # Record thought
            self._thought_history.append({
                "soul_id": soul_id,
                "thought": response.get("thought", ""),
                "action": response.get("action", ""),
                "emotion": response.get("emotion", ""),
                "time": time.time(),
            })

            # Publish thought event
            if self._event_bus:
                self._event_bus.publish("graphling_thought", data={
                    "soul_id": soul_id,
                    "thought": response.get("thought", ""),
                    "action": response.get("action", ""),
                })

            # Execute action
            action = response.get("action", "")
            if action and self._motor:
                self._motor.execute(target_id, action)

    # ── Event handling ────────────────────────────────────────────

    def _event_drain_loop(self) -> None:
        while self._event_running:
            try:
                event = self._event_queue.get(timeout=0.1)
                self._handle_event(event)
            except queue_mod.Empty:
                pass
            except Exception as e:
                log.error("Event drain error: %s", e)

    def _handle_event(self, event: dict) -> None:
        event_type = event.get("type", event.get("event_type", ""))
        if event_type == "game_state_change" and self._lifecycle:
            self._lifecycle.on_game_state_change(event)
        if self._perception and event_type:
            self._perception.record_event(event_type)

    # ── HTTP routes ──────────────────────────────────────────────

    def _register_routes(self) -> None:
        if not self._app:
            return

        plugin = self

        @self._app.get("/api/graphlings/status")
        async def graphlings_status():
            return {
                "plugin": plugin.plugin_id,
                "version": plugin.version,
                "running": plugin._running,
                "deployed_count": len(plugin._deployed),
                "deployed": list(plugin._deployed.keys()),
            }

        @self._app.post("/api/graphlings/deploy")
        async def graphlings_deploy(request: dict):
            soul_id = request.get("soul_id", "")
            role_name = request.get("role_name", "")
            if not soul_id or not role_name:
                return {"success": False, "error": "soul_id and role_name required"}
            ok = plugin.deploy_graphling(
                soul_id=soul_id,
                role_name=role_name,
                role_description=request.get("role_description", ""),
                spawn_point=request.get("spawn_point", "marketplace"),
                consciousness_min=request.get("consciousness_min"),
                consciousness_max=request.get("consciousness_max"),
            )
            return {"success": ok, "soul_id": soul_id}

        @self._app.post("/api/graphlings/{soul_id}/recall")
        async def graphlings_recall(soul_id: str):
            ok = plugin._recall_agent(soul_id, "api_recall")
            return {"success": ok, "soul_id": soul_id}

        @self._app.get("/api/graphlings/agents")
        async def graphlings_agents():
            return {"agents": list(plugin._deployed.values())}

        @self._app.get("/api/graphlings/thoughts")
        async def graphlings_thoughts_sse(request=None):
            import asyncio
            import json
            from starlette.responses import StreamingResponse

            sub = plugin._event_bus.subscribe()

            async def event_stream():
                try:
                    loop = asyncio.get_event_loop()
                    while True:
                        try:
                            msg = await loop.run_in_executor(
                                None, lambda: sub.get(timeout=30)
                            )
                            if msg.get("type") == "graphling_thought":
                                data = msg.get("data", {})
                                yield f"data: {json.dumps(data)}\n\n"
                        except Exception:
                            yield ": keepalive\n\n"
                finally:
                    plugin._event_bus.unsubscribe(sub)

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        @self._app.get("/api/graphlings/{soul_id}/thoughts")
        async def graphlings_soul_thoughts(soul_id: str):
            recent = [
                t for t in plugin._thought_history
                if t.get("soul_id") == soul_id
            ]
            return {"thoughts": recent[-20:]}

        @self._app.get("/api/graphlings/{soul_id}/status")
        async def graphlings_soul_status(soul_id: str):
            info = plugin._deployed.get(soul_id)
            if not info:
                return {"deployed": False, "soul_id": soul_id}
            return {
                "deployed": True,
                **info,
            }
