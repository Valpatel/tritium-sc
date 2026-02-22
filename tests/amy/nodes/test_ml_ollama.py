"""ML integration tests for Ollama LLM connectivity."""

from __future__ import annotations

import urllib.request

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestOllamaConnectivity:
    """Tests for Ollama API reachability and chat responses."""

    def test_ollama_is_reachable(self):
        """Ollama server responds to GET /api/tags with 200."""
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200

    def test_ollama_chat_returns_message(self):
        """ollama_chat returns a response dict with a 'message' key."""
        from amy.brain.vision import ollama_chat

        response = ollama_chat(
            model="gemma3:4b",
            messages=[{"role": "user", "content": "Say hello in exactly 3 words."}],
        )
        assert "message" in response
        assert "content" in response["message"]
        assert len(response["message"]["content"].strip()) > 0

    def test_thinking_prompt_produces_valid_lua(self):
        """THINKING_SYSTEM_PROMPT + ollama_chat produces parseable Lua via parse_motor_output."""
        from amy.actions.lua_motor import parse_motor_output
        from amy.brain.thinking import THINKING_SYSTEM_PROMPT
        from amy.brain.vision import ollama_chat

        system = THINKING_SYSTEM_PROMPT.format(
            time_of_day="afternoon",
            narrative="5s ago: 1 person (nearby center)",
            battlespace="",
            memory="(no memories yet)",
            people="(no known people)",
            self_model="(no self-model yet)",
            thoughts="(none yet)",
            goals="(no goals set)",
            war_mode="",
        )

        response = ollama_chat(
            model="gemma3:4b",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": "What do you do next? Respond with a single Lua function call."},
            ],
        )

        response_text = response.get("message", {}).get("content", "").strip()
        assert len(response_text) > 0, "LLM returned empty response"

        result = parse_motor_output(response_text)
        assert result.valid is True, f"parse_motor_output failed: {result.error} (raw: {response_text!r})"
