# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for ModelRouter wiring into Amy's subsystems.

Tests that create_amy(), Commander, ThinkingThread, and Agent correctly
use the ModelRouter when fleet_enabled=True, and fall back to static
behavior when fleet_enabled=False.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# Config — fleet_enabled setting
# ===========================================================================

@pytest.mark.unit
class TestConfigFleetEnabled:
    """Settings.fleet_enabled — opt-in fleet routing."""

    def test_fleet_disabled_by_default(self):
        from app.config import Settings
        s = Settings()
        assert s.fleet_enabled is False

    def test_fleet_auto_discover_default(self):
        from app.config import Settings
        s = Settings()
        assert s.fleet_auto_discover is True


# ===========================================================================
# create_amy — fleet wiring
# ===========================================================================

@pytest.mark.unit
class TestCreateAmyFleet:
    """create_amy() — ModelRouter creation when fleet_enabled."""

    def test_no_fleet_no_router(self):
        """Without fleet_enabled, commander has no model_router."""
        mock_settings = MagicMock()
        mock_settings.fleet_enabled = False
        mock_settings.amy_deep_model = "llava:7b"
        mock_settings.amy_chat_model = "gemma3:4b"
        mock_settings.amy_whisper_model = "large-v3"
        mock_settings.amy_tts_enabled = False
        mock_settings.amy_wake_word = "amy"
        mock_settings.amy_camera_device = None
        mock_settings.amy_think_interval = 8.0
        mock_settings.ollama_host = "http://localhost:11434"
        mock_settings.simulation_mode = "sim"

        from amy import create_amy
        commander = create_amy(settings=mock_settings)
        assert commander.model_router is None

    def test_fleet_creates_router(self):
        """With fleet_enabled, commander gets a model_router."""
        mock_settings = MagicMock()
        mock_settings.fleet_enabled = True
        mock_settings.fleet_auto_discover = False  # Don't scan Tailscale
        mock_settings.amy_deep_model = "llava:7b"
        mock_settings.amy_chat_model = "gemma3:4b"
        mock_settings.amy_whisper_model = "large-v3"
        mock_settings.amy_tts_enabled = False
        mock_settings.amy_wake_word = "amy"
        mock_settings.amy_camera_device = None
        mock_settings.amy_think_interval = 8.0
        mock_settings.ollama_host = "http://localhost:11434"
        mock_settings.simulation_mode = "sim"

        # Mock fleet discovery to avoid network calls
        with patch("engine.inference.fleet.OllamaFleet") as MockFleet:
            mock_fleet = MagicMock()
            mock_fleet.hosts = []
            mock_fleet.status.return_value = "Ollama Fleet: 0 hosts"
            MockFleet.return_value = mock_fleet

            from amy import create_amy
            commander = create_amy(settings=mock_settings)
            assert commander.model_router is not None


# ===========================================================================
# Commander — model_router attribute
# ===========================================================================

@pytest.mark.unit
class TestCommanderModelRouter:
    """Commander — model_router stored and accessible."""

    def test_commander_default_no_router(self):
        from amy.commander import Commander
        from tests.amy.conftest import MockSensorNode
        node = MockSensorNode()
        commander = Commander(nodes={"test": node})
        assert commander.model_router is None

    def test_commander_with_router(self):
        from amy.commander import Commander
        from engine.inference.model_router import ModelRouter
        from tests.amy.conftest import MockSensorNode
        node = MockSensorNode()
        router = ModelRouter.from_static()
        commander = Commander(nodes={"test": node}, model_router=router)
        assert commander.model_router is not None
        assert isinstance(commander.model_router, ModelRouter)


# ===========================================================================
# ModelRouter — TaskType classification from battlespace
# ===========================================================================

@pytest.mark.unit
class TestModelRouterBattlespace:
    """ModelRouter classification based on battlespace state."""

    def test_empty_battlespace_simple(self):
        from engine.inference.model_router import ModelRouter, TaskType
        router = ModelRouter()
        tt = router.classify_task(
            messages=[{"role": "user", "content": "What do you do?"}],
            context={"hostile_count": 0, "active_threats": 0},
        )
        assert tt == TaskType.SIMPLE_THINK

    def test_hostiles_complex(self):
        from engine.inference.model_router import ModelRouter, TaskType
        router = ModelRouter()
        tt = router.classify_task(
            messages=[{"role": "user", "content": "What do you do?"}],
            context={"hostile_count": 5, "active_threats": 2},
        )
        assert tt == TaskType.COMPLEX_REASON

    def test_images_vision(self):
        from engine.inference.model_router import ModelRouter, TaskType
        router = ModelRouter()
        tt = router.classify_task(
            messages=[{"role": "user", "content": "Describe."}],
            has_images=True,
        )
        assert tt == TaskType.VISION

    def test_chat_explicit(self):
        from engine.inference.model_router import ModelRouter, TaskType
        router = ModelRouter()
        tt = router.classify_task(
            messages=[{"role": "user", "content": "Hey Amy"}],
            context={"is_chat": True},
        )
        assert tt == TaskType.CHAT


# ===========================================================================
# LuaActionRegistry — with_core_actions matches VALID_ACTIONS
# ===========================================================================

@pytest.mark.unit
class TestRegistryCoreConsistency:
    """LuaActionRegistry core actions match lua_motor VALID_ACTIONS exactly."""

    def test_all_valid_actions_registered(self):
        from engine.actions.lua_registry import LuaActionRegistry
        from engine.actions.lua_motor import VALID_ACTIONS
        reg = LuaActionRegistry.with_core_actions()
        for name in VALID_ACTIONS:
            assert reg.get(name) is not None, f"Missing core action: {name}"

    def test_param_counts_match(self):
        from engine.actions.lua_registry import LuaActionRegistry
        from engine.actions.lua_motor import VALID_ACTIONS
        reg = LuaActionRegistry.with_core_actions()
        for name, (min_p, max_p, types) in VALID_ACTIONS.items():
            action = reg.get(name)
            assert action.min_params == min_p, f"{name} min_params mismatch"
            assert action.max_params == max_p, f"{name} max_params mismatch"

    def test_no_extra_actions(self):
        from engine.actions.lua_registry import LuaActionRegistry
        from engine.actions.lua_motor import VALID_ACTIONS
        reg = LuaActionRegistry.with_core_actions()
        assert len(reg) == len(VALID_ACTIONS)


# ===========================================================================
# Multi-Action Lua — edge cases
# ===========================================================================

@pytest.mark.unit
class TestMultiActionEdgeCases:
    """Multi-action Lua parsing edge cases for compound behaviors."""

    def test_function_in_comment(self):
        from engine.actions.lua_multi import extract_multi_actions
        code = '-- say("This is a comment")\nthink("Real action")'
        actions = extract_multi_actions(code)
        assert len(actions) == 1
        assert "think" in actions[0]

    def test_nested_quotes(self):
        from engine.actions.lua_multi import extract_multi_actions
        code = '''say("He said 'hello' to me")'''
        actions = extract_multi_actions(code)
        assert len(actions) == 1

    def test_multiline_string(self):
        from engine.actions.lua_multi import extract_multi_actions
        code = 'think("Scanning the perimeter")\nescalate("h-1", "hostile")'
        actions = extract_multi_actions(code)
        assert len(actions) == 2

    def test_code_gen_response(self):
        """A compound behavior response from code generation mode."""
        from engine.actions.lua_multi import extract_multi_actions
        code = '''```lua
-- Respond to intruder from the north
escalate("hostile-7", "hostile")
dispatch("rover-alpha", 10.0, 5.0)
battle_cry("Contact north! Deploying rover to intercept!")
```'''
        actions = extract_multi_actions(code)
        assert len(actions) == 3
        assert "escalate" in actions[0]
        assert "dispatch" in actions[1]
        assert "battle_cry" in actions[2]


# ===========================================================================
# RobotThinker — integration with LuaActionRegistry
# ===========================================================================

@pytest.mark.unit
class TestRobotThinkerRegistryIntegration:
    """RobotThinker — registry has both core and robot actions."""

    def test_robot_plus_core_actions(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})
        thinker.register_action(name="fire_nerf", description="Fire nerf turret")

        # Should have core + robot actions
        from engine.actions.lua_motor import VALID_ACTIONS
        assert len(thinker.registry) == len(VALID_ACTIONS) + 1

    def test_prompt_includes_both(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})
        thinker.register_action(name="fire_nerf", description="Fire nerf turret")
        context = thinker.build_context(telemetry={})
        assert "fire_nerf" in context
        assert "think" in context  # Core action
        assert "say" in context    # Core action
