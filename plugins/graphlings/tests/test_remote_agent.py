# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for RemoteAgentRegistry — generic remote agent join protocol.

Tests the local RemoteAgentRegistry class from graphlings.remote_agent.
No SDK dependency — this is a standalone tritium-sc component.
"""
from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock

import pytest

from graphlings.remote_agent import RemoteAgentRegistry


# ── Registry basics ──────────────────────────────────────────────


class TestRemoteAgentRegistration:
    """Remote agents can register and unregister."""

    def test_register_agent(self):
        registry = RemoteAgentRegistry(max_agents=5)
        result = registry.register_agent(
            agent_id="agent-1",
            name="Twilight",
            capabilities=["think", "observe"],
            callback_url="http://localhost:9000/callback",
        )
        assert result is True
        agents = registry.get_agents()
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "agent-1"
        assert agents[0]["name"] == "Twilight"

    def test_unregister_agent(self):
        registry = RemoteAgentRegistry(max_agents=5)
        registry.register_agent(
            agent_id="agent-1",
            name="Twilight",
            capabilities=["think"],
        )
        result = registry.unregister_agent("agent-1")
        assert result is True
        assert len(registry.get_agents()) == 0

    def test_unregister_unknown_agent(self):
        registry = RemoteAgentRegistry(max_agents=5)
        result = registry.unregister_agent("nonexistent")
        assert result is False

    def test_duplicate_agent_rejected(self):
        registry = RemoteAgentRegistry(max_agents=5)
        registry.register_agent(
            agent_id="agent-1",
            name="Twilight",
            capabilities=["think"],
        )
        result = registry.register_agent(
            agent_id="agent-1",
            name="Twilight Clone",
            capabilities=["think"],
        )
        assert result is False
        assert len(registry.get_agents()) == 1

    def test_max_agents_limit(self):
        registry = RemoteAgentRegistry(max_agents=2)
        registry.register_agent(agent_id="a1", name="A1", capabilities=[])
        registry.register_agent(agent_id="a2", name="A2", capabilities=[])
        result = registry.register_agent(agent_id="a3", name="A3", capabilities=[])
        assert result is False
        assert len(registry.get_agents()) == 2

    def test_agent_capabilities_stored(self):
        registry = RemoteAgentRegistry(max_agents=5)
        registry.register_agent(
            agent_id="agent-1",
            name="Twilight",
            capabilities=["think", "observe", "emote"],
        )
        agents = registry.get_agents()
        assert set(agents[0]["capabilities"]) == {"think", "observe", "emote"}

    def test_agent_callback_url_optional(self):
        """Agents can register without a callback_url (they may use WebSocket)."""
        registry = RemoteAgentRegistry(max_agents=5)
        result = registry.register_agent(
            agent_id="ws-agent",
            name="WebSocket Agent",
            capabilities=["think"],
        )
        assert result is True
        agents = registry.get_agents()
        assert agents[0]["callback_url"] is None


# ── Perception routing ───────────────────────────────────────────


class TestPerceptionRouting:
    """Perceptions can be routed to registered agents."""

    def test_route_perception_to_agent(self):
        registry = RemoteAgentRegistry(max_agents=5)
        registry.register_agent(
            agent_id="agent-1",
            name="Twilight",
            capabilities=["think", "observe"],
        )
        perception = {
            "nearby_entities": [{"name": "tree", "distance": 5.0}],
            "danger_level": 0.1,
        }
        result = registry.route_perception(
            agent_id="agent-1",
            perception=perception,
            available_actions=["observe", "move_to"],
            urgency=0.3,
        )
        assert result is not None
        assert result["agent_id"] == "agent-1"
        assert result["perception"] == perception
        assert result["available_actions"] == ["observe", "move_to"]
        assert result["urgency"] == 0.3

    def test_route_perception_unknown_agent(self):
        registry = RemoteAgentRegistry(max_agents=5)
        result = registry.route_perception(
            agent_id="nonexistent",
            perception={},
            available_actions=[],
            urgency=0.0,
        )
        assert result is None

    def test_route_perception_filters_by_capability(self):
        """Agent without 'think' capability should not receive perceptions."""
        registry = RemoteAgentRegistry(max_agents=5)
        registry.register_agent(
            agent_id="limited",
            name="Limited Bot",
            capabilities=["emote"],  # no 'think' or 'observe'
        )
        result = registry.route_perception(
            agent_id="limited",
            perception={"nearby_entities": []},
            available_actions=["observe"],
            urgency=0.5,
        )
        assert result is None


# ── Graceful disconnect ──────────────────────────────────────────


class TestGracefulDisconnect:
    """Handle agent disconnection scenarios."""

    def test_unregister_cleans_up_state(self):
        registry = RemoteAgentRegistry(max_agents=5)
        registry.register_agent(
            agent_id="agent-1",
            name="Twilight",
            capabilities=["think"],
        )
        registry.unregister_agent("agent-1")
        result = registry.register_agent(
            agent_id="agent-1",
            name="Twilight Reborn",
            capabilities=["think", "observe"],
        )
        assert result is True
        agents = registry.get_agents()
        assert agents[0]["name"] == "Twilight Reborn"

    def test_get_agent_by_id(self):
        registry = RemoteAgentRegistry(max_agents=5)
        registry.register_agent(
            agent_id="agent-1",
            name="Twilight",
            capabilities=["think"],
            callback_url="http://example.com/cb",
        )
        agent = registry.get_agent("agent-1")
        assert agent is not None
        assert agent["name"] == "Twilight"
        assert agent["callback_url"] == "http://example.com/cb"

    def test_get_agent_unknown_returns_none(self):
        registry = RemoteAgentRegistry(max_agents=5)
        assert registry.get_agent("no-such") is None


# ── HTTP route handlers ─────────────────────────────────────────


class TestJoinRoute:
    """POST /api/graphlings/join handler."""

    def test_join_success(self):
        registry = RemoteAgentRegistry(max_agents=5)
        result = registry.register_agent(
            agent_id="ext-1",
            name="External Bot",
            capabilities=["think", "observe"],
            callback_url="http://external:8080/decide",
        )
        assert result is True

    def test_join_missing_agent_id_fails(self):
        registry = RemoteAgentRegistry(max_agents=5)
        result = registry.register_agent(
            agent_id="",
            name="No ID Bot",
            capabilities=["think"],
        )
        assert result is False

    def test_join_missing_name_fails(self):
        registry = RemoteAgentRegistry(max_agents=5)
        result = registry.register_agent(
            agent_id="agent-1",
            name="",
            capabilities=["think"],
        )
        assert result is False


class TestLeaveRoute:
    """POST /api/graphlings/leave handler."""

    def test_leave_success(self):
        registry = RemoteAgentRegistry(max_agents=5)
        registry.register_agent(
            agent_id="ext-1",
            name="External Bot",
            capabilities=["think"],
        )
        result = registry.unregister_agent("ext-1")
        assert result is True


class TestAgentsRoute:
    """GET /api/graphlings/agents handler."""

    def test_agents_returns_all(self):
        registry = RemoteAgentRegistry(max_agents=5)
        registry.register_agent(agent_id="a1", name="Bot1", capabilities=["think"])
        registry.register_agent(agent_id="a2", name="Bot2", capabilities=["observe"])
        agents = registry.get_agents()
        assert len(agents) == 2
        ids = {a["agent_id"] for a in agents}
        assert ids == {"a1", "a2"}

    def test_agents_empty(self):
        registry = RemoteAgentRegistry(max_agents=5)
        agents = registry.get_agents()
        assert agents == []


# ── WebSocket message handling ───────────────────────────────────


class TestWebSocketMessages:
    """WebSocket message construction and validation."""

    def test_build_perceive_message(self):
        registry = RemoteAgentRegistry(max_agents=5)
        msg = registry.build_perceive_message(
            perception={"nearby_entities": [], "danger_level": 0.0},
            available_actions=["observe", "say", "move_to"],
            urgency=0.2,
        )
        assert msg["type"] == "perceive"
        assert msg["perception"]["danger_level"] == 0.0
        assert "observe" in msg["available_actions"]
        assert msg["urgency"] == 0.2

    def test_parse_decide_message_valid(self):
        registry = RemoteAgentRegistry(max_agents=5)
        raw = {
            "type": "decide",
            "thought": "I should explore the area.",
            "action": "move_to(100, 200)",
            "emotion": "curious",
        }
        result = registry.parse_decide_message(raw)
        assert result is not None
        assert result["thought"] == "I should explore the area."
        assert result["action"] == "move_to(100, 200)"
        assert result["emotion"] == "curious"

    def test_parse_decide_message_invalid_type(self):
        registry = RemoteAgentRegistry(max_agents=5)
        raw = {"type": "wrong", "thought": "hello"}
        result = registry.parse_decide_message(raw)
        assert result is None

    def test_parse_decide_message_missing_fields(self):
        """A decide message with no thought or action is still valid but empty."""
        registry = RemoteAgentRegistry(max_agents=5)
        raw = {"type": "decide"}
        result = registry.parse_decide_message(raw)
        assert result is not None
        assert result["thought"] == ""
        assert result["action"] == ""
        assert result["emotion"] == ""

    def test_build_act_result_message(self):
        registry = RemoteAgentRegistry(max_agents=5)
        msg = registry.build_act_result_message(success=True, details="Action executed")
        assert msg["type"] == "act_result"
        assert msg["success"] is True
        assert msg["details"] == "Action executed"


# ── Thread safety ────────────────────────────────────────────────


class TestThreadSafety:
    """Registry operations are thread-safe."""

    def test_concurrent_register_unregister(self):
        registry = RemoteAgentRegistry(max_agents=100)
        errors = []

        def register_batch(start: int, count: int):
            try:
                for i in range(start, start + count):
                    registry.register_agent(
                        agent_id=f"agent-{i}",
                        name=f"Bot {i}",
                        capabilities=["think"],
                    )
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_batch, args=(i * 10, 10))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        agents = registry.get_agents()
        assert len(agents) == 50
