"""Tests for NPCIntelligencePlugin — plugin lifecycle and brain management."""

import pytest
from unittest.mock import MagicMock

from engine.comms.event_bus import EventBus
from engine.plugins.base import PluginContext, PluginInterface
from engine.simulation.npc_intelligence.plugin import NPCIntelligencePlugin


def _make_ctx(event_bus=None, engine=None):
    """Create a minimal PluginContext."""
    import logging
    return PluginContext(
        event_bus=event_bus or EventBus(),
        target_tracker=MagicMock(),
        simulation_engine=engine,
        settings={},
        app=None,
        logger=logging.getLogger("test"),
        plugin_manager=MagicMock(),
    )


class TestPluginIdentity:
    def test_plugin_id(self):
        p = NPCIntelligencePlugin()
        assert p.plugin_id == "tritium.npc-intelligence"

    def test_name(self):
        p = NPCIntelligencePlugin()
        assert "NPC" in p.name

    def test_version(self):
        p = NPCIntelligencePlugin()
        assert p.version  # non-empty

    def test_capabilities(self):
        p = NPCIntelligencePlugin()
        assert "ai" in p.capabilities
        assert "data_source" in p.capabilities
        assert "background" in p.capabilities

    def test_is_plugin_interface(self):
        p = NPCIntelligencePlugin()
        assert isinstance(p, PluginInterface)


class TestPluginLifecycle:
    def test_configure(self):
        p = NPCIntelligencePlugin()
        ctx = _make_ctx()
        p.configure(ctx)
        assert p._event_bus is not None

    def test_start_stop(self):
        p = NPCIntelligencePlugin()
        ctx = _make_ctx()
        p.configure(ctx)
        p.start()
        assert p.healthy
        p.stop()

    def test_healthy_before_start(self):
        p = NPCIntelligencePlugin()
        # Before configure/start, should still report healthy (no crash)
        assert p.healthy

    def test_double_start_safe(self):
        p = NPCIntelligencePlugin()
        ctx = _make_ctx()
        p.configure(ctx)
        p.start()
        p.start()  # no crash
        p.stop()

    def test_double_stop_safe(self):
        p = NPCIntelligencePlugin()
        ctx = _make_ctx()
        p.configure(ctx)
        p.start()
        p.stop()
        p.stop()  # no crash


class TestPluginBrainManagement:
    def test_attach_brain(self):
        p = NPCIntelligencePlugin()
        ctx = _make_ctx()
        p.configure(ctx)
        p.start()
        brain = p.attach_brain("npc-1", "person", "neutral")
        assert brain is not None
        assert brain.target_id == "npc-1"
        p.stop()

    def test_detach_brain(self):
        p = NPCIntelligencePlugin()
        ctx = _make_ctx()
        p.configure(ctx)
        p.start()
        p.attach_brain("npc-1", "person", "neutral")
        removed = p.detach_brain("npc-1")
        assert removed is True
        p.stop()

    def test_detach_nonexistent(self):
        p = NPCIntelligencePlugin()
        ctx = _make_ctx()
        p.configure(ctx)
        p.start()
        removed = p.detach_brain("npc-999")
        assert removed is False
        p.stop()

    def test_get_brain(self):
        p = NPCIntelligencePlugin()
        ctx = _make_ctx()
        p.configure(ctx)
        p.start()
        p.attach_brain("npc-1", "person", "neutral")
        brain = p.get_brain("npc-1")
        assert brain is not None
        assert brain.target_id == "npc-1"
        p.stop()

    def test_brain_count(self):
        p = NPCIntelligencePlugin()
        ctx = _make_ctx()
        p.configure(ctx)
        p.start()
        p.attach_brain("npc-1", "person", "neutral")
        p.attach_brain("npc-2", "vehicle", "neutral")
        assert p.brain_count == 2
        p.stop()
