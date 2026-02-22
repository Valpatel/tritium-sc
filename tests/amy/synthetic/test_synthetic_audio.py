"""Tests for synthetic audio generation."""
import pytest
import numpy as np


@pytest.mark.unit
class TestSyntheticAudio:
    def test_ambient_shape(self):
        from amy.audio.synthetic import generate_ambient
        audio = generate_ambient(duration=2.0, sample_rate=16000)
        assert audio.shape == (32000,)
        assert audio.dtype == np.float32

    def test_ambient_quiet(self):
        from amy.audio.synthetic import generate_ambient
        audio = generate_ambient(duration=2.0)
        assert np.mean(np.abs(audio)) < 0.1

    def test_ambient_bounded(self):
        from amy.audio.synthetic import generate_ambient
        audio = generate_ambient()
        assert np.all(audio >= -1.0) and np.all(audio <= 1.0)

    def test_speech_tone_shape(self):
        from amy.audio.synthetic import generate_speech_tone
        audio = generate_speech_tone("hello world", duration=1.0, sample_rate=16000)
        assert audio.shape == (16000,)
        assert audio.dtype == np.float32

    def test_speech_tone_bounded(self):
        from amy.audio.synthetic import generate_speech_tone
        audio = generate_speech_tone()
        assert np.all(audio >= -1.0) and np.all(audio <= 1.0)

    def test_gunshot_shape(self):
        from amy.audio.synthetic import generate_gunshot
        audio = generate_gunshot(sample_rate=16000)
        assert len(audio) == 8000  # 0.5s at 16kHz
        assert audio.dtype == np.float32

    def test_gunshot_peak_then_decay(self):
        from amy.audio.synthetic import generate_gunshot
        audio = generate_gunshot()
        # Peak should be in first 10% of samples
        peak_idx = np.argmax(np.abs(audio))
        assert peak_idx < len(audio) * 0.1
        # Last 20% should be quieter than first 20%
        first_rms = np.sqrt(np.mean(audio[:len(audio)//5]**2))
        last_rms = np.sqrt(np.mean(audio[-len(audio)//5:]**2))
        assert last_rms < first_rms

    def test_gunshot_bounded(self):
        from amy.audio.synthetic import generate_gunshot
        audio = generate_gunshot()
        assert np.all(audio >= -1.0) and np.all(audio <= 1.0)
