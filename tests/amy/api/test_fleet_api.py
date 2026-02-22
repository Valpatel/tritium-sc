"""Tests for fleet API endpoints — /api/amy/fleet/*.

Tests the fleet status, model listing, and action listing endpoints
with both fleet-enabled and fleet-disabled Amy configurations.
"""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import MagicMock, patch


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.mark.unit
class TestFleetStatusEndpoint:
    """GET /api/amy/fleet/status — fleet host discovery results."""

    def test_no_amy_returns_503(self):
        from amy.router import fleet_status
        request = MagicMock()
        request.app.state = MagicMock(spec=[])  # No amy attribute
        result = _run(fleet_status(request))
        assert result.status_code == 503

    def test_no_router_returns_disabled(self):
        from amy.router import fleet_status
        request = MagicMock()
        amy_mock = MagicMock()
        amy_mock.model_router = None
        request.app.state.amy = amy_mock
        result = _run(fleet_status(request))
        assert result["fleet_enabled"] is False
        assert result["hosts"] == []

    def test_with_router_returns_enabled(self):
        from amy.router import fleet_status
        from amy.inference.model_router import ModelRouter, ModelProfile
        request = MagicMock()
        amy_mock = MagicMock()
        router = ModelRouter.from_static()
        amy_mock.model_router = router
        request.app.state.amy = amy_mock
        result = _run(fleet_status(request))
        assert result["fleet_enabled"] is True
        assert isinstance(result["profiles"], list)

    def test_with_fleet_hosts(self):
        from amy.router import fleet_status
        from amy.inference.model_router import ModelRouter
        from amy.inference.fleet import FleetHost
        request = MagicMock()
        amy_mock = MagicMock()
        router = ModelRouter.from_static()
        mock_fleet = MagicMock()
        mock_fleet.hosts = [
            FleetHost(url="http://host1:11434", name="host1", models=["gemma3:4b"]),
        ]
        router._fleet = mock_fleet
        amy_mock.model_router = router
        request.app.state.amy = amy_mock
        result = _run(fleet_status(request))
        assert len(result["hosts"]) == 1
        assert result["hosts"][0]["name"] == "host1"


@pytest.mark.unit
class TestFleetModelsEndpoint:
    """GET /api/amy/fleet/models — all models across fleet."""

    def test_no_amy_returns_503(self):
        from amy.router import fleet_models
        request = MagicMock()
        request.app.state = MagicMock(spec=[])
        result = _run(fleet_models(request))
        assert result.status_code == 503

    def test_no_router_returns_static_models(self):
        from amy.router import fleet_models
        request = MagicMock()
        amy_mock = MagicMock()
        amy_mock.model_router = None
        amy_mock._chat_model = "gemma3:4b"
        amy_mock.deep_model = "llava:7b"
        request.app.state.amy = amy_mock
        result = _run(fleet_models(request))
        assert len(result["models"]) == 2

    def test_with_fleet_models(self):
        from amy.router import fleet_models
        from amy.inference.model_router import ModelRouter
        from amy.inference.fleet import FleetHost
        request = MagicMock()
        amy_mock = MagicMock()
        router = ModelRouter.from_static()
        mock_fleet = MagicMock()
        mock_fleet.hosts = [
            FleetHost(url="http://h1:11434", name="h1", models=["gemma3:4b", "llava:7b"]),
            FleetHost(url="http://h2:11434", name="h2", models=["gemma3:4b", "qwen2.5:7b"]),
        ]
        router._fleet = mock_fleet
        amy_mock.model_router = router
        request.app.state.amy = amy_mock
        result = _run(fleet_models(request))
        names = {m["name"] for m in result["models"]}
        assert "gemma3:4b" in names
        assert "llava:7b" in names
        # gemma3:4b should show 2 hosts
        for m in result["models"]:
            if m["name"] == "gemma3:4b":
                assert len(m["hosts"]) == 2


@pytest.mark.unit
class TestFleetActionsEndpoint:
    """GET /api/amy/fleet/actions — all registered Lua actions."""

    def test_returns_core_actions(self):
        from amy.router import fleet_actions
        request = MagicMock()
        request.app.state.amy = MagicMock()
        result = _run(fleet_actions(request))
        assert "actions" in result
        assert result["count"] > 0
        action_names = {a["name"] for a in result["actions"]}
        assert "think" in action_names
        assert "say" in action_names
        assert "dispatch" in action_names

    def test_actions_have_required_fields(self):
        from amy.router import fleet_actions
        request = MagicMock()
        request.app.state.amy = MagicMock()
        result = _run(fleet_actions(request))
        for action in result["actions"]:
            assert "name" in action
            assert "min_params" in action
            assert "max_params" in action
            assert "source" in action
