# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for AgentBridge agency methods — feedback, objectives.

Tests the thin HTTP bridge interface for feedback and objective setting.
Mocks httpx directly (no SDK dependency).
"""
from __future__ import annotations

import httpx
import pytest
from unittest.mock import MagicMock, patch

from graphlings.agent_bridge import AgentBridge
from graphlings.config import GraphlingsConfig


def _ok_response(data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


# ── Feedback ────────────────────────────────────────────────────


class TestFeedback:
    """AgentBridge.feedback() reports action success/failure to close the RL loop."""

    @patch("graphlings.agent_bridge.httpx.post")
    def test_feedback_sends_correct_json(self, mock_post):
        mock_post.return_value = _ok_response({"recorded": True})

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.feedback(
            soul_id="twilight_001",
            action="attack()",
            success=True,
            outcome="defeated_goblin",
        )

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "/deployment/twilight_001/feedback" in url
        body = mock_post.call_args[1]["json"]
        assert body["action"] == "attack()"
        assert body["success"] is True
        assert body["outcome"] == "defeated_goblin"
        assert result is not None

    @patch("graphlings.agent_bridge.httpx.post")
    def test_feedback_failure_sends_correct_json(self, mock_post):
        mock_post.return_value = _ok_response({"recorded": True})

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.feedback(
            soul_id="sparkle_004",
            action='move_to(100, 200)',
            success=False,
            outcome="path_blocked",
        )

        body = mock_post.call_args[1]["json"]
        assert body["success"] is False
        assert body["outcome"] == "path_blocked"

    @patch("graphlings.agent_bridge.httpx.post")
    def test_feedback_returns_none_on_error(self, mock_post):
        mock_post.side_effect = httpx.ConnectError("refused")

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.feedback("x", "observe()", True, "ok")
        assert result is None


# ── Objectives ──────────────────────────────────────────────────


class TestSetObjective:
    """AgentBridge.set_objective() gives graphlings goals from game events."""

    @patch("graphlings.agent_bridge.httpx.post")
    def test_set_objective_sends_correct_json(self, mock_post):
        mock_post.return_value = _ok_response({"id": "obj_123", "status": "PENDING"})

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.set_objective(
            soul_id="twilight_001",
            description="Protect the village from night creatures",
            priority=0.9,
            deadline_seconds=3600,
        )

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "/deployment/twilight_001/objective" in url
        body = mock_post.call_args[1]["json"]
        assert body["description"] == "Protect the village from night creatures"
        assert body["priority"] == 0.9
        assert body["deadline_seconds"] == 3600
        assert result is not None

    @patch("graphlings.agent_bridge.httpx.post")
    def test_set_objective_returns_none_on_error(self, mock_post):
        mock_post.side_effect = httpx.ConnectError("refused")

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.set_objective("x", "test")
        assert result is None


# ── Error Handling Across All Agency Methods ───────────────────


class TestAgencyErrorHandling:
    """All agency methods handle errors gracefully -- never crash."""

    @patch("graphlings.agent_bridge.httpx.get")
    @patch("graphlings.agent_bridge.httpx.post")
    def test_all_methods_survive_connection_error(self, mock_post, mock_get):
        mock_post.side_effect = httpx.ConnectError("refused")
        mock_get.side_effect = httpx.ConnectError("refused")

        bridge = AgentBridge(GraphlingsConfig())

        # None of these should raise
        assert bridge.feedback("x", "a", True, "ok") is None
        assert bridge.get_status("x") is None
        assert bridge.set_objective("x", "test") is None
        assert bridge.record_experiences("x", []) == 0
