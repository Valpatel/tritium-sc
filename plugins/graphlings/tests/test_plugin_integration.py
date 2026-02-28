# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Integration tests for the fully wired GraphlingsPlugin.

Tests the complete deploy → think × N → recall lifecycle with all
sub-components connected (PerceptionEngine, MotorOutput, EntityFactory,
MemorySync, AgentBridge).

AgentBridge HTTP calls are mocked — no real server needed.
"""
from __future__ import annotations

import queue
import sys
import threading
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

    def publish(self, event_type: str, data: dict):
        event = {"type": event_type, **data}
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
            alliance=target.alliance,
            asset_type=target.asset_type,
            position=target.position,
            is_combatant=target.is_combatant,
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


class FakePluginContext:
    """Mimics PluginContext."""

    def __init__(self, tracker, event_bus, engine, app):
        self.target_tracker = tracker
        self.event_bus = event_bus
        self.simulation_engine = engine
        self.app = app
        self.logger = None


# ── Mock SimulationTarget for EntityFactory import ────────────────

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
def ctx(tracker, event_bus, engine, app):
    return FakePluginContext(tracker, event_bus, engine, app)

@pytest.fixture
def mock_bridge():
    """Mock AgentBridge that returns successful responses."""
    bridge = MagicMock()
    bridge.deploy.return_value = {"success": True, "record": {"status": "ACTIVE"}}
    bridge.recall.return_value = {"success": True}
    bridge.think.return_value = {
        "thought": "I should patrol the area.",
        "action": 'observe()',
        "emotion": "alert",
        "consciousness_layer": 3,
        "model_used": "local_heuristic",
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
        # Override config for fast test cycles
        p._config.think_interval_seconds = 0.1
        p._config.heartbeat_interval = 60.0
        p._config.experience_sync_interval = 30.0
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            p.configure(ctx)
        # Replace bridge with our mock
        p._bridge = mock_bridge
        p._memory._bridge = mock_bridge
        return p


# ── Integration Tests ─────────────────────────────────────────────


class TestDeployGraphling:
    """Test deploying graphlings via the plugin."""

    def test_deploy_calls_bridge(self, plugin, mock_bridge, tracker):
        """Deploy calls AgentBridge.deploy() with correct config."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            ok = plugin.deploy_graphling("twilight_001", "City Guard")
        assert ok is True
        mock_bridge.deploy.assert_called_once()
        args = mock_bridge.deploy.call_args
        assert args[0][0] == "twilight_001"
        assert args[0][1]["role_name"] == "City Guard"

    def test_deploy_spawns_entity(self, plugin, mock_bridge, tracker):
        """Deploy creates a SimulationTarget in the tracker."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "City Guard")
        # EntityFactory should have added a target to the engine/tracker
        targets = tracker.get_all()
        assert len(targets) == 1
        assert targets[0].asset_type == "graphling"

    def test_deploy_tracks_soul_id(self, plugin, mock_bridge):
        """Deployed graphling is tracked in _deployed dict."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "City Guard")
        assert "twilight_001" in plugin._deployed

    def test_deploy_already_deployed_fails(self, plugin, mock_bridge):
        """Cannot deploy the same soul_id twice."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            assert plugin.deploy_graphling("twilight_001", "Guard") is True
            assert plugin.deploy_graphling("twilight_001", "Other") is False

    def test_deploy_max_agents_reached(self, plugin, mock_bridge):
        """Cannot exceed max_agents limit."""
        plugin._config.max_agents = 2
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            assert plugin.deploy_graphling("soul_1", "Guard") is True
            assert plugin.deploy_graphling("soul_2", "Merchant") is True
            assert plugin.deploy_graphling("soul_3", "Baker") is False

    def test_deploy_server_failure_returns_false(self, plugin, mock_bridge):
        """If home server rejects deploy, return False."""
        mock_bridge.deploy.return_value = None
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            assert plugin.deploy_graphling("twilight_001", "Guard") is False
        assert "twilight_001" not in plugin._deployed

    def test_deploy_custom_spawn_point(self, plugin, mock_bridge, tracker):
        """Deploy at named spawn point."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard", spawn_point="watchtower")
        targets = tracker.get_all()
        assert len(targets) == 1
        assert targets[0].position == (50.0, 150.0)


class TestRecallAgent:
    """Test recalling deployed graphlings."""

    def test_recall_calls_bridge(self, plugin, mock_bridge):
        """Recall notifies the home server."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")
        plugin._recall_agent("twilight_001", "test_recall")
        mock_bridge.recall.assert_called_once_with("twilight_001", "test_recall")

    def test_recall_despawns_entity(self, plugin, mock_bridge, tracker):
        """Recall removes the SimulationTarget."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")
        assert len(tracker.get_all()) == 1
        plugin._recall_agent("twilight_001")
        assert len(tracker.get_all()) == 0

    def test_recall_removes_from_deployed(self, plugin, mock_bridge):
        """Recall removes soul_id from tracking."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")
        plugin._recall_agent("twilight_001")
        assert "twilight_001" not in plugin._deployed

    def test_recall_flushes_experiences(self, plugin, mock_bridge):
        """Recall flushes pending experiences before disconnect."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")
        # Queue some experiences
        plugin._memory.record_event("twilight_001", "npc_thought", "saw a rover")
        plugin._memory.record_event("twilight_001", "explosion", "boom nearby")
        plugin._recall_agent("twilight_001")
        # Should have flushed before recalling
        mock_bridge.record_experiences.assert_called()

    def test_recall_unknown_returns_false(self, plugin, mock_bridge):
        """Recalling a non-deployed soul returns False."""
        assert plugin._recall_agent("nonexistent") is False


class TestThinkCycle:
    """Test the think decision cycle."""

    def test_think_calls_bridge(self, plugin, mock_bridge, tracker):
        """Think cycle calls AgentBridge.think() with perception."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")
        plugin._think_cycle("twilight_001")
        mock_bridge.think.assert_called_once()
        call_kwargs = mock_bridge.think.call_args
        assert call_kwargs[1]["soul_id"] == "twilight_001"
        assert "perception" in call_kwargs[1]

    def test_think_executes_action(self, plugin, mock_bridge, tracker, event_bus):
        """Think cycle executes the returned action via MotorOutput."""
        mock_bridge.think.return_value = {
            "thought": "Alert!",
            "action": 'say("Halt! Who goes there?")',
            "emotion": "stern",
            "consciousness_layer": 3,
            "confidence": 0.7,
        }
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")
        plugin._think_cycle("twilight_001")
        # MotorOutput should have published npc_thought event via EventBus
        speech_events = [e for e in event_bus._published if e["type"] == "npc_thought"]
        assert len(speech_events) >= 1
        assert "Halt" in speech_events[0]["text"]

    def test_think_timeout_doesnt_crash(self, plugin, mock_bridge):
        """If think returns None (timeout), cycle continues gracefully."""
        mock_bridge.think.return_value = None
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")
        # Should not raise
        plugin._think_cycle("twilight_001")

    def test_think_uses_danger_as_urgency(self, plugin, mock_bridge, tracker):
        """Think urgency comes from perception danger_level."""
        # Add a hostile entity near the graphling
        hostile = FakeTarget(
            target_id="enemy_01", name="Enemy", alliance="hostile",
            asset_type="drone", position=(105.0, 205.0),
        )
        tracker.add(hostile)

        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard", spawn_point="marketplace")
        plugin._think_cycle("twilight_001")

        call_kwargs = mock_bridge.think.call_args[1]
        # Urgency should reflect the nearby hostile
        assert call_kwargs["urgency"] > 0.0


class TestAgentLoop:
    """Test the background agent loop."""

    def test_loop_runs_think_cycles(self, plugin, mock_bridge):
        """Agent loop calls think for deployed graphlings."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")
        plugin.start()
        # Wait for at least one think cycle
        time.sleep(0.3)
        plugin.stop()
        assert mock_bridge.think.call_count >= 1

    def test_loop_processes_events(self, plugin, mock_bridge, event_bus):
        """Agent loop processes events from the EventBus."""
        # Prevent experience sync from flushing during test
        plugin._config.experience_sync_interval = 9999.0
        # Make record_experiences return 0 so flush doesn't clear
        mock_bridge.record_experiences.return_value = 0
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")
        plugin.start()
        # Publish a game event
        event_bus.publish("projectile_fired", {"description": "missile launched"})
        time.sleep(0.3)
        plugin._running = False  # stop loop without recall
        if plugin._agent_thread:
            plugin._agent_thread.join(timeout=2.0)
        # The event should have been recorded in memory
        assert plugin._memory.pending_count("twilight_001") >= 1

    def test_stop_recalls_all(self, plugin, mock_bridge):
        """Stopping the plugin recalls all deployed graphlings."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("soul_1", "Guard")
            plugin.deploy_graphling("soul_2", "Merchant")
        plugin.start()
        time.sleep(0.1)
        plugin.stop()
        assert len(plugin._deployed) == 0
        assert mock_bridge.recall.call_count == 2


class TestEventHandling:
    """Test game event processing."""

    def test_event_feeds_perception(self, plugin, mock_bridge):
        """Events are recorded in PerceptionEngine for recent_events."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")
        plugin._handle_event({"type": "explosion", "description": "big boom"})
        # Perception engine should have the event
        assert "explosion" in list(plugin._perception._recent_events)

    def test_event_feeds_memory(self, plugin, mock_bridge):
        """Events are recorded in MemorySync for experience sync."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")
        plugin._handle_event({"type": "combat_damage", "description": "took hit"})
        assert plugin._memory.pending_count("twilight_001") == 1


class TestMultipleGraphlings:
    """Test multiple graphlings deployed simultaneously."""

    def test_two_graphlings_think_independently(self, plugin, mock_bridge):
        """Each deployed graphling gets its own think cycle."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("soul_1", "Guard", spawn_point="watchtower")
            plugin.deploy_graphling("soul_2", "Merchant", spawn_point="marketplace")

        plugin._think_cycle("soul_1")
        plugin._think_cycle("soul_2")

        assert mock_bridge.think.call_count == 2
        soul_ids = [c[1]["soul_id"] for c in mock_bridge.think.call_args_list]
        assert "soul_1" in soul_ids
        assert "soul_2" in soul_ids

    def test_recall_one_keeps_other(self, plugin, mock_bridge, tracker):
        """Recalling one graphling doesn't affect the other."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("soul_1", "Guard")
            plugin.deploy_graphling("soul_2", "Merchant")

        plugin._recall_agent("soul_1")

        assert "soul_1" not in plugin._deployed
        assert "soul_2" in plugin._deployed
        assert len(tracker.get_all()) == 1


class TestFullLifecycle:
    """Test the complete deploy → think × N → event → recall cycle."""

    def test_full_cycle(self, plugin, mock_bridge, tracker, event_bus):
        """Deploy, think 3 times, receive events, recall."""
        # 1. Deploy
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            assert plugin.deploy_graphling("twilight_001", "City Guard") is True
        assert len(tracker.get_all()) == 1
        mock_bridge.deploy.assert_called_once()

        # 2. Think 3 times
        for _ in range(3):
            plugin._think_cycle("twilight_001")
        assert mock_bridge.think.call_count == 3

        # 3. Receive game events
        plugin._handle_event({"type": "target_spawned", "description": "new rover"})
        plugin._handle_event({"type": "explosion", "description": "big boom"})
        assert plugin._memory.pending_count("twilight_001") == 2

        # 4. Recall
        plugin._recall_agent("twilight_001", "mission_complete")

        # Verify: experiences flushed
        mock_bridge.record_experiences.assert_called()
        # Verify: server notified
        mock_bridge.recall.assert_called_once_with("twilight_001", "mission_complete")
        # Verify: entity removed
        assert len(tracker.get_all()) == 0
        # Verify: tracking cleared
        assert "twilight_001" not in plugin._deployed

    def test_error_recovery_think_timeout(self, plugin, mock_bridge):
        """Think timeout doesn't disrupt the agent — retries next cycle."""
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin.deploy_graphling("twilight_001", "Guard")

        # First think: timeout
        mock_bridge.think.return_value = None
        plugin._think_cycle("twilight_001")
        assert "twilight_001" in plugin._deployed  # still deployed

        # Second think: success
        mock_bridge.think.return_value = {
            "thought": "All clear",
            "action": "observe()",
            "emotion": "calm",
            "consciousness_layer": 3,
            "confidence": 0.6,
        }
        plugin._think_cycle("twilight_001")
        assert mock_bridge.think.call_count == 2


class TestLifecycleWiring:
    """Test that game_state_change events route to SimulationLifecycleHandler."""

    def test_plugin_has_lifecycle_handler(self, plugin):
        """configure() creates a SimulationLifecycleHandler."""
        assert hasattr(plugin, "_lifecycle")
        assert plugin._lifecycle is not None

    def test_game_state_change_routes_to_lifecycle(self, plugin, mock_bridge):
        """game_state_change events are forwarded to lifecycle handler."""
        mock_bridge.batch_deploy.return_value = {
            "deployed": [
                {"soul_id": "twilight_001", "name": "Twilight"},
            ],
            "count": 1,
        }
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin._handle_event({
                "type": "game_state_change",
                "data": {"state": "countdown"},
            })

        mock_bridge.batch_deploy.assert_called_once()

    def test_stop_recalls_lifecycle_deployed(self, plugin, mock_bridge):
        """stop() recalls graphlings deployed by lifecycle handler."""
        mock_bridge.batch_deploy.return_value = {
            "deployed": [
                {"soul_id": "twilight_001", "name": "Twilight"},
            ],
            "count": 1,
        }
        with patch("graphlings.entity_factory.SimulationTarget", MockSimulationTarget):
            plugin._handle_event({
                "type": "game_state_change",
                "data": {"state": "countdown"},
            })

        # Lifecycle should have deployed
        assert plugin._lifecycle._deployed is True

        # stop() should recall lifecycle-deployed agents
        plugin.stop()
        mock_bridge.batch_recall.assert_called()
