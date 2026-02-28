# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for audio generation."""
import pytest
import numpy as np

from engine.scenarios.audio_gen import AudioGenerator


@pytest.mark.unit
class TestAudioGenerator:
    def test_init(self):
        gen = AudioGenerator()
        assert gen.sample_rate == 16000

    def test_custom_sample_rate(self):
        gen = AudioGenerator(sample_rate=22050)
        assert gen.sample_rate == 22050

    def test_silence_correct_length(self):
        gen = AudioGenerator()
        audio = gen.generate_ambient("silence", 1.0)
        assert len(audio) == 16000
        assert audio.dtype == np.float32

    def test_silence_near_zero(self):
        gen = AudioGenerator()
        audio = gen.generate_ambient("silence", 1.0)
        assert np.max(np.abs(audio)) < 0.1

    def test_office_ambient(self):
        gen = AudioGenerator()
        audio = gen.generate_ambient("office", 2.0)
        assert len(audio) == 32000
        assert audio.dtype == np.float32
        # Should have some signal (60Hz hum)
        assert np.max(np.abs(audio)) > 0.005

    def test_footsteps_ambient(self):
        gen = AudioGenerator()
        audio = gen.generate_ambient("footsteps", 2.0)
        assert len(audio) == 32000
        assert audio.dtype == np.float32
        assert np.max(np.abs(audio)) > 0.01

    def test_procedural_speech(self):
        gen = AudioGenerator()
        audio = gen._procedural_speech("Hello world")
        assert audio.dtype == np.float32
        assert len(audio) > 0
        # Should have actual signal
        assert np.max(np.abs(audio)) > 0.05

    def test_procedural_speech_different_texts(self):
        gen = AudioGenerator()
        a1 = gen._procedural_speech("Hello")
        a2 = gen._procedural_speech("Goodbye everyone")
        # Different texts should produce different lengths
        assert len(a1) != len(a2)

    def test_generate_speech_fallback(self):
        """Should fall through to procedural speech when gTTS unavailable."""
        gen = AudioGenerator()
        audio = gen.generate_speech("Test sentence")
        assert audio.dtype == np.float32
        assert len(audio) > 0

    def test_mix_same_length(self):
        gen = AudioGenerator()
        a = np.ones(100, dtype=np.float32) * 0.5
        b = np.ones(100, dtype=np.float32) * 0.3
        mixed = gen.mix_audio(a, b)
        assert len(mixed) == 100
        assert np.allclose(mixed, 0.8)

    def test_mix_different_lengths(self):
        gen = AudioGenerator()
        a = np.ones(100, dtype=np.float32) * 0.5
        b = np.ones(50, dtype=np.float32) * 0.3
        mixed = gen.mix_audio(a, b)
        assert len(mixed) == 100

    def test_mix_with_levels(self):
        gen = AudioGenerator()
        a = np.ones(100, dtype=np.float32)
        b = np.ones(100, dtype=np.float32)
        mixed = gen.mix_audio(a, b, levels=[0.5, 0.3])
        assert np.allclose(mixed, 0.8)

    def test_mix_clips_output(self):
        gen = AudioGenerator()
        a = np.ones(100, dtype=np.float32)
        b = np.ones(100, dtype=np.float32)
        mixed = gen.mix_audio(a, b)
        assert np.max(mixed) <= 1.0
        assert np.min(mixed) >= -1.0

    def test_mix_empty(self):
        gen = AudioGenerator()
        mixed = gen.mix_audio()
        assert len(mixed) == 0

    def test_ambient_preserves_range(self):
        """All ambient types should stay in [-1, 1]."""
        gen = AudioGenerator()
        for atype in ("silence", "office", "footsteps"):
            audio = gen.generate_ambient(atype, 1.0)
            assert np.max(np.abs(audio)) <= 1.0, f"{atype} out of range"
