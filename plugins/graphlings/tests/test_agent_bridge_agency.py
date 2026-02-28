# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for AgentBridge agency methods — feedback, pending-actions, world model, mood, objectives.

These close the loop between the Tritium-SC plugin and the Graphlings server,
turning deployed graphlings from reactive thinkers into full autonomous agents.

TDD: Written before implementation.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def _ok_response(data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.json.return_value = data
    return resp


def _error_response(status_code: int = 500):
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = False
    resp.json.return_value = {"error": "server error"}
    return resp


# ── Feedback ────────────────────────────────────────────────────


class TestFeedback:
    """AgentBridge.feedback() reports action success/failure to close the RL loop."""

    @patch("graphlings.agent_bridge.httpx")
    def test_feedback_sends_correct_json(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig

        mock_httpx.post.return_value = _ok_response({"recorded": True})

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.feedback(
            soul_id="twilight_001",
            action="attack()",
            success=True,
            outcome="defeated_goblin",
        )

        mock_httpx.post.assert_called_once()
        url = mock_httpx.post.call_args[0][0]
        assert "/deployment/twilight_001/feedback" in url
        body = mock_httpx.post.call_args[1]["json"]
        assert body["action"] == "attack()"
        assert body["success"] is True
        assert body["outcome"] == "defeated_goblin"
        assert result is not None

    @patch("graphlings.agent_bridge.httpx")
    def test_feedback_failure_sends_correct_json(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig

        mock_httpx.post.return_value = _ok_response({"recorded": True})

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.feedback(
            soul_id="sparkle_004",
            action='move_to(100, 200)',
            success=False,
            outcome="path_blocked",
        )

        body = mock_httpx.post.call_args[1]["json"]
        assert body["success"] is False
        assert body["outcome"] == "path_blocked"

    @patch("graphlings.agent_bridge.httpx")
    def test_feedback_returns_none_on_error(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig
        import httpx as real_httpx

        mock_httpx.post.side_effect = real_httpx.ConnectError("refused")
        mock_httpx.ConnectError = real_httpx.ConnectError

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.feedback("x", "observe()", True, "ok")
        assert result is None


# ── Pending Actions ─────────────────────────────────────────────


class TestPendingActions:
    """AgentBridge.get_pending_actions() polls server-generated autonomous actions."""

    @patch("graphlings.agent_bridge.httpx")
    def test_pending_actions_returns_list(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig

        mock_httpx.get.return_value = _ok_response({
            "actions": [
                {"action": "move_toward(forest_clearing)", "urgency": 0.4},
                {"action": "say('Hello!')", "urgency": 0.2},
            ]
        })

        bridge = AgentBridge(GraphlingsConfig())
        actions = bridge.get_pending_actions("twilight_001")

        mock_httpx.get.assert_called_once()
        url = mock_httpx.get.call_args[0][0]
        assert "/deployment/twilight_001/pending-actions" in url
        assert len(actions) == 2
        assert actions[0]["action"] == "move_toward(forest_clearing)"

    @patch("graphlings.agent_bridge.httpx")
    def test_pending_actions_empty(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig

        mock_httpx.get.return_value = _ok_response({"actions": []})

        bridge = AgentBridge(GraphlingsConfig())
        actions = bridge.get_pending_actions("twilight_001")
        assert actions == []

    @patch("graphlings.agent_bridge.httpx")
    def test_pending_actions_returns_empty_on_error(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig

        mock_httpx.get.return_value = _error_response(500)

        bridge = AgentBridge(GraphlingsConfig())
        actions = bridge.get_pending_actions("twilight_001")
        assert actions == []


# ── World Model Entity Reporting ────────────────────────────────


class TestReportEntity:
    """AgentBridge.report_entity() updates the graphling's mental model."""

    @patch("graphlings.agent_bridge.httpx")
    def test_report_entity_sends_correct_json(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig

        mock_httpx.post.return_value = _ok_response({"updated": True})

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.report_entity(
            soul_id="twilight_001",
            entity={
                "entity_id": "goblin_001",
                "entity_type": "hostile",
                "position": [100.0, 200.0],
                "last_seen": "now",
                "threat_level": 3,
            },
        )

        mock_httpx.post.assert_called_once()
        url = mock_httpx.post.call_args[0][0]
        assert "/deployment/twilight_001/world/entity" in url
        body = mock_httpx.post.call_args[1]["json"]
        assert body["entity_id"] == "goblin_001"
        assert body["entity_type"] == "hostile"
        assert result is not None

    @patch("graphlings.agent_bridge.httpx")
    def test_report_entity_returns_none_on_error(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig
        import httpx as real_httpx

        mock_httpx.post.side_effect = real_httpx.TimeoutException("timeout")
        mock_httpx.TimeoutException = real_httpx.TimeoutException

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.report_entity("x", {"entity_id": "y"})
        assert result is None


# ── Mood ────────────────────────────────────────────────────────


class TestGetMood:
    """AgentBridge.get_mood() checks graphling emotional state for adaptive behavior."""

    @patch("graphlings.agent_bridge.httpx")
    def test_get_mood_returns_mood_data(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig

        mock_httpx.get.return_value = _ok_response({
            "happiness": 0.7,
            "stress": 0.3,
            "engagement": 0.8,
            "confidence": 0.6,
        })

        bridge = AgentBridge(GraphlingsConfig())
        mood = bridge.get_mood("twilight_001")

        mock_httpx.get.assert_called_once()
        url = mock_httpx.get.call_args[0][0]
        assert "/deployment/twilight_001/mood" in url
        assert mood is not None
        assert mood["happiness"] == 0.7
        assert mood["stress"] == 0.3

    @patch("graphlings.agent_bridge.httpx")
    def test_get_mood_returns_none_on_error(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig

        mock_httpx.get.return_value = _error_response(404)

        bridge = AgentBridge(GraphlingsConfig())
        mood = bridge.get_mood("unknown_soul")
        assert mood is None


# ── Objectives ──────────────────────────────────────────────────


class TestSetObjective:
    """AgentBridge.set_objective() gives graphlings goals from game events."""

    @patch("graphlings.agent_bridge.httpx")
    def test_set_objective_sends_correct_json(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig

        mock_httpx.post.return_value = _ok_response({"id": "obj_123", "status": "PENDING"})

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.set_objective(
            soul_id="twilight_001",
            objective={
                "description": "Protect the village from night creatures",
                "priority": 0.9,
                "deadline_seconds": 3600,
            },
        )

        mock_httpx.post.assert_called_once()
        url = mock_httpx.post.call_args[0][0]
        assert "/deployment/twilight_001/objectives" in url
        body = mock_httpx.post.call_args[1]["json"]
        assert body["description"] == "Protect the village from night creatures"
        assert body["priority"] == 0.9
        assert result is not None
        assert result["id"] == "obj_123"

    @patch("graphlings.agent_bridge.httpx")
    def test_set_objective_returns_none_on_error(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig
        import httpx as real_httpx

        mock_httpx.post.side_effect = real_httpx.ConnectError("refused")
        mock_httpx.ConnectError = real_httpx.ConnectError

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.set_objective("x", {"description": "test"})
        assert result is None


# ── Error Handling Across All New Methods ───────────────────────


class TestAgencyErrorHandling:
    """All new agency methods handle errors gracefully — never crash."""

    @patch("graphlings.agent_bridge.httpx")
    def test_all_new_methods_survive_connection_error(self, mock_httpx):
        from graphlings.agent_bridge import AgentBridge
        from graphlings.config import GraphlingsConfig
        import httpx as real_httpx

        mock_httpx.post.side_effect = real_httpx.ConnectError("refused")
        mock_httpx.get.side_effect = real_httpx.ConnectError("refused")
        mock_httpx.ConnectError = real_httpx.ConnectError

        bridge = AgentBridge(GraphlingsConfig())

        # None of these should raise
        assert bridge.feedback("x", "a", True, "ok") is None
        assert bridge.get_pending_actions("x") == []
        assert bridge.report_entity("x", {}) is None
        assert bridge.get_mood("x") is None
        assert bridge.set_objective("x", {}) is None
