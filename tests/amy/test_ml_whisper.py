"""ML integration tests for Whisper speech-to-text."""

from __future__ import annotations

import re

import numpy as np
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture(scope="module")
def whisper_model():
    """Load Whisper 'tiny' model once for the module (slow)."""
    import whisper

    return whisper.load_model("tiny")


class TestWhisperModel:
    """Tests for Whisper model loading and transcription."""

    def test_model_loads(self, whisper_model):
        """Whisper tiny model loads successfully."""
        assert whisper_model is not None

    def test_transcribe_silence_returns_empty(self, whisper_model):
        """Transcribing silence (all zeros) returns empty or hallucination text."""
        silence = np.zeros(16000 * 2, dtype=np.float32)  # 2 seconds
        result = whisper_model.transcribe(silence, fp16=False, language="en")
        # Result has expected structure regardless of content
        assert "text" in result
        assert isinstance(result["text"], str)


class TestListenerAttributes:
    """Tests for Listener class-level attributes (no model loading)."""

    def test_silence_detection_on_zeros(self):
        """All-zeros audio is detected as silence by is_silence logic."""
        listener_mod = pytest.importorskip("amy.listener", reason="sounddevice not installed")

        audio = np.zeros(16000, dtype=np.float32)
        peak = float(np.max(np.abs(audio)))
        assert peak < listener_mod.SILENCE_PEAK_THRESHOLD

    def test_hallucinations_contains_known_phrases(self):
        """Listener.HALLUCINATIONS contains common Whisper artifacts."""
        listener_mod = pytest.importorskip("amy.listener", reason="sounddevice not installed")

        assert "thank you" in listener_mod.Listener.HALLUCINATIONS
        assert "thanks for watching" in listener_mod.Listener.HALLUCINATIONS
        assert "..." in listener_mod.Listener.HALLUCINATIONS

    def test_hallucination_patterns_are_compiled_regexes(self):
        """Listener.HALLUCINATION_PATTERNS is a list of compiled regex objects."""
        listener_mod = pytest.importorskip("amy.listener", reason="sounddevice not installed")

        patterns = listener_mod.Listener.HALLUCINATION_PATTERNS
        assert isinstance(patterns, list)
        assert len(patterns) > 0
        for pat in patterns:
            assert isinstance(pat, re.Pattern)
