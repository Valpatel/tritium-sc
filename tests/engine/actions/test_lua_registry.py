# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for LuaActionRegistry — extensible Lua action registration.

Tests dynamic action registration, validation, prompt generation, and
source filtering. Written TDD-first.
"""
from __future__ import annotations

import pytest


# ===========================================================================
# ActionDef Dataclass
# ===========================================================================

@pytest.mark.unit
class TestActionDef:
    """ActionDef — action definition metadata."""

    def test_construction(self):
        from engine.actions.lua_registry import ActionDef
        a = ActionDef(
            name="fire_nerf",
            min_params=0,
            max_params=0,
            param_types=[],
            description="Fire nerf turret",
            source="robot:rover-alpha",
        )
        assert a.name == "fire_nerf"
        assert a.source == "robot:rover-alpha"

    def test_defaults(self):
        from engine.actions.lua_registry import ActionDef
        a = ActionDef(name="test")
        assert a.min_params == 0
        assert a.max_params == 0
        assert a.param_types == []
        assert a.description == ""
        assert a.source == "core"

    def test_to_prompt(self):
        from engine.actions.lua_registry import ActionDef
        a = ActionDef(
            name="say",
            min_params=1,
            max_params=1,
            param_types=[str],
            description="speak aloud",
        )
        prompt = a.to_prompt()
        assert "say" in prompt
        assert "speak aloud" in prompt


# ===========================================================================
# LuaActionRegistry — Registration
# ===========================================================================

@pytest.mark.unit
class TestLuaRegistryRegister:
    """LuaActionRegistry — register and unregister actions."""

    def test_starts_empty(self):
        from engine.actions.lua_registry import LuaActionRegistry
        reg = LuaActionRegistry()
        assert len(reg) == 0

    def test_register_action(self):
        from engine.actions.lua_registry import LuaActionRegistry, ActionDef
        reg = LuaActionRegistry()
        reg.register(ActionDef(name="fire"))
        assert len(reg) == 1

    def test_register_by_kwargs(self):
        from engine.actions.lua_registry import LuaActionRegistry
        reg = LuaActionRegistry()
        reg.register_action(
            name="fire",
            min_params=0,
            max_params=0,
            param_types=[],
            description="Fire turret",
        )
        assert reg.get("fire") is not None

    def test_register_many(self):
        """Backwards-compatible bulk registration from VALID_ACTIONS dict."""
        from engine.actions.lua_registry import LuaActionRegistry
        reg = LuaActionRegistry()
        actions = {
            "say": (1, 1, [str]),
            "think": (1, 1, [str]),
            "scan": (0, 0, []),
        }
        reg.register_many(actions)
        assert len(reg) == 3
        assert reg.get("say") is not None
        assert reg.get("think") is not None
        assert reg.get("scan") is not None

    def test_register_replaces_existing(self):
        from engine.actions.lua_registry import LuaActionRegistry, ActionDef
        reg = LuaActionRegistry()
        reg.register(ActionDef(name="fire", description="v1"))
        reg.register(ActionDef(name="fire", description="v2"))
        assert len(reg) == 1
        assert reg.get("fire").description == "v2"

    def test_unregister(self):
        from engine.actions.lua_registry import LuaActionRegistry, ActionDef
        reg = LuaActionRegistry()
        reg.register(ActionDef(name="fire"))
        result = reg.unregister("fire")
        assert result is True
        assert len(reg) == 0

    def test_unregister_missing_returns_false(self):
        from engine.actions.lua_registry import LuaActionRegistry
        reg = LuaActionRegistry()
        assert reg.unregister("nonexistent") is False

    def test_get_action(self):
        from engine.actions.lua_registry import LuaActionRegistry, ActionDef
        reg = LuaActionRegistry()
        reg.register(ActionDef(name="fire", description="Fire turret"))
        a = reg.get("fire")
        assert a.name == "fire"
        assert a.description == "Fire turret"

    def test_get_missing(self):
        from engine.actions.lua_registry import LuaActionRegistry
        reg = LuaActionRegistry()
        assert reg.get("nonexistent") is None

    def test_list_actions(self):
        from engine.actions.lua_registry import LuaActionRegistry, ActionDef
        reg = LuaActionRegistry()
        reg.register(ActionDef(name="alpha"))
        reg.register(ActionDef(name="beta"))
        names = reg.list_actions()
        assert "alpha" in names
        assert "beta" in names


# ===========================================================================
# LuaActionRegistry — Source Filtering
# ===========================================================================

@pytest.mark.unit
class TestLuaRegistrySourceFilter:
    """LuaActionRegistry — filter actions by source."""

    def test_filter_by_source(self):
        from engine.actions.lua_registry import LuaActionRegistry, ActionDef
        reg = LuaActionRegistry()
        reg.register(ActionDef(name="say", source="core"))
        reg.register(ActionDef(name="fire", source="robot:rover-alpha"))
        reg.register(ActionDef(name="set_led", source="robot:rover-alpha"))

        core_actions = reg.actions_by_source("core")
        assert len(core_actions) == 1
        assert core_actions[0].name == "say"

        robot_actions = reg.actions_by_source("robot:rover-alpha")
        assert len(robot_actions) == 2

    def test_filter_by_source_prefix(self):
        from engine.actions.lua_registry import LuaActionRegistry, ActionDef
        reg = LuaActionRegistry()
        reg.register(ActionDef(name="fire", source="robot:rover-alpha"))
        reg.register(ActionDef(name="scan", source="robot:drone-beta"))
        reg.register(ActionDef(name="say", source="core"))

        robot_actions = reg.actions_by_source_prefix("robot:")
        assert len(robot_actions) == 2

    def test_filter_empty_source(self):
        from engine.actions.lua_registry import LuaActionRegistry
        reg = LuaActionRegistry()
        assert reg.actions_by_source("nonexistent") == []

    def test_unregister_by_source(self):
        from engine.actions.lua_registry import LuaActionRegistry, ActionDef
        reg = LuaActionRegistry()
        reg.register(ActionDef(name="say", source="core"))
        reg.register(ActionDef(name="fire", source="robot:rover-alpha"))
        reg.register(ActionDef(name="set_led", source="robot:rover-alpha"))

        count = reg.unregister_by_source("robot:rover-alpha")
        assert count == 2
        assert len(reg) == 1
        assert reg.get("say") is not None


# ===========================================================================
# LuaActionRegistry — Validation
# ===========================================================================

@pytest.mark.unit
class TestLuaRegistryValidation:
    """LuaActionRegistry.validate — action + params validation."""

    def _registry_with_core(self):
        from engine.actions.lua_registry import LuaActionRegistry
        reg = LuaActionRegistry()
        reg.register_many({
            "say": (1, 1, [str]),
            "think": (1, 1, [str]),
            "scan": (0, 0, []),
            "dispatch": (3, 3, [str, float, float]),
            "wait": (1, 1, [float]),
        })
        return reg

    def test_valid_action(self):
        reg = self._registry_with_core()
        assert reg.validate("say", ["Hello"]) is None

    def test_unknown_action(self):
        reg = self._registry_with_core()
        error = reg.validate("nonexistent", [])
        assert error is not None
        assert "Unknown" in error or "unknown" in error.lower()

    def test_too_few_params(self):
        reg = self._registry_with_core()
        error = reg.validate("say", [])
        assert error is not None
        assert "param" in error.lower()

    def test_too_many_params(self):
        reg = self._registry_with_core()
        error = reg.validate("scan", ["extra"])
        assert error is not None
        assert "param" in error.lower()

    def test_valid_no_params(self):
        reg = self._registry_with_core()
        assert reg.validate("scan", []) is None

    def test_valid_multi_params(self):
        reg = self._registry_with_core()
        assert reg.validate("dispatch", ["rover-01", 5.0, 10.0]) is None


# ===========================================================================
# LuaActionRegistry — Prompt Generation
# ===========================================================================

@pytest.mark.unit
class TestLuaRegistryPrompt:
    """LuaActionRegistry.prompt_section — generate thinking prompt text."""

    def test_prompt_section_all(self):
        from engine.actions.lua_registry import LuaActionRegistry, ActionDef
        reg = LuaActionRegistry()
        reg.register(ActionDef(name="say", min_params=1, max_params=1,
                               param_types=[str], description="speak aloud"))
        reg.register(ActionDef(name="scan", description="resume scanning"))

        prompt = reg.prompt_section()
        assert "say" in prompt
        assert "scan" in prompt
        assert "speak aloud" in prompt

    def test_prompt_section_filtered(self):
        from engine.actions.lua_registry import LuaActionRegistry, ActionDef
        reg = LuaActionRegistry()
        reg.register(ActionDef(name="say", source="core", description="speak"))
        reg.register(ActionDef(name="fire", source="robot:rover", description="fire turret"))

        prompt = reg.prompt_section(source_filter="core")
        assert "say" in prompt
        assert "fire" not in prompt

    def test_prompt_section_empty(self):
        from engine.actions.lua_registry import LuaActionRegistry
        reg = LuaActionRegistry()
        prompt = reg.prompt_section()
        assert prompt == "" or "no actions" in prompt.lower() or len(prompt) == 0

    def test_prompt_section_includes_robot_actions(self):
        from engine.actions.lua_registry import LuaActionRegistry, ActionDef
        reg = LuaActionRegistry()
        reg.register(ActionDef(name="say", source="core", description="speak"))
        reg.register(ActionDef(name="fire_nerf", source="robot:rover-alpha",
                               description="fire nerf turret"))

        # When no filter, includes everything
        prompt = reg.prompt_section()
        assert "fire_nerf" in prompt
        assert "say" in prompt


# ===========================================================================
# LuaActionRegistry — Default Core Actions
# ===========================================================================

@pytest.mark.unit
class TestLuaRegistryDefaults:
    """LuaActionRegistry.with_core_actions — load Amy's default actions."""

    def test_with_core_actions(self):
        from engine.actions.lua_registry import LuaActionRegistry
        reg = LuaActionRegistry.with_core_actions()
        # Should have all the actions from VALID_ACTIONS
        assert reg.get("say") is not None
        assert reg.get("think") is not None
        assert reg.get("scan") is not None
        assert reg.get("dispatch") is not None
        assert reg.get("battle_cry") is not None

    def test_core_actions_count(self):
        from engine.actions.lua_registry import LuaActionRegistry
        from engine.actions.lua_motor import VALID_ACTIONS
        reg = LuaActionRegistry.with_core_actions()
        assert len(reg) == len(VALID_ACTIONS)

    def test_core_actions_all_source_core(self):
        from engine.actions.lua_registry import LuaActionRegistry
        reg = LuaActionRegistry.with_core_actions()
        for action in reg.actions_by_source("core"):
            assert action.source == "core"
