# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""GraphlingsPlugin — Graphling agents living in the TRITIUM-SC world."""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

from .agent_bridge import AgentBridge
from .config import GraphlingsConfig
from .entity_factory import EntityFactory
from .lifecycle import SimulationLifecycleHandler
from .memory_sync import MemorySync
from .motor import MotorOutput
from .perception import PerceptionEngine


class GraphlingsPlugin(PluginInterface):
    """Graphling consciousness agents deployed as NPCs in TRITIUM-SC.

    Bridges the Graphlings server (crystal creature AI) with tritium-sc's
    simulation world, allowing graphlings to perceive, think, and act as
    NPCs alongside existing units.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._engine: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None
        self._config = GraphlingsConfig.from_env()
        self._running = False
        self._event_queue: Any = None
        self._agent_thread: Optional[threading.Thread] = None

        # Sub-components (initialized in configure)
        self._bridge: Optional[AgentBridge] = None
        self._perception: Optional[PerceptionEngine] = None
        self._motor: Optional[MotorOutput] = None
        self._factory: Optional[EntityFactory] = None
        self._memory: Optional[MemorySync] = None
        self._lifecycle: Optional[SimulationLifecycleHandler] = None

        # Track deployed graphlings: soul_id -> deployment info
        self._deployed: dict[str, dict] = {}
        # Timing: soul_id -> last_think_time
        self._last_think: dict[str, float] = {}
        self._last_heartbeat: float = 0.0
        self._last_experience_sync: float = 0.0

        # Adaptive compute: per-graphling think intervals
        self._think_intervals: dict[str, float] = {}
        # Reflection timing: soul_id -> last_reflection_time
        self._last_reflection: dict[str, float] = {}
        # Compute stats: soul_id -> {think_count, total_latency, models_used}
        self._compute_stats: dict[str, dict] = {}

        # Agency: pending actions + mood timing
        self._last_pending_poll: float = 0.0
        self._last_mood_check: float = 0.0

    # ── PluginInterface identity ─────────────────────────────────

    @property
    def plugin_id(self) -> str:
        return "com.graphlings.agent"

    @property
    def name(self) -> str:
        return "Graphlings Agent Bridge"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def capabilities(self) -> set[str]:
        return {"ai", "data_source", "routes", "background"}

    # ── PluginInterface lifecycle ────────────────────────────────

    def configure(self, ctx: PluginContext) -> None:
        """Store references to game systems and initialize sub-components."""
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._engine = ctx.simulation_engine
        self._app = ctx.app
        self._logger = ctx.logger or logging.getLogger("graphlings")

        # Initialize sub-components
        self._bridge = AgentBridge(self._config)
        self._perception = PerceptionEngine(
            self._tracker, self._config.perception_radius
        )
        self._motor = MotorOutput(self._tracker, self._event_bus, self._logger)
        self._factory = EntityFactory(self._engine)
        self._memory = MemorySync(self._bridge)
        self._lifecycle = SimulationLifecycleHandler(
            self._bridge, self._factory, self._config
        )

        # Register HTTP routes
        self._register_routes()

        self._logger.info(
            "Graphlings plugin configured (server: %s, max agents: %d)",
            self._config.server_url,
            self._config.max_agents,
        )

    def start(self) -> None:
        """Start the agent background loop."""
        if self._running:
            return

        self._running = True

        # Subscribe to game events
        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()

        # Start background agent loop
        self._agent_thread = threading.Thread(
            target=self._agent_loop, daemon=True, name="graphlings-agent"
        )
        self._agent_thread.start()

        if self._logger:
            self._logger.info("Graphlings Agent Bridge started")

    def stop(self) -> None:
        """Gracefully stop all agents."""
        self._running = False

        # Recall lifecycle-deployed graphlings first
        if self._lifecycle:
            self._lifecycle._recall_all(reason="shutdown")

        # Flush all pending experiences before recall
        if self._memory:
            self._memory.flush_all()

        # Recall all manually deployed graphlings
        for soul_id in list(self._deployed.keys()):
            self._recall_agent(soul_id, "plugin_shutdown")

        # Wait for agent thread
        if self._agent_thread and self._agent_thread.is_alive():
            self._agent_thread.join(timeout=3.0)

        # Unsubscribe from events
        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        if self._logger:
            self._logger.info("Graphlings Agent Bridge stopped")

    @property
    def healthy(self) -> bool:
        """Check if plugin is healthy."""
        return self._running or not self._agent_thread

    # ── Deploy / Recall ───────────────────────────────────────────

    def deploy_graphling(
        self,
        soul_id: str,
        role_name: str,
        role_description: str = "",
        spawn_point: str = "marketplace",
        consciousness_min: int | None = None,
        consciousness_max: int | None = None,
    ) -> bool:
        """Deploy a graphling into the tritium-sc world.

        Returns True if deployment succeeded.
        """
        if soul_id in self._deployed:
            if self._logger:
                self._logger.warning("Graphling %s already deployed", soul_id)
            return False

        if len(self._deployed) >= self._config.max_agents:
            if self._logger:
                self._logger.warning("Max agents (%d) reached", self._config.max_agents)
            return False

        # Build deployment config
        deploy_config = {
            "context": self._config.default_context,
            "role_name": role_name,
            "role_description": role_description,
            "service_name": self._config.default_service_name,
            "consciousness_layer_min": consciousness_min or self._config.default_consciousness_min,
            "consciousness_layer_max": consciousness_max or self._config.default_consciousness_max,
            "heartbeat_interval_seconds": int(self._config.heartbeat_interval),
        }

        # 1. Deploy on the Graphling home server
        result = self._bridge.deploy(soul_id, deploy_config)
        if result is None:
            if self._logger:
                self._logger.error("Failed to deploy %s on home server", soul_id)
            return False

        # 2. Spawn entity in tritium-sc simulation
        position = self._config.spawn_points.get(
            spawn_point, (100.0, 200.0)
        )
        target_id = self._factory.spawn(soul_id, role_name, position)

        # 3. Track deployment (include personality snapshot if server returned one)
        personality = None
        if isinstance(result, dict):
            personality = result.get("personality")
        self._deployed[soul_id] = {
            "target_id": target_id,
            "role_name": role_name,
            "position": position,
            "deploy_config": deploy_config,
            "personality": personality,
        }
        self._last_think[soul_id] = 0.0

        # 4. Initialize adaptive compute tracking
        self._init_compute_tracking(soul_id)

        if self._logger:
            self._logger.info(
                "Deployed %s as '%s' at %s (target: %s)",
                soul_id, role_name, spawn_point, target_id,
            )

        return True

    def _recall_agent(self, soul_id: str, reason: str = "manual") -> bool:
        """Recall a deployed graphling — flush experiences, notify server, despawn."""
        info = self._deployed.pop(soul_id, None)
        if info is None:
            return False

        # 1. Flush pending experiences
        if self._memory:
            self._memory.flush(soul_id)

        # 2. Notify home server
        if self._bridge:
            self._bridge.recall(soul_id, reason)

        # 3. Despawn from simulation
        if self._factory:
            self._factory.despawn(soul_id)

        # Clean up timing and compute tracking
        self._last_think.pop(soul_id, None)
        self._cleanup_compute_tracking(soul_id)

        if self._logger:
            self._logger.info("Recalled %s (reason: %s)", soul_id, reason)

        return True

    # ── HTTP routes ──────────────────────────────────────────────

    def _register_routes(self) -> None:
        """Register custom HTTP routes."""
        if not self._app:
            return

        plugin = self  # closure reference

        @self._app.get("/api/graphlings/status")
        async def graphlings_status():
            # Build per-graphling compute stats
            compute_stats = {}
            for sid in plugin._deployed:
                compute_stats[sid] = plugin._get_compute_stats(sid)
            return {
                "plugin": plugin.plugin_id,
                "version": plugin.version,
                "running": plugin._running,
                "deployed_count": len(plugin._deployed),
                "deployed": list(plugin._deployed.keys()),
                "config": {
                    "server_url": plugin._config.server_url,
                    "max_agents": plugin._config.max_agents,
                    "think_interval": plugin._config.think_interval_seconds,
                },
                "compute_stats": compute_stats,
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

    # ── Background loop ──────────────────────────────────────────

    def _agent_loop(self) -> None:
        """Background loop: process events, think, heartbeat, sync."""
        while self._running:
            try:
                # 1. Process game events (non-blocking)
                self._drain_events()

                # 2. Think cycle for each deployed graphling (adaptive intervals)
                now = time.monotonic()
                for soul_id in list(self._deployed.keys()):
                    last = self._last_think.get(soul_id, 0.0)
                    interval = self._get_think_interval(soul_id)
                    if now - last >= interval:
                        self._think_cycle(soul_id)
                        self._last_think[soul_id] = now

                # 2b. Poll server-generated autonomous actions (every 10s)
                if now - self._last_pending_poll >= 10.0:
                    self._poll_pending_actions()
                    self._last_pending_poll = now

                # 2c. Check graphling moods for auto-recall (every 60s)
                if now - self._last_mood_check >= 60.0:
                    self._check_moods()
                    self._last_mood_check = now

                # 3. Periodic heartbeat
                if now - self._last_heartbeat >= self._config.heartbeat_interval:
                    self._heartbeat_all()
                    self._last_heartbeat = now

                # 4. Periodic experience sync
                if now - self._last_experience_sync >= self._config.experience_sync_interval:
                    if self._memory:
                        self._memory.flush_all()
                    self._last_experience_sync = now

                # Brief sleep to avoid spinning
                time.sleep(0.05)

            except Exception as e:
                if self._logger:
                    self._logger.error("Agent loop error: %s", e)

    def _drain_events(self) -> None:
        """Process all pending game events from the EventBus queue."""
        if not self._event_queue:
            return
        drained = 0
        while drained < 50:  # cap to prevent starvation
            try:
                event = self._event_queue.get_nowait()
                self._handle_event(event)
                drained += 1
            except queue.Empty:
                break

    def _handle_event(self, event: dict) -> None:
        """Process a game event — feed to perception, memory, and lifecycle."""
        event_type = event.get("type", event.get("event_type", ""))

        # Route game state changes to lifecycle handler
        if event_type == "game_state_change" and self._lifecycle:
            self._lifecycle.on_game_state_change(event)

        # Route threat events to set defensive objectives
        if event_type == "threat_detected" and self._bridge:
            threat_level = event.get("threat_level", "unknown")
            for soul_id in self._deployed:
                self._bridge.set_objective(soul_id, {
                    "description": f"Defend against {threat_level} threat",
                    "priority": 0.8,
                    "deadline_seconds": 300,
                })

        # Feed event to perception engine for recent_events
        if self._perception:
            self._perception.record_event(event_type)

        # Feed significant events to memory for all deployed graphlings
        if self._memory and event_type:
            description = event.get("description", event.get("text", str(event)))
            for soul_id in self._deployed:
                self._memory.record_event(soul_id, event_type, description)

    def _think_cycle(self, soul_id: str) -> None:
        """Run one think cycle for a deployed graphling.

        Includes adaptive interval updates, compute stats tracking,
        and periodic reflection cycles.
        """
        info = self._deployed.get(soul_id)
        if not info:
            return

        target_id = info["target_id"]

        # 1. Get graphling's current position from simulation
        target = self._tracker.get_target(target_id) if self._tracker else None
        if target:
            own_position = tuple(target.position[:2])
            own_heading = getattr(target, "heading", 0.0)
            current_state = getattr(target, "status", "idle")
        else:
            own_position = info.get("position", (0.0, 0.0))
            own_heading = 0.0
            current_state = "idle"

        # 2. Build perception packet
        perception = {}
        if self._perception:
            perception = self._perception.build_perception(
                target_id, own_position, own_heading
            )

        # 3. Calculate urgency from danger level
        urgency = perception.get("danger_level", 0.2)

        # 4. Update adaptive think interval based on urgency + personality
        personality = info.get("personality")
        nearby_friendlies = perception.get("nearby_friendlies", 0)
        has_events = len(perception.get("recent_events", [])) > 0
        self._think_intervals[soul_id] = self._calculate_adaptive_interval(
            urgency,
            personality=personality,
            nearby_friendlies=nearby_friendlies,
            has_events=has_events,
        )

        # 5. Check for periodic reflection cycle (every 30 minutes)
        last_refl = self._last_reflection.get(soul_id, 0.0)
        if time.monotonic() - last_refl > 1800:
            self._reflection_cycle(soul_id)

        # 6. Ask the Graphling server to think (track latency)
        t0 = time.monotonic()
        response = self._bridge.think(
            soul_id=soul_id,
            perception=perception,
            current_state=current_state,
            available_actions=["say", "move_to", "observe", "flee", "emote"],
            urgency=urgency,
        )
        latency = time.monotonic() - t0

        # 7. Update compute stats
        stats = self._compute_stats.get(soul_id)
        if stats is not None:
            stats["think_count"] += 1
            stats["total_latency"] += latency
            if response:
                model = response.get("model_used", "")
                if model:
                    stats["models_used"][model] = stats["models_used"].get(model, 0) + 1

        if response is None:
            if self._logger:
                self._logger.debug("Think timeout for %s, will retry", soul_id)
            return

        # 8. Execute the action in the simulation and report feedback
        action = response.get("action", "")
        if action and self._motor:
            success = self._motor.execute(target_id, action)

            # Close the RL loop — tell the server if the action worked
            if self._bridge:
                self._bridge.feedback(
                    soul_id=soul_id,
                    action=action,
                    success=success,
                    outcome="executed" if success else "failed",
                )

        # 8b. Report perceived entities to build the graphling's mental model
        if self._bridge and perception:
            entities = perception.get("nearby_entities", [])
            for entity in entities:
                if entity.get("is_threat") or entity.get("alliance") == "hostile":
                    self._bridge.report_entity(soul_id, {
                        "entity_id": entity.get("target_id", ""),
                        "entity_type": entity.get("alliance", "unknown"),
                        "position": [
                            entity.get("distance", 0.0),
                            entity.get("heading_to", 0.0),
                        ],
                        "threat_level": 1 if entity.get("is_threat") else 0,
                        "asset_type": entity.get("asset_type", ""),
                        "name": entity.get("name", ""),
                    })

        # 9. Set emotion if provided
        emotion = response.get("emotion", "")
        if emotion and self._motor:
            self._motor.execute(target_id, f'emote("{emotion}")')

    def _heartbeat_all(self) -> None:
        """Send heartbeat for all deployed graphlings."""
        if not self._bridge:
            return
        for soul_id in list(self._deployed.keys()):
            self._bridge.heartbeat(soul_id)

    # ── Agency: pending actions, mood, world model ────────────────

    def _poll_pending_actions(self) -> None:
        """Poll and execute server-generated autonomous actions for each graphling.

        The server's tickDeployedAutonomous() generates proactive goals and
        queues actions. We poll them here and execute via MotorOutput.
        """
        if not self._bridge or not self._motor:
            return

        for soul_id in list(self._deployed.keys()):
            info = self._deployed.get(soul_id)
            if not info:
                continue

            target_id = info["target_id"]
            actions = self._bridge.get_pending_actions(soul_id)

            for pending in actions:
                action_str = pending.get("action", "")
                if action_str:
                    success = self._motor.execute(target_id, action_str)
                    self._bridge.feedback(
                        soul_id=soul_id,
                        action=action_str,
                        success=success,
                        outcome="autonomous_executed" if success else "autonomous_failed",
                    )

    def _check_moods(self) -> None:
        """Check graphling moods and auto-recall those that are too stressed.

        Protects graphlings from emotional damage during long deployments.
        Threshold: stress > 0.8 triggers recall.
        """
        if not self._bridge:
            return

        for soul_id in list(self._deployed.keys()):
            mood = self._bridge.get_mood(soul_id)
            if mood is None:
                continue

            stress = mood.get("stress", 0.0)
            if stress > 0.8:
                if self._logger:
                    self._logger.warning(
                        "Graphling %s stress %.2f > 0.8 — auto-recalling",
                        soul_id, stress,
                    )
                self._recall_agent(soul_id, f"high_stress_{stress:.2f}")

    # ── Adaptive compute efficiency ───────────────────────────────

    def _calculate_adaptive_interval(
        self,
        urgency: float,
        personality: dict[str, float] | None = None,
        nearby_friendlies: int = 0,
        has_events: bool = False,
    ) -> float:
        """Calculate think interval based on urgency and personality.

        Higher urgency means shorter intervals (faster thinking):
          urgency > 0.8 -> 0.5s  (danger: react fast, L1-L2)
          urgency > 0.5 -> 1.0s  (active: engaged, L3)
          urgency > 0.3 -> 3.0s  (normal: aware, L3)
          urgency <= 0.3 -> 10.0s (idle: conserve compute, L2)

        Personality modifiers (applied multiplicatively):
          caution >= 0.7:    interval * 0.7 (more vigilant, think more often)
          sociability >= 0.7 + friendlies nearby: interval * 0.6
          curiosity >= 0.7 + events pending:      interval * 0.5

        Floor: 0.5s (never faster than reflex rate).
        """
        # Base interval from urgency
        if urgency > 0.8:
            interval = 0.5
        elif urgency > 0.5:
            interval = 1.0
        elif urgency > 0.3:
            interval = 3.0
        else:
            interval = 10.0

        # Apply personality modifiers
        if personality:
            caution = personality.get("caution", 0.0)
            if caution >= 0.7:
                interval *= 0.7

            sociability = personality.get("sociability", 0.0)
            if sociability >= 0.7 and nearby_friendlies > 0:
                interval *= 0.6

            curiosity = personality.get("curiosity", 0.0)
            if curiosity >= 0.7 and has_events:
                interval *= 0.5

        # Floor at 0.5s
        return max(interval, 0.5)

    def _get_think_interval(self, soul_id: str) -> float:
        """Get the current adaptive think interval for a graphling."""
        return self._think_intervals.get(soul_id, self._config.think_interval_seconds)

    def _get_compute_stats(self, soul_id: str) -> dict:
        """Get compute stats for a graphling.

        Returns dict with think_count, total_latency, models_used, current_interval.
        """
        defaults = {
            "think_count": 0,
            "total_latency": 0.0,
            "models_used": {},
            "current_interval": self._get_think_interval(soul_id),
        }
        stats = self._compute_stats.get(soul_id, defaults)
        stats["current_interval"] = self._get_think_interval(soul_id)
        return stats

    def _init_compute_tracking(self, soul_id: str) -> None:
        """Initialize compute tracking for a newly deployed graphling."""
        self._compute_stats[soul_id] = {
            "think_count": 0,
            "total_latency": 0.0,
            "models_used": {},
        }
        self._think_intervals[soul_id] = self._config.think_interval_seconds
        self._last_reflection[soul_id] = time.monotonic()

    def _cleanup_compute_tracking(self, soul_id: str) -> None:
        """Clean up compute tracking when a graphling is recalled."""
        self._compute_stats.pop(soul_id, None)
        self._think_intervals.pop(soul_id, None)
        self._last_reflection.pop(soul_id, None)

    def _reflection_cycle(self, soul_id: str) -> None:
        """Run a periodic L5 reflection cycle for a deployed graphling.

        Sends a think request with preferred_layer=5, current_state="reflection",
        and low urgency (0.1) to allow the graphling to consolidate memories.
        """
        if not self._bridge:
            return

        response = self._bridge.think(
            soul_id=soul_id,
            perception={},
            current_state="reflection",
            available_actions=["observe", "emote"],
            urgency=0.1,
            preferred_layer=5,
        )

        self._last_reflection[soul_id] = time.monotonic()

        if response is None:
            if self._logger:
                self._logger.debug("Reflection timeout for %s", soul_id)
            return

        if self._logger:
            self._logger.info(
                "Reflection complete for %s: %s",
                soul_id, response.get("thought", ""),
            )
