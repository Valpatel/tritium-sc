# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for dry-run mode — AgentBridge returns stubs without external server."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from graphlings.config import GraphlingsConfig
from graphlings.agent_bridge import AgentBridge


class TestDryRunConfig:
    """Config should support dry_run flag."""

    def test_dry_run_default_false(self):
        config = GraphlingsConfig()
        assert config.dry_run is False

    def test_dry_run_from_env(self):
        with patch.dict("os.environ", {"GRAPHLINGS_DRY_RUN": "1"}):
            config = GraphlingsConfig.from_env()
            assert config.dry_run is True

    def test_dry_run_env_false(self):
        with patch.dict("os.environ", {"GRAPHLINGS_DRY_RUN": "0"}):
            config = GraphlingsConfig.from_env()
            assert config.dry_run is False


class TestAgentBridgeDryRun:
    """AgentBridge should return stub responses in dry-run mode."""

    def _make_bridge(self, dry_run=True):
        config = GraphlingsConfig(dry_run=dry_run)
        return AgentBridge(config)

    def test_deploy_returns_stub(self):
        bridge = self._make_bridge(dry_run=True)
        result = bridge.deploy("twilight", {"role_name": "Scout"})
        assert result is not None
        assert result.get("dry_run") is True

    def test_think_returns_stub(self):
        bridge = self._make_bridge(dry_run=True)
        result = bridge.think(
            soul_id="twilight",
            perception={"nearby_entities": [], "danger_level": 0.2},
            current_state="idle",
            available_actions=["say", "move_to", "observe"],
            urgency=0.3,
        )
        assert result is not None
        assert result.get("dry_run") is True

    def test_recall_dry_run(self):
        bridge = self._make_bridge(dry_run=True)
        result = bridge.recall("twilight", "test")
        assert result is not None
        assert result.get("dry_run") is True

    def test_heartbeat_dry_run(self):
        bridge = self._make_bridge(dry_run=True)
        result = bridge.heartbeat("twilight")
        assert result is not None

    def test_feedback_dry_run(self):
        bridge = self._make_bridge(dry_run=True)
        result = bridge.feedback("twilight", "say('hello')", True, "ok")
        assert result is not None

    def test_get_status_dry_run(self):
        bridge = self._make_bridge(dry_run=True)
        result = bridge.get_status("twilight")
        assert result is not None

    def test_dry_run_no_http_calls(self):
        """Dry-run mode must never make real HTTP calls."""
        bridge = self._make_bridge(dry_run=True)
        with patch("graphlings.agent_bridge.httpx") as mock_httpx:
            bridge.deploy("twilight", {})
            bridge.think("twilight", {}, "idle", ["say"], 0.3)
            bridge.recall("twilight", "test")
            bridge.heartbeat("twilight")
            bridge.feedback("twilight", "say", True, "ok")
            bridge.get_status("twilight")
            # No HTTP calls should have been made
            mock_httpx.post.assert_not_called()
            mock_httpx.get.assert_not_called()
