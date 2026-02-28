# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for ScenarioRunner and ScenarioLibrary."""

import json
import pytest
import time

from engine.scenarios.schema import (
    Scenario, ScenarioEvent, EventKind, Position2D, PersonConfig,
    ExpectedAction, ScenarioResult,
)
from engine.scenarios.library import ScenarioLibrary
from engine.scenarios.runner import ScenarioRunner


# ---------------------------------------------------------------------------
# ScenarioLibrary tests (no LLM needed)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestScenarioLibrary:
    def test_list_scenarios(self):
        """Should find the bundled scenario JSON files."""
        lib = ScenarioLibrary()
        scenarios = lib.list_scenarios()
        names = [s["name"] for s in scenarios]
        assert "intruder_basic" in names
        assert "empty_room" in names

    def test_load_scenario(self):
        lib = ScenarioLibrary()
        scenario = lib.load_scenario("intruder_basic")
        assert scenario.name == "intruder_basic"
        assert scenario.duration == 30.0
        assert len(scenario.events) > 0
        assert len(scenario.people) > 0

    def test_load_scenario_not_found(self):
        lib = ScenarioLibrary()
        with pytest.raises(FileNotFoundError):
            lib.load_scenario("nonexistent_scenario_xyz")

    def test_save_and_load_scenario(self, tmp_path):
        lib = ScenarioLibrary(tmp_path)
        scenario = Scenario(
            name="test_save",
            description="Test scenario",
            duration=10.0,
            events=[],
            expected=[],
        )
        lib.save_scenario(scenario)
        loaded = lib.load_scenario("test_save")
        assert loaded.name == "test_save"
        assert loaded.duration == 10.0

    def test_save_and_list_results(self, tmp_path):
        lib = ScenarioLibrary(tmp_path)
        # Create a scenario first
        scenario = Scenario(name="test_res", duration=5.0)
        lib.save_scenario(scenario)

        # Save a result
        result = ScenarioResult(
            scenario_name="test_res",
            run_id="run-abc123",
            status="completed",
        )
        lib.save_result(result)

        results = lib.list_results("test_res")
        assert len(results) == 1
        assert results[0].run_id == "run-abc123"

    def test_rate_result(self, tmp_path):
        lib = ScenarioLibrary(tmp_path)
        result = ScenarioResult(
            scenario_name="test_rate",
            run_id="run-rate01",
            status="completed",
        )
        lib.save_result(result)

        assert lib.rate_result("run-rate01", 4) is True
        loaded = lib.list_results("test_rate")
        assert loaded[0].human_rating == 4

    def test_get_latest_result(self, tmp_path):
        lib = ScenarioLibrary(tmp_path)
        scenario = Scenario(name="test_latest", duration=5.0)
        lib.save_scenario(scenario)

        r1 = ScenarioResult(scenario_name="test_latest", run_id="run-001", timestamp=100.0)
        r2 = ScenarioResult(scenario_name="test_latest", run_id="run-002", timestamp=200.0)
        lib.save_result(r1)
        lib.save_result(r2)

        latest = lib.get_latest_result("test_latest")
        assert latest is not None

    def test_get_stats_empty(self, tmp_path):
        lib = ScenarioLibrary(tmp_path)
        stats = lib.get_stats()
        assert stats == {}

    def test_get_stats_with_results(self, tmp_path):
        lib = ScenarioLibrary(tmp_path)
        scenario = Scenario(name="test_stats", duration=5.0)
        lib.save_scenario(scenario)

        from engine.scenarios.schema import ScenarioScore
        result = ScenarioResult(
            scenario_name="test_stats",
            run_id="run-s01",
            status="completed",
            score=ScenarioScore(total_score=0.75),
        )
        lib.save_result(result)

        stats = lib.get_stats()
        assert "test_stats" in stats
        assert stats["test_stats"]["avg_score"] == 0.75
        assert stats["test_stats"]["run_count"] == 1


# ---------------------------------------------------------------------------
# ScenarioRunner (unit-level: tests the wiring, not LLM output)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestScenarioRunnerUnit:
    def test_runner_creates_result(self):
        """Runner should produce a ScenarioResult even with no LLM."""
        scenario = Scenario(
            name="runner_test",
            description="Minimal test",
            duration=3.0,
            time_scale=0.05,
            think_interval=100.0,  # Effectively disable thinking
            people=[PersonConfig(person_id="p1")],
            events=[
                ScenarioEvent(
                    time=0.5, kind=EventKind.PERSON_ENTER,
                    person_id="p1", position=Position2D(x=0.5, y=0.6),
                ),
                ScenarioEvent(time=2.5, kind=EventKind.PERSON_EXIT, person_id="p1"),
            ],
            expected=[],
        )
        runner = ScenarioRunner(scenario, use_listener=False)
        result = runner.run()

        assert result.status == "completed"
        assert result.scenario_name == "runner_test"
        assert result.run_id.startswith("run-")
        assert result.duration_actual > 0
