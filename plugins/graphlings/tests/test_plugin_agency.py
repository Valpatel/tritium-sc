# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for plugin agency wiring — feedback loop, pending actions, world model, mood.

These test that the GraphlingsPlugin correctly uses the new AgentBridge agency
methods during its think cycle and background loop.

TDD: Written before the plugin wiring implementation.
"""
from __future__ import annotations

import time
import threading
import queue
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ── Fixtures ─────────────────────────────────────────────────────


class FakeTarget:
    """Minimal SimulationTarget mock."""

    def __init__(self, target_id="graphling_tw_001", position=(100.0, 200.0)):
        self.target_id = target_id
        self.position = list(position)
        self.heading = 0.0
        self.status = "idle"
        self.waypoints = []
        self.name = "Twilight"
        self.alliance = "friendly"
        self.asset_type = "graphling"


class FakeTracker:
    """Minimal TargetTracker mock."""

    def __init__(self):
        self._targets: dict[str, FakeTarget] = {}

    def add(self, target: FakeTarget) -> None:
        self._targets[target.target_id] = target

    def get_target(self, target_id: str):
        return self._targets.get(target_id)

    def get_all(self):
        return list(self._targets.values())


class FakeEventBus:
    """Minimal EventBus mock."""

    def __init__(self):
        self.published: list[tuple[str, dict]] = []
        self._queues: list[queue.Queue] = []

    def publish(self, event_type: str, data: dict) -> None:
        self.published.append((event_type, data))
        for q in self._queues:
            q.put({"type": event_type, **data})

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        if q in self._queues:
            self._queues.remove(q)


def _make_plugin():
    """Create a GraphlingsPlugin with mocked subsystems."""
    from graphlings.plugin import GraphlingsPlugin
    from graphlings.config import GraphlingsConfig

    plugin = GraphlingsPlugin()

    tracker = FakeTracker()
    event_bus = FakeEventBus()

    # Inject a fake PluginContext
    ctx = MagicMock()
    ctx.event_bus = event_bus
    ctx.target_tracker = tracker
    ctx.simulation_engine = MagicMock()
    ctx.app = None  # skip route registration
    ctx.logger = MagicMock()

    plugin.configure(ctx)
    return plugin, tracker, event_bus


# ── Feedback Loop Tests ──────────────────────────────────────────


class TestFeedbackLoop:
    """Plugin reports action success/failure after motor execution."""

    def test_think_cycle_reports_feedback_on_success(self):
        """After motor.execute() succeeds, plugin calls bridge.feedback(success=True)."""
        plugin, tracker, _ = _make_plugin()

        # Set up a deployed graphling
        target = FakeTarget("graphling_tw_001", (100.0, 200.0))
        tracker.add(target)

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._last_think["twilight_001"] = 0.0
        plugin._init_compute_tracking("twilight_001")

        # Mock bridge.think to return an action
        plugin._bridge.think = MagicMock(return_value={
            "thought": "I see danger",
            "action": 'say("Watch out!")',
            "emotion": "afraid",
            "consciousness_layer": 3,
            "model_used": "qwen2.5:1.5b",
            "confidence": 0.8,
        })
        plugin._bridge.feedback = MagicMock(return_value={"recorded": True})

        # Motor will succeed (say action works)
        plugin._think_cycle("twilight_001")

        # Verify feedback was called
        plugin._bridge.feedback.assert_called_once()
        call_args = plugin._bridge.feedback.call_args
        assert call_args[1]["soul_id"] == "twilight_001" or call_args[0][0] == "twilight_001"
        # Check success=True was passed
        if call_args[1]:
            assert call_args[1].get("success", call_args[0][2] if len(call_args[0]) > 2 else None) is True
        else:
            assert call_args[0][2] is True  # positional: soul_id, action, success

    def test_think_cycle_reports_feedback_on_failure(self):
        """After motor.execute() fails, plugin calls bridge.feedback(success=False)."""
        plugin, tracker, _ = _make_plugin()

        target = FakeTarget("graphling_tw_001", (100.0, 200.0))
        tracker.add(target)

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._last_think["twilight_001"] = 0.0
        plugin._init_compute_tracking("twilight_001")

        # Return an action that will fail (move_to with no params)
        plugin._bridge.think = MagicMock(return_value={
            "thought": "Moving",
            "action": "move_to()",  # No coordinates -> fails
            "emotion": "neutral",
            "consciousness_layer": 2,
            "model_used": "qwen2.5:0.5b",
            "confidence": 0.5,
        })
        plugin._bridge.feedback = MagicMock(return_value={"recorded": True})

        plugin._think_cycle("twilight_001")

        # Feedback should report failure
        plugin._bridge.feedback.assert_called_once()
        args = plugin._bridge.feedback.call_args
        # success should be False
        if len(args[0]) > 2:
            assert args[0][2] is False
        else:
            assert args[1]["success"] is False

    def test_no_feedback_when_no_action(self):
        """If think returns no action, no feedback is sent."""
        plugin, tracker, _ = _make_plugin()

        target = FakeTarget("graphling_tw_001", (100.0, 200.0))
        tracker.add(target)

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._last_think["twilight_001"] = 0.0
        plugin._init_compute_tracking("twilight_001")

        # Return empty action
        plugin._bridge.think = MagicMock(return_value={
            "thought": "Just thinking",
            "action": "",
            "emotion": "calm",
            "consciousness_layer": 2,
            "model_used": "qwen2.5:0.5b",
            "confidence": 0.5,
        })
        plugin._bridge.feedback = MagicMock()

        plugin._think_cycle("twilight_001")

        # No feedback for empty actions
        plugin._bridge.feedback.assert_not_called()


# ── Pending Actions Tests ────────────────────────────────────────


class TestPendingActions:
    """Plugin polls and executes server-generated autonomous actions."""

    def test_pending_actions_are_polled_in_loop(self):
        """Background loop polls get_pending_actions for each deployed graphling."""
        plugin, tracker, _ = _make_plugin()

        target = FakeTarget("graphling_tw_001", (100.0, 200.0))
        tracker.add(target)

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._init_compute_tracking("twilight_001")

        # Mock pending actions
        plugin._bridge.get_pending_actions = MagicMock(return_value=[
            {"action": 'say("I want to explore")', "urgency": 0.3},
        ])
        plugin._bridge.feedback = MagicMock(return_value={"recorded": True})

        # Call the pending actions poll directly
        plugin._poll_pending_actions()

        plugin._bridge.get_pending_actions.assert_called_once_with("twilight_001")

    def test_pending_actions_are_executed(self):
        """Pending actions from server are executed via MotorOutput."""
        plugin, tracker, event_bus = _make_plugin()

        target = FakeTarget("graphling_tw_001", (100.0, 200.0))
        tracker.add(target)

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._init_compute_tracking("twilight_001")

        plugin._bridge.get_pending_actions = MagicMock(return_value=[
            {"action": 'say("Hello friend!")', "urgency": 0.2},
        ])
        plugin._bridge.feedback = MagicMock(return_value={"recorded": True})

        plugin._poll_pending_actions()

        # Check that motor executed the action (say publishes npc_thought)
        found = any(
            ev_type == "npc_thought" and data.get("text") == "Hello friend!"
            for ev_type, data in event_bus.published
        )
        assert found, f"Expected npc_thought with 'Hello friend!' in {event_bus.published}"

    def test_empty_pending_actions_no_crash(self):
        """Empty pending actions list is handled gracefully."""
        plugin, tracker, _ = _make_plugin()

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._init_compute_tracking("twilight_001")

        plugin._bridge.get_pending_actions = MagicMock(return_value=[])

        # Should not raise
        plugin._poll_pending_actions()


# ── World Model Tests ────────────────────────────────────────────


class TestWorldModel:
    """Plugin reports perceived entities to build graphling mental models."""

    def test_entities_reported_after_think(self):
        """After building perception, significant entities are reported to server."""
        plugin, tracker, _ = _make_plugin()

        # Add a hostile entity nearby
        hostile = FakeTarget("enemy_001", (110.0, 200.0))
        hostile.alliance = "hostile"
        hostile.asset_type = "drone"
        hostile.name = "Evil Drone"
        tracker.add(hostile)

        target = FakeTarget("graphling_tw_001", (100.0, 200.0))
        tracker.add(target)

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._last_think["twilight_001"] = 0.0
        plugin._init_compute_tracking("twilight_001")

        # Mock bridge methods
        plugin._bridge.think = MagicMock(return_value={
            "thought": "Danger", "action": "", "emotion": "alert",
            "consciousness_layer": 2, "model_used": "qwen2.5:0.5b", "confidence": 0.7,
        })
        plugin._bridge.report_entity = MagicMock(return_value={"updated": True})
        plugin._bridge.feedback = MagicMock()

        plugin._think_cycle("twilight_001")

        # Verify entities were reported (hostile entity should be reported)
        plugin._bridge.report_entity.assert_called()
        call_args = plugin._bridge.report_entity.call_args
        entity_data = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["entity"]
        assert entity_data["entity_id"] == "enemy_001"

    def test_no_entity_report_when_none_nearby(self):
        """No entity reports when perception finds nothing."""
        plugin, tracker, _ = _make_plugin()

        target = FakeTarget("graphling_tw_001", (100.0, 200.0))
        tracker.add(target)

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._last_think["twilight_001"] = 0.0
        plugin._init_compute_tracking("twilight_001")

        plugin._bridge.think = MagicMock(return_value={
            "thought": "Quiet", "action": "", "emotion": "calm",
            "consciousness_layer": 2, "model_used": "qwen2.5:0.5b", "confidence": 0.5,
        })
        plugin._bridge.report_entity = MagicMock()
        plugin._bridge.feedback = MagicMock()

        plugin._think_cycle("twilight_001")

        plugin._bridge.report_entity.assert_not_called()


# ── Mood Check Tests ─────────────────────────────────────────────


class TestMoodCheck:
    """Plugin checks mood periodically and auto-recalls stressed graphlings."""

    def test_mood_check_detects_high_stress(self):
        """When stress > 0.8, graphling should be flagged for recall."""
        plugin, tracker, _ = _make_plugin()

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._init_compute_tracking("twilight_001")

        plugin._bridge.get_mood = MagicMock(return_value={
            "happiness": 0.2,
            "stress": 0.85,
            "engagement": 0.3,
            "confidence": 0.2,
        })
        plugin._bridge.recall = MagicMock(return_value={"recalled": True})
        plugin._bridge.feedback = MagicMock()

        # Spy on _recall_agent
        original_recall = plugin._recall_agent
        recall_called = []
        def spy_recall(soul_id, reason=""):
            recall_called.append((soul_id, reason))
            return original_recall(soul_id, reason)
        plugin._recall_agent = spy_recall

        plugin._check_moods()

        # Should have triggered recall for stressed graphling
        assert len(recall_called) == 1
        assert recall_called[0][0] == "twilight_001"
        assert "stress" in recall_called[0][1]

    def test_mood_check_happy_graphling_stays(self):
        """Happy, unstressed graphlings are not recalled."""
        plugin, tracker, _ = _make_plugin()

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._init_compute_tracking("twilight_001")

        plugin._bridge.get_mood = MagicMock(return_value={
            "happiness": 0.8,
            "stress": 0.1,
            "engagement": 0.9,
            "confidence": 0.7,
        })

        plugin._check_moods()

        # Graphling should still be deployed
        assert "twilight_001" in plugin._deployed

    def test_mood_check_handles_server_error(self):
        """If mood endpoint fails, graphling stays deployed."""
        plugin, tracker, _ = _make_plugin()

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._init_compute_tracking("twilight_001")

        plugin._bridge.get_mood = MagicMock(return_value=None)

        plugin._check_moods()

        assert "twilight_001" in plugin._deployed


# ── Game Event Objectives Tests ──────────────────────────────────


class TestGameEventObjectives:
    """Plugin sets objectives based on game events."""

    def test_threat_event_sets_defensive_objective(self):
        """When enemy spawns nearby, plugin sets a defensive objective."""
        plugin, tracker, event_bus = _make_plugin()

        target = FakeTarget("graphling_tw_001", (100.0, 200.0))
        tracker.add(target)

        plugin._deployed["twilight_001"] = {
            "target_id": "graphling_tw_001",
            "role_name": "Guard",
            "position": (100.0, 200.0),
            "deploy_config": {},
            "personality": None,
        }
        plugin._init_compute_tracking("twilight_001")

        plugin._bridge.set_objective = MagicMock(return_value={"id": "obj_1"})

        # Simulate a threat event
        plugin._handle_event({
            "type": "threat_detected",
            "threat_level": "high",
            "position": [120.0, 210.0],
        })

        # Should have set objective for deployed combatant graphlings
        plugin._bridge.set_objective.assert_called()
        call_args = plugin._bridge.set_objective.call_args
        objective = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["objective"]
        assert "threat" in objective["description"].lower() or "defend" in objective["description"].lower()
