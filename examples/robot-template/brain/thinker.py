# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Robot Thinker — LLM-powered autonomous thinking for robots.

Gives the robot its own thinking thread. Each cycle:
1. Build context (telemetry, targets, commands, thought history)
2. Call Ollama for LLM inference
3. Parse Lua function call(s) from the response
4. Dispatch parsed actions to local hardware handlers
5. Publish thoughts via MQTT for Amy's situational awareness

Uses the same Lua action format as Amy's lua_motor, so Amy and robots
speak the same language. Tries to import from amy/ for shared parsing,
falls back to a built-in parser when deployed standalone.

Config (in config.yaml):
    thinker:
      enabled: true
      model: "gemma3:4b"
      ollama_host: "http://localhost:11434"
      think_interval: 5.0
      actions:
        - name: fire_nerf
          description: "Fire the nerf turret"
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable

import requests


# ---- Default actions every robot gets (subset of Amy's core) ----
DEFAULT_ACTIONS = {
    "think": "Internal reasoning (most common). think(text)",
    "say": "Report to Amy via MQTT. say(text)",
    "look_at": "Point camera/turret toward a direction. look_at(direction)",
}

MAX_THOUGHT_HISTORY = 20

# ---- Lua Parsing (standalone, no amy/ dependency) ----

_FUNC_RE = re.compile(r'([a-z_][a-z0-9_]*)\s*\(', re.IGNORECASE)


def parse_lua_call(text: str) -> tuple[str, list[str]] | None:
    """Parse a single Lua function call into (action, params).

    Returns None if the text is not a valid Lua function call.
    Handles string params (double/single quoted) and bare numeric params.
    """
    if not text or not text.strip():
        return None

    text = text.strip()
    match = _FUNC_RE.match(text)
    if not match:
        return None

    action = match.group(1)

    # Find the opening paren
    paren_start = text.index('(')
    # Find matching closing paren
    depth = 0
    end = -1
    for i in range(paren_start, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        return None

    inner = text[paren_start + 1:end].strip()
    if not inner:
        return action, []

    # Parse params — handle quoted strings and bare values
    params = []
    i = 0
    while i < len(inner):
        c = inner[i]
        if c in ('"', "'"):
            # Quoted string
            quote = c
            j = i + 1
            while j < len(inner) and inner[j] != quote:
                if inner[j] == '\\':
                    j += 1  # skip escaped char
                j += 1
            params.append(inner[i + 1:j])
            i = j + 1
        elif c == ',':
            i += 1
        elif c == ' ':
            i += 1
        else:
            # Bare value (number, identifier)
            j = i
            while j < len(inner) and inner[j] not in (',', ')'):
                j += 1
            params.append(inner[i:j].strip())
            i = j

    return action, params


def extract_lua_calls(
    response: str,
    known_actions: set[str] | None = None,
) -> list[str]:
    """Extract Lua function calls from an LLM response.

    Handles code blocks, comments, thinking tags, and mixed text.
    If known_actions is provided, only extracts calls to those functions.
    """
    if not response or not response.strip():
        return []

    response = response.strip()

    # Strip thinking tags
    response = re.sub(r'<think>.*?</think>\s*', '', response, flags=re.DOTALL | re.IGNORECASE)
    if '<think>' in response.lower():
        idx = response.lower().find('<think>')
        response = response[:idx].strip()

    # Extract from code blocks
    block = re.search(r'```(?:lua)?\s*\n?(.*?)\n?```', response, re.DOTALL | re.IGNORECASE)
    if block:
        response = block.group(1)

    # Remove comments
    lines = []
    for line in response.split('\n'):
        stripped = line.strip()
        if stripped.startswith('--'):
            continue
        comment_idx = stripped.find('--')
        if comment_idx > 0:
            stripped = stripped[:comment_idx].strip()
        if stripped:
            lines.append(stripped)

    text = '\n'.join(lines)

    # Build pattern from known_actions or match any function call
    if known_actions:
        action_pattern = '|'.join(re.escape(a) for a in known_actions)
    else:
        action_pattern = r'[a-z_][a-z0-9_]*'

    pattern = re.compile(rf'({action_pattern})\s*\(', re.IGNORECASE)

    results = []
    for match in pattern.finditer(text):
        start = match.start()
        # Find closing paren
        depth = 0
        i = match.end() - 1  # back to '('
        while i < len(text):
            if text[i] == '(':
                depth += 1
            elif text[i] == ')':
                depth -= 1
                if depth == 0:
                    results.append(text[start:i + 1])
                    break
            i += 1

    return results


# ---- Thinking Prompt Template ----

ROBOT_THINKING_PROMPT = """\
You are {robot_name}, a {asset_type} in the TRITIUM-SC security network.
You are an autonomous unit with cameras, sensors, and actuators.
Your commander is Amy, who may send you orders via MQTT.

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
- When you detect hostiles with YOLO, report via say() or engage.

Respond with ONE Lua function call.
"""


class RobotThinker:
    """LLM-powered autonomous thinking for robots.

    Calls Ollama directly (no dependency on amy package).
    Uses the same Lua action format as Amy so robots and Amy
    speak the same language.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._robot_id = config.get("robot_id", "robot")
        self._robot_name = config.get("robot_name", self._robot_id)
        self._asset_type = config.get("asset_type", "rover")
        self._site_id = config.get("site_id", "home")

        thinker_cfg = config.get("thinker", {})
        self._enabled = thinker_cfg.get("enabled", False)
        self._model = thinker_cfg.get("model", "gemma3:4b")
        self._ollama_host = thinker_cfg.get("ollama_host", "http://localhost:11434")
        self._think_interval = thinker_cfg.get("think_interval", 5.0)

        # Action registry
        self._actions: dict[str, str] = dict(DEFAULT_ACTIONS)
        self._handlers: dict[str, Callable] = {}
        self._think_count = 0
        self._thought_history: list[dict] = []
        self._last_thought = ""

        # Register actions from config
        for action_cfg in thinker_cfg.get("actions", []):
            name = action_cfg.get("name", "")
            desc = action_cfg.get("description", "")
            if name:
                self._actions[name] = desc

    # ---- Properties ----

    @property
    def robot_id(self) -> str:
        return self._robot_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def ollama_host(self) -> str:
        return self._ollama_host

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def think_interval(self) -> float:
        return self._think_interval

    @property
    def think_count(self) -> int:
        return self._think_count

    @property
    def thought_history(self) -> list[dict]:
        return list(self._thought_history)

    @property
    def last_thought(self) -> str:
        return self._last_thought

    @property
    def actions(self) -> dict[str, str]:
        return dict(self._actions)

    @property
    def mqtt_topic(self) -> str:
        return f"tritium/{self._site_id}/robots/{self._robot_id}/thoughts"

    # ---- Action Registration ----

    def register_action(self, name: str, description: str = "") -> None:
        """Register a custom Lua action."""
        self._actions[name] = description

    def unregister_action(self, name: str) -> None:
        """Remove a custom action."""
        self._actions.pop(name, None)
        self._handlers.pop(name, None)

    def on_action(self, name: str, handler: Callable) -> None:
        """Register a handler function for an action.

        When dispatch_action(name, params) is called, handler(params) runs.
        """
        self._handlers[name] = handler

    def actions_prompt(self) -> str:
        """Generate the actions section for the thinking prompt."""
        lines = []
        for name, desc in sorted(self._actions.items()):
            if desc:
                lines.append(f"- {name}() — {desc}")
            else:
                lines.append(f"- {name}()")
        return "\n".join(lines)

    # ---- Context Building ----

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
        actions = self.actions_prompt()

        return ROBOT_THINKING_PROMPT.format(
            robot_name=self._robot_name,
            asset_type=self._asset_type,
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

    # ---- Think Cycle ----

    def think_once(
        self,
        telemetry: dict | None = None,
        nearby_targets: list[dict] | None = None,
        recent_commands: list[dict] | None = None,
    ) -> dict | None:
        """Run one thinking cycle.

        Returns {"action": str, "params": list[str]} or None on failure.
        """
        context = self.build_context(telemetry, nearby_targets, recent_commands)

        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": "What do you do next? Respond with a single Lua function call."},
        ]

        try:
            resp = requests.post(
                f"{self._ollama_host}/api/chat",
                json={"model": self._model, "messages": messages, "stream": False},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None

        content = data.get("message", {}).get("content", "").strip()
        if not content:
            return None

        # Extract Lua calls
        known = set(self._actions.keys())
        calls = extract_lua_calls(content, known_actions=known)
        if not calls:
            # Try parsing the raw content as a single call
            parsed = parse_lua_call(content)
            if parsed is None:
                return None
            action, params = parsed
        else:
            # Take the first valid call
            parsed = parse_lua_call(calls[0])
            if parsed is None:
                return None
            action, params = parsed

        self._think_count += 1
        self._record_thought(action, params)

        return {"action": action, "params": params}

    def _record_thought(self, action: str, params: list[str]) -> None:
        """Record a thought in history."""
        if action in ("think", "say") and params:
            text = params[0]
        else:
            text = f"{action}({', '.join(repr(p) for p in params)})"

        self._last_thought = text
        self._thought_history.append({
            "text": text,
            "action": action,
            "timestamp": time.monotonic(),
        })

        if len(self._thought_history) > MAX_THOUGHT_HISTORY:
            self._thought_history = self._thought_history[-MAX_THOUGHT_HISTORY:]

    # ---- Action Dispatch ----

    def dispatch_action(self, action: str, params: list[str]) -> None:
        """Dispatch a parsed action to a registered handler."""
        handler = self._handlers.get(action)
        if handler is not None:
            try:
                handler(params)
            except Exception as e:
                print(f"  [THINKER] Handler error for {action}: {e}")

    # ---- MQTT ----

    def to_mqtt_message(self) -> dict:
        """Generate an MQTT message about the robot's latest thought."""
        return {
            "robot_id": self._robot_id,
            "type": "thought",
            "text": self._last_thought,
            "think_count": self._think_count,
            "timestamp": time.time(),
        }
