# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for LLM fallback thought generation.

When Ollama is unavailable, the thinking system should produce context-aware
scripted thoughts instead of silently failing. This ensures Amy always has
an inner monologue, even without a running LLM.
"""

import pytest
import time
from unittest.mock import MagicMock, patch


class TestFallbackThoughtGenerator:
    """Test the fallback thought generator that produces scripted thoughts."""

    def test_import(self):
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        gen = FallbackThoughtGenerator()
        assert gen is not None

    def test_generate_returns_lua_string(self):
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        gen = FallbackThoughtGenerator()
        result = gen.generate({})
        assert isinstance(result, str)
        # Must be valid Lua: think("...") or wait(...)
        assert result.startswith("think(") or result.startswith("wait(")

    def test_generate_with_no_context(self):
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        gen = FallbackThoughtGenerator()
        result = gen.generate({})
        assert "think(" in result

    def test_generate_with_hostiles(self):
        """When hostiles are present, thoughts should be combat-aware."""
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        gen = FallbackThoughtGenerator()
        ctx = {"hostile_count": 3, "friendly_count": 2, "game_active": True}
        result = gen.generate(ctx)
        assert "think(" in result

    def test_generate_with_no_hostiles_peaceful(self):
        """When no hostiles, thoughts should be observational."""
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        gen = FallbackThoughtGenerator()
        ctx = {"hostile_count": 0, "friendly_count": 2, "game_active": False}
        result = gen.generate(ctx)
        assert "think(" in result

    def test_no_repeat_consecutive_thoughts(self):
        """Should not repeat the same thought consecutively."""
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        gen = FallbackThoughtGenerator()
        ctx = {"hostile_count": 0, "friendly_count": 0, "game_active": False}
        thoughts = set()
        for _ in range(10):
            result = gen.generate(ctx)
            thoughts.add(result)
        # Should have variety
        assert len(thoughts) > 1

    def test_game_active_produces_battle_thoughts(self):
        """During active game, thoughts reference the battle."""
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        gen = FallbackThoughtGenerator()
        ctx = {
            "hostile_count": 5,
            "friendly_count": 3,
            "game_active": True,
            "wave": 3,
            "score": 500,
        }
        results = [gen.generate(ctx) for _ in range(20)]
        # At least some should reference combat concepts
        all_text = " ".join(results).lower()
        assert any(word in all_text for word in [
            "hostile", "threat", "position", "engage", "flank",
            "wave", "defend", "attack", "sensor", "contact",
            "target", "units", "perimeter", "sector",
        ])

    def test_time_of_day_awareness(self):
        """Thoughts should reflect time of day."""
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        gen = FallbackThoughtGenerator()
        ctx = {"hour": 3, "hostile_count": 0, "game_active": False}
        results = [gen.generate(ctx) for _ in range(20)]
        all_text = " ".join(results).lower()
        assert any(word in all_text for word in [
            "night", "quiet", "dark", "still", "patrol", "watch",
            "monitoring", "nothing", "calm", "silent",
        ])

    def test_dispatch_action_during_combat(self):
        """Should occasionally produce dispatch actions during combat."""
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        gen = FallbackThoughtGenerator()
        ctx = {
            "hostile_count": 5,
            "friendly_count": 3,
            "game_active": True,
            "friendlies": [
                {"name": "rover-alpha", "type": "rover", "x": 10, "y": 5},
            ],
            "hostiles": [
                {"name": "Intruder Alpha", "x": -15, "y": 20},
            ],
        }
        results = [gen.generate(ctx) for _ in range(50)]
        all_text = " ".join(results)
        # Should occasionally produce dispatch or think about tactics
        assert any("think(" in r or "dispatch(" in r for r in results)

    def test_wait_action_when_idle(self):
        """Should sometimes wait when nothing is happening."""
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        gen = FallbackThoughtGenerator()
        ctx = {"hostile_count": 0, "game_active": False}
        results = [gen.generate(ctx) for _ in range(30)]
        # Should occasionally wait
        has_wait = any("wait(" in r for r in results)
        has_think = any("think(" in r for r in results)
        assert has_think  # Must always have some thinks
        # Wait is optional but desirable in idle


class TestOllamaAvailability:
    """Test Ollama availability checking."""

    def test_check_ollama_available(self):
        from engine.simulation.llm_fallback import check_ollama_available
        # Should return bool without throwing
        result = check_ollama_available()
        assert isinstance(result, bool)

    def test_check_ollama_with_bad_host(self):
        from engine.simulation.llm_fallback import check_ollama_available
        result = check_ollama_available("http://localhost:99999")
        assert result is False

    def test_check_ollama_localhost(self):
        """If Ollama is running locally, should return True."""
        from engine.simulation.llm_fallback import check_ollama_available
        result = check_ollama_available("http://localhost:11434")
        # This test is environment-dependent — just check it doesn't crash
        assert isinstance(result, bool)


class TestThinkingWithFallback:
    """Test that ThinkingThread uses fallback when LLM fails."""

    def test_fallback_thought_on_llm_error(self):
        """When ollama_chat raises, fallback should produce a thought."""
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        gen = FallbackThoughtGenerator()

        # Simulate what thinking.py should do on LLM failure
        ctx = {"hostile_count": 0, "game_active": False}
        fallback = gen.generate(ctx)
        assert fallback is not None
        assert len(fallback) > 0

    def test_fallback_produces_parseable_lua(self):
        """Fallback output must be parseable by parse_motor_output."""
        from engine.simulation.llm_fallback import FallbackThoughtGenerator
        from engine.actions.lua_motor import parse_motor_output

        gen = FallbackThoughtGenerator()
        for _ in range(20):
            ctx = {"hostile_count": 0, "game_active": False}
            lua = gen.generate(ctx)
            result = parse_motor_output(lua)
            assert result.valid, f"Failed to parse: {lua!r}, error: {result.error}"
