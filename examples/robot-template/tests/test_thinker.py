# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for robot brain thinker — LLM-powered autonomous thinking.

Tests the standalone thinker that runs on-robot, calls Ollama for LLM inference,
parses Lua function calls from responses, and publishes thoughts via MQTT.
No dependency on amy/ package — fully self-contained.
"""

import json
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

# Add parent to path for imports
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock paho.mqtt before importing brain modules
_mock_paho = MagicMock()
sys.modules.setdefault("paho", _mock_paho)
sys.modules.setdefault("paho.mqtt", _mock_paho.mqtt)
sys.modules.setdefault("paho.mqtt.client", _mock_paho.mqtt.client)

from brain.thinker import RobotThinker, parse_lua_call, extract_lua_calls


# ===========================================================================
# Lua Parser — standalone (no amy/ dependency)
# ===========================================================================

class TestParseLuaCall:
    """parse_lua_call — extracts action name and params from Lua syntax."""

    def test_no_params(self):
        action, params = parse_lua_call('think()')
        assert action == 'think'
        assert params == []

    def test_single_string_param(self):
        action, params = parse_lua_call('think("Scanning area")')
        assert action == 'think'
        assert params == ['Scanning area']

    def test_single_quoted_param(self):
        action, params = parse_lua_call("say('Hello commander')")
        assert action == 'say'
        assert params == ['Hello commander']

    def test_numeric_param(self):
        action, params = parse_lua_call('dispatch("rover-01", 10.5, -3.2)')
        assert action == 'dispatch'
        assert params == ['rover-01', '10.5', '-3.2']

    def test_invalid_syntax(self):
        result = parse_lua_call('this is not lua')
        assert result is None

    def test_empty_string(self):
        result = parse_lua_call('')
        assert result is None

    def test_nested_quotes(self):
        action, params = parse_lua_call("""say("He said 'hello' to me")""")
        assert action == 'say'
        assert params == ["He said 'hello' to me"]

    def test_fire_nerf_custom(self):
        action, params = parse_lua_call('fire_nerf()')
        assert action == 'fire_nerf'
        assert params == []


class TestExtractLuaCalls:
    """extract_lua_calls — finds Lua function calls in LLM output."""

    def test_single_call(self):
        calls = extract_lua_calls('think("Patrolling area")')
        assert len(calls) == 1
        assert 'think' in calls[0]

    def test_multi_line(self):
        calls = extract_lua_calls('think("Check north")\nsay("Contact!")')
        assert len(calls) == 2

    def test_code_block(self):
        calls = extract_lua_calls('```lua\nthink("Hello")\n```')
        assert len(calls) == 1
        assert 'think' in calls[0]

    def test_comments_stripped(self):
        calls = extract_lua_calls('-- This is a comment\nthink("Real")')
        assert len(calls) == 1
        assert 'think' in calls[0]

    def test_empty_response(self):
        calls = extract_lua_calls('')
        assert len(calls) == 0

    def test_no_lua(self):
        calls = extract_lua_calls('I will think about that')
        assert len(calls) == 0

    def test_mixed_text_and_lua(self):
        calls = extract_lua_calls('Let me check... think("Scanning")')
        assert len(calls) == 1

    def test_custom_actions_extracted(self):
        """Custom robot actions should also be extracted."""
        calls = extract_lua_calls(
            'fire_nerf()\nset_led("red")',
            known_actions={"fire_nerf", "set_led", "think", "say"},
        )
        assert len(calls) == 2


# ===========================================================================
# RobotThinker — initialization
# ===========================================================================

class TestThinkerInit:
    """RobotThinker initialization from config."""

    def test_default_config(self):
        config = {"robot_id": "rover-alpha", "robot_name": "Rover Alpha"}
        thinker = RobotThinker(config)
        assert thinker.robot_id == "rover-alpha"
        assert thinker.model == "gemma3:4b"
        assert thinker.think_count == 0

    def test_custom_model(self):
        config = {
            "robot_id": "rover-alpha",
            "thinker": {"model": "qwen2.5:3b", "ollama_host": "http://remote:11434"},
        }
        thinker = RobotThinker(config)
        assert thinker.model == "qwen2.5:3b"
        assert thinker.ollama_host == "http://remote:11434"

    def test_disabled_by_default(self):
        config = {"robot_id": "rover-alpha"}
        thinker = RobotThinker(config)
        assert thinker.enabled is False

    def test_enabled_in_config(self):
        config = {"robot_id": "rover-alpha", "thinker": {"enabled": True}}
        thinker = RobotThinker(config)
        assert thinker.enabled is True

    def test_think_interval(self):
        config = {"robot_id": "rover-alpha", "thinker": {"think_interval": 3.0}}
        thinker = RobotThinker(config)
        assert thinker.think_interval == 3.0


# ===========================================================================
# RobotThinker — action registry
# ===========================================================================

class TestThinkerActions:
    """RobotThinker action registration and built-in actions."""

    def test_default_actions(self):
        thinker = RobotThinker({"robot_id": "r1"})
        # Must have at least think, say
        assert "think" in thinker.actions
        assert "say" in thinker.actions

    def test_register_custom_action(self):
        thinker = RobotThinker({"robot_id": "r1"})
        thinker.register_action("fire_nerf", description="Fire nerf turret")
        assert "fire_nerf" in thinker.actions

    def test_config_actions(self):
        config = {
            "robot_id": "r1",
            "thinker": {
                "enabled": True,
                "actions": [
                    {"name": "fire_nerf", "description": "Fire turret"},
                    {"name": "set_led", "description": "Set LED color"},
                ],
            },
        }
        thinker = RobotThinker(config)
        assert "fire_nerf" in thinker.actions
        assert "set_led" in thinker.actions

    def test_unregister_action(self):
        thinker = RobotThinker({"robot_id": "r1"})
        thinker.register_action("fire_nerf", description="Fire turret")
        assert "fire_nerf" in thinker.actions
        thinker.unregister_action("fire_nerf")
        assert "fire_nerf" not in thinker.actions

    def test_action_prompt_generation(self):
        thinker = RobotThinker({"robot_id": "r1"})
        thinker.register_action("fire_nerf", description="Fire the nerf turret")
        prompt = thinker.actions_prompt()
        assert "fire_nerf" in prompt
        assert "Fire the nerf turret" in prompt
        assert "think" in prompt


# ===========================================================================
# RobotThinker — context building
# ===========================================================================

class TestThinkerContext:
    """RobotThinker builds thinking prompt from state."""

    def test_basic_context(self):
        thinker = RobotThinker({
            "robot_id": "rover-alpha",
            "robot_name": "Rover Alpha",
            "asset_type": "rover",
        })
        ctx = thinker.build_context(
            telemetry={"position": {"x": 5.0, "y": -3.0}, "battery": 0.85, "status": "idle"},
        )
        assert "rover-alpha" in ctx
        assert "Rover Alpha" in ctx
        assert "5.0" in ctx
        assert "85%" in ctx

    def test_context_with_targets(self):
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        ctx = thinker.build_context(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
            nearby_targets=[
                {"name": "hostile-1", "alliance": "hostile", "position": {"x": 10, "y": 5}},
            ],
        )
        assert "hostile-1" in ctx
        assert "hostile" in ctx

    def test_context_with_commands(self):
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        ctx = thinker.build_context(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
            recent_commands=[{"command": "dispatch", "x": 10, "y": 5}],
        )
        assert "dispatch" in ctx

    def test_context_includes_thought_history(self):
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        thinker._thought_history.append({"text": "Checking north sector", "action": "think"})
        ctx = thinker.build_context(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
        )
        assert "Checking north sector" in ctx


# ===========================================================================
# RobotThinker — think cycle (mocked Ollama)
# ===========================================================================

class TestThinkerCycle:
    """RobotThinker.think_once — one thinking cycle with mocked Ollama."""

    def _mock_ollama_response(self, content: str):
        """Create a mock requests.post response."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": content, "role": "assistant"},
        }
        return mock_resp

    @patch("brain.thinker.requests.post")
    def test_think_returns_action(self, mock_post):
        mock_post.return_value = self._mock_ollama_response('think("All clear")')
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        result = thinker.think_once(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
        )
        assert result is not None
        assert result["action"] == "think"
        assert result["params"] == ["All clear"]
        assert thinker.think_count == 1

    @patch("brain.thinker.requests.post")
    def test_think_say_action(self, mock_post):
        mock_post.return_value = self._mock_ollama_response('say("Contact north!")')
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        result = thinker.think_once(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
        )
        assert result is not None
        assert result["action"] == "say"

    @patch("brain.thinker.requests.post")
    def test_think_custom_action(self, mock_post):
        mock_post.return_value = self._mock_ollama_response('fire_nerf()')
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        thinker.register_action("fire_nerf", description="Fire nerf turret")
        result = thinker.think_once(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
        )
        assert result is not None
        assert result["action"] == "fire_nerf"

    @patch("brain.thinker.requests.post")
    def test_think_records_history(self, mock_post):
        mock_post.return_value = self._mock_ollama_response('think("Scanning")')
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        thinker.think_once(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
        )
        assert len(thinker.thought_history) == 1
        assert thinker.last_thought == "Scanning"

    @patch("brain.thinker.requests.post")
    def test_think_ollama_failure(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        result = thinker.think_once(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
        )
        assert result is None
        assert thinker.think_count == 0

    @patch("brain.thinker.requests.post")
    def test_think_empty_response(self, mock_post):
        mock_post.return_value = self._mock_ollama_response('')
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        result = thinker.think_once(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
        )
        assert result is None

    @patch("brain.thinker.requests.post")
    def test_think_history_trimmed(self, mock_post):
        mock_post.return_value = self._mock_ollama_response('think("Hello")')
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        for _ in range(30):
            thinker.think_once(
                telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
            )
        assert len(thinker.thought_history) <= 20

    @patch("brain.thinker.requests.post")
    def test_think_multi_action(self, mock_post):
        """Multi-action responses should extract the first valid action."""
        mock_post.return_value = self._mock_ollama_response(
            'think("Hostile spotted")\nfire_nerf()'
        )
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        thinker.register_action("fire_nerf", description="Fire nerf turret")
        result = thinker.think_once(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
        )
        # Returns the first action; multi-dispatch is caller's responsibility
        assert result is not None
        assert result["action"] == "think"


# ===========================================================================
# RobotThinker — MQTT thought publishing
# ===========================================================================

class TestThinkerMQTT:
    """RobotThinker generates MQTT-publishable thought messages."""

    @patch("brain.thinker.requests.post")
    def test_to_mqtt_message(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": 'think("All clear")', "role": "assistant"},
        }
        mock_post.return_value = mock_resp

        thinker = RobotThinker({"robot_id": "rover-alpha", "robot_name": "Rover Alpha"})
        thinker.think_once(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
        )
        msg = thinker.to_mqtt_message()
        assert msg["robot_id"] == "rover-alpha"
        assert msg["type"] == "thought"
        assert msg["text"] == "All clear"
        assert msg["think_count"] == 1
        assert "timestamp" in msg

    def test_mqtt_message_empty_before_thinking(self):
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        msg = thinker.to_mqtt_message()
        assert msg["text"] == ""
        assert msg["think_count"] == 0

    def test_mqtt_topic(self):
        thinker = RobotThinker({"robot_id": "rover-alpha", "site_id": "home"})
        expected = "tritium/home/robots/rover-alpha/thoughts"
        assert thinker.mqtt_topic == expected

    def test_mqtt_topic_custom_site(self):
        thinker = RobotThinker({"robot_id": "r1", "site_id": "lab"})
        assert thinker.mqtt_topic == "tritium/lab/robots/r1/thoughts"


# ===========================================================================
# RobotThinker — action dispatch mapping
# ===========================================================================

class TestThinkerDispatch:
    """RobotThinker maps Lua actions to local hardware functions."""

    def test_register_handler(self):
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        thinker.register_action("fire_nerf", description="Fire turret")
        called = []
        thinker.on_action("fire_nerf", lambda params: called.append(params))
        thinker.dispatch_action("fire_nerf", [])
        assert len(called) == 1

    def test_dispatch_unknown_action(self):
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        # Should not crash
        thinker.dispatch_action("nonexistent", [])

    def test_dispatch_think_noop(self):
        """think() is internal — no hardware dispatch."""
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        # think() should not raise
        thinker.dispatch_action("think", ["Scanning area"])

    def test_dispatch_say_calls_handler(self):
        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        spoken = []
        thinker.on_action("say", lambda params: spoken.append(params[0]))
        thinker.dispatch_action("say", ["Contact!"])
        assert spoken == ["Contact!"]

    @patch("brain.thinker.requests.post")
    def test_full_think_dispatch_cycle(self, mock_post):
        """Full cycle: think -> parse -> dispatch."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": 'fire_nerf()', "role": "assistant"},
        }
        mock_post.return_value = mock_resp

        thinker = RobotThinker({"robot_id": "r1", "robot_name": "Bot"})
        fired = []
        thinker.register_action("fire_nerf", description="Fire turret")
        thinker.on_action("fire_nerf", lambda params: fired.append(True))

        result = thinker.think_once(
            telemetry={"position": {"x": 0, "y": 0}, "battery": 1.0, "status": "idle"},
        )
        assert result is not None
        thinker.dispatch_action(result["action"], result["params"])
        assert fired == [True]
