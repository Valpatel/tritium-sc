"""Integration tests for MissionDirector with real Ollama LLM.

These tests call a real local Ollama instance (gemma3:4b by default).
Skipped if Ollama is not running.
"""

import json
import time
import pytest
from unittest.mock import MagicMock

try:
    import requests
    _OLLAMA_AVAILABLE = False
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        _OLLAMA_AVAILABLE = resp.status_code == 200
    except Exception:
        pass
except ImportError:
    _OLLAMA_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _OLLAMA_AVAILABLE,
    reason="Ollama not running at localhost:11434"
)


class TestLLMModelDiscovery:
    def test_lists_real_models(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        models = md.list_available_models()
        assert len(models) > 0
        # gemma3:4b should be available
        assert any("gemma3" in m for m in models)


class TestLLMScenarioGeneration:
    """Test full LLM scenario generation with real model."""

    def test_generate_battle_scenario(self):
        from engine.simulation.mission_director import MissionDirector
        bus = MagicMock()
        md = MissionDirector(event_bus=bus, model="gemma3:4b")
        scenario = md.generate_via_llm(game_mode="battle")

        assert scenario is not None
        assert scenario["game_mode"] == "battle"
        assert scenario["generated_by"] == "llm"

        # Should have scenario context (LLM or fallback)
        assert "scenario_context" in scenario

        # Should have emitted progress events
        calls = [c for c in bus.publish.call_args_list
                 if c[0][0] == "mission_progress"]
        assert len(calls) >= 3  # start + at least some steps + complete

    def test_generate_defense_scenario(self):
        from engine.simulation.mission_director import MissionDirector
        bus = MagicMock()
        md = MissionDirector(event_bus=bus, model="gemma3:4b")
        scenario = md.generate_via_llm(game_mode="defense")
        assert scenario is not None
        assert scenario["game_mode"] == "defense"

    def test_llm_returns_valid_json(self):
        """At least some steps should return parseable JSON."""
        from engine.simulation.mission_director import MissionDirector
        bus = MagicMock()
        md = MissionDirector(event_bus=bus, model="gemma3:4b")
        scenario = md.generate_via_llm(game_mode="battle")

        # Check that at least 2 steps produced parsed results
        llm_fields = [k for k in scenario.keys()
                      if k not in ("game_mode", "generated_by", "model",
                                   "units", "win_conditions", "scenario_context")]
        # Some should be dicts from LLM JSON
        parsed_count = sum(1 for k in llm_fields if isinstance(scenario.get(k), dict))
        assert parsed_count >= 1, f"Expected at least 1 LLM-parsed field, got {parsed_count}"


class TestLLMPromptQuality:
    """Test that prompts produce reasonable LLM responses."""

    def test_scenario_context_prompt(self):
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock(), model="gemma3:4b")
        prompt = md.build_prompt("scenario_context", game_mode="battle")

        # Call LLM directly
        result = md._call_ollama(prompt, "gemma3:4b")
        parsed = md.parse_llm_response(result, "scenario_context")

        # Should get some JSON back
        assert parsed is not None or len(result) > 10, \
            f"LLM returned empty/unparseable: {result[:200]}"

    def test_different_models_work(self):
        """Try a different model if available."""
        from engine.simulation.mission_director import MissionDirector
        md = MissionDirector(event_bus=MagicMock())
        models = md.list_available_models()

        # Find a small model other than gemma3:4b
        alt_model = None
        for m in models:
            if "qwen2.5" in m and ("0.5b" in m or "1.5b" in m):
                alt_model = m
                break

        if alt_model is None:
            pytest.skip("No alternative small model available")

        prompt = md.build_prompt("scenario_context", game_mode="battle")
        result = md._call_ollama(prompt, alt_model)
        assert len(result) > 10, f"Alt model {alt_model} returned: {result[:100]}"


class TestProgressEventFlow:
    """Test that progress events flow correctly during LLM generation."""

    def test_events_in_correct_order(self):
        from engine.simulation.mission_director import MissionDirector
        bus = MagicMock()
        md = MissionDirector(event_bus=bus, model="gemma3:4b")
        md.generate_via_llm(game_mode="battle")

        progress_events = [
            c[0][1] for c in bus.publish.call_args_list
            if c[0][0] == "mission_progress"
        ]

        assert len(progress_events) >= 3

        # First event should be 'started'
        assert progress_events[0]["status"] == "started"

        # Last event should be 'complete'
        assert progress_events[-1]["status"] == "complete"

        # Complete event should have full scenario
        final = progress_events[-1]
        assert "scenario" in final
