"""Unit tests for the Listener — hallucination filtering, silence detection,
audio-to-WAV conversion, and find_mic().

Hardware-dependent features (VAD, transcription) are skipped — these tests
focus on pure logic that runs without a microphone or GPU.
"""
from __future__ import annotations

import io
import re
import wave

import numpy as np
import pytest

# Import the module-level constants + class statics directly
# (Listener __init__ requires torch+whisper — we test without instantiating)
from amy.comms.listener import SAMPLE_RATE, SILENCE_PEAK_THRESHOLD, Listener


# ---------------------------------------------------------------------------
# Helpers — we test the class methods without going through __init__
# ---------------------------------------------------------------------------

def _filter(text: str) -> str:
    """Call _filter_hallucinations without instantiating Listener."""
    # Static-ish method — we can call it on an uninitialized "self"
    # by creating a minimal object that has the class attributes.
    return Listener._filter_hallucinations(Listener, text)


def _is_silence(audio: np.ndarray) -> bool:
    """Call is_silence without instantiation."""
    return Listener.is_silence(Listener, audio)


def _audio_to_wav(audio: np.ndarray) -> bytes:
    """Call _audio_to_wav_bytes without instantiation."""
    return Listener._audio_to_wav_bytes(Listener, audio)


# ---------------------------------------------------------------------------
# Hallucination filtering
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHallucinationFiltering:
    """Whisper hallucinates YouTube/recipe phrases on silence or noise."""

    def test_empty_string_returns_empty(self):
        assert _filter("") == ""

    def test_whitespace_returns_empty(self):
        assert _filter("   ") == ""

    def test_exact_hallucination_matches(self):
        for phrase in [
            "Thank you.", "thanks for watching", "you",
            "bye.", "the end", "subscribe", "\u2026",
        ]:
            assert _filter(phrase) == "", f"Should filter: {phrase!r}"

    def test_ellipsis_filtered(self):
        """'...' is a common whisper hallucination and should be filtered."""
        assert _filter("...") == ""

    def test_case_insensitive_exact(self):
        assert _filter("THANK YOU") == ""
        assert _filter("Thank You.") == ""
        assert _filter("THE END") == ""

    def test_trailing_punctuation_stripped(self):
        assert _filter("thank you!") == ""
        assert _filter("bye,") == ""
        assert _filter("the end?") == ""

    def test_pattern_welcome_channel(self):
        assert _filter("Welcome to my channel everyone") == ""
        assert _filter("welcome to our channel") == ""

    def test_pattern_subscribe(self):
        assert _filter("Don't forget to like and subscribe") == ""
        assert _filter("Please subscribe and share") == ""
        assert _filter("Hit the subscribe button") == ""

    def test_pattern_recipe(self):
        assert _filter("This is a delicious and simple recipe") == ""
        assert _filter("Easy chicken breast recipe") == ""

    def test_pattern_video(self):
        assert _filter("In this video we will learn") == ""
        assert _filter("Check the links in the description") == ""

    def test_pattern_see_you(self):
        assert _filter("See you in the next video") == ""

    def test_real_speech_passes_through(self):
        real = "Hey, can you look to the left?"
        assert _filter(real) == real

    def test_sentence_with_name(self):
        assert _filter("Hello Amy, how are you today?") == "Hello Amy, how are you today?"

    def test_long_real_sentence(self):
        text = "I think there might be someone at the front door, can you check?"
        assert _filter(text) == text

    def test_command_passes_through(self):
        assert _filter("Look at the backyard") == "Look at the backyard"

    def test_numbers_pass_through(self):
        assert _filter("There are 3 people outside") == "There are 3 people outside"


# ---------------------------------------------------------------------------
# Silence detection
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSilenceDetection:
    """is_silence() uses peak amplitude threshold."""

    def test_zeros_are_silence(self):
        audio = np.zeros(16000, dtype=np.float32)
        assert _is_silence(audio) is True

    def test_low_noise_is_silence(self):
        audio = np.random.uniform(-0.01, 0.01, 16000).astype(np.float32)
        assert _is_silence(audio) is True

    def test_speech_level_is_not_silence(self):
        audio = np.random.uniform(-0.5, 0.5, 16000).astype(np.float32)
        assert _is_silence(audio) is False

    def test_threshold_boundary(self):
        # Just below threshold
        audio = np.full(16000, SILENCE_PEAK_THRESHOLD - 0.001, dtype=np.float32)
        assert _is_silence(audio) is True

        # Just above threshold
        audio = np.full(16000, SILENCE_PEAK_THRESHOLD + 0.001, dtype=np.float32)
        assert _is_silence(audio) is False

    def test_single_spike(self):
        """A single loud sample should break silence."""
        audio = np.zeros(16000, dtype=np.float32)
        audio[8000] = 0.5
        assert _is_silence(audio) is False


# ---------------------------------------------------------------------------
# Audio to WAV conversion
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAudioToWav:
    """_audio_to_wav_bytes() produces valid WAV data."""

    def test_produces_valid_wav(self):
        audio = np.zeros(16000, dtype=np.float32)
        wav_bytes = _audio_to_wav(audio)
        assert wav_bytes[:4] == b"RIFF"

    def test_wav_params(self):
        audio = np.zeros(16000, dtype=np.float32)
        wav_bytes = _audio_to_wav(audio)
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2  # 16-bit
            assert wf.getframerate() == SAMPLE_RATE
            assert wf.getnframes() == 16000

    def test_short_audio(self):
        audio = np.zeros(512, dtype=np.float32)
        wav_bytes = _audio_to_wav(audio)
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnframes() == 512

    def test_clipping(self):
        """Values outside [-1, 1] should be clipped to int16 range."""
        audio = np.array([2.0, -2.0, 0.5], dtype=np.float32)
        wav_bytes = _audio_to_wav(audio)
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            frames = np.frombuffer(wf.readframes(3), dtype=np.int16)
            assert frames[0] == 32767   # clipped max
            assert frames[1] == -32768  # clipped min


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestListenerConstants:
    """Module-level constants are sensible."""

    def test_sample_rate(self):
        assert SAMPLE_RATE == 16000

    def test_silence_threshold_positive(self):
        assert 0 < SILENCE_PEAK_THRESHOLD < 1.0

    def test_hallucination_set_not_empty(self):
        assert len(Listener.HALLUCINATIONS) > 5

    def test_hallucination_patterns_compiled(self):
        for pat in Listener.HALLUCINATION_PATTERNS:
            assert isinstance(pat, re.Pattern)
