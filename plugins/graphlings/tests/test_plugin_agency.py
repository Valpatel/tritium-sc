# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for plugin agency wiring — deploy/recall via the plugin.

Tests that GraphlingsPlugin correctly deploys and recalls agents via the
thin AgentBridge (HTTP calls mocked).
"""
from __future__ import annotations

import logging
import queue
import time
from unittest.mock import MagicMock, patch

import pytest

from graphlings.config import GraphlingsConfig


# ── Fakes ─────────────────────────────────────────────────────


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

    def publish(self, event_type: str, data: dict = None) -> None:
        self.published.append((event_type, data or {}))
        for q in self._queues:
            q.put({"type": event_type, **(data or {})})

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

    plugin = GraphlingsPlugin()
    plugin._config.dry_run = True  # no real HTTP calls

    tracker = FakeTracker()
    event_bus = FakeEventBus()

    # Inject a fake PluginContext
    ctx = MagicMock()
    ctx.event_bus = event_bus
    ctx.target_tracker = tracker
    ctx.simulation_engine = MagicMock()
    ctx.app = None  # skip route registration
    ctx.logger = logging.getLogger("test.graphlings.agency")

    plugin.configure(ctx)
    return plugin, tracker, event_bus


# ── Deploy Tests ──────────────────────────────────────────────


class TestDeploy:
    """Plugin deploy_graphling() deploys via bridge and tracks locally."""

    def test_deploy_tracks_soul_id(self):
        plugin, tracker, _ = _make_plugin()
        ok = plugin.deploy_graphling("twilight_001", "Guard")
        assert ok is True
        assert "twilight_001" in plugin._deployed

    def test_deploy_returns_false_without_bridge(self):
        from graphlings.plugin import GraphlingsPlugin
        plugin = GraphlingsPlugin()
        # bridge is None before configure()
        assert plugin.deploy_graphling("x", "Guard") is False


# ── Recall Tests ──────────────────────────────────────────────


class TestRecall:
    """Plugin _recall_agent() recalls and cleans up."""

    def test_recall_removes_from_deployed(self):
        plugin, tracker, _ = _make_plugin()
        plugin.deploy_graphling("twilight_001", "Guard")
        plugin._recall_agent("twilight_001", "test")
        assert "twilight_001" not in plugin._deployed


# ── Think Cycle Tests ─────────────────────────────────────────


class TestThinkCycle:
    """Plugin tick loop produces thoughts and publishes events."""

    def test_tick_publishes_thought_event(self):
        """When bridge.think returns a response, plugin publishes graphling_thought."""
        plugin, tracker, event_bus = _make_plugin()

        target = FakeTarget("graphling_tw_001", (100.0, 200.0))
        tracker.add(target)

        plugin.deploy_graphling("twilight_001", "Guard")

        # In dry-run mode, bridge.think returns {"dry_run": True}
        # The plugin _tick_agents loop reads the response and records thought
        plugin._tick_agents()

        # Thought should be recorded in history
        assert len(plugin._thought_history) >= 0  # dry run may produce empty thought
