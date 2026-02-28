# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for personality-influenced urgency scaling in adaptive intervals.

TDD: These tests are written FIRST, before the implementation.
They verify that personality traits (caution, sociability, curiosity)
influence the think interval beyond pure urgency.

Key design:
- Cautious graphlings think more often (interval * 0.7)
- Social graphlings think more when friendlies nearby (interval * 0.6)
- Curious graphlings think more when events pending (interval * 0.5)
- No personality data = default intervals (backward compat)
- Interval floor at 0.5s (never faster)
"""
from __future__ import annotations

import sys
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


# ── Fakes (reused from test_compute_efficiency.py) ────────────────────


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
        "action": "observe()",
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


# ── Test: Cautious graphling has shorter interval ─────────────────────


class TestCautiousGraphlingShorterInterval:
    """A graphling with high caution should have a shorter think interval at same urgency."""

    def test_cautious_graphling_shorter_interval(self, plugin):
        """High caution (>= 0.7) should multiply interval by 0.7."""
        # Base interval at medium urgency (0.4 → 3.0s)
        base = plugin._calculate_adaptive_interval(0.4)
        assert base == 3.0

        # With high caution personality
        personality = {"caution": 0.8}
        adjusted = plugin._calculate_adaptive_interval(0.4, personality=personality)

        assert adjusted < base, (
            f"Cautious graphling interval ({adjusted}s) should be shorter than base ({base}s)"
        )
        assert adjusted == pytest.approx(3.0 * 0.7, abs=0.01), (
            f"Expected {3.0 * 0.7}s, got {adjusted}s"
        )

    def test_low_caution_no_effect(self, plugin):
        """Caution below 0.7 should not affect interval."""
        base = plugin._calculate_adaptive_interval(0.4)
        personality = {"caution": 0.5}
        adjusted = plugin._calculate_adaptive_interval(0.4, personality=personality)

        assert adjusted == base, (
            f"Low-caution graphling should keep base interval ({base}s), got {adjusted}s"
        )


# ── Test: Social graphling reacts to friendlies ──────────────────────


class TestSocialGraphlingReactsToFriendlies:
    """High sociability with friendlies nearby should shorten the interval."""

    def test_social_graphling_reacts_to_friendlies(self, plugin):
        """High sociability (>= 0.7) + friendlies → interval * 0.6."""
        base = plugin._calculate_adaptive_interval(0.4)
        personality = {"sociability": 0.8}
        adjusted = plugin._calculate_adaptive_interval(
            0.4, personality=personality, nearby_friendlies=3
        )

        assert adjusted < base, (
            f"Social graphling with friendlies ({adjusted}s) should be shorter than base ({base}s)"
        )
        assert adjusted == pytest.approx(3.0 * 0.6, abs=0.01)

    def test_social_graphling_no_friendlies_no_effect(self, plugin):
        """High sociability without friendlies should not affect interval."""
        base = plugin._calculate_adaptive_interval(0.4)
        personality = {"sociability": 0.8}
        adjusted = plugin._calculate_adaptive_interval(
            0.4, personality=personality, nearby_friendlies=0
        )

        assert adjusted == base

    def test_low_sociability_friendlies_no_effect(self, plugin):
        """Low sociability even with friendlies should not affect interval."""
        base = plugin._calculate_adaptive_interval(0.4)
        personality = {"sociability": 0.3}
        adjusted = plugin._calculate_adaptive_interval(
            0.4, personality=personality, nearby_friendlies=5
        )

        assert adjusted == base


# ── Test: Curious graphling reacts to events ─────────────────────────


class TestCuriousGraphlingReactsToEvents:
    """High curiosity with pending events should shorten the interval."""

    def test_curious_graphling_reacts_to_events(self, plugin):
        """High curiosity (>= 0.7) + events → interval * 0.5."""
        base = plugin._calculate_adaptive_interval(0.4)
        personality = {"curiosity": 0.8}
        adjusted = plugin._calculate_adaptive_interval(
            0.4, personality=personality, has_events=True
        )

        assert adjusted < base, (
            f"Curious graphling with events ({adjusted}s) should be shorter than base ({base}s)"
        )
        assert adjusted == pytest.approx(3.0 * 0.5, abs=0.01)

    def test_curious_graphling_no_events_no_effect(self, plugin):
        """High curiosity without events should not affect interval."""
        base = plugin._calculate_adaptive_interval(0.4)
        personality = {"curiosity": 0.8}
        adjusted = plugin._calculate_adaptive_interval(
            0.4, personality=personality, has_events=False
        )

        assert adjusted == base

    def test_low_curiosity_events_no_effect(self, plugin):
        """Low curiosity even with events should not affect interval."""
        base = plugin._calculate_adaptive_interval(0.4)
        personality = {"curiosity": 0.3}
        adjusted = plugin._calculate_adaptive_interval(
            0.4, personality=personality, has_events=True
        )

        assert adjusted == base


# ── Test: No personality → default intervals (backward compat) ───────


class TestNoPersonalityDefault:
    """Without personality data, intervals should be unchanged from base."""

    def test_no_personality_default(self, plugin):
        """No personality dict → default intervals."""
        base = plugin._calculate_adaptive_interval(0.4)
        adjusted = plugin._calculate_adaptive_interval(0.4, personality=None)
        assert adjusted == base

    def test_empty_personality_default(self, plugin):
        """Empty personality dict → default intervals."""
        base = plugin._calculate_adaptive_interval(0.4)
        adjusted = plugin._calculate_adaptive_interval(0.4, personality={})
        assert adjusted == base

    def test_all_urgency_levels_unchanged(self, plugin):
        """All urgency bands should return default without personality."""
        for urgency, expected in [(0.9, 0.5), (0.6, 1.0), (0.4, 3.0), (0.2, 10.0)]:
            result = plugin._calculate_adaptive_interval(urgency)
            assert result == expected, (
                f"urgency={urgency}: expected {expected}s, got {result}s"
            )


# ── Test: Multiple traits stack with floor ───────────────────────────


class TestMultipleTraitsStack:
    """Multiple personality traits should stack but respect the 0.5s floor."""

    def test_multiple_traits_stack(self, plugin):
        """Cautious + social + curious at low urgency should stack multipliers."""
        personality = {"caution": 0.9, "sociability": 0.9, "curiosity": 0.9}
        adjusted = plugin._calculate_adaptive_interval(
            0.4,
            personality=personality,
            nearby_friendlies=3,
            has_events=True,
        )

        # Base: 3.0s, * 0.7 (caution) * 0.6 (social+friends) * 0.5 (curious+events)
        # = 3.0 * 0.21 = 0.63s → but floor is 0.5s
        assert adjusted >= 0.5, (
            f"Interval ({adjusted}s) must not go below 0.5s floor"
        )

    def test_floor_enforced(self, plugin):
        """Even with max personality boosts at high urgency, floor is 0.5s."""
        personality = {"caution": 1.0, "sociability": 1.0, "curiosity": 1.0}
        adjusted = plugin._calculate_adaptive_interval(
            0.9,  # base 0.5s
            personality=personality,
            nearby_friendlies=10,
            has_events=True,
        )

        # Base 0.5 * 0.7 * 0.6 * 0.5 = 0.105 → clamped to 0.5
        assert adjusted == 0.5, (
            f"Floor should clamp to 0.5s, got {adjusted}s"
        )
