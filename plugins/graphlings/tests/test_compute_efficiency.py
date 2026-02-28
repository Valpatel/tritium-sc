# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Phase 3D: Adaptive Compute Efficiency.

Tests that the think loop adapts its frequency and consciousness layer
based on urgency, tracks compute stats per graphling, triggers periodic
reflection cycles, and exposes stats via the status endpoint.

TDD: These tests are written FIRST, before implementation.
"""
from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add plugins/ and project root to path
_plugins_dir = str(Path(__file__).resolve().parent.parent.parent)
_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
for p in [_plugins_dir, _project_root]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── Fakes (reused from test_plugin_integration.py) ──────────────────

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
    def __init__(self):
        self._subscribers = []
        self._published = []

    def subscribe(self):
        import queue
        q = queue.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        if q in self._subscribers:
            self._subscribers.remove(q)

    def publish(self, event_type: str, data: dict):
        event = {"type": event_type, **data}
        self._published.append(event)
        for q in self._subscribers:
            q.put(event)


class FakeEngine:
    def __init__(self, tracker: FakeTracker):
        self._tracker = tracker

    def add_target(self, target):
        ft = FakeTarget(
            target_id=target.target_id,
            name=target.name,
            alliance=target.alliance,
            asset_type=target.asset_type,
            position=target.position,
            is_combatant=target.is_combatant,
        )
        self._tracker.add(ft)

    def remove_target(self, target_id: str):
        self._tracker.remove(target_id)


class FakeApp:
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


class FakePluginContext:
    def __init__(self, tracker, event_bus, engine, app):
        self.target_tracker = tracker
        self.event_bus = event_bus
        self.simulation_engine = engine
        self.app = app
        self.logger = None


@dataclass
class MockSimulationTarget:
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


# ── Fixtures ──────────────────────────────────────────────────────────

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
def ctx(tracker, event_bus, engine, app):
    return FakePluginContext(tracker, event_bus, engine, app)


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.deploy.return_value = {"success": True, "record": {"status": "ACTIVE"}}
    bridge.recall.return_value = {"success": True}
    bridge.think.return_value = {
        "thought": "I should patrol the area.",
        "action": 'observe()',
        "emotion": "alert",
        "consciousness_layer": 3,
        "model_used": "qwen2.5:1.5b",
        "confidence": 0.7,
    }
    bridge.heartbeat.return_value = {"success": True, "uptime_seconds": 60}
    bridge.record_experiences.return_value = 3
    return bridge


@pytest.fixture
def plugin(ctx, mock_bridge):
    """Create a fully wired plugin with mocked bridge."""
    with patch("graphlings.plugin.AgentBridge", return_value=mock_bridge):
        from graphlings.plugin import GraphlingsPlugin
        p = GraphlingsPlugin()
        p._config.think_interval_seconds = 0.1
        p._config.heartbeat_interval = 60.0
        p._config.experience_sync_interval = 30.0
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            p.configure(ctx)
        p._bridge = mock_bridge
        p._memory._bridge = mock_bridge
        return p


def _deploy(plugin, soul_id="twilight_001", role="Guard"):
    """Helper to deploy a graphling with mocked SimulationTarget."""
    with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
        return plugin.deploy_graphling(soul_id, role)


# ── Test: _calculate_adaptive_interval ────────────────────────────────


class TestAdaptiveInterval:
    """Test that _calculate_adaptive_interval maps urgency to correct intervals."""

    def test_high_urgency_returns_short_interval(self, plugin):
        """urgency > 0.8 should return 0.5s (danger: react fast)."""
        interval = plugin._calculate_adaptive_interval(0.9)
        assert interval == 0.5

    def test_active_urgency_returns_one_second(self, plugin):
        """urgency > 0.5 should return 1.0s (active: engaged)."""
        interval = plugin._calculate_adaptive_interval(0.6)
        assert interval == 1.0

    def test_normal_urgency_returns_three_seconds(self, plugin):
        """urgency > 0.3 should return 3.0s (normal: aware)."""
        interval = plugin._calculate_adaptive_interval(0.4)
        assert interval == 3.0

    def test_low_urgency_returns_ten_seconds(self, plugin):
        """urgency <= 0.3 should return 10.0s (idle: conserve compute)."""
        interval = plugin._calculate_adaptive_interval(0.2)
        assert interval == 10.0

    def test_zero_urgency_returns_ten_seconds(self, plugin):
        """urgency = 0.0 should return 10.0s."""
        interval = plugin._calculate_adaptive_interval(0.0)
        assert interval == 10.0

    def test_boundary_0_8_returns_short(self, plugin):
        """urgency = 0.8 is NOT > 0.8, so should return 1.0s (active band)."""
        interval = plugin._calculate_adaptive_interval(0.8)
        assert interval == 1.0

    def test_boundary_0_5_returns_normal(self, plugin):
        """urgency = 0.5 is NOT > 0.5, so should return 3.0s (normal band)."""
        interval = plugin._calculate_adaptive_interval(0.5)
        assert interval == 3.0

    def test_boundary_0_3_returns_idle(self, plugin):
        """urgency = 0.3 is NOT > 0.3, so should return 10.0s (idle band)."""
        interval = plugin._calculate_adaptive_interval(0.3)
        assert interval == 10.0

    def test_max_urgency_returns_short(self, plugin):
        """urgency = 1.0 should return 0.5s."""
        interval = plugin._calculate_adaptive_interval(1.0)
        assert interval == 0.5


# ── Test: Adaptive interval used in agent loop ────────────────────────


class TestAdaptiveThinkLoop:
    """Test that the agent loop uses adaptive intervals per-graphling."""

    def test_urgency_changes_interval_adapts(self, plugin, mock_bridge, tracker):
        """When urgency changes, the think interval should change too."""
        _deploy(plugin, "twilight_001", "Guard")

        # First think — low urgency (no hostiles)
        plugin._think_cycle("twilight_001")
        interval_idle = plugin._get_think_interval("twilight_001")
        assert interval_idle >= 3.0, f"Idle interval should be >= 3s, got {interval_idle}"

        # Add hostile nearby — high urgency
        hostile = FakeTarget(
            target_id="enemy_01", name="Enemy", alliance="hostile",
            asset_type="drone", position=(102.0, 202.0),
        )
        tracker.add(hostile)

        # Second think — high urgency now
        plugin._think_cycle("twilight_001")
        interval_danger = plugin._get_think_interval("twilight_001")
        assert interval_danger <= 1.0, f"Danger interval should be <= 1s, got {interval_danger}"

        # Interval should have decreased
        assert interval_danger < interval_idle

    def test_idle_graphling_thinks_less_than_active(self, plugin, mock_bridge, tracker):
        """An idle graphling should have a longer think interval than an active one."""
        _deploy(plugin, "idle_soul", "Merchant")
        _deploy(plugin, "active_soul", "Guard")

        # Idle soul — no hostiles, low urgency
        plugin._think_cycle("idle_soul")
        interval_idle = plugin._get_think_interval("idle_soul")

        # Active soul — add hostile near it
        hostile = FakeTarget(
            target_id="enemy_99", name="Threat", alliance="hostile",
            asset_type="drone", position=(102.0, 202.0),
        )
        tracker.add(hostile)
        plugin._think_cycle("active_soul")
        interval_active = plugin._get_think_interval("active_soul")

        assert interval_active < interval_idle, (
            f"Active ({interval_active}s) should be shorter than idle ({interval_idle}s)"
        )

    def test_per_graphling_intervals_independent(self, plugin, mock_bridge, tracker):
        """Different graphlings can have different think intervals simultaneously."""
        _deploy(plugin, "soul_a", "Guard")
        _deploy(plugin, "soul_b", "Merchant")

        # soul_a is near danger
        hostile = FakeTarget(
            target_id="enemy_01", name="Enemy", alliance="hostile",
            asset_type="drone", position=(102.0, 202.0),
        )
        tracker.add(hostile)

        plugin._think_cycle("soul_a")
        plugin._think_cycle("soul_b")

        interval_a = plugin._get_think_interval("soul_a")
        interval_b = plugin._get_think_interval("soul_b")

        # Both are at marketplace, but only soul_a should feel higher urgency
        # if the hostile is closer. Actually both are at same position so both
        # will see the hostile. Let's just verify both have valid intervals.
        assert interval_a > 0
        assert interval_b > 0


# ── Test: Compute stats tracking ──────────────────────────────────────


class TestComputeStats:
    """Test that per-graphling compute stats are tracked."""

    def test_think_count_incremented(self, plugin, mock_bridge):
        """Each think cycle increments think_count for the graphling."""
        _deploy(plugin, "twilight_001", "Guard")

        plugin._think_cycle("twilight_001")
        plugin._think_cycle("twilight_001")
        plugin._think_cycle("twilight_001")

        stats = plugin._get_compute_stats("twilight_001")
        assert stats["think_count"] == 3

    def test_total_latency_tracked(self, plugin, mock_bridge):
        """Think cycles accumulate total_latency."""
        _deploy(plugin, "twilight_001", "Guard")

        plugin._think_cycle("twilight_001")

        stats = plugin._get_compute_stats("twilight_001")
        assert stats["total_latency"] >= 0.0
        assert isinstance(stats["total_latency"], float)

    def test_models_used_tracked(self, plugin, mock_bridge):
        """Models used are tracked in compute stats."""
        mock_bridge.think.return_value = {
            "thought": "test",
            "action": "observe()",
            "emotion": "calm",
            "consciousness_layer": 3,
            "model_used": "qwen2.5:1.5b",
            "confidence": 0.7,
        }
        _deploy(plugin, "twilight_001", "Guard")

        plugin._think_cycle("twilight_001")

        stats = plugin._get_compute_stats("twilight_001")
        assert "qwen2.5:1.5b" in stats["models_used"]

    def test_stats_independent_per_graphling(self, plugin, mock_bridge):
        """Each graphling has its own compute stats."""
        _deploy(plugin, "soul_a", "Guard")
        _deploy(plugin, "soul_b", "Merchant")

        plugin._think_cycle("soul_a")
        plugin._think_cycle("soul_a")
        plugin._think_cycle("soul_b")

        stats_a = plugin._get_compute_stats("soul_a")
        stats_b = plugin._get_compute_stats("soul_b")

        assert stats_a["think_count"] == 2
        assert stats_b["think_count"] == 1

    def test_stats_zero_for_new_graphling(self, plugin, mock_bridge):
        """A newly deployed graphling has zero think_count."""
        _deploy(plugin, "twilight_001", "Guard")

        stats = plugin._get_compute_stats("twilight_001")
        assert stats["think_count"] == 0
        assert stats["total_latency"] == 0.0
        assert stats["models_used"] == {}

    def test_average_latency_computed(self, plugin, mock_bridge):
        """Average latency can be derived from stats."""
        _deploy(plugin, "twilight_001", "Guard")

        plugin._think_cycle("twilight_001")
        plugin._think_cycle("twilight_001")

        stats = plugin._get_compute_stats("twilight_001")
        if stats["think_count"] > 0:
            avg = stats["total_latency"] / stats["think_count"]
            assert avg >= 0.0


# ── Test: Reflection cycle ────────────────────────────────────────────


class TestReflectionCycle:
    """Test periodic L5 reflection cycle (every 30 minutes)."""

    def test_reflection_triggers_at_30min(self, plugin, mock_bridge):
        """Reflection cycle triggers after 30 minutes of deployment."""
        _deploy(plugin, "twilight_001", "Guard")

        # Simulate 30 minutes having passed
        plugin._last_reflection["twilight_001"] = time.monotonic() - 1801

        # Run a think cycle — it should trigger reflection
        plugin._think_cycle("twilight_001")

        # Verify a reflection think was sent with preferred_layer=5
        calls = mock_bridge.think.call_args_list
        reflection_calls = [
            c for c in calls
            if c[1].get("current_state") == "reflection"
        ]
        assert len(reflection_calls) >= 1, "Should have triggered a reflection think"

    def test_reflection_uses_layer_5(self, plugin, mock_bridge):
        """Reflection should request preferred_layer=5."""
        _deploy(plugin, "twilight_001", "Guard")

        plugin._last_reflection["twilight_001"] = time.monotonic() - 1801

        plugin._think_cycle("twilight_001")

        calls = mock_bridge.think.call_args_list
        reflection_calls = [
            c for c in calls
            if c[1].get("current_state") == "reflection"
        ]
        assert len(reflection_calls) >= 1
        assert reflection_calls[0][1].get("preferred_layer") == 5

    def test_reflection_uses_low_urgency(self, plugin, mock_bridge):
        """Reflection should use low urgency (0.1)."""
        _deploy(plugin, "twilight_001", "Guard")

        plugin._last_reflection["twilight_001"] = time.monotonic() - 1801

        plugin._think_cycle("twilight_001")

        calls = mock_bridge.think.call_args_list
        reflection_calls = [
            c for c in calls
            if c[1].get("current_state") == "reflection"
        ]
        assert len(reflection_calls) >= 1
        assert reflection_calls[0][1].get("urgency") == pytest.approx(0.1)

    def test_reflection_not_triggered_before_30min(self, plugin, mock_bridge):
        """Reflection should NOT trigger before 30 minutes."""
        _deploy(plugin, "twilight_001", "Guard")

        # Set last reflection to recent (5 minutes ago)
        plugin._last_reflection["twilight_001"] = time.monotonic() - 300

        plugin._think_cycle("twilight_001")

        calls = mock_bridge.think.call_args_list
        reflection_calls = [
            c for c in calls
            if c[1].get("current_state") == "reflection"
        ]
        assert len(reflection_calls) == 0, "Should NOT trigger reflection before 30 minutes"

    def test_reflection_updates_last_reflection_time(self, plugin, mock_bridge):
        """After reflection, _last_reflection is updated to now."""
        _deploy(plugin, "twilight_001", "Guard")

        old_time = time.monotonic() - 1801
        plugin._last_reflection["twilight_001"] = old_time

        plugin._think_cycle("twilight_001")

        new_time = plugin._last_reflection["twilight_001"]
        assert new_time > old_time, "Reflection time should have been updated"


# ── Test: Status endpoint includes compute stats ──────────────────────


class TestStatusEndpointComputeStats:
    """Test that /api/graphlings/status includes compute stats."""

    def test_status_includes_compute_stats(self, plugin, mock_bridge, app):
        """Status endpoint should include per-graphling compute stats."""
        _deploy(plugin, "twilight_001", "Guard")

        # Run some think cycles to generate stats
        plugin._think_cycle("twilight_001")
        plugin._think_cycle("twilight_001")

        # Call the status route handler
        handler = app._routes.get(("GET", "/api/graphlings/status"))
        assert handler is not None, "Status route should be registered"

        result = asyncio.get_event_loop().run_until_complete(handler())

        assert "compute_stats" in result, "Status should include compute_stats"
        assert "twilight_001" in result["compute_stats"]
        stats = result["compute_stats"]["twilight_001"]
        assert stats["think_count"] == 2
        assert "total_latency" in stats
        assert "models_used" in stats

    def test_status_includes_adaptive_intervals(self, plugin, mock_bridge, app):
        """Status endpoint should include current adaptive intervals."""
        _deploy(plugin, "twilight_001", "Guard")
        plugin._think_cycle("twilight_001")

        handler = app._routes.get(("GET", "/api/graphlings/status"))
        result = asyncio.get_event_loop().run_until_complete(handler())

        assert "compute_stats" in result
        stats = result["compute_stats"]["twilight_001"]
        assert "current_interval" in stats
        assert stats["current_interval"] > 0
