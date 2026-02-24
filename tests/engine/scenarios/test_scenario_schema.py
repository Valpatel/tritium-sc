"""Unit tests for scenario schema models — Pydantic validation and defaults.

Pure model tests, no file I/O or runners needed.
"""
from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from engine.scenarios.schema import (
    EventKind,
    Position2D,
    PersonConfig,
    ScenarioEvent,
    ExpectedAction,
    Scenario,
    RecordedAction,
    BehavioralProfile,
    ScenarioScore,
    ScenarioResult,
)


# ===========================================================================
# EventKind Enum
# ===========================================================================

@pytest.mark.unit
class TestEventKind:
    """EventKind — scenario event types."""

    def test_all_values(self):
        kinds = [k.value for k in EventKind]
        assert "person_enter" in kinds
        assert "person_exit" in kinds
        assert "person_speak" in kinds
        assert "ambient_change" in kinds
        assert "wait" in kinds

    def test_string_enum(self):
        assert EventKind.PERSON_ENTER == "person_enter"


# ===========================================================================
# Position2D
# ===========================================================================

@pytest.mark.unit
class TestPosition2D:
    """Position2D — normalized frame position."""

    def test_defaults(self):
        p = Position2D()
        assert p.x == 0.5
        assert p.y == 0.5

    def test_custom(self):
        p = Position2D(x=0.1, y=0.9)
        assert p.x == 0.1
        assert p.y == 0.9


# ===========================================================================
# PersonConfig
# ===========================================================================

@pytest.mark.unit
class TestPersonConfig:
    """PersonConfig — synthetic person in scenario."""

    def test_minimal(self):
        p = PersonConfig(person_id="p1")
        assert p.person_id == "p1"
        assert p.name == ""

    def test_defaults(self):
        p = PersonConfig(person_id="p1")
        assert p.height_ratio == 0.6
        assert p.color == (60, 60, 180)

    def test_custom(self):
        p = PersonConfig(person_id="p1", name="Bob", height_ratio=0.8, color=(0, 255, 0))
        assert p.name == "Bob"
        assert p.height_ratio == 0.8


# ===========================================================================
# ScenarioEvent
# ===========================================================================

@pytest.mark.unit
class TestScenarioEvent:
    """ScenarioEvent — timeline event."""

    def test_minimal(self):
        e = ScenarioEvent(time=5.0, kind=EventKind.PERSON_ENTER)
        assert e.time == 5.0
        assert e.kind == EventKind.PERSON_ENTER
        assert e.person_id is None
        assert e.text is None

    def test_with_speech(self):
        e = ScenarioEvent(
            time=10.0, kind=EventKind.PERSON_SPEAK,
            person_id="p1", text="Hello Amy",
        )
        assert e.text == "Hello Amy"
        assert e.person_id == "p1"

    def test_default_position(self):
        e = ScenarioEvent(time=0, kind=EventKind.WAIT)
        assert e.position.x == 0.5
        assert e.position.y == 0.5

    def test_metadata(self):
        e = ScenarioEvent(
            time=1.0, kind=EventKind.AMBIENT_CHANGE,
            metadata={"weather": "rain"},
        )
        assert e.metadata["weather"] == "rain"


# ===========================================================================
# ExpectedAction
# ===========================================================================

@pytest.mark.unit
class TestExpectedAction:
    """ExpectedAction — scoring expectations."""

    def test_minimal(self):
        a = ExpectedAction(time_window=(0.0, 10.0), action_type="say")
        assert a.time_window == (0.0, 10.0)
        assert a.action_type == "say"

    def test_defaults(self):
        a = ExpectedAction(time_window=(5.0, 15.0), action_type="think")
        assert a.contains is None
        assert a.not_contains is None
        assert a.weight == 1.0

    def test_with_filters(self):
        a = ExpectedAction(
            time_window=(0, 5), action_type="say",
            contains="hello", not_contains="goodbye",
            weight=2.0,
        )
        assert a.contains == "hello"
        assert a.not_contains == "goodbye"
        assert a.weight == 2.0


# ===========================================================================
# Scenario
# ===========================================================================

@pytest.mark.unit
class TestScenario:
    """Scenario — complete definition."""

    def test_minimal(self):
        s = Scenario(name="test", duration=30.0)
        assert s.name == "test"
        assert s.duration == 30.0

    def test_defaults(self):
        s = Scenario(name="test", duration=10.0)
        assert s.people == []
        assert s.events == []
        assert s.expected == []
        assert s.time_scale == 1.0
        assert s.think_interval == 4.0
        assert s.ambient_type == "silence"

    def test_full(self):
        s = Scenario(
            name="encounter",
            description="Person walks in",
            duration=60.0,
            people=[PersonConfig(person_id="p1", name="Alice")],
            events=[
                ScenarioEvent(time=5.0, kind=EventKind.PERSON_ENTER, person_id="p1"),
            ],
            expected=[
                ExpectedAction(time_window=(5, 15), action_type="greet"),
            ],
            time_scale=0.5,
            think_interval=3.0,
            ambient_type="office",
        )
        assert len(s.people) == 1
        assert len(s.events) == 1
        assert s.time_scale == 0.5

    def test_model_dump_round_trip(self):
        s = Scenario(name="rt_test", duration=10.0)
        d = s.model_dump()
        s2 = Scenario(**d)
        assert s2.name == "rt_test"


# ===========================================================================
# RecordedAction
# ===========================================================================

@pytest.mark.unit
class TestRecordedAction:
    """RecordedAction — Amy action during a run."""

    def test_minimal(self):
        a = RecordedAction(timestamp=3.5, category="speech", action_type="say")
        assert a.timestamp == 3.5
        assert a.text == ""

    def test_with_text(self):
        a = RecordedAction(
            timestamp=5.0, category="speech",
            action_type="say", text="Hello there!",
        )
        assert a.text == "Hello there!"


# ===========================================================================
# BehavioralProfile
# ===========================================================================

@pytest.mark.unit
class TestBehavioralProfile:
    """BehavioralProfile — behavioral metrics."""

    def test_defaults(self):
        b = BehavioralProfile()
        assert b.verbosity == 0.0
        assert b.lexical_diversity == 0.0
        assert b.composite_score == 0.0
        assert b.speech_count == 0
        assert b.thought_count == 0

    def test_custom(self):
        b = BehavioralProfile(
            verbosity=0.8, lexical_diversity=0.7,
            responsiveness=1.0, safety=1.0,
            composite_score=0.95,
            speech_count=5, thought_count=12,
        )
        assert b.composite_score == 0.95
        assert b.speech_count == 5


# ===========================================================================
# ScenarioScore
# ===========================================================================

@pytest.mark.unit
class TestScenarioScore:
    """ScenarioScore — scoring breakdown."""

    def test_defaults(self):
        s = ScenarioScore()
        assert s.total_score == 0.0
        assert s.matched == 0
        assert s.total_expected == 0
        assert s.behavioral is None

    def test_with_behavioral(self):
        b = BehavioralProfile(composite_score=0.9)
        s = ScenarioScore(
            total_score=0.85, matched=4, total_expected=5,
            behavioral=b,
        )
        assert s.behavioral.composite_score == 0.9


# ===========================================================================
# ScenarioResult
# ===========================================================================

@pytest.mark.unit
class TestScenarioResult:
    """ScenarioResult — complete run result."""

    def test_minimal(self):
        r = ScenarioResult(scenario_name="test")
        assert r.scenario_name == "test"
        assert r.status == "pending"
        assert r.human_rating is None

    def test_defaults(self):
        r = ScenarioResult(scenario_name="test")
        assert r.run_id == ""
        assert r.actions == []
        assert r.config == {}
        assert r.error is None

    def test_timestamp_auto(self):
        before = time.time()
        r = ScenarioResult(scenario_name="test")
        after = time.time()
        assert before <= r.timestamp <= after

    def test_full(self):
        r = ScenarioResult(
            scenario_name="encounter",
            run_id="run-001",
            duration_actual=58.5,
            status="completed",
            actions=[RecordedAction(timestamp=3.0, category="speech", action_type="say", text="Hi")],
            score=ScenarioScore(total_score=0.9, matched=3, total_expected=4),
            human_rating=4,
            config={"chat_model": "qwen2.5:7b"},
        )
        assert r.status == "completed"
        assert len(r.actions) == 1
        assert r.human_rating == 4

    def test_model_dump_round_trip(self):
        r = ScenarioResult(scenario_name="rt", run_id="r1")
        d = r.model_dump()
        r2 = ScenarioResult(**d)
        assert r2.scenario_name == "rt"
