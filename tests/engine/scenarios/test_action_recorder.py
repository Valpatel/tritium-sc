# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for ActionRecorder — event categorization and recording.

Tests the _record() method directly to avoid threading complexity.
"""
from __future__ import annotations

import time

import pytest

from engine.scenarios.recorder import ActionRecorder
from engine.scenarios.schema import RecordedAction


class _FakeEventBus:
    """Minimal EventBus stub for ActionRecorder construction."""

    def subscribe(self):
        import queue
        return queue.Queue()

    def unsubscribe(self, q):
        pass


# ===========================================================================
# Construction
# ===========================================================================

@pytest.mark.unit
class TestActionRecorderInit:
    """ActionRecorder — initialization."""

    def test_construction(self):
        bus = _FakeEventBus()
        rec = ActionRecorder(bus)
        assert rec.actions == []

    def test_custom_start_time(self):
        bus = _FakeEventBus()
        t = time.monotonic() - 10.0
        rec = ActionRecorder(bus, start_time=t)
        assert rec._start_time == t

    def test_default_start_time(self):
        bus = _FakeEventBus()
        before = time.monotonic()
        rec = ActionRecorder(bus)
        after = time.monotonic()
        assert before <= rec._start_time <= after


# ===========================================================================
# Event Recording — _record()
# ===========================================================================

@pytest.mark.unit
class TestActionRecorderRecord:
    """ActionRecorder._record() — event categorization."""

    def _make_recorder(self):
        bus = _FakeEventBus()
        return ActionRecorder(bus, start_time=time.monotonic())

    def test_transcript_amy_speech(self):
        rec = self._make_recorder()
        rec._record({"type": "transcript", "data": {"speaker": "amy", "text": "Hello there!"}})
        assert len(rec.actions) == 1
        assert rec.actions[0].category == "speech"
        assert rec.actions[0].action_type == "say"
        assert rec.actions[0].text == "Hello there!"

    def test_transcript_user_speech(self):
        rec = self._make_recorder()
        rec._record({"type": "transcript", "data": {"speaker": "user", "text": "Hi Amy"}})
        assert len(rec.actions) == 1
        assert rec.actions[0].category == "event"
        assert rec.actions[0].action_type == "user_speech"
        assert rec.actions[0].text == "Hi Amy"

    def test_thought(self):
        rec = self._make_recorder()
        rec._record({"type": "thought", "data": {"text": "I wonder who that is"}})
        assert rec.actions[0].category == "thought"
        assert rec.actions[0].action_type == "think"

    def test_detections_with_people(self):
        rec = self._make_recorder()
        rec._record({"type": "detections", "data": {
            "people": 2,
            "summary": "2 person(s) detected",
            "boxes": [{"cls": "person"}] * 2,
        }})
        assert rec.actions[0].category == "detection"
        assert rec.actions[0].action_type == "detect_person"
        assert rec.actions[0].metadata["people"] == 2

    def test_detections_zero_people_ignored(self):
        rec = self._make_recorder()
        rec._record({"type": "detections", "data": {"people": 0, "summary": "nothing"}})
        assert len(rec.actions) == 0

    def test_state_change(self):
        rec = self._make_recorder()
        rec._record({"type": "state_change", "data": {"state": "alert"}})
        assert rec.actions[0].category == "event"
        assert rec.actions[0].action_type == "state_change"
        assert rec.actions[0].text == "alert"

    def test_goal(self):
        rec = self._make_recorder()
        rec._record({"type": "goal", "data": {"text": "Greet visitor", "priority": 5}})
        assert rec.actions[0].category == "thought"
        assert rec.actions[0].action_type == "goal"
        assert rec.actions[0].metadata["priority"] == 5

    def test_goal_completed(self):
        rec = self._make_recorder()
        rec._record({"type": "goal_completed", "data": {"text": "Greeted visitor"}})
        assert rec.actions[0].category == "thought"
        assert rec.actions[0].action_type == "goal_completed"

    def test_event_person_detection(self):
        rec = self._make_recorder()
        rec._record({"type": "event", "data": {"text": "[YOLO: 1 person detected]"}})
        assert rec.actions[0].category == "detection"
        assert rec.actions[0].action_type == "person_event"

    def test_event_motor(self):
        rec = self._make_recorder()
        rec._record({"type": "event", "data": {"text": "motor scanning left"}})
        assert rec.actions[0].category == "motor"
        assert rec.actions[0].action_type == "motor_event"

    def test_event_look(self):
        rec = self._make_recorder()
        rec._record({"type": "event", "data": {"text": "looking at door"}})
        assert rec.actions[0].category == "motor"
        assert rec.actions[0].action_type == "motor_event"

    def test_event_generic(self):
        rec = self._make_recorder()
        rec._record({"type": "event", "data": {"text": "ambient noise detected"}})
        assert rec.actions[0].category == "event"
        assert rec.actions[0].action_type == "event"

    def test_unknown_event_ignored(self):
        rec = self._make_recorder()
        rec._record({"type": "unknown_event_type", "data": {}})
        assert len(rec.actions) == 0

    def test_timestamp_relative_to_start(self):
        start = time.monotonic() - 5.0
        bus = _FakeEventBus()
        rec = ActionRecorder(bus, start_time=start)
        rec._record({"type": "thought", "data": {"text": "test"}})
        assert rec.actions[0].timestamp >= 5.0


# ===========================================================================
# Filtered Properties
# ===========================================================================

@pytest.mark.unit
class TestActionRecorderFilters:
    """ActionRecorder — filtered property accessors."""

    def _make_populated_recorder(self):
        bus = _FakeEventBus()
        rec = ActionRecorder(bus, start_time=time.monotonic())
        rec._record({"type": "transcript", "data": {"speaker": "amy", "text": "Hi"}})
        rec._record({"type": "thought", "data": {"text": "thinking..."}})
        rec._record({"type": "detections", "data": {"people": 1, "summary": "1 person"}})
        rec._record({"type": "event", "data": {"text": "generic event"}})
        rec._record({"type": "goal", "data": {"text": "goal"}})
        return rec

    def test_speech_filter(self):
        rec = self._make_populated_recorder()
        assert len(rec.speech) == 1
        assert rec.speech[0].action_type == "say"

    def test_thoughts_filter(self):
        rec = self._make_populated_recorder()
        assert len(rec.thoughts) == 2  # thought + goal

    def test_detections_filter(self):
        rec = self._make_populated_recorder()
        assert len(rec.detections) == 1

    def test_all_actions(self):
        rec = self._make_populated_recorder()
        assert len(rec.all_actions) == 5

    def test_all_actions_returns_copy(self):
        rec = self._make_populated_recorder()
        actions = rec.all_actions
        actions.clear()
        assert len(rec.all_actions) == 5  # Original unchanged
