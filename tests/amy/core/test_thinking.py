# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for GoalStack and ThinkingThread logic."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from amy.brain.thinking import GoalStack, ThinkingThread
from engine.actions.lua_motor import MotorOutput


pytestmark = pytest.mark.unit


class TestGoalStack:
    def test_add_goal(self):
        gs = GoalStack()
        gs.add("explore the room")
        assert len(gs.active) == 1
        assert gs.active[0]["description"] == "explore the room"

    def test_add_goal_with_priority(self):
        gs = GoalStack()
        gs.add("low priority", priority=1)
        gs.add("high priority", priority=5)
        # Sorted by priority descending
        assert gs.active[0]["description"] == "high priority"
        assert gs.active[1]["description"] == "low priority"

    def test_max_goals_enforced(self):
        gs = GoalStack()
        for i in range(7):
            gs.add(f"goal {i}", priority=i % 5 + 1)
        assert len(gs.active) <= GoalStack.MAX_GOALS

    def test_priority_clamped(self):
        gs = GoalStack()
        gs.add("test", priority=10)
        assert gs.active[0]["priority"] == 5
        gs.add("test2", priority=-3)
        # Clamped to 1
        low = [g for g in gs.active if g["description"] == "test2"]
        assert low[0]["priority"] == 1

    def test_complete_top_goal(self):
        gs = GoalStack()
        gs.add("first goal", priority=3)
        gs.add("second goal", priority=1)
        completed = gs.complete()
        assert completed == "first goal"
        assert len(gs.active) == 1

    def test_complete_by_description(self):
        gs = GoalStack()
        gs.add("explore the room", priority=3)
        gs.add("check the desk", priority=2)
        completed = gs.complete("desk")
        assert completed == "check the desk"
        assert len(gs.active) == 1

    def test_complete_returns_none_when_empty(self):
        gs = GoalStack()
        assert gs.complete() is None

    def test_complete_returns_none_when_no_match(self):
        gs = GoalStack()
        gs.add("explore the room")
        assert gs.complete("nonexistent") is None

    def test_goals_expire(self):
        gs = GoalStack()
        gs.add("temporary goal")

        # Force expiry by setting past time
        with gs._lock:
            gs._goals[0]["expiry"] = 0.0

        assert len(gs.active) == 0

    def test_context_empty(self):
        gs = GoalStack()
        assert gs.context() == ""

    def test_context_with_goals(self):
        gs = GoalStack()
        gs.add("explore the room", priority=3)
        ctx = gs.context()
        assert "ACTIVE GOALS" in ctx
        assert "explore the room" in ctx
        assert "[3]" in ctx

    def test_default_priority_is_3(self):
        gs = GoalStack()
        gs.add("test goal")
        assert gs.active[0]["priority"] == 3

    def test_default_expiry_is_5_minutes(self):
        gs = GoalStack()
        gs.add("test")
        with gs._lock:
            goal = gs._goals[0]
            remaining = goal["expiry"] - goal["created"]
        assert abs(remaining - 300.0) < 1.0


# ---------------------------------------------------------------------------
# Goal progress tracking (C3)
# ---------------------------------------------------------------------------

class TestGoalProgress:
    def test_update_progress_basic(self):
        gs = GoalStack()
        gs.add("check hallway")
        assert gs.update_progress(0.5) is True
        assert gs.active[0].get("progress") == 0.5

    def test_update_progress_with_note(self):
        gs = GoalStack()
        gs.add("check hallway")
        gs.update_progress(0.3, "looked at east side")
        goal = gs.active[0]
        assert goal.get("progress") == 0.3
        assert "looked at east side" in goal.get("progress_notes", [])

    def test_update_progress_clamps_fraction(self):
        gs = GoalStack()
        gs.add("test")
        gs.update_progress(1.5)
        assert gs.active[0].get("progress") == 1.0
        gs.update_progress(-0.5)
        assert gs.active[0].get("progress") == 0.0

    def test_update_progress_returns_false_when_empty(self):
        gs = GoalStack()
        assert gs.update_progress(0.5) is False

    def test_update_progress_extends_expiry(self):
        gs = GoalStack()
        gs.add("test")
        with gs._lock:
            old_expiry = gs._goals[0]["expiry"]
        gs.update_progress(0.5)
        with gs._lock:
            new_expiry = gs._goals[0]["expiry"]
        # New expiry is ~3 min from now, which should be different from old
        assert new_expiry != old_expiry

    def test_progress_notes_capped_at_3(self):
        gs = GoalStack()
        gs.add("test")
        for i in range(5):
            gs.update_progress(i * 0.2, f"note {i}")
        notes = gs.active[0].get("progress_notes", [])
        assert len(notes) == 3
        assert notes[0] == "note 2"
        assert notes[-1] == "note 4"

    def test_progress_note_truncated(self):
        gs = GoalStack()
        gs.add("test")
        long_note = "x" * 200
        gs.update_progress(0.5, long_note)
        notes = gs.active[0].get("progress_notes", [])
        assert len(notes[0]) == 80

    def test_context_shows_progress_percentage(self):
        gs = GoalStack()
        gs.add("check hallway", priority=3)
        gs.update_progress(0.6, "east side done")
        ctx = gs.context()
        assert "[60%]" in ctx

    def test_context_shows_latest_note(self):
        gs = GoalStack()
        gs.add("check hallway", priority=3)
        gs.update_progress(0.5, "started east")
        gs.update_progress(0.8, "almost done")
        ctx = gs.context()
        assert "almost done" in ctx

    def test_progress_backward_compatible(self):
        """Goals created without progress work via .get()."""
        gs = GoalStack()
        gs.add("old style goal")
        ctx = gs.context()
        # No percentage shown for 0 progress
        assert "[0%]" not in ctx

    def test_multiple_goals_progress_independent(self):
        gs = GoalStack()
        gs.add("goal A", priority=5)
        gs.add("goal B", priority=3)
        gs.update_progress(0.7)  # Updates top goal (A)
        assert gs.active[0].get("progress") == 0.7
        assert gs.active[1].get("progress", 0.0) == 0.0

    def test_update_progress_on_expired_goal(self):
        gs = GoalStack()
        gs.add("temp")
        with gs._lock:
            gs._goals[0]["expiry"] = 0.0
        assert gs.update_progress(0.5) is False


# ---------------------------------------------------------------------------
# Thought deduplication (A3)
# ---------------------------------------------------------------------------

class TestThoughtDedup:
    def _make_thinking(self):
        commander = MagicMock()
        commander.sensorium = MagicMock()
        commander.event_bus = MagicMock()
        tt = ThinkingThread(commander)
        return tt, commander

    def test_exact_duplicate_suppressed(self):
        """Exact match with _last_thought is suppressed."""
        tt, cmd = self._make_thinking()
        result = MotorOutput(action="think", params=["Scanning the room"], valid=True)
        tt._dispatch(result)
        assert cmd.sensorium.push.call_count == 1

        # Same thought again — should be suppressed
        result2 = MotorOutput(action="think", params=["Scanning the room"], valid=True)
        tt._dispatch(result2)
        assert cmd.sensorium.push.call_count == 1  # No additional call

    def test_prefix_duplicate_suppressed(self):
        """Shared 20-char lowercase prefix is suppressed."""
        tt, cmd = self._make_thinking()
        result = MotorOutput(action="think", params=["Observing the quiet command center and monitoring"], valid=True)
        tt._dispatch(result)

        # Similar thought with shared 20-char prefix
        result2 = MotorOutput(action="think", params=["Observing the quiet command center with interest"], valid=True)
        tt._dispatch(result2)
        assert cmd.sensorium.push.call_count == 1

    def test_different_thought_passes(self):
        """Completely different thought is not suppressed."""
        tt, cmd = self._make_thinking()
        result = MotorOutput(action="think", params=["Looking at the desk"], valid=True)
        tt._dispatch(result)

        result2 = MotorOutput(action="think", params=["I wonder what that noise was"], valid=True)
        tt._dispatch(result2)
        assert cmd.sensorium.push.call_count == 2

    def test_short_thought_not_prefix_matched(self):
        """Thoughts shorter than 20 chars skip prefix matching."""
        tt, cmd = self._make_thinking()
        result = MotorOutput(action="think", params=["Hmm, interesting"], valid=True)
        tt._dispatch(result)

        result2 = MotorOutput(action="think", params=["Hmm, intriguing!"], valid=True)
        tt._dispatch(result2)
        # Both should pass (different text, both < 20 chars prefix test skipped)
        assert cmd.sensorium.push.call_count == 2


# ---------------------------------------------------------------------------
# Scan dispatch no longer publishes thought (A1)
# ---------------------------------------------------------------------------

class TestScanDispatch:
    def test_scan_does_not_publish_thought(self):
        """scan() dispatch should NOT publish 'Scanning the area' to event_bus."""
        commander = MagicMock()
        commander.primary_camera = None
        commander.sensorium = MagicMock()
        commander.event_bus = MagicMock()
        commander.motor = None
        tt = ThinkingThread(commander)

        result = MotorOutput(action="scan", params=[], valid=True)
        tt._dispatch(result)

        # Should push to sensorium but NOT publish a thought event
        commander.sensorium.push.assert_called_once_with("motor", "Resumed scanning")
        # Verify no thought published
        for call in commander.event_bus.publish.call_args_list:
            assert call[0][0] != "thought"

    def test_scan_still_pushes_motor_event(self):
        """scan() still pushes 'Resumed scanning' to sensorium."""
        commander = MagicMock()
        commander.primary_camera = None
        commander.sensorium = MagicMock()
        commander.event_bus = MagicMock()
        commander.motor = None
        tt = ThinkingThread(commander)

        result = MotorOutput(action="scan", params=[], valid=True)
        tt._dispatch(result)
        commander.sensorium.push.assert_called_with("motor", "Resumed scanning")


# ---------------------------------------------------------------------------
# Unprompted speech guardrails (Fix 3)
# ---------------------------------------------------------------------------

class TestSpeechGuardrails:
    """Tests for speech suppression when nobody is present."""

    def _make_thinking(self, people_present=False, simulation_engine=None):
        commander = MagicMock()
        commander.sensorium = MagicMock()
        commander.sensorium.people_present = people_present
        commander.event_bus = MagicMock()
        commander._state = MagicMock()
        commander._state.value = "IDLE"
        commander._last_spoke = 0.0  # Long time ago
        commander.simulation_engine = simulation_engine
        tt = ThinkingThread(commander)
        return tt, commander

    def test_say_suppressed_when_nobody_present(self):
        """say() is suppressed to thought when nobody is present."""
        tt, cmd = self._make_thinking(people_present=False)
        result = MotorOutput(action="say", params=["Hello there!"], valid=True)
        tt._dispatch(result)
        # Should NOT call commander.say
        cmd.say.assert_not_called()
        # Should push suppression thought
        calls = [c for c in cmd.sensorium.push.call_args_list
                 if "suppressed" in str(c)]
        assert len(calls) >= 1

    def test_say_allowed_when_people_present(self):
        """say() proceeds normally when someone is present."""
        tt, cmd = self._make_thinking(people_present=True)
        result = MotorOutput(action="say", params=["Hello there!"], valid=True)
        tt._dispatch(result)
        cmd.say.assert_called_once_with("Hello there!")

    def test_say_cooldown_is_15_seconds(self):
        """say() cooldown is 15 seconds (not 8)."""
        import inspect
        source = inspect.getsource(ThinkingThread._dispatch)
        assert "< 15" in source

    def test_say_held_back_during_cooldown(self):
        """say() is held back when within 15s cooldown."""
        tt, cmd = self._make_thinking(people_present=True)
        # Set last_spoke to just now
        cmd._last_spoke = time.monotonic()
        result = MotorOutput(action="say", params=["Too soon!"], valid=True)
        tt._dispatch(result)
        cmd.say.assert_not_called()
        calls = [c for c in cmd.sensorium.push.call_args_list
                 if "held back" in str(c)]
        assert len(calls) >= 1

    def test_say_allowed_in_simulation_mode_without_people(self):
        """say() is allowed when simulation engine is active, even without
        people physically present (War Room operator is the audience)."""
        sim_engine = MagicMock()  # Truthy — simulation is active
        tt, cmd = self._make_thinking(
            people_present=False, simulation_engine=sim_engine
        )
        result = MotorOutput(action="say", params=["Contact north!"], valid=True)
        tt._dispatch(result)
        cmd.say.assert_called_once_with("Contact north!")


# ---------------------------------------------------------------------------
# Name hallucination prevention in thinking prompt (Fix 2)
# ---------------------------------------------------------------------------

class TestNameHallucinationPrompt:
    """Tests that thinking prompt prevents name guessing."""

    def test_prompt_warns_against_inventing_names(self):
        """THINKING_SYSTEM_PROMPT tells Amy never to invent names."""
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert "NEVER invent or guess names" in THINKING_SYSTEM_PROMPT

    def test_prompt_no_empty_room_speech(self):
        """THINKING_SYSTEM_PROMPT discourages speaking to empty rooms."""
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert "nobody is present" in THINKING_SYSTEM_PROMPT

    @pytest.mark.unit
    def test_prompt_includes_tactical_doctrine(self):
        """THINKING_SYSTEM_PROMPT includes tactical commander behavior."""
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        assert "TACTICAL COMMANDER DOCTRINE" in THINKING_SYSTEM_PROMPT
        assert "clear_threat()" in THINKING_SYSTEM_PROMPT
        assert "escalate()" in THINKING_SYSTEM_PROMPT
        assert "patrol()" in THINKING_SYSTEM_PROMPT
