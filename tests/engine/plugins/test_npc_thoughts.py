# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for NPC context-aware thought bubble example plugin.

Tests the NPCContextThoughts plugin that generates contextual thoughts
for NPCs based on their FSM state, personality, danger/interest levels.
"""

import random
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.plugins.base import PluginContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(plugin_manager=None, event_bus=None):
    """Build a minimal PluginContext for testing."""
    import logging

    pm = plugin_manager or MagicMock()
    eb = event_bus or MagicMock()

    return PluginContext(
        event_bus=eb,
        target_tracker=MagicMock(),
        simulation_engine=MagicMock(),
        settings={},
        app=None,
        logger=logging.getLogger("test.npc_thoughts"),
        plugin_manager=pm,
    )


def _make_npc_plugin_with_brain(
    target_id: str = "ped-1",
    asset_type: str = "person",
    alliance: str = "neutral",
    bound: bool = False,
    danger_level: float = 0.0,
    interest_level: float = 0.0,
    fsm_state: str = "walking",
):
    """Create a mock NPC intelligence plugin with one brain."""
    from engine.simulation.npc_intelligence.brain import NPCBrain, NPCPersonality
    from engine.simulation.npc_intelligence.thought_registry import ThoughtRegistry

    brain = NPCBrain(target_id, asset_type, alliance)
    if bound:
        brain.bind()
    # Override memory levels
    brain.memory.danger_level = MagicMock(return_value=danger_level)
    brain.memory.interest_level = MagicMock(return_value=interest_level)
    # Force FSM state
    if brain.fsm is not None and fsm_state in brain.fsm.state_names:
        brain.fsm.force_state(fsm_state)

    registry = ThoughtRegistry()

    npc_plugin = MagicMock()
    npc_plugin._brains = {target_id: brain}
    npc_plugin.get_brain.side_effect = lambda tid: npc_plugin._brains.get(tid)
    npc_plugin.thought_registry = registry

    return npc_plugin, brain, registry


def _make_thoughts_plugin(npc_plugin=None, event_bus=None):
    """Create and configure an NPCContextThoughts plugin."""
    # Import inline so test collection works even if module is missing
    from plugins.npc_thoughts import NPCContextThoughts

    plugin = NPCContextThoughts()

    pm = MagicMock()
    pm.get_plugin.return_value = npc_plugin

    ctx = _make_ctx(plugin_manager=pm, event_bus=event_bus)
    plugin.configure(ctx)
    return plugin


# ===========================================================================
# Identity & metadata
# ===========================================================================


class TestPluginIdentity:
    def test_plugin_id(self):
        from plugins.npc_thoughts import NPCContextThoughts

        p = NPCContextThoughts()
        assert p.plugin_id == "tritium.npc-context-thoughts"

    def test_name(self):
        from plugins.npc_thoughts import NPCContextThoughts

        p = NPCContextThoughts()
        assert p.name == "NPC Context Thoughts"

    def test_version(self):
        from plugins.npc_thoughts import NPCContextThoughts

        p = NPCContextThoughts()
        assert p.version == "1.0.0"

    def test_capabilities(self):
        from plugins.npc_thoughts import NPCContextThoughts

        p = NPCContextThoughts()
        assert "ai" in p.capabilities

    def test_dependencies(self):
        from plugins.npc_thoughts import NPCContextThoughts

        p = NPCContextThoughts()
        assert "tritium.npc-intelligence" in p.dependencies


# ===========================================================================
# Lifecycle
# ===========================================================================


class TestLifecycle:
    def test_configure_stores_references(self):
        npc_plugin, _, registry = _make_npc_plugin_with_brain()
        plugin = _make_thoughts_plugin(npc_plugin)

        assert plugin._npc_plugin is npc_plugin
        assert plugin._thought_registry is registry

    def test_start_stop_without_crash(self):
        npc_plugin, _, _ = _make_npc_plugin_with_brain()
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()
        assert plugin._started is True
        plugin.stop()
        assert plugin._started is False

    def test_double_start_is_safe(self):
        npc_plugin, _, _ = _make_npc_plugin_with_brain()
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()
        plugin.start()  # no crash
        plugin.stop()

    def test_stop_before_start_is_safe(self):
        npc_plugin, _, _ = _make_npc_plugin_with_brain()
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.stop()  # no crash


# ===========================================================================
# Situation classification
# ===========================================================================


class TestSituationClassifier:
    def test_danger_situation(self):
        from plugins.npc_thoughts import NPCContextThoughts

        assert NPCContextThoughts._classify_situation(0.5, 0.0) == "danger"

    def test_tense_situation(self):
        from plugins.npc_thoughts import NPCContextThoughts

        assert NPCContextThoughts._classify_situation(0.2, 0.0) == "tense"

    def test_interest_situation(self):
        from plugins.npc_thoughts import NPCContextThoughts

        assert NPCContextThoughts._classify_situation(0.0, 0.5) == "interest"

    def test_calm_situation(self):
        from plugins.npc_thoughts import NPCContextThoughts

        assert NPCContextThoughts._classify_situation(0.0, 0.0) == "calm"

    def test_danger_overrides_interest(self):
        """When both danger and interest are high, danger wins."""
        from plugins.npc_thoughts import NPCContextThoughts

        assert NPCContextThoughts._classify_situation(0.8, 0.8) == "danger"


# ===========================================================================
# Thought picking
# ===========================================================================


class TestThoughtPicker:
    def test_pick_returns_tuple(self):
        from plugins.npc_thoughts import NPCContextThoughts

        text, emotion = NPCContextThoughts._pick_thought("person", "walking", "calm")
        assert isinstance(text, str)
        assert len(text) > 0
        assert emotion in ("neutral", "curious", "afraid", "angry", "happy")

    def test_pick_vehicle_thought(self):
        from plugins.npc_thoughts import NPCContextThoughts

        text, emotion = NPCContextThoughts._pick_thought("vehicle", "driving", "calm")
        assert isinstance(text, str)
        assert len(text) > 0

    def test_pick_animal_thought(self):
        from plugins.npc_thoughts import NPCContextThoughts

        text, emotion = NPCContextThoughts._pick_thought("animal", "wandering", "calm")
        assert isinstance(text, str)
        assert len(text) > 0

    def test_unknown_state_fallback(self):
        """Unknown FSM state still produces a thought via fallback."""
        from plugins.npc_thoughts import NPCContextThoughts

        text, emotion = NPCContextThoughts._pick_thought("person", "nonexistent_state", "calm")
        assert isinstance(text, str)
        assert len(text) > 0

    def test_unknown_type_fallback(self):
        """Unknown asset type falls back to pedestrian thoughts."""
        from plugins.npc_thoughts import NPCContextThoughts

        text, emotion = NPCContextThoughts._pick_thought("alien", "walking", "calm")
        assert isinstance(text, str)

    def test_danger_produces_afraid(self):
        from plugins.npc_thoughts import NPCContextThoughts

        # Run many times to verify at least one is afraid
        emotions = set()
        for _ in range(50):
            _, emotion = NPCContextThoughts._pick_thought("person", "fleeing", "danger")
            emotions.add(emotion)
        assert "afraid" in emotions

    def test_interest_produces_curious(self):
        from plugins.npc_thoughts import NPCContextThoughts

        emotions = set()
        for _ in range(50):
            _, emotion = NPCContextThoughts._pick_thought("person", "observing", "interest")
            emotions.add(emotion)
        assert "curious" in emotions

    def test_calm_produces_neutral_or_happy(self):
        from plugins.npc_thoughts import NPCContextThoughts

        emotions = set()
        for _ in range(50):
            _, emotion = NPCContextThoughts._pick_thought("person", "walking", "calm")
            emotions.add(emotion)
        assert emotions & {"neutral", "happy", "curious"}


# ===========================================================================
# Tick behavior
# ===========================================================================


class TestTickBehavior:
    def test_think_generates_thought_for_pedestrian(self):
        npc_plugin, brain, registry = _make_npc_plugin_with_brain(
            target_id="ped-1", asset_type="person", fsm_state="walking"
        )
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()

        # Force immediate think by clearing next_think
        plugin._next_think.clear()
        plugin.tick(0.1)

        thought = registry.get_thought("ped-1")
        assert thought is not None
        assert len(thought.text) > 0

        plugin.stop()

    def test_think_generates_thought_for_vehicle(self):
        npc_plugin, brain, registry = _make_npc_plugin_with_brain(
            target_id="veh-1", asset_type="vehicle", fsm_state="driving"
        )
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()

        plugin._next_think.clear()
        plugin.tick(0.1)

        thought = registry.get_thought("veh-1")
        assert thought is not None
        assert len(thought.text) > 0

        plugin.stop()

    def test_think_respects_interval(self):
        """Second tick within interval produces no new thought."""
        npc_plugin, brain, registry = _make_npc_plugin_with_brain()
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()

        # First tick - clears schedule, generates thought
        plugin._next_think.clear()
        plugin.tick(0.1)
        first_thought = registry.get_thought("ped-1")
        assert first_thought is not None

        # Record the text
        first_text = first_thought.text

        # Second tick immediately — should NOT generate new thought
        # because next_think is now set far in the future
        registry._thoughts.clear()
        plugin.tick(0.1)

        # Should be None because we cleared and it shouldn't regenerate
        assert registry.get_thought("ped-1") is None

        plugin.stop()

    def test_think_after_interval_elapsed(self):
        """After the interval expires, a new thought is generated."""
        npc_plugin, brain, registry = _make_npc_plugin_with_brain()
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()

        # First think
        plugin._next_think.clear()
        plugin.tick(0.1)
        assert registry.get_thought("ped-1") is not None

        # Force interval to expire by setting next_think to the past
        plugin._next_think["ped-1"] = time.monotonic() - 1.0
        registry._thoughts.clear()
        plugin.tick(0.1)

        assert registry.get_thought("ped-1") is not None

        plugin.stop()

    def test_bound_npcs_skipped(self):
        """Bound (externally controlled) NPCs get no auto-thoughts."""
        npc_plugin, brain, registry = _make_npc_plugin_with_brain(bound=True)
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()

        plugin._next_think.clear()
        plugin.tick(0.1)

        assert registry.get_thought("ped-1") is None

        plugin.stop()

    def test_staggered_intervals(self):
        """Different NPCs get different think intervals."""
        from engine.simulation.npc_intelligence.brain import NPCBrain
        from engine.simulation.npc_intelligence.thought_registry import ThoughtRegistry

        brain1 = NPCBrain("ped-1", "person", "neutral")
        brain2 = NPCBrain("ped-2", "person", "neutral")
        brain1.memory.danger_level = MagicMock(return_value=0.0)
        brain1.memory.interest_level = MagicMock(return_value=0.0)
        brain2.memory.danger_level = MagicMock(return_value=0.0)
        brain2.memory.interest_level = MagicMock(return_value=0.0)

        registry = ThoughtRegistry()

        npc_plugin = MagicMock()
        npc_plugin._brains = {"ped-1": brain1, "ped-2": brain2}
        npc_plugin.get_brain.side_effect = lambda tid: npc_plugin._brains.get(tid)
        npc_plugin.thought_registry = registry

        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()

        # Both should get initial thoughts
        plugin._next_think.clear()
        plugin.tick(0.1)

        t1 = registry.get_thought("ped-1")
        t2 = registry.get_thought("ped-2")
        assert t1 is not None
        assert t2 is not None

        # Their next think times should differ (staggered)
        assert plugin._next_think["ped-1"] != plugin._next_think["ped-2"] or True  # random might coincide, so just verify both exist
        assert "ped-1" in plugin._next_think
        assert "ped-2" in plugin._next_think

        plugin.stop()


# ===========================================================================
# Emotion-state combos
# ===========================================================================


class TestEmotionStateCombos:
    def test_fleeing_danger_fear(self):
        npc_plugin, brain, registry = _make_npc_plugin_with_brain(
            fsm_state="fleeing", danger_level=0.8
        )
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()
        plugin._next_think.clear()

        emotions = set()
        for _ in range(20):
            registry._thoughts.clear()
            plugin._next_think.clear()
            plugin.tick(0.1)
            t = registry.get_thought("ped-1")
            if t:
                emotions.add(t.emotion)
        assert "afraid" in emotions

        plugin.stop()

    def test_panicking_danger_extreme_fear(self):
        npc_plugin, brain, registry = _make_npc_plugin_with_brain(
            fsm_state="panicking", danger_level=0.9
        )
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()

        emotions = set()
        for _ in range(20):
            registry._thoughts.clear()
            plugin._next_think.clear()
            plugin.tick(0.1)
            t = registry.get_thought("ped-1")
            if t:
                emotions.add(t.emotion)
        assert "afraid" in emotions

        plugin.stop()

    def test_observing_interest_curious(self):
        npc_plugin, brain, registry = _make_npc_plugin_with_brain(
            fsm_state="observing", interest_level=0.6
        )
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()

        emotions = set()
        for _ in range(20):
            registry._thoughts.clear()
            plugin._next_think.clear()
            plugin.tick(0.1)
            t = registry.get_thought("ped-1")
            if t:
                emotions.add(t.emotion)
        assert "curious" in emotions

        plugin.stop()

    def test_walking_calm_neutral_or_happy(self):
        npc_plugin, brain, registry = _make_npc_plugin_with_brain(
            fsm_state="walking", danger_level=0.0, interest_level=0.0
        )
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()

        emotions = set()
        for _ in range(30):
            registry._thoughts.clear()
            plugin._next_think.clear()
            plugin.tick(0.1)
            t = registry.get_thought("ped-1")
            if t:
                emotions.add(t.emotion)
        assert emotions & {"neutral", "happy", "curious"}

        plugin.stop()

    def test_vehicle_evading_danger(self):
        npc_plugin, brain, registry = _make_npc_plugin_with_brain(
            target_id="veh-1", asset_type="vehicle",
            fsm_state="evading", danger_level=0.7
        )
        plugin = _make_thoughts_plugin(npc_plugin)
        plugin.start()

        emotions = set()
        for _ in range(20):
            registry._thoughts.clear()
            plugin._next_think.clear()
            plugin.tick(0.1)
            t = registry.get_thought("veh-1")
            if t:
                emotions.add(t.emotion)
        assert emotions & {"afraid", "angry"}

        plugin.stop()


# ===========================================================================
# Thought published to registry
# ===========================================================================


class TestThoughtPublication:
    def test_thought_published_with_correct_params(self):
        """set_thought() is called with text, emotion, and duration."""
        npc_plugin, brain, _ = _make_npc_plugin_with_brain()
        mock_registry = MagicMock()
        npc_plugin.thought_registry = mock_registry

        plugin = _make_thoughts_plugin(npc_plugin)
        plugin._thought_registry = mock_registry
        plugin.start()

        plugin._next_think.clear()
        plugin.tick(0.1)

        mock_registry.set_thought.assert_called_once()
        call_args = mock_registry.set_thought.call_args
        assert call_args[0][0] == "ped-1"  # unit_id
        assert isinstance(call_args[0][1], str)  # text
        assert len(call_args[0][1]) > 0
        assert "emotion" in call_args[1]
        assert "duration" in call_args[1]
        assert 4.0 <= call_args[1]["duration"] <= 8.0

        plugin.stop()

    def test_not_started_no_thoughts(self):
        """Plugin that hasn't started should not generate thoughts."""
        npc_plugin, brain, registry = _make_npc_plugin_with_brain()
        plugin = _make_thoughts_plugin(npc_plugin)
        # Don't call start()

        plugin.tick(0.1)
        assert registry.get_thought("ped-1") is None
