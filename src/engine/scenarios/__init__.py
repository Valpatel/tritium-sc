# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Amy Synthetic World — scenario testing and evaluation framework.

Generates synthetic video + audio, runs through Amy's full pipeline,
scores her reactions, and enables human rating of results.
"""

from .schema import (
    EventKind,
    Position2D,
    PersonConfig,
    ScenarioEvent,
    ExpectedAction,
    Scenario,
    ScenarioScore,
    ScenarioResult,
    RecordedAction,
)
from .recorder import ActionRecorder
from .scorer import Scorer

__all__ = [
    "EventKind",
    "Position2D",
    "PersonConfig",
    "ScenarioEvent",
    "ExpectedAction",
    "Scenario",
    "ScenarioScore",
    "ScenarioResult",
    "RecordedAction",
    "ActionRecorder",
    "Scorer",
]
