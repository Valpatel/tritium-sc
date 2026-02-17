"""Unit tests for Amy Agent — LLM conversation management."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from amy.agent import Agent, SYSTEM_PROMPT, clean_speech


class _MinimalCommander:
    """Bare stand-in so Agent.__init__ doesn't need a real Commander."""

    primary_camera = None


@pytest.mark.unit
class TestAgentInit:
    """Tests for Agent initialization and history management."""

    def test_history_starts_with_system_prompt(self):
        """Default system prompt is inserted as first history message."""
        agent = Agent(commander=_MinimalCommander())
        assert len(agent.history) == 1
        assert agent.history[0]["role"] == "system"
        assert agent.history[0]["content"] == SYSTEM_PROMPT

    def test_custom_system_prompt(self):
        """A custom system prompt replaces the default."""
        agent = Agent(commander=_MinimalCommander(), system_prompt="You are a test bot.")
        assert agent.history[0]["content"] == "You are a test bot."


@pytest.mark.unit
class TestTrimHistory:
    """Tests for Agent._trim_history."""

    def test_trim_keeps_system_plus_max_history(self):
        """When over limit, trims to system message + last max_history entries."""
        agent = Agent(commander=_MinimalCommander(), max_history=4)
        # Add more messages than max_history
        for i in range(10):
            agent.history.append({"role": "user", "content": f"msg_{i}"})
        # 1 system + 10 user = 11, max_history=4, so trim to 1 + 4 = 5
        agent._trim_history()
        assert len(agent.history) == 5
        assert agent.history[0]["role"] == "system"
        assert agent.history[1]["content"] == "msg_6"
        assert agent.history[-1]["content"] == "msg_9"

    def test_trim_no_op_when_under_limit(self):
        """No trimming when history length is within max_history + 1."""
        agent = Agent(commander=_MinimalCommander(), max_history=20)
        agent.history.append({"role": "user", "content": "hello"})
        agent.history.append({"role": "assistant", "content": "hi"})
        # 1 system + 2 = 3, well under 20 + 1 = 21
        agent._trim_history()
        assert len(agent.history) == 3


@pytest.mark.unit
class TestProcessTurn:
    """Tests for Agent.process_turn message construction."""

    @patch("amy.agent.ollama_chat")
    def test_process_turn_builds_correct_message(self, mock_ollama):
        """process_turn assembles scene context + transcript into user message."""
        mock_ollama.return_value = {"message": {"content": "test response"}}

        agent = Agent(commander=_MinimalCommander(), use_tools=False)
        result = agent.process_turn(
            transcript="what do you see",
            scene_context="Visible: 1 person (center).",
        )

        assert result == "test response"
        # Check the user message that was sent
        call_args = mock_ollama.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0] if call_args[0] else None
        if messages is None:
            messages = call_args.kwargs["messages"]
        user_msg = messages[-2]  # Last message before the assistant response is appended
        assert "Visible: 1 person" in user_msg["content"]
        assert "what do you see" in user_msg["content"]

    @patch("amy.agent.ollama_chat")
    def test_process_turn_strips_stage_directions(self, mock_ollama):
        """Stage directions in LLM output should be stripped from response."""
        mock_ollama.return_value = {
            "message": {"content": '(I swivel my camera to focus on the person) "Hello there, welcome!"'}
        }
        agent = Agent(commander=_MinimalCommander(), use_tools=False)
        result = agent.process_turn(transcript="Hi Amy")
        assert "swivel" not in result
        assert "Hello there, welcome!" in result


@pytest.mark.unit
class TestCleanSpeech:
    """Tests for the clean_speech stage-direction stripper."""

    def test_strips_parenthetical_directions(self):
        text = '(Turns head slightly, focusing camera) "Hello there!"'
        assert clean_speech(text) == "Hello there!"

    def test_strips_asterisk_actions(self):
        text = '*A slight whirring sound is audible* Hello, welcome to the command center.'
        assert clean_speech(text) == "Hello, welcome to the command center."

    def test_preserves_short_parens(self):
        """Short parentheticals like (2pm) should be preserved."""
        text = "Meeting at (2pm) in the briefing room."
        assert "(2pm)" in clean_speech(text)

    def test_strips_multiple_directions(self):
        text = '(Camera adjusts) "Welcome!" (Sound of whirring) "How are you?"'
        result = clean_speech(text)
        assert "Camera adjusts" not in result
        assert "Sound of whirring" not in result
        assert "Welcome!" in result
        assert "How are you?" in result

    def test_plain_text_unchanged(self):
        text = "Hello! I see one person near the center."
        assert clean_speech(text) == text

    def test_strips_smart_quotes(self):
        text = '\u201cHello there, welcome!\u201d'
        assert clean_speech(text) == "Hello there, welcome!"

    def test_empty_after_strip(self):
        """If stripping removes everything, return empty string."""
        text = "(The camera pans slowly across the room)"
        assert clean_speech(text) == ""
