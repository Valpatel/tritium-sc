# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for SimulationLifecycleHandler — auto deploy/recall on game state.

TDD: Written before implementation.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call


def _make_mock_bridge(deployed=None):
    """Create a mock AgentBridge with batch_deploy/batch_recall methods."""
    bridge = MagicMock()
    bridge.batch_deploy.return_value = deployed or {
        "deployed": [
            {"soul_id": "twilight_001", "name": "Twilight", "role": "drone_operator"},
            {"soul_id": "moonrise_002", "name": "Moonrise", "role": "civilian"},
            {"soul_id": "dewdrop_003", "name": "Dewdrop", "role": "civilian"},
        ],
        "count": 3,
    }
    bridge.batch_recall.return_value = {"recalled": 3}
    return bridge


def _make_mock_factory():
    """Create a mock EntityFactory with spawn/despawn_all."""
    factory = MagicMock()
    return factory


def _make_config():
    """Create a GraphlingsConfig with defaults."""
    from graphlings.config import GraphlingsConfig

    return GraphlingsConfig()


def _make_event(state: str) -> dict:
    """Create a game_state_change event dict."""
    return {"type": "game_state_change", "data": {"state": state}}


# ── Deploy on countdown ──────────────────────────────────────────


class TestCountdownDeploy:
    """Countdown state triggers batch deploy of all graphlings."""

    def test_countdown_triggers_batch_deploy(self):
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))

        bridge.batch_deploy.assert_called_once()

    def test_countdown_spawns_all_deployed_graphlings(self):
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))

        assert factory.spawn.call_count == 3

    def test_no_double_deploy_on_repeated_countdown(self):
        """Sending countdown twice must NOT re-deploy."""
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))
        handler.on_game_state_change(_make_event("countdown"))

        # batch_deploy called exactly once
        bridge.batch_deploy.assert_called_once()


# ── Role assignment ──────────────────────────────────────────────


class TestRoleAssignment:
    """First graphling gets combatant role (drone_operator), rest are civilians."""

    def test_first_graphling_is_combatant(self):
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))

        # First spawn call should have is_combatant=True
        first_call = factory.spawn.call_args_list[0]
        assert first_call[1].get("is_combatant") is True or (
            len(first_call[0]) > 3 and first_call[0][3] is True
        )

    def test_remaining_graphlings_are_non_combatant(self):
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))

        # Second and third should NOT be combatants
        for spawn_call in factory.spawn.call_args_list[1:]:
            is_combatant = spawn_call[1].get("is_combatant", False)
            assert is_combatant is False


# ── Recall on game over states ───────────────────────────────────


class TestRecallOnGameOver:
    """Game-over states trigger batch recall of all graphlings."""

    def test_victory_triggers_batch_recall(self):
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        # Deploy first
        handler.on_game_state_change(_make_event("countdown"))
        # Then victory
        handler.on_game_state_change(_make_event("victory"))

        bridge.batch_recall.assert_called_once_with(
            config.default_service_name, "victory"
        )
        factory.despawn_all.assert_called_once()

    def test_defeat_triggers_batch_recall(self):
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))
        handler.on_game_state_change(_make_event("defeat"))

        bridge.batch_recall.assert_called_once_with(
            config.default_service_name, "defeat"
        )

    def test_game_over_triggers_batch_recall(self):
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))
        handler.on_game_state_change(_make_event("game_over"))

        bridge.batch_recall.assert_called_once_with(
            config.default_service_name, "game_over"
        )

    def test_recall_resets_deployed_flag_allowing_redeploy(self):
        """After recall, a new countdown should trigger a fresh deploy."""
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))
        handler.on_game_state_change(_make_event("victory"))
        handler.on_game_state_change(_make_event("countdown"))

        # batch_deploy should have been called twice
        assert bridge.batch_deploy.call_count == 2


# ── Graceful degradation ─────────────────────────────────────────


class TestGracefulDegradation:
    """Handler doesn't crash when things go wrong."""

    def test_server_unreachable_doesnt_crash(self):
        """batch_deploy returning None should not raise."""
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        bridge.batch_deploy.return_value = None
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        # Should not raise
        handler.on_game_state_change(_make_event("countdown"))

        # No spawns since deploy failed
        factory.spawn.assert_not_called()

    def test_recall_with_nothing_deployed_is_noop(self):
        """Recalling before deploying should be a safe no-op."""
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        # Recall without prior deploy
        handler.on_game_state_change(_make_event("victory"))

        bridge.batch_recall.assert_not_called()
        factory.despawn_all.assert_not_called()

    def test_unknown_state_is_ignored(self):
        """States other than countdown/victory/defeat/game_over are ignored."""
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("warmup"))

        bridge.batch_deploy.assert_not_called()
        bridge.batch_recall.assert_not_called()

    def test_empty_deployed_list_is_handled(self):
        """Server returns empty deployed list -- no spawns, no crash."""
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge(deployed={"deployed": [], "count": 0})
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))

        factory.spawn.assert_not_called()
        # Still marked as deployed (deploy was successful, just no agents available)
        assert handler._deployed is True


# ── Deploy config ────────────────────────────────────────────────


class TestDeployConfig:
    """batch_deploy is called with correct config from GraphlingsConfig."""

    def test_deploy_sends_config_from_settings(self):
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))

        call_args = bridge.batch_deploy.call_args[0][0]
        inner = call_args["config"]
        assert inner["context"] == config.default_context
        assert inner["service_name"] == config.default_service_name
        assert inner["consciousness_layer_min"] == config.default_consciousness_min
        assert inner["consciousness_layer_max"] == config.default_consciousness_max
        assert call_args["max_agents"] == config.max_agents

    def test_deploy_config_includes_allowed_actions(self):
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))

        call_args = bridge.batch_deploy.call_args[0][0]
        actions = call_args["config"]["allowed_actions"]
        assert "say" in actions
        assert "move_to" in actions
        assert "observe" in actions
        assert "flee" in actions
        assert "emote" in actions


# ── Spawn points ─────────────────────────────────────────────────


class TestSpawnPoints:
    """Graphlings are assigned spawn points from config."""

    def test_spawn_points_cycle_through_config(self):
        from graphlings.lifecycle import SimulationLifecycleHandler

        bridge = _make_mock_bridge()
        factory = _make_mock_factory()
        config = _make_config()
        handler = SimulationLifecycleHandler(bridge, factory, config)

        handler.on_game_state_change(_make_event("countdown"))

        # Each spawn should get a position from config.spawn_points
        points = list(config.spawn_points.values())
        for i, spawn_call in enumerate(factory.spawn.call_args_list):
            position = spawn_call[0][2]  # 3rd positional arg
            expected = points[i % len(points)]
            assert position == expected
