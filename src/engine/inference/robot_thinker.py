"""Robot Thinker — LLM-powered autonomous thinking for robots.

Gives robots their own thinking thread with Lua action generation,
using the same parser as Amy but with robot-specific context and actions.
Each robot can register custom actions (fire_nerf, set_led, etc.) and
uses the shared OllamaFleet for model selection.

Thoughts are published back to Amy via MQTT for situational awareness.
"""
from __future__ import annotations

import time
from typing import Any

from engine.actions.lua_motor import parse_motor_output, MotorOutput
from engine.actions.lua_registry import LuaActionRegistry, ActionDef
from engine.perception.vision import ollama_chat


# Type map for config-based action registration
_TYPE_MAP = {"str": str, "int": int, "float": float, "bool": bool}

MAX_THOUGHT_HISTORY = 20

ROBOT_THINKING_PROMPT = """\
You are {robot_name}, a {asset_type} in the TRITIUM-SC security network.
You are an autonomous unit with your own sensors and actuators.
Your commander is Amy, who may send you orders.

IDENTITY: {robot_id}
STATUS: {status}
POSITION: ({pos_x:.1f}, {pos_y:.1f})
BATTERY: {battery}

{targets_context}

{commands_context}

RECENT THOUGHTS:
{thoughts}

Available actions:
{actions}

RULES:
- Use think() for internal reasoning (most common).
- Only say() when you have something worth reporting to Amy.
- Follow Amy's commands when they arrive.
- Act autonomously when no commands are pending.
- Be aware of your battery level and return home if critically low.

Respond with ONE Lua function call.
"""


class RobotThinker:
    """LLM-powered thinking for autonomous robots."""

    def __init__(
        self,
        robot_id: str,
        config: dict,
        model_router: Any | None = None,
    ):
        self._robot_id = robot_id
        self._config = config
        self._model_router = model_router
        self._model = config.get("think_model", "gemma3:4b")
        self._think_count = 0
        self._thought_history: list[dict] = []
        self._last_thought = ""

        # Initialize registry with core actions + robot-specific
        self._registry = LuaActionRegistry.with_core_actions()
        self._register_from_config(config)

    @property
    def robot_id(self) -> str:
        return self._robot_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def registry(self) -> LuaActionRegistry:
        return self._registry

    @property
    def think_count(self) -> int:
        return self._think_count

    @property
    def thought_history(self) -> list[dict]:
        return list(self._thought_history)

    @property
    def last_thought(self) -> str:
        return self._last_thought

    # ----- Action Registration -----

    def register_action(
        self,
        name: str,
        min_params: int = 0,
        max_params: int = 0,
        param_types: list[type] | None = None,
        description: str = "",
    ) -> None:
        """Register a robot-specific Lua action."""
        self._registry.register(ActionDef(
            name=name,
            min_params=min_params,
            max_params=max_params,
            param_types=param_types or [],
            description=description,
            source=f"robot:{self._robot_id}",
        ))

    def unregister_robot_actions(self) -> int:
        """Remove all actions registered by this robot."""
        return self._registry.unregister_by_source(f"robot:{self._robot_id}")

    def _register_from_config(self, config: dict) -> None:
        """Register actions from config dict."""
        for action_cfg in config.get("actions", []):
            param_types = []
            for t in action_cfg.get("param_types", []):
                param_types.append(_TYPE_MAP.get(t, str))

            self.register_action(
                name=action_cfg["name"],
                min_params=action_cfg.get("min_params", 0),
                max_params=action_cfg.get("max_params", 0),
                param_types=param_types,
                description=action_cfg.get("description", ""),
            )

    # ----- Context Building -----

    def build_context(
        self,
        telemetry: dict | None = None,
        nearby_targets: list[dict] | None = None,
        recent_commands: list[dict] | None = None,
    ) -> str:
        """Build the thinking prompt context."""
        tel = telemetry or {}
        pos = tel.get("position", {})
        pos_x = pos.get("x", 0.0) if isinstance(pos, dict) else 0.0
        pos_y = pos.get("y", 0.0) if isinstance(pos, dict) else 0.0
        battery = tel.get("battery", 1.0)
        status = tel.get("status", "idle")

        # Battery formatting
        if isinstance(battery, (int, float)):
            battery_str = f"{battery:.0%}" if battery <= 1.0 else f"{battery}%"
        else:
            battery_str = str(battery)

        # Targets context
        targets_ctx = ""
        if nearby_targets:
            lines = []
            for t in nearby_targets[:5]:
                tp = t.get("position", {})
                tx = tp.get("x", 0) if isinstance(tp, dict) else 0
                ty = tp.get("y", 0) if isinstance(tp, dict) else 0
                lines.append(
                    f"  - {t.get('name', 'Unknown')} [{t.get('alliance', 'unknown')}] "
                    f"at ({tx}, {ty})"
                )
            targets_ctx = "NEARBY TARGETS:\n" + "\n".join(lines)

        # Commands context
        commands_ctx = ""
        if recent_commands:
            lines = []
            for cmd in recent_commands[-3:]:
                cmd_type = cmd.get("command", "unknown")
                cmd_x = cmd.get("x", "")
                cmd_y = cmd.get("y", "")
                if cmd_x and cmd_y:
                    lines.append(f"  - {cmd_type} to ({cmd_x}, {cmd_y})")
                else:
                    lines.append(f"  - {cmd_type}")
            commands_ctx = "RECENT COMMANDS FROM AMY:\n" + "\n".join(lines)

        # Thoughts
        recent = self._thought_history[-5:]
        thoughts_str = "\n".join(
            f"- {t['text']}" for t in recent
        ) if recent else "(none yet)"

        # Available actions
        actions = self._registry.prompt_section()

        return ROBOT_THINKING_PROMPT.format(
            robot_name=self._config.get("robot_name", self._robot_id),
            asset_type=self._config.get("asset_type", "robot"),
            robot_id=self._robot_id,
            status=status,
            pos_x=pos_x,
            pos_y=pos_y,
            battery=battery_str,
            targets_context=targets_ctx,
            commands_context=commands_ctx,
            thoughts=thoughts_str,
            actions=actions,
        )

    # ----- Think Cycle -----

    def think_cycle(
        self,
        telemetry: dict | None = None,
        nearby_targets: list[dict] | None = None,
        recent_commands: list[dict] | None = None,
    ) -> MotorOutput | None:
        """Run one thinking cycle. Returns parsed Lua action or None."""
        context = self.build_context(telemetry, nearby_targets, recent_commands)

        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": "What do you do next? Respond with a single Lua function call."},
        ]

        try:
            if self._model_router is not None:
                from .model_router import TaskType
                response = self._model_router.infer(
                    TaskType.SIMPLE_THINK, messages,
                )
            else:
                response = ollama_chat(model=self._model, messages=messages)
        except Exception:
            return None

        response_text = response.get("message", {}).get("content", "").strip()
        if not response_text:
            return None

        result = parse_motor_output(response_text)
        self._think_count += 1

        if result.valid:
            self._record_thought(result)

        return result

    def _record_thought(self, result: MotorOutput) -> None:
        """Record a thought in history."""
        text = ""
        if result.action in ("think", "say") and result.params:
            text = result.params[0]
        else:
            text = f"{result.action}({', '.join(repr(p) for p in result.params)})"

        self._last_thought = text
        self._thought_history.append({
            "text": text,
            "action": result.action,
            "timestamp": time.monotonic(),
        })

        if len(self._thought_history) > MAX_THOUGHT_HISTORY:
            self._thought_history = self._thought_history[-MAX_THOUGHT_HISTORY:]

    # ----- MQTT -----

    def to_mqtt_message(self) -> dict:
        """Generate an MQTT message about the robot's latest thought."""
        return {
            "robot_id": self._robot_id,
            "type": "thought",
            "text": self._last_thought,
            "think_count": self._think_count,
            "timestamp": time.time(),
        }
