# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for LLM-based scenario generation.

At the start of each battle round, the system generates rich scenario context:
- Why is this battle happening?
- Who are the attackers and what do they want?
- What's the neighborhood's history?
- What are the stakes?
- What's the weather and time of day?
- What happened in the previous wave?

Each prompt returns structured JSON that gets parsed into scenario state.
Uses Ollama gemma3:4b by default, with scripted fallbacks.
"""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestScenarioGeneratorImport:
    def test_import(self):
        from engine.simulation.scenario_gen import ScenarioGenerator
        assert ScenarioGenerator is not None

    def test_create(self):
        from engine.simulation.scenario_gen import ScenarioGenerator
        gen = ScenarioGenerator()
        assert gen is not None


class TestPromptTemplates:
    """Test that all prompt templates produce valid prompts."""

    def test_all_prompts_exist(self):
        from engine.simulation.scenario_gen import SCENARIO_PROMPTS
        required = [
            "battle_reason",
            "attacker_background",
            "neighborhood_history",
            "stakes",
            "weather_atmosphere",
            "wave_briefing",
            "unit_orders",
            "aftermath",
        ]
        for key in required:
            assert key in SCENARIO_PROMPTS, f"Missing prompt: {key}"

    def test_prompts_are_strings(self):
        from engine.simulation.scenario_gen import SCENARIO_PROMPTS
        for key, prompt in SCENARIO_PROMPTS.items():
            assert isinstance(prompt, str)
            assert len(prompt) > 20

    def test_prompts_request_json(self):
        """All prompts should instruct the LLM to return JSON."""
        from engine.simulation.scenario_gen import SCENARIO_PROMPTS
        for key, prompt in SCENARIO_PROMPTS.items():
            assert "json" in prompt.lower() or "JSON" in prompt


class TestScriptedFallback:
    """Test scripted fallback scenario generation."""

    def test_generate_scripted_scenario(self):
        from engine.simulation.scenario_gen import ScenarioGenerator
        gen = ScenarioGenerator()
        scenario = gen.generate_scripted(wave=1, total_waves=10)
        assert isinstance(scenario, dict)
        assert "battle_reason" in scenario
        assert "attacker_background" in scenario
        assert "stakes" in scenario

    def test_scripted_varies_by_wave(self):
        """Different waves should produce different scenarios."""
        from engine.simulation.scenario_gen import ScenarioGenerator
        gen = ScenarioGenerator()
        s1 = gen.generate_scripted(wave=1, total_waves=10)
        s5 = gen.generate_scripted(wave=5, total_waves=10)
        s10 = gen.generate_scripted(wave=10, total_waves=10)
        # Not all identical
        reasons = {s1["battle_reason"], s5["battle_reason"], s10["battle_reason"]}
        assert len(reasons) >= 2

    def test_scripted_has_all_fields(self):
        from engine.simulation.scenario_gen import ScenarioGenerator
        gen = ScenarioGenerator()
        scenario = gen.generate_scripted(wave=3, total_waves=10)
        expected_keys = [
            "battle_reason", "attacker_background", "neighborhood_history",
            "stakes", "weather", "wave_briefing", "loading_messages",
        ]
        for key in expected_keys:
            assert key in scenario, f"Missing field: {key}"

    def test_loading_messages(self):
        """Scenario should include loading screen messages."""
        from engine.simulation.scenario_gen import ScenarioGenerator
        gen = ScenarioGenerator()
        scenario = gen.generate_scripted(wave=1, total_waves=10)
        msgs = scenario["loading_messages"]
        assert isinstance(msgs, list)
        assert len(msgs) >= 3


class TestLLMPromptBuilding:
    """Test building prompts for the LLM."""

    def test_build_all_prompts(self):
        from engine.simulation.scenario_gen import ScenarioGenerator
        gen = ScenarioGenerator()
        prompts = gen.build_prompts(wave=3, total_waves=10, score=1500)
        assert isinstance(prompts, dict)
        assert len(prompts) >= 5

    def test_prompts_include_wave_info(self):
        from engine.simulation.scenario_gen import ScenarioGenerator
        gen = ScenarioGenerator()
        prompts = gen.build_prompts(wave=7, total_waves=10, score=3000)
        # At least one prompt should mention the wave
        all_text = " ".join(prompts.values())
        assert "7" in all_text or "wave" in all_text.lower()


class TestScenarioCache:
    """Test that generated scenarios are cached."""

    def test_cache_scripted(self):
        from engine.simulation.scenario_gen import ScenarioGenerator
        gen = ScenarioGenerator()
        s1 = gen.generate_scripted(wave=1, total_waves=10)
        assert gen.get_current_scenario() is not None

    def test_reset_clears_cache(self):
        from engine.simulation.scenario_gen import ScenarioGenerator
        gen = ScenarioGenerator()
        gen.generate_scripted(wave=1, total_waves=10)
        gen.reset()
        assert gen.get_current_scenario() is None
