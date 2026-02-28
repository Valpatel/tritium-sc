# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for RobotThinker — LLM-powered autonomous robot thinking.

Tests thinking cycle, Lua action dispatch, registry integration,
and MQTT thought publishing. Written TDD-first.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# RobotThinker — Construction
# ===========================================================================

@pytest.mark.unit
class TestRobotThinkerInit:
    """RobotThinker — initialization."""

    def test_construction(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})
        assert thinker.robot_id == "rover-alpha"

    def test_default_model(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})
        assert thinker.model == "gemma3:4b"

    def test_custom_model(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(
            robot_id="rover-alpha",
            config={"think_model": "llava:7b"},
        )
        assert thinker.model == "llava:7b"

    def test_has_registry(self):
        from engine.inference.robot_thinker import RobotThinker
        from engine.actions.lua_registry import LuaActionRegistry
        thinker = RobotThinker(robot_id="r1", config={})
        assert isinstance(thinker.registry, LuaActionRegistry)

    def test_registry_has_core_actions(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="r1", config={})
        assert thinker.registry.get("think") is not None
        assert thinker.registry.get("say") is not None

    def test_think_count_starts_zero(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="r1", config={})
        assert thinker.think_count == 0


# ===========================================================================
# RobotThinker — Custom Action Registration
# ===========================================================================

@pytest.mark.unit
class TestRobotThinkerActions:
    """RobotThinker — register robot-specific actions."""

    def test_register_robot_action(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})
        thinker.register_action(
            name="fire_nerf",
            min_params=0,
            max_params=0,
            description="Fire nerf turret",
        )
        assert thinker.registry.get("fire_nerf") is not None

    def test_robot_action_source_tagged(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})
        thinker.register_action(name="fire_nerf")
        action = thinker.registry.get("fire_nerf")
        assert action.source == "robot:rover-alpha"

    def test_register_from_config(self):
        from engine.inference.robot_thinker import RobotThinker
        config = {
            "actions": [
                {"name": "fire_nerf", "min_params": 0, "max_params": 0,
                 "description": "Fire nerf turret"},
                {"name": "set_led", "min_params": 1, "max_params": 1,
                 "param_types": ["str"], "description": "Set LED color"},
            ]
        }
        thinker = RobotThinker(robot_id="rover-alpha", config=config)
        assert thinker.registry.get("fire_nerf") is not None
        assert thinker.registry.get("set_led") is not None

    def test_unregister_robot_actions(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})
        thinker.register_action(name="fire_nerf")
        thinker.register_action(name="set_led")

        count = thinker.unregister_robot_actions()
        assert count == 2
        assert thinker.registry.get("fire_nerf") is None
        assert thinker.registry.get("set_led") is None
        # Core actions should remain
        assert thinker.registry.get("think") is not None


# ===========================================================================
# RobotThinker — Context Building
# ===========================================================================

@pytest.mark.unit
class TestRobotThinkerContext:
    """RobotThinker.build_context — thinking prompt context."""

    def test_build_context_basic(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={
            "robot_name": "Rover Alpha",
            "asset_type": "rover",
        })
        context = thinker.build_context(telemetry={
            "position": {"x": 5.0, "y": 10.0},
            "battery": 0.85,
            "status": "active",
        })
        assert "Rover Alpha" in context
        assert "rover" in context.lower()
        assert "5.0" in context
        assert "85%" in context or "0.85" in context

    def test_build_context_with_targets(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})
        context = thinker.build_context(
            telemetry={"position": {"x": 0, "y": 0}},
            nearby_targets=[
                {"name": "Intruder A", "alliance": "hostile",
                 "position": {"x": 5, "y": 5}},
            ],
        )
        assert "Intruder" in context or "hostile" in context.lower()

    def test_build_context_with_commands(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})
        context = thinker.build_context(
            telemetry={"position": {"x": 0, "y": 0}},
            recent_commands=[
                {"command": "dispatch", "x": 10.0, "y": 5.0},
            ],
        )
        assert "dispatch" in context.lower() or "10.0" in context

    def test_build_context_includes_actions(self):
        """Context should include available actions for the prompt."""
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})
        thinker.register_action(name="fire_nerf", description="Fire nerf turret")
        context = thinker.build_context(telemetry={})
        assert "fire_nerf" in context


# ===========================================================================
# RobotThinker — Think Cycle
# ===========================================================================

@pytest.mark.unit
class TestRobotThinkerCycle:
    """RobotThinker.think_cycle — run one thinking cycle."""

    def test_think_cycle_returns_motor_output(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})

        with patch("engine.inference.robot_thinker.ollama_chat") as mock_chat:
            mock_chat.return_value = {
                "message": {"content": 'think("Scanning area...")'},
            }
            result = thinker.think_cycle(telemetry={
                "position": {"x": 0, "y": 0},
                "battery": 0.9,
            })
            assert result is not None
            assert result.valid
            assert result.action == "think"

    def test_think_cycle_increments_count(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})

        with patch("engine.inference.robot_thinker.ollama_chat") as mock_chat:
            mock_chat.return_value = {
                "message": {"content": 'think("OK")'},
            }
            thinker.think_cycle(telemetry={})
            thinker.think_cycle(telemetry={})
            assert thinker.think_count == 2

    def test_think_cycle_llm_failure_returns_none(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})

        with patch("engine.inference.robot_thinker.ollama_chat", side_effect=ConnectionError("Down")):
            result = thinker.think_cycle(telemetry={})
            assert result is None

    def test_think_cycle_invalid_response_returns_none(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})

        with patch("engine.inference.robot_thinker.ollama_chat") as mock_chat:
            mock_chat.return_value = {
                "message": {"content": ""},
            }
            result = thinker.think_cycle(telemetry={})
            assert result is None

    def test_think_cycle_uses_model_router(self):
        """When a model_router is provided, uses it for inference."""
        from engine.inference.robot_thinker import RobotThinker
        from engine.inference.model_router import ModelRouter, ModelProfile, TaskType

        mock_router = MagicMock()
        mock_router.infer.return_value = {
            "message": {"content": 'think("Routed!")'},
        }

        thinker = RobotThinker(
            robot_id="rover-alpha",
            config={},
            model_router=mock_router,
        )
        result = thinker.think_cycle(telemetry={})
        assert result is not None
        assert result.action == "think"
        mock_router.infer.assert_called_once()


# ===========================================================================
# RobotThinker — Thought Publishing
# ===========================================================================

@pytest.mark.unit
class TestRobotThinkerPublish:
    """RobotThinker — publish thoughts for Amy consumption."""

    def test_thought_history(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})

        with patch("engine.inference.robot_thinker.ollama_chat") as mock_chat:
            mock_chat.return_value = {
                "message": {"content": 'think("I see something")'},
            }
            thinker.think_cycle(telemetry={})
            assert len(thinker.thought_history) == 1
            assert "see something" in thinker.thought_history[0]["text"]

    def test_thought_history_max(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})

        with patch("engine.inference.robot_thinker.ollama_chat") as mock_chat:
            for i in range(25):
                mock_chat.return_value = {
                    "message": {"content": f'think("Thought {i}")'},
                }
                thinker.think_cycle(telemetry={})
            assert len(thinker.thought_history) <= 20

    def test_last_thought(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})

        with patch("engine.inference.robot_thinker.ollama_chat") as mock_chat:
            mock_chat.return_value = {
                "message": {"content": 'think("Latest thought")'},
            }
            thinker.think_cycle(telemetry={})
            assert thinker.last_thought == "Latest thought"

    def test_to_mqtt_message(self):
        from engine.inference.robot_thinker import RobotThinker
        thinker = RobotThinker(robot_id="rover-alpha", config={})

        with patch("engine.inference.robot_thinker.ollama_chat") as mock_chat:
            mock_chat.return_value = {
                "message": {"content": 'think("Scanning area")'},
            }
            thinker.think_cycle(telemetry={})
            msg = thinker.to_mqtt_message()
            assert msg["robot_id"] == "rover-alpha"
            assert msg["type"] == "thought"
            assert "Scanning area" in msg["text"]
