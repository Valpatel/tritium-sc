# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for synthetic audio generation functions.

Tests that generated audio has correct shape, dtype, and range.
Pure numpy, no ML required.
"""
from __future__ import annotations

import numpy as np
import pytest

from engine.audio.synthetic import generate_ambient, generate_speech_tone, generate_gunshot


@pytest.mark.unit
class TestGenerateAmbient:
    """generate_ambient — pink noise + bird chirps."""

    def test_output_shape(self):
        audio = generate_ambient(duration=1.0, sample_rate=16000)
        assert audio.shape == (16000,)

    def test_output_dtype(self):
        audio = generate_ambient(duration=0.5)
        assert audio.dtype == np.float32

    def test_output_range(self):
        audio = generate_ambient(duration=2.0)
        assert np.all(audio >= -1.0)
        assert np.all(audio <= 1.0)

    def test_not_silence(self):
        audio = generate_ambient(duration=1.0)
        assert np.max(np.abs(audio)) > 0.001

    def test_custom_sample_rate(self):
        audio = generate_ambient(duration=1.0, sample_rate=8000)
        assert audio.shape == (8000,)

    def test_short_duration(self):
        audio = generate_ambient(duration=0.1)
        assert len(audio) == int(0.1 * 16000)


@pytest.mark.unit
class TestGenerateSpeechTone:
    """generate_speech_tone — syllable-like tone bursts."""

    def test_output_shape(self):
        audio = generate_speech_tone(text="hello world", duration=1.0)
        assert audio.shape == (16000,)

    def test_output_range(self):
        audio = generate_speech_tone(text="test", duration=0.5)
        assert np.all(audio >= -1.0)
        assert np.all(audio <= 1.0)

    def test_not_silence(self):
        audio = generate_speech_tone(text="test", duration=1.0)
        assert np.max(np.abs(audio)) > 0.01

    def test_single_word(self):
        audio = generate_speech_tone(text="hello", duration=0.5)
        assert len(audio) == int(0.5 * 16000)

    def test_multiple_words(self):
        audio = generate_speech_tone(text="hello world foo bar", duration=2.0)
        assert len(audio) == int(2.0 * 16000)

    def test_empty_text(self):
        """Empty text produces at least 1 syllable."""
        audio = generate_speech_tone(text="", duration=0.5)
        assert len(audio) == int(0.5 * 16000)


@pytest.mark.unit
class TestGenerateGunshot:
    """generate_gunshot — impulse with decay."""

    def test_output_shape(self):
        audio = generate_gunshot(sample_rate=16000)
        assert audio.shape == (8000,)  # 0.5s * 16000

    def test_output_range(self):
        audio = generate_gunshot()
        assert np.all(audio >= -1.0)
        assert np.all(audio <= 1.0)

    def test_not_silence(self):
        audio = generate_gunshot()
        assert np.max(np.abs(audio)) > 0.1

    def test_attack_is_loud(self):
        """First few samples should ramp up quickly."""
        audio = generate_gunshot()
        # By sample 100 (~6ms), should have significant amplitude
        assert np.max(np.abs(audio[:100])) > 0.1

    def test_decay(self):
        """End of audio should be quieter than start."""
        audio = generate_gunshot()
        early_energy = np.mean(np.abs(audio[:1000]))
        late_energy = np.mean(np.abs(audio[-1000:]))
        assert late_energy < early_energy

    def test_custom_sample_rate(self):
        audio = generate_gunshot(sample_rate=8000)
        assert len(audio) == int(0.5 * 8000)
