# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MotorOutput — converts graphling LLM actions to TRITIUM-SC state changes.

Parses Lua-style action strings (from the Graphlings consciousness engine)
and executes them as SimulationTarget modifications and EventBus events.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any


class MotorOutput:
    """Execute graphling actions in the TRITIUM-SC game world.

    Args:
        tracker: TargetTracker (or mock) with get_target(id) method.
        event_bus: EventBus for publishing NPC events.
        logger: Optional logger for action logging.
    """

    def __init__(
        self,
        tracker: Any,
        event_bus: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self._tracker = tracker
        self._event_bus = event_bus
        self._logger = logger or logging.getLogger("graphlings.motor")
        self._current_emotions: dict[str, str] = {}

    def execute(self, graphling_target_id: str, action_string: str) -> bool:
        """Parse and execute a Lua-style action string.

        Returns True if the action was executed successfully, False otherwise.
        """
        action, params = self._parse_action(action_string)
        if not action:
            self._logger.debug("No action parsed from: %s", action_string)
            return False

        target = self._tracker.get_target(graphling_target_id)
        if not target:
            self._logger.warning("Target %s not found", graphling_target_id)
            return False

        self._logger.debug(
            "[%s] executing: %s(%s)",
            graphling_target_id,
            action,
            ", ".join(repr(p) for p in params),
        )

        try:
            if action == "say":
                return self._say(target, params[0] if params else "")
            elif action == "move_to":
                return self._move_to(target, params)
            elif action == "flee":
                return self._flee(target, params)
            elif action == "observe":
                return self._observe(target)
            elif action == "emote":
                return self._emote(target, params[0] if params else "neutral")
            elif action == "think":
                return self._think(target, params[0] if params else "")
            elif action == "remember":
                return self._remember(target, params)
            else:
                self._logger.warning("Unknown action: %s", action)
                return False
        except Exception as e:
            self._logger.error("Action %s failed: %s", action, e)
            return False

    # ── Action handlers ───────────────────────────────────────────

    def _say(self, target: Any, text: str) -> bool:
        """Publish a speech bubble for the graphling."""
        if not text:
            return False
        emotion = self._current_emotions.get(target.target_id, "neutral")
        self._event_bus.publish("npc_thought", {
            "target_id": target.target_id,
            "text": text,
            "emotion": emotion,
            "source": "graphling",
            "duration": max(3.0, len(text) * 0.08),
        })
        return True

    def _move_to(self, target: Any, params: list) -> bool:
        """Set waypoint for the graphling."""
        if len(params) < 2:
            return False
        try:
            x = float(params[0])
            y = float(params[1])
        except (ValueError, TypeError):
            return False
        target.waypoints = [(x, y)]
        target.status = "active"
        return True

    def _flee(self, target: Any, params: list) -> bool:
        """Move away from a threat position."""
        if len(params) < 2:
            # No coordinates — flee in default direction
            target.waypoints = [(
                target.position[0] + 30.0,
                target.position[1] + 30.0,
            )]
            target.status = "active"
            return True
        try:
            threat_x = float(params[0])
            threat_y = float(params[1])
        except (ValueError, TypeError):
            return False
        dx = target.position[0] - threat_x
        dy = target.position[1] - threat_y
        dist = max(0.1, math.sqrt(dx * dx + dy * dy))
        target.waypoints = [(
            target.position[0] + (dx / dist) * 30.0,
            target.position[1] + (dy / dist) * 30.0,
        )]
        target.status = "active"
        return True

    def _observe(self, target: Any) -> bool:
        """Set target to idle/observing state."""
        target.status = "idle"
        return True

    def _emote(self, target: Any, emotion: str) -> bool:
        """Publish an emotion event."""
        self._current_emotions[target.target_id] = emotion
        self._event_bus.publish("npc_emotion", {
            "target_id": target.target_id,
            "emotion": emotion,
            "source": "graphling",
        })
        return True

    def _think(self, target: Any, text: str) -> bool:
        """Internal thought — logged but not broadcast."""
        self._logger.debug("[%s] thinks: %s", target.target_id, text)
        return True

    def _remember(self, target: Any, params: list) -> bool:
        """Record an experience via EventBus."""
        if len(params) < 2:
            return False
        self._event_bus.publish("npc_experience", {
            "target_id": target.target_id,
            "subject": params[0],
            "value": params[1],
            "source": "graphling",
        })
        return True

    # ── Parsing ───────────────────────────────────────────────────

    @staticmethod
    def _parse_action(action_string: str) -> tuple[str | None, list[str]]:
        """Parse a Lua-style action: say("hello") -> ("say", ["hello"])

        Returns (action_name, [params]) or (None, []) on failure.
        """
        if not action_string:
            return None, []

        action_string = action_string.strip()

        # Match: action_name(params...)
        match = re.match(r'(\w+)\s*\((.*)\)$', action_string, re.DOTALL)
        if not match:
            # Bare action name without parens
            return action_string.strip(), []

        action = match.group(1)
        params_str = match.group(2).strip()
        if not params_str:
            return action, []

        # Parse params: extract quoted strings and numbers
        params: list[str] = []
        for p in re.findall(r'"([^"]*)"|([\d.]+)', params_str):
            params.append(p[0] if p[0] else p[1])

        return action, params
