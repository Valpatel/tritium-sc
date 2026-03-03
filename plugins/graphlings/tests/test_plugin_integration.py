# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for the fully wired GraphlingsPlugin.

Tests the complete configure -> start -> stop lifecycle with all
sub-components connected.  AgentBridge uses dry-run mode — no real
server needed.
"""
from __future__ import annotations

import logging
import os
import queue
import time
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Enable dry-run mode so AgentBridge returns stubs instead of hitting the network
os.environ["GRAPHLINGS_DRY_RUN"] = "1"


# ── Fakes that mimic tritium-sc types ─────────────────────────────


@dataclass
class FakeTarget:
    target_id: str = ""
    name: str = ""
    alliance: str = "friendly"
    asset_type: str = "graphling"
    position: tuple = (0.0, 0.0)
    speed: float = 1.0
    battery: float = 1.0
    is_combatant: bool = False
    health: float = 50.0
    max_health: float = 50.0
    weapon_range: float = 0.0
    weapon_cooldown: float = 0.0
    weapon_damage: float = 0.0
    status: str = "idle"
    heading: float = 0.0
    waypoints: list = field(default_factory=list)


class FakeTracker:
    """Mimics TargetTracker."""

    def __init__(self):
        self._targets: dict[str, FakeTarget] = {}

    def get_all(self) -> list[FakeTarget]:
        return list(self._targets.values())

    def get_target(self, target_id: str):
        return self._targets.get(target_id)

    def add(self, target: FakeTarget):
        self._targets[target.target_id] = target

    def remove(self, target_id: str):
        self._targets.pop(target_id, None)


class FakeEventBus:
    """Mimics EventBus with subscribe/publish/unsubscribe."""

    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._published: list[dict] = []

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        if q in self._subscribers:
            self._subscribers.remove(q)

    def publish(self, event_type: str, data: dict = None):
        event = {"type": event_type, **(data or {})}
        self._published.append(event)
        for q in self._subscribers:
            q.put(event)


class FakeEngine:
    """Mimics SimulationEngine."""

    def __init__(self, tracker: FakeTracker):
        self._tracker = tracker

    def add_target(self, target):
        ft = FakeTarget(
            target_id=target.target_id,
            name=target.name,
            alliance=getattr(target, "alliance", "friendly"),
            asset_type=getattr(target, "asset_type", "graphling"),
            position=getattr(target, "position", (0.0, 0.0)),
            is_combatant=getattr(target, "is_combatant", False),
        )
        self._tracker.add(ft)

    def remove_target(self, target_id: str):
        self._tracker.remove(target_id)


class FakeApp:
    """Mimics FastAPI app for route registration."""

    def __init__(self):
        self._routes: dict = {}

    def get(self, path: str):
        def decorator(fn):
            self._routes[("GET", path)] = fn
            return fn
        return decorator

    def post(self, path: str):
        def decorator(fn):
            self._routes[("POST", path)] = fn
            return fn
        return decorator


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def tracker():
    return FakeTracker()

@pytest.fixture
def event_bus():
    return FakeEventBus()

@pytest.fixture
def engine(tracker):
    return FakeEngine(tracker)

@pytest.fixture
def app():
    return FakeApp()

@pytest.fixture
def plugin(tracker, event_bus, engine, app):
    """Create a fully wired plugin in dry-run mode."""
    from graphlings.plugin import GraphlingsPlugin

    p = GraphlingsPlugin()
    p._config.think_interval_seconds = 0.1
    p._config.dry_run = True

    ctx = MagicMock()
    ctx.event_bus = event_bus
    ctx.target_tracker = tracker
    ctx.simulation_engine = engine
    ctx.app = app
    ctx.logger = logging.getLogger("test.integration")

    p.configure(ctx)
    return p


# ── Integration Tests ─────────────────────────────────────────────


class TestPluginConfigure:
    """Test that configure() wires all components."""

    def test_configure_creates_bridge(self, plugin):
        assert plugin._bridge is not None

    def test_configure_creates_perception(self, plugin):
        assert plugin._perception is not None

    def test_configure_creates_motor(self, plugin):
        assert plugin._motor is not None

    def test_configure_creates_factory(self, plugin):
        assert plugin._factory is not None

    def test_configure_creates_lifecycle(self, plugin):
        assert plugin._lifecycle is not None


class TestPluginStartStop:
    """Test start/stop lifecycle."""

    def test_start_sets_running(self, plugin):
        plugin.start()
        try:
            assert plugin._running is True
        finally:
            plugin.stop()

    def test_stop_clears_running(self, plugin):
        plugin.start()
        plugin.stop()
        assert plugin._running is False

    def test_start_creates_agent_thread(self, plugin):
        plugin.start()
        try:
            assert plugin._agent_thread is not None
            assert plugin._agent_thread.is_alive()
        finally:
            plugin.stop()


class TestDeployGraphling:
    """Test deploying graphlings via the plugin in dry-run mode."""

    def test_deploy_tracks_soul_id(self, plugin):
        ok = plugin.deploy_graphling("twilight_001", "City Guard")
        assert ok is True
        assert "twilight_001" in plugin._deployed

    def test_deploy_position_in_deployed_info(self, plugin):
        plugin.deploy_graphling("twilight_001", "Guard", spawn_point="marketplace")
        info = plugin._deployed["twilight_001"]
        assert "position" in info


class TestRecallAgent:
    """Test recalling deployed graphlings."""

    def test_recall_removes_from_deployed(self, plugin):
        plugin.deploy_graphling("twilight_001", "Guard")
        plugin._recall_agent("twilight_001", "test_recall")
        assert "twilight_001" not in plugin._deployed


class TestAgentLoop:
    """Test the background agent loop."""

    def test_loop_runs_without_crash(self, plugin):
        """Agent loop runs for a short time without error."""
        plugin.deploy_graphling("twilight_001", "Guard")
        plugin.start()
        time.sleep(0.3)
        plugin.stop()
        # If we get here without exception, the loop is working

    def test_stop_recalls_all(self, plugin):
        """Stopping the plugin recalls all deployed graphlings."""
        plugin.deploy_graphling("soul_1", "Guard")
        plugin.deploy_graphling("soul_2", "Merchant")
        plugin.start()
        time.sleep(0.1)
        plugin.stop()
        assert len(plugin._deployed) == 0


class TestEventHandling:
    """Test game event processing."""

    def test_event_feeds_perception(self, plugin):
        """Events are recorded in PerceptionEngine for recent_events."""
        plugin.deploy_graphling("twilight_001", "Guard")
        plugin._handle_event({"type": "explosion", "description": "big boom"})
        # Perception engine should have the event
        assert "explosion" in list(plugin._perception._recent_events)
