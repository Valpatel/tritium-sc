"""Unit tests for ScenarioLibrary — load, list, save, rate, stats, export.

Uses temp directories so no real scenario files are needed.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from amy.scenarios.library import ScenarioLibrary
from amy.scenarios.schema import (
    Scenario, ScenarioEvent, ScenarioResult, ScenarioScore,
    RecordedAction, ExpectedAction, BehavioralProfile, EventKind,
)


def _make_scenario(name: str = "test_scenario", duration: float = 30.0) -> Scenario:
    return Scenario(
        name=name,
        description="A test scenario",
        duration=duration,
        events=[
            ScenarioEvent(time=5.0, kind=EventKind.PERSON_ENTER, person_id="p1"),
        ],
        expected=[
            ExpectedAction(time_window=(0, 10), action_type="greet"),
        ],
    )


def _make_result(
    name: str = "test_scenario",
    run_id: str = "run-001",
    score: float = 0.85,
    rating: int | None = None,
    model: str = "gemma3:4b",
) -> ScenarioResult:
    return ScenarioResult(
        scenario_name=name,
        run_id=run_id,
        duration_actual=30.0,
        actions=[
            RecordedAction(timestamp=3.0, category="speech", action_type="say", text="Hello"),
        ],
        score=ScenarioScore(
            total_score=score,
            matched=1,
            total_expected=1,
            behavioral=BehavioralProfile(composite_score=score),
        ),
        human_rating=rating,
        config={"chat_model": model},
        status="completed",
    )


@pytest.mark.unit
class TestScenarioLibraryCRUD:
    """Basic save/load/list operations."""

    def test_save_and_load_scenario(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            scenario = _make_scenario()
            path = lib.save_scenario(scenario)
            assert path.exists()

            loaded = lib.load_scenario("test_scenario")
            assert loaded.name == "test_scenario"
            assert loaded.duration == 30.0
            assert len(loaded.events) == 1

    def test_load_nonexistent_raises(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            with pytest.raises(FileNotFoundError):
                lib.load_scenario("nonexistent")

    def test_list_scenarios(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_scenario(_make_scenario("alpha"))
            lib.save_scenario(_make_scenario("beta"))

            listing = lib.list_scenarios()
            names = [s["name"] for s in listing]
            assert "alpha" in names
            assert "beta" in names

    def test_list_scenarios_empty(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            assert lib.list_scenarios() == []

    def test_list_scenarios_includes_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_scenario(_make_scenario("meta_test", duration=45.0))
            listing = lib.list_scenarios()
            assert listing[0]["duration"] == 45.0
            assert listing[0]["event_count"] == 1
            assert listing[0]["expected_count"] == 1


@pytest.mark.unit
class TestScenarioResults:
    """Result save/list/get operations."""

    def test_save_and_list_results(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_result(_make_result(run_id="run-001"))
            lib.save_result(_make_result(run_id="run-002"))

            results = lib.list_results("test_scenario")
            assert len(results) == 2

    def test_get_latest_result(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_result(_make_result(run_id="run-001", score=0.7))
            lib.save_result(_make_result(run_id="run-002", score=0.9))

            latest = lib.get_latest_result("test_scenario")
            assert latest is not None
            assert latest.score.total_score in (0.7, 0.9)

    def test_get_latest_none(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            assert lib.get_latest_result("nonexistent") is None

    def test_results_dir_created(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            assert (Path(td) / ".results").is_dir()


@pytest.mark.unit
class TestScenarioRating:
    """Human rating application."""

    def test_rate_result(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_result(_make_result(run_id="rated-001"))

            success = lib.rate_result("rated-001", 4)
            assert success is True

            # Verify persisted
            result = lib.get_latest_result("test_scenario")
            assert result.human_rating == 4

    def test_rate_clamps(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_result(_make_result(run_id="clamp-001"))

            lib.rate_result("clamp-001", 10)
            result = lib.get_latest_result("test_scenario")
            assert result.human_rating == 5  # Clamped

            lib.rate_result("clamp-001", -1)
            result = lib.get_latest_result("test_scenario")
            assert result.human_rating == 1  # Clamped

    def test_rate_nonexistent(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            assert lib.rate_result("nonexistent", 3) is False


@pytest.mark.unit
class TestScenarioStats:
    """Aggregate statistics."""

    def test_stats_empty(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_scenario(_make_scenario("empty_stats"))
            stats = lib.get_stats()
            assert "empty_stats" not in stats  # No results yet

    def test_stats_with_results(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_scenario(_make_scenario("stats_test"))
            lib.save_result(_make_result("stats_test", "r1", score=0.8, model="gemma3:4b"))
            lib.save_result(_make_result("stats_test", "r2", score=0.9, model="gemma3:4b"))
            lib.save_result(_make_result("stats_test", "r3", score=0.95, model="llama3:8b"))

            stats = lib.get_stats()
            assert "stats_test" in stats
            s = stats["stats_test"]
            assert s["run_count"] == 3
            assert s["best_score"] == 0.95
            assert "gemma3:4b" in s["by_model"]
            assert "llama3:8b" in s["by_model"]

    def test_stats_with_ratings(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_scenario(_make_scenario("rated_stats"))
            lib.save_result(_make_result("rated_stats", "r1", rating=4))
            lib.save_result(_make_result("rated_stats", "r2", rating=5))

            stats = lib.get_stats()
            assert stats["rated_stats"]["avg_rating"] == 4.5


@pytest.mark.unit
class TestScenarioExport:
    """Export for CSV/JSON analysis."""

    def test_export_all(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_scenario(_make_scenario("export_a"))
            lib.save_scenario(_make_scenario("export_b"))
            lib.save_result(_make_result("export_a", "r1"))
            lib.save_result(_make_result("export_b", "r2"))

            rows = lib.export_results()
            assert len(rows) == 2
            assert rows[0]["scenario"] in ("export_a", "export_b")
            assert "score" in rows[0]
            assert "beh_composite" in rows[0]

    def test_export_single_scenario(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_scenario(_make_scenario("only_this"))
            lib.save_result(_make_result("only_this", "r1"))
            lib.save_result(_make_result("other", "r2"))

            rows = lib.export_results("only_this")
            assert len(rows) == 1
            assert rows[0]["scenario"] == "only_this"

    def test_export_includes_behavioral(self):
        with tempfile.TemporaryDirectory() as td:
            lib = ScenarioLibrary(td)
            lib.save_scenario(_make_scenario("beh_export"))
            lib.save_result(_make_result("beh_export", "r1", score=0.9))

            rows = lib.export_results("beh_export")
            assert rows[0]["beh_composite"] == 0.9


# ---------------------------------------------------------------------------
# Schema models
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSchemaModels:
    """Pydantic model validation and defaults."""

    def test_scenario_defaults(self):
        s = Scenario(name="test", duration=10.0)
        assert s.time_scale == 1.0
        assert s.think_interval == 4.0
        assert s.ambient_type == "silence"
        assert s.events == []
        assert s.expected == []

    def test_recorded_action_defaults(self):
        a = RecordedAction(timestamp=1.0, category="speech", action_type="say")
        assert a.text == ""
        assert a.metadata == {}

    def test_scenario_result_defaults(self):
        r = ScenarioResult(scenario_name="test")
        assert r.status == "pending"
        assert r.actions == []
        assert r.human_rating is None

    def test_behavioral_profile_defaults(self):
        bp = BehavioralProfile()
        assert bp.composite_score == 0.0
        assert bp.speech_count == 0

    def test_event_kind_enum(self):
        assert EventKind.PERSON_ENTER.value == "person_enter"
        assert EventKind.WAIT.value == "wait"

    def test_expected_action_weight_default(self):
        ea = ExpectedAction(time_window=(0, 10), action_type="say")
        assert ea.weight == 1.0
