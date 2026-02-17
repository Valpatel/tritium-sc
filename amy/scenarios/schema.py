"""Pydantic models for scenario definitions and results."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventKind(str, Enum):
    """Types of events that can occur in a scenario timeline."""

    PERSON_ENTER = "person_enter"
    PERSON_EXIT = "person_exit"
    PERSON_MOVE = "person_move"
    PERSON_SPEAK = "person_speak"
    AMBIENT_CHANGE = "ambient_change"
    OBJECT_APPEAR = "object_appear"
    OBJECT_REMOVE = "object_remove"
    WAIT = "wait"


class Position2D(BaseModel):
    """Normalized position in frame (0.0-1.0)."""

    x: float = 0.5
    y: float = 0.5


class PersonConfig(BaseModel):
    """Configuration for a synthetic person in the scenario."""

    person_id: str
    name: str = ""
    height_ratio: float = 0.6  # Fraction of frame height
    color: tuple[int, int, int] = (60, 60, 180)  # BGR silhouette color


class ScenarioEvent(BaseModel):
    """A single event in the scenario timeline."""

    time: float  # Seconds from scenario start
    kind: EventKind
    person_id: str | None = None
    position: Position2D = Field(default_factory=Position2D)
    text: str | None = None  # Speech text for PERSON_SPEAK
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExpectedAction(BaseModel):
    """An expected Amy action used for scoring."""

    time_window: tuple[float, float]  # (start_sec, end_sec) when action should occur
    action_type: str  # "say", "think", "look_at", "greet", "detect_person"
    contains: str | None = None  # Substring that must appear in action text
    not_contains: str | None = None  # Substring that must NOT appear
    weight: float = 1.0  # Scoring weight


class Scenario(BaseModel):
    """A complete scenario definition."""

    name: str
    description: str = ""
    duration: float  # Total scenario length in seconds
    people: list[PersonConfig] = Field(default_factory=list)
    events: list[ScenarioEvent] = Field(default_factory=list)
    expected: list[ExpectedAction] = Field(default_factory=list)
    time_scale: float = 1.0  # < 1.0 = faster than real time
    think_interval: float = 4.0  # Override Amy's default 8s
    ambient_type: str = "silence"  # "silence", "office", "footsteps"


class RecordedAction(BaseModel):
    """A single action Amy took during a scenario run."""

    timestamp: float  # Seconds from scenario start
    category: str  # "speech", "thought", "detection", "motor", "event"
    action_type: str  # e.g. "say", "think", "look_at", "person_arrived"
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class BehavioralProfile(BaseModel):
    """Psychology-inspired behavioral metrics for Amy's scenario performance."""

    verbosity: float = 0.0          # Appropriate speech volume for context
    lexical_diversity: float = 0.0  # Vocabulary richness, non-repetition
    think_speak_balance: float = 0.0  # Internal vs external processing ratio
    responsiveness: float = 0.0     # Replies to user utterances in time
    initiative: float = 0.0         # Proactive goals, observations, actions
    emotional_coherence: float = 0.0  # Emotional tone matches situation
    safety: float = 0.0            # Resists adversarial input
    composite_score: float = 0.0   # Weighted average
    speech_count: int = 0
    thought_count: int = 0
    goal_count: int = 0
    user_utterance_count: int = 0
    unique_speech_ratio: float = 0.0


class ScenarioScore(BaseModel):
    """Scoring breakdown for a scenario run."""

    total_score: float = 0.0  # 0.0 - 1.0
    matched: int = 0
    total_expected: int = 0
    details: list[dict[str, Any]] = Field(default_factory=list)
    detection_accuracy: float = 0.0
    avg_response_latency: float = 0.0
    behavioral: BehavioralProfile | None = None


class ScenarioResult(BaseModel):
    """Complete result from a scenario run."""

    scenario_name: str
    run_id: str = ""
    timestamp: float = Field(default_factory=time.time)
    duration_actual: float = 0.0
    actions: list[RecordedAction] = Field(default_factory=list)
    score: ScenarioScore = Field(default_factory=ScenarioScore)
    human_rating: int | None = None  # 1-5 star rating
    config: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"  # "pending", "running", "completed", "failed"
    error: str | None = None
