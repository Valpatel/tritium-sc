"""Extensible Lua action registry for Amy and robots.

Replaces the hardcoded VALID_ACTIONS dict in lua_motor.py with a dynamic
registry. Nodes, robots, and plugins can register their own Lua actions
at runtime. Amy's thinking prompt dynamically lists available actions.

Backwards-compatible: register_many() accepts the old VALID_ACTIONS dict
format for zero-migration-cost.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionDef:
    """Definition of a Lua action — metadata for validation and prompts."""

    name: str
    min_params: int = 0
    max_params: int = 0
    param_types: list[type] = field(default_factory=list)
    description: str = ""
    source: str = "core"  # "core", "robot:<id>", "plugin:<name>"

    def to_prompt(self) -> str:
        """Generate a single line for the thinking prompt."""
        if self.min_params == 0 and self.max_params == 0:
            sig = f"{self.name}()"
        else:
            type_names = {str: "text", int: "n", float: "n", bool: "flag"}
            args = []
            for i, t in enumerate(self.param_types[:self.max_params]):
                arg_name = type_names.get(t, "arg")
                if i >= self.min_params:
                    arg_name = f"[{arg_name}]"
                args.append(f'"{arg_name}"' if t is str else arg_name)
            sig = f"{self.name}({', '.join(args)})"
        desc = f" -- {self.description}" if self.description else ""
        return f"- {sig}{desc}"


class LuaActionRegistry:
    """Registry of available Lua actions for thinking prompts."""

    def __init__(self):
        self._actions: dict[str, ActionDef] = {}

    def __len__(self) -> int:
        return len(self._actions)

    def register(self, action: ActionDef) -> None:
        """Register or replace an action definition."""
        self._actions[action.name] = action

    def register_action(
        self,
        name: str,
        min_params: int = 0,
        max_params: int = 0,
        param_types: list[type] | None = None,
        description: str = "",
        source: str = "core",
    ) -> None:
        """Register an action by keyword arguments."""
        self._actions[name] = ActionDef(
            name=name,
            min_params=min_params,
            max_params=max_params,
            param_types=param_types or [],
            description=description,
            source=source,
        )

    def register_many(self, actions: dict[str, tuple]) -> None:
        """Bulk register from VALID_ACTIONS format: {name: (min, max, [types])}.

        Backwards-compatible with the old lua_motor.VALID_ACTIONS dict.
        """
        for name, (min_p, max_p, types) in actions.items():
            self._actions[name] = ActionDef(
                name=name,
                min_params=min_p,
                max_params=max_p,
                param_types=types,
                source="core",
            )

    def unregister(self, name: str) -> bool:
        """Remove an action. Returns True if it existed."""
        if name in self._actions:
            del self._actions[name]
            return True
        return False

    def unregister_by_source(self, source: str) -> int:
        """Remove all actions from a specific source. Returns count removed."""
        to_remove = [n for n, a in self._actions.items() if a.source == source]
        for name in to_remove:
            del self._actions[name]
        return len(to_remove)

    def get(self, name: str) -> ActionDef | None:
        """Get an action definition by name."""
        return self._actions.get(name)

    def list_actions(self) -> list[str]:
        """Return sorted list of action names."""
        return sorted(self._actions.keys())

    def actions_by_source(self, source: str) -> list[ActionDef]:
        """Return actions from a specific source."""
        return [a for a in self._actions.values() if a.source == source]

    def actions_by_source_prefix(self, prefix: str) -> list[ActionDef]:
        """Return actions whose source starts with prefix."""
        return [a for a in self._actions.values() if a.source.startswith(prefix)]

    def validate(self, action: str, params: list[Any]) -> str | None:
        """Validate action name and parameter count. Returns error or None."""
        defn = self._actions.get(action)
        if defn is None:
            valid_names = ", ".join(sorted(self._actions.keys()))
            return f"Unknown action '{action}'. Valid: {valid_names}"

        n = len(params)
        if n < defn.min_params:
            return f"'{action}' requires at least {defn.min_params} param(s), got {n}"
        if n > defn.max_params:
            return f"'{action}' accepts at most {defn.max_params} param(s), got {n}"

        return None

    def prompt_section(self, source_filter: str | None = None) -> str:
        """Generate the 'Available actions:' text for thinking prompts.

        Args:
            source_filter: If set, only include actions from this source.
        """
        actions = list(self._actions.values())
        if source_filter is not None:
            actions = [a for a in actions if a.source == source_filter]

        if not actions:
            return ""

        actions.sort(key=lambda a: a.name)
        lines = [a.to_prompt() for a in actions]
        return "\n".join(lines)

    @classmethod
    def with_core_actions(cls) -> LuaActionRegistry:
        """Create a registry pre-loaded with Amy's core actions."""
        from .lua_motor import VALID_ACTIONS
        reg = cls()
        reg.register_many(VALID_ACTIONS)
        return reg
