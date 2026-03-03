# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for AgentBridge — thin HTTP adapter to a creature server.

The AgentBridge makes raw httpx POST/GET calls to a configurable REST
server.  No SDK dependency — just raw HTTP calls.  Tests mock httpx
directly.
"""
from __future__ import annotations

import httpx
import pytest
from unittest.mock import MagicMock, patch

from graphlings.agent_bridge import AgentBridge
from graphlings.config import GraphlingsConfig


def _ok_response(data: dict, status_code: int = 200):
    """Create a mock httpx.Response with JSON body."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


def _error_response(status_code: int = 500):
    """Create a mock httpx.Response for errors."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"error": "error"}
    return resp


# ── Deploy ───────────────────────────────────────────────────────


class TestDeploy:
    """AgentBridge.deploy() POSTs to /deployment/deploy."""

    @patch("graphlings.agent_bridge.httpx.post")
    def test_deploy_sends_correct_json(self, mock_post):
        mock_post.return_value = _ok_response({
            "soul_id": "twilight_001", "deployment_id": "d1",
            "status": "deployed", "name": "Twilight",
        })

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.deploy("twilight_001", {
            "context": "npc_game",
            "service_name": "tritium-sc",
            "role_name": "pedestrian",
        })

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "/deployment/deploy" in url
        body = mock_post.call_args[1]["json"]
        assert body["soul_id"] == "twilight_001"
        assert body["config"]["context"] == "npc_game"
        assert result is not None
        assert result["soul_id"] == "twilight_001"

    @patch("graphlings.agent_bridge.httpx.post")
    def test_deploy_handles_server_error(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.deploy("twilight_001", {"context": "npc_game"})
        assert result is None


# ── Recall ───────────────────────────────────────────────────────


class TestRecall:
    """AgentBridge.recall() POSTs to /deployment/{soul_id}/recall."""

    @patch("graphlings.agent_bridge.httpx.post")
    def test_recall_sends_to_correct_endpoint(self, mock_post):
        mock_post.return_value = _ok_response({
            "soul_id": "twilight_001",
            "experiences_merged": 12,
            "snapshot_restored": False,
        })

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.recall("twilight_001", reason="game_ended")

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "/deployment/twilight_001/recall" in url
        body = mock_post.call_args[1]["json"]
        assert body["reason"] == "game_ended"
        assert result is not None
        assert result["experiences_merged"] == 12


# ── Think ────────────────────────────────────────────────────────


class TestThink:
    """AgentBridge.think() POSTs to /deployment/{soul_id}/think."""

    @patch("graphlings.agent_bridge.httpx.post")
    def test_think_sends_perception(self, mock_post):
        mock_post.return_value = _ok_response({
            "thought": "What was that noise?",
            "action": "say('Watch out!')",
            "emotion": "afraid",
            "layer": 3,
            "model_used": "qwen2.5:1.5b",
            "confidence": 0.75,
        })

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.think(
            soul_id="twilight_001",
            perception={"danger_level": 0.8, "nearby_entities": []},
            current_state="patrolling",
            available_actions=["move", "speak", "hide"],
            urgency=0.7,
        )

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "/deployment/twilight_001/think" in url
        body = mock_post.call_args[1]["json"]
        assert body["perception"]["danger_level"] == 0.8
        assert body["current_state"] == "patrolling"
        assert body["urgency"] == 0.7
        assert result is not None
        assert result["thought"] == "What was that noise?"
        assert result["action"] == "say('Watch out!')"

    @patch("graphlings.agent_bridge.httpx.post")
    def test_think_handles_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.think(
            soul_id="twilight_001",
            perception={},
            current_state="idle",
            available_actions=["wait"],
            urgency=0.0,
        )
        assert result is None

    @patch("graphlings.agent_bridge.httpx.post")
    def test_think_preferred_layer(self, mock_post):
        mock_post.return_value = _ok_response({"thought": "deep", "action": ""})

        bridge = AgentBridge(GraphlingsConfig())
        bridge.think("soul", {}, "idle", ["observe"], 0.1, preferred_layer=5)

        body = mock_post.call_args[1]["json"]
        assert body["preferred_layer"] == 5


# ── Heartbeat ────────────────────────────────────────────────────


class TestHeartbeat:
    """AgentBridge.heartbeat() POSTs to /deployment/{soul_id}/heartbeat."""

    @patch("graphlings.agent_bridge.httpx.post")
    def test_heartbeat_sends_to_correct_endpoint(self, mock_post):
        mock_post.return_value = _ok_response({"status": "active"})

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.heartbeat("twilight_001")

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "/deployment/twilight_001/heartbeat" in url
        assert result is not None
        assert result["status"] == "active"


# ── Experience ───────────────────────────────────────────────────


class TestExperience:
    """AgentBridge.record_experiences() POSTs experiences batch."""

    @patch("graphlings.agent_bridge.httpx.post")
    def test_experience_batch_sends_array(self, mock_post):
        mock_post.return_value = _ok_response({"count": 3})

        experiences = [
            {"subject": "battle", "predicate": "witnessed", "value": "explosion"},
            {"subject": "drone", "predicate": "saw", "value": "flying_overhead"},
            {"subject": "soldier", "predicate": "heard", "value": "shouting"},
        ]

        bridge = AgentBridge(GraphlingsConfig())
        count = bridge.record_experiences("twilight_001", experiences)

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "/deployment/twilight_001/experience" in url
        body = mock_post.call_args[1]["json"]
        assert len(body["experiences"]) == 3
        assert count == 3


# ── Status ───────────────────────────────────────────────────────


class TestStatus:
    """AgentBridge.get_status() and list_active()."""

    @patch("graphlings.agent_bridge.httpx.get")
    def test_get_status_returns_record(self, mock_get):
        mock_get.return_value = _ok_response({
            "soul_id": "twilight_001",
            "status": "deployed",
            "context": "npc_game",
        })

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.get_status("twilight_001")

        mock_get.assert_called_once()
        url = mock_get.call_args[0][0]
        assert "/deployment/twilight_001" in url
        assert result is not None
        assert result["soul_id"] == "twilight_001"

    @patch("graphlings.agent_bridge.httpx.get")
    def test_get_status_returns_none_for_unknown(self, mock_get):
        mock_get.return_value = _error_response(404)

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.get_status("unknown_soul")
        assert result is None

    @patch("graphlings.agent_bridge.httpx.get")
    def test_list_active_returns_array(self, mock_get):
        mock_get.return_value = _ok_response({
            "deployments": [
                {"soul_id": "twilight_001", "status": "deployed"},
                {"soul_id": "moonrise_002", "status": "deployed"},
            ]
        })

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.list_active()

        mock_get.assert_called_once()
        assert len(result) == 2


# ── Batch Deploy ─────────────────────────────────────────────────


class TestBatchDeploy:
    """AgentBridge.batch_deploy() POSTs to /deployment/batch/deploy."""

    @patch("graphlings.agent_bridge.httpx.post")
    def test_batch_deploy_sends_to_correct_endpoint(self, mock_post):
        mock_post.return_value = _ok_response({
            "deployed": [
                {"soul_id": "twilight_001", "name": "Twilight"},
                {"soul_id": "moonrise_002", "name": "Moonrise"},
            ],
            "count": 2,
        })

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.batch_deploy({"config": {"context": "npc_game"}, "max_agents": 5})

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "/deployment/batch/deploy" in url
        assert result is not None
        assert len(result["deployed"]) == 2

    @patch("graphlings.agent_bridge.httpx.post")
    def test_batch_deploy_returns_none_on_error(self, mock_post):
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.batch_deploy({"config": {}})
        assert result is None


# ── Batch Recall ─────────────────────────────────────────────────


class TestBatchRecall:
    """AgentBridge.batch_recall() POSTs to /deployment/batch/recall."""

    @patch("graphlings.agent_bridge.httpx.post")
    def test_batch_recall_sends_to_correct_endpoint(self, mock_post):
        mock_post.return_value = _ok_response({"recalled": 3})

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.batch_recall("tritium-sc", "victory")

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "/deployment/batch/recall" in url
        body = mock_post.call_args[1]["json"]
        assert body["service_name"] == "tritium-sc"
        assert body["reason"] == "victory"
        assert result is not None

    @patch("graphlings.agent_bridge.httpx.post")
    def test_batch_recall_returns_none_on_error(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")

        bridge = AgentBridge(GraphlingsConfig())
        result = bridge.batch_recall("tritium-sc", "defeat")
        assert result is None


# ── Error handling ───────────────────────────────────────────────


class TestErrorHandling:
    """AgentBridge handles connection errors gracefully."""

    @patch("graphlings.agent_bridge.httpx.post")
    def test_connection_error_doesnt_crash(self, mock_post):
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        bridge = AgentBridge(GraphlingsConfig())
        assert bridge.deploy("x", {}) is None
        assert bridge.recall("x") is None
        assert bridge.think("x", {}, "", [], 0.0) is None
        assert bridge.heartbeat("x") is None
        assert bridge.record_experiences("x", []) == 0

    def test_server_url_is_configurable(self):
        cfg = GraphlingsConfig()
        cfg.server_url = "http://localhost:9999"
        bridge = AgentBridge(cfg)
        assert bridge._base_url == "http://localhost:9999"
