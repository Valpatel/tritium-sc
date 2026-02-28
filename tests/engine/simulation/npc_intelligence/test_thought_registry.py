# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for ThoughtRegistry — central store for NPC thought bubbles."""

import time
import threading
import pytest
from unittest.mock import MagicMock, call

from engine.comms.event_bus import EventBus
from engine.simulation.npc_intelligence.thought_registry import (
    ThoughtRegistry,
    UnitThought,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def registry(event_bus: EventBus) -> ThoughtRegistry:
    return ThoughtRegistry(event_bus=event_bus)


class TestSetThought:
    def test_set_thought_publishes_event(self, registry: ThoughtRegistry, event_bus: EventBus) -> None:
        """EventBus receives `npc_thought` when a thought is set."""
        received = []
        sub = event_bus.subscribe()

        def reader():
            try:
                msg = sub.get(timeout=1.0)
                received.append(msg)
            except Exception:
                pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        registry.set_thought("npc-1", "Hello world", emotion="happy", duration=5.0)
        t.join(timeout=2.0)

        assert len(received) == 1
        assert received[0]["type"] == "npc_thought"
        assert received[0]["data"]["unit_id"] == "npc-1"
        assert received[0]["data"]["text"] == "Hello world"
        assert received[0]["data"]["emotion"] == "happy"
        assert received[0]["data"]["duration"] == 5.0

    def test_set_thought_returns_unit_thought(self, registry: ThoughtRegistry) -> None:
        thought = registry.set_thought("npc-1", "Thinking...")
        assert isinstance(thought, UnitThought)
        assert thought.unit_id == "npc-1"
        assert thought.text == "Thinking..."
        assert thought.emotion == "neutral"

    def test_set_thought_default_emotion(self, registry: ThoughtRegistry) -> None:
        thought = registry.set_thought("npc-1", "test")
        assert thought.emotion == "neutral"

    def test_set_thought_overwrites_previous(self, registry: ThoughtRegistry) -> None:
        registry.set_thought("npc-1", "First")
        registry.set_thought("npc-1", "Second")
        thought = registry.get_thought("npc-1")
        assert thought is not None
        assert thought.text == "Second"


class TestClearThought:
    def test_clear_thought_publishes_clear(self, registry: ThoughtRegistry, event_bus: EventBus) -> None:
        """EventBus receives `npc_thought_clear` when a thought is cleared."""
        received = []
        sub = event_bus.subscribe()

        registry.set_thought("npc-1", "Hello")

        # Drain the set event
        try:
            sub.get(timeout=0.5)
        except Exception:
            pass

        def reader():
            try:
                msg = sub.get(timeout=1.0)
                received.append(msg)
            except Exception:
                pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        registry.clear_thought("npc-1")
        t.join(timeout=2.0)

        assert len(received) == 1
        assert received[0]["type"] == "npc_thought_clear"
        assert received[0]["data"]["unit_id"] == "npc-1"

    def test_clear_nonexistent_no_error(self, registry: ThoughtRegistry) -> None:
        """Clearing a non-existent thought should not raise."""
        registry.clear_thought("nonexistent")

    def test_clear_removes_thought(self, registry: ThoughtRegistry) -> None:
        registry.set_thought("npc-1", "Hello")
        registry.clear_thought("npc-1")
        assert registry.get_thought("npc-1") is None


class TestThoughtExpiry:
    def test_thought_expiry(self, registry: ThoughtRegistry) -> None:
        """Expired thoughts auto-removed on get."""
        registry.set_thought("npc-1", "Temporary", duration=0.01)
        time.sleep(0.05)
        assert registry.get_thought("npc-1") is None

    def test_thought_not_expired(self, registry: ThoughtRegistry) -> None:
        """Non-expired thoughts remain accessible."""
        registry.set_thought("npc-1", "Lasting", duration=60.0)
        thought = registry.get_thought("npc-1")
        assert thought is not None
        assert thought.text == "Lasting"

    def test_expiry_thread_clears_expired(self, registry: ThoughtRegistry) -> None:
        """Background expiry thread clears expired thoughts."""
        registry.set_thought("npc-1", "Short lived", duration=0.1)
        registry.start()
        try:
            time.sleep(1.5)  # Expiry loop runs every 1s
            assert registry.get_thought("npc-1") is None
        finally:
            registry.stop()


class TestGetThought:
    def test_get_thought_returns_active(self, registry: ThoughtRegistry) -> None:
        """Returns current thought for a unit."""
        registry.set_thought("npc-1", "Active thought", duration=60.0)
        thought = registry.get_thought("npc-1")
        assert thought is not None
        assert thought.text == "Active thought"

    def test_get_thought_nonexistent(self, registry: ThoughtRegistry) -> None:
        assert registry.get_thought("nonexistent") is None


class TestAllThoughts:
    def test_all_thoughts_snapshot(self, registry: ThoughtRegistry) -> None:
        """Returns dict of all active thoughts."""
        registry.set_thought("npc-1", "Hello", duration=60.0)
        registry.set_thought("npc-2", "World", duration=60.0)
        all_t = registry.all_thoughts()
        assert len(all_t) == 2
        assert "npc-1" in all_t
        assert "npc-2" in all_t
        assert all_t["npc-1"].text == "Hello"
        assert all_t["npc-2"].text == "World"

    def test_all_thoughts_excludes_expired(self, registry: ThoughtRegistry) -> None:
        registry.set_thought("npc-1", "Active", duration=60.0)
        registry.set_thought("npc-2", "Expired", duration=0.01)
        time.sleep(0.05)
        all_t = registry.all_thoughts()
        assert len(all_t) == 1
        assert "npc-1" in all_t

    def test_all_thoughts_empty(self, registry: ThoughtRegistry) -> None:
        assert len(registry.all_thoughts()) == 0


class TestControl:
    def test_take_control_binds_brain(self) -> None:
        """Calls brain.bind() when taking control."""
        plugin = MagicMock()
        brain = MagicMock()
        plugin.get_brain.return_value = brain

        reg = ThoughtRegistry(plugin=plugin)
        result = reg.take_control("npc-1", "graphlings-client")
        assert result is True
        brain.bind.assert_called_once()

    def test_release_control_unbinds_brain(self) -> None:
        """Calls brain.unbind() when releasing control."""
        plugin = MagicMock()
        brain = MagicMock()
        plugin.get_brain.return_value = brain

        reg = ThoughtRegistry(plugin=plugin)
        reg.take_control("npc-1", "graphlings-client")
        reg.release_control("npc-1")
        brain.unbind.assert_called_once()

    def test_double_lock_rejected(self) -> None:
        """409 when already controlled by different controller."""
        plugin = MagicMock()
        brain = MagicMock()
        plugin.get_brain.return_value = brain

        reg = ThoughtRegistry(plugin=plugin)
        assert reg.take_control("npc-1", "controller-A") is True
        assert reg.take_control("npc-1", "controller-B") is False

    def test_same_controller_can_relock(self) -> None:
        """Same controller_id can re-lock."""
        plugin = MagicMock()
        brain = MagicMock()
        plugin.get_brain.return_value = brain

        reg = ThoughtRegistry(plugin=plugin)
        assert reg.take_control("npc-1", "controller-A") is True
        assert reg.take_control("npc-1", "controller-A") is True

    def test_set_thought_without_control(self, registry: ThoughtRegistry) -> None:
        """No lock needed for display-only thoughts."""
        thought = registry.set_thought("npc-1", "Just a thought")
        assert thought.text == "Just a thought"

    def test_take_control_nonexistent_unit(self) -> None:
        """Returns False when unit doesn't exist (no brain)."""
        plugin = MagicMock()
        plugin.get_brain.return_value = None

        reg = ThoughtRegistry(plugin=plugin)
        result = reg.take_control("nonexistent", "controller-A")
        assert result is False

    def test_get_controller(self) -> None:
        plugin = MagicMock()
        brain = MagicMock()
        plugin.get_brain.return_value = brain

        reg = ThoughtRegistry(plugin=plugin)
        assert reg.get_controller("npc-1") is None
        reg.take_control("npc-1", "ctrl-1")
        assert reg.get_controller("npc-1") == "ctrl-1"

    def test_release_clears_controller(self) -> None:
        plugin = MagicMock()
        brain = MagicMock()
        plugin.get_brain.return_value = brain

        reg = ThoughtRegistry(plugin=plugin)
        reg.take_control("npc-1", "ctrl-1")
        reg.release_control("npc-1")
        assert reg.get_controller("npc-1") is None


class TestLifecycle:
    def test_start_stop(self, registry: ThoughtRegistry) -> None:
        """Start and stop without error."""
        registry.start()
        registry.stop()

    def test_double_start(self, registry: ThoughtRegistry) -> None:
        """Double start is safe."""
        registry.start()
        registry.start()
        registry.stop()
