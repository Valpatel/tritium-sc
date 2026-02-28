# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for procedural sound effect generation pipeline.

TDD: These tests were written FIRST, then the implementation.
Covers: SoundEffectGenerator, AudioLibrary, WAV I/O, spectral distinctness.
"""

import os
import struct
import tempfile
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# SoundEffectGenerator tests
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16000

# Every effect method name and its default duration
EFFECTS = [
    ("nerf_shot", 0.3),
    ("projectile_whoosh", 0.5),
    ("impact_hit", 0.2),
    ("explosion", 1.0),
    ("turret_rotate", 0.8),
    ("drone_buzz", 2.0),
    ("footstep", 0.15),
    ("alert_tone", 0.5),
    ("escalation_siren", 2.0),
    ("dispatch_ack", 0.3),
    ("wave_start", 1.5),
    ("victory_fanfare", 3.0),
    ("defeat_sting", 2.0),
    ("ambient_wind", 5.0),
    ("ambient_birds", 5.0),
]


@pytest.mark.unit
class TestSoundEffectGenerator:
    """Core generator tests: dtype, shape, bounds, duration, no NaN/Inf."""

    @pytest.fixture(autouse=True)
    def _gen(self):
        from engine.audio.sound_effects import SoundEffectGenerator
        self.gen = SoundEffectGenerator()

    # -- parametrized over all effects --

    @pytest.mark.parametrize("method,duration", EFFECTS)
    def test_dtype_float32(self, method, duration):
        audio = getattr(self.gen, method)(duration=duration)
        assert audio.dtype == np.float32, f"{method} dtype is {audio.dtype}"

    @pytest.mark.parametrize("method,duration", EFFECTS)
    def test_normalized_bounds(self, method, duration):
        audio = getattr(self.gen, method)(duration=duration)
        assert np.all(audio >= -1.0), f"{method} has values below -1.0"
        assert np.all(audio <= 1.0), f"{method} has values above 1.0"

    @pytest.mark.parametrize("method,duration", EFFECTS)
    def test_no_nan_or_inf(self, method, duration):
        audio = getattr(self.gen, method)(duration=duration)
        assert not np.any(np.isnan(audio)), f"{method} contains NaN"
        assert not np.any(np.isinf(audio)), f"{method} contains Inf"

    @pytest.mark.parametrize("method,duration", EFFECTS)
    def test_duration_approximate(self, method, duration):
        """Duration within 10% of requested."""
        audio = getattr(self.gen, method)(duration=duration)
        expected_samples = int(duration * SAMPLE_RATE)
        tolerance = int(expected_samples * 0.10)
        assert abs(len(audio) - expected_samples) <= tolerance, (
            f"{method}: expected ~{expected_samples} samples, got {len(audio)}"
        )

    @pytest.mark.parametrize("method,duration", EFFECTS)
    def test_not_silent(self, method, duration):
        """Effect produces audible output (RMS > 0.001)."""
        audio = getattr(self.gen, method)(duration=duration)
        rms = np.sqrt(np.mean(audio ** 2))
        assert rms > 0.001, f"{method} is silent (RMS={rms:.6f})"

    @pytest.mark.parametrize("method,duration", EFFECTS)
    def test_1d_array(self, method, duration):
        """All effects produce 1D mono arrays."""
        audio = getattr(self.gen, method)(duration=duration)
        assert audio.ndim == 1, f"{method} is not 1D: shape={audio.shape}"


@pytest.mark.unit
class TestKillStreakEffect:
    """Kill streak effect with various streak names."""

    @pytest.fixture(autouse=True)
    def _gen(self):
        from engine.audio.sound_effects import SoundEffectGenerator
        self.gen = SoundEffectGenerator()

    @pytest.mark.parametrize("streak_name", [
        "ON A STREAK", "RAMPAGE", "DOMINATING", "GODLIKE",
    ])
    def test_elimination_streak_valid_names(self, streak_name):
        audio = self.gen.elimination_streak(streak_name, duration=1.5)
        assert audio.dtype == np.float32
        assert np.all(audio >= -1.0) and np.all(audio <= 1.0)
        assert len(audio) == int(1.5 * SAMPLE_RATE)

    def test_elimination_streak_unknown_name(self):
        """Unknown streak name should still produce audio (fallback)."""
        audio = self.gen.elimination_streak("UNKNOWN_STREAK", duration=1.0)
        assert audio.dtype == np.float32
        assert len(audio) == SAMPLE_RATE

    def test_elimination_streak_different_names_differ(self):
        """Different streak names should produce distinct waveforms."""
        np.random.seed(42)
        a = self.gen.elimination_streak("ON A STREAK", duration=1.0)
        np.random.seed(42)
        b = self.gen.elimination_streak("GODLIKE", duration=1.0)
        # Correlation should not be perfect
        corr = np.abs(np.corrcoef(a, b)[0, 1])
        assert corr < 0.99, f"KILLING SPREE and GODLIKE are too similar (corr={corr:.4f})"


@pytest.mark.unit
class TestDeterministicOutput:
    """Fixed seed produces identical output."""

    @pytest.fixture(autouse=True)
    def _gen(self):
        from engine.audio.sound_effects import SoundEffectGenerator
        self.gen = SoundEffectGenerator()

    @pytest.mark.parametrize("method", [
        "nerf_shot", "explosion", "ambient_birds", "alert_tone",
    ])
    def test_deterministic_with_seed(self, method):
        np.random.seed(123)
        a = getattr(self.gen, method)()
        np.random.seed(123)
        b = getattr(self.gen, method)()
        np.testing.assert_array_equal(a, b)


@pytest.mark.unit
class TestSpectralDistinctness:
    """Effects produce distinct spectral content (not the same waveform)."""

    @pytest.fixture(autouse=True)
    def _gen(self):
        from engine.audio.sound_effects import SoundEffectGenerator
        self.gen = SoundEffectGenerator()

    def _spectral_centroid(self, audio: np.ndarray) -> float:
        """Compute spectral centroid (center of mass of FFT magnitude)."""
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), d=1.0 / SAMPLE_RATE)
        if fft.sum() == 0:
            return 0.0
        return float(np.sum(freqs * fft) / np.sum(fft))

    def test_combat_vs_ambient_spectral_difference(self):
        """Combat sounds should have higher spectral centroid than ambient."""
        np.random.seed(99)
        shot = self.gen.nerf_shot(duration=0.3)
        wind = self.gen.ambient_wind(duration=0.3)
        sc_shot = self._spectral_centroid(shot)
        sc_wind = self._spectral_centroid(wind)
        # Shot should have more high-frequency energy than wind
        assert sc_shot > sc_wind, (
            f"nerf_shot centroid ({sc_shot:.0f}) should be > ambient_wind ({sc_wind:.0f})"
        )

    def test_alert_vs_footstep_different(self):
        """Alert tone (tonal) vs footstep (noise) should differ spectrally."""
        np.random.seed(99)
        alert = self.gen.alert_tone(duration=0.3)
        foot = self.gen.footstep(duration=0.15)
        # Pad footstep to same length for fair comparison
        foot_padded = np.zeros_like(alert)
        foot_padded[:len(foot)] = foot
        sc_alert = self._spectral_centroid(alert)
        sc_foot = self._spectral_centroid(foot_padded)
        assert abs(sc_alert - sc_foot) > 50, (
            f"alert_tone and footstep centroids too similar: {sc_alert:.0f} vs {sc_foot:.0f}"
        )

    def test_all_effects_pairwise_distinct(self):
        """No two effects should have correlation > 0.95 when normalized to same length."""
        np.random.seed(42)
        # Generate all effects at 1.0s to normalize length
        audios = {}
        for method, _ in EFFECTS:
            audios[method] = getattr(self.gen, method)(duration=1.0)

        names = list(audios.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a = audios[names[i]]
                b = audios[names[j]]
                # Truncate to same length
                min_len = min(len(a), len(b))
                corr = np.abs(np.corrcoef(a[:min_len], b[:min_len])[0, 1])
                assert corr < 0.95, (
                    f"{names[i]} and {names[j]} are too similar (corr={corr:.4f})"
                )


# ---------------------------------------------------------------------------
# WAV I/O tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWavIO:
    """WAV file writing and reading."""

    @pytest.fixture(autouse=True)
    def _gen(self):
        from engine.audio.sound_effects import SoundEffectGenerator
        self.gen = SoundEffectGenerator()

    def test_write_wav_scipy(self):
        """Write WAV with scipy, read back, verify PCM16 data."""
        audio = self.gen.nerf_shot(duration=0.3)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name

        try:
            from engine.audio.audio_library import _write_wav
            _write_wav(path, audio, SAMPLE_RATE)

            # Read back with scipy
            from scipy.io import wavfile
            rate, data = wavfile.read(path)
            assert rate == SAMPLE_RATE
            # Data should be int16
            assert data.dtype == np.int16
            # Convert back to float and check approximate match
            data_float = data.astype(np.float32) / 32767.0
            np.testing.assert_allclose(data_float, audio, atol=1e-3)
        finally:
            os.unlink(path)

    def test_write_wav_creates_file(self):
        """WAV file is created with valid RIFF header."""
        audio = self.gen.alert_tone(duration=0.2)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name

        try:
            from engine.audio.audio_library import _write_wav
            _write_wav(path, audio, SAMPLE_RATE)

            with open(path, "rb") as f:
                header = f.read(4)
                assert header == b"RIFF", f"Not a RIFF file: {header}"
                f.read(4)  # file size
                assert f.read(4) == b"WAVE"
        finally:
            os.unlink(path)

    def test_write_wav_file_size_reasonable(self):
        """File size should match: 44 (header) + samples * 2 (int16)."""
        audio = self.gen.nerf_shot(duration=0.3)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name

        try:
            from engine.audio.audio_library import _write_wav
            _write_wav(path, audio, SAMPLE_RATE)

            file_size = os.path.getsize(path)
            expected = 44 + len(audio) * 2  # 44 byte header + PCM16
            assert file_size == expected, f"Size {file_size} != expected {expected}"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# AudioLibrary tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAudioLibrary:
    """Audio library: lazy generation, listing, WAV bytes."""

    @pytest.fixture
    def lib(self, tmp_path):
        from engine.audio.audio_library import AudioLibrary
        return AudioLibrary(library_path=str(tmp_path / "audio"))

    def test_generate_all_returns_dict(self, lib):
        result = lib.generate_all()
        assert isinstance(result, dict)
        assert len(result) > 0
        for name, path in result.items():
            assert isinstance(name, str)
            assert Path(path).exists(), f"{name}: {path} does not exist"

    def test_generate_all_creates_wav_files(self, lib):
        result = lib.generate_all()
        for name, path in result.items():
            assert str(path).endswith(".wav"), f"{name} is not a .wav"
            assert os.path.getsize(str(path)) > 44, f"{name} too small"

    def test_get_effect_lazy_generation(self, lib):
        """First call generates, second call returns cached."""
        path1 = lib.get_effect("nerf_shot")
        assert path1.exists()
        mtime1 = path1.stat().st_mtime

        path2 = lib.get_effect("nerf_shot")
        assert path2 == path1
        # File should not have been regenerated
        assert path2.stat().st_mtime == mtime1

    def test_get_effect_unknown_raises(self, lib):
        with pytest.raises(KeyError):
            lib.get_effect("nonexistent_effect_xyz")

    def test_list_effects(self, lib):
        lib.generate_all()
        effects = lib.list_effects()
        assert isinstance(effects, list)
        assert len(effects) > 0
        for item in effects:
            assert "name" in item
            assert "duration" in item
            assert "file_size" in item
            assert "category" in item

    def test_get_wav_bytes(self, lib):
        wav_bytes = lib.get_wav_bytes("nerf_shot")
        assert isinstance(wav_bytes, bytes)
        assert wav_bytes[:4] == b"RIFF"
        assert wav_bytes[8:12] == b"WAVE"

    def test_categories_correct(self, lib):
        """Effects are sorted into combat/ambient/alerts/game categories."""
        lib.generate_all()
        effects = lib.list_effects()
        categories = set(e["category"] for e in effects)
        assert "combat" in categories
        assert "ambient" in categories
        assert "alerts" in categories
        assert "game" in categories

    def test_library_path_structure(self, lib):
        """Generated files live in category subdirectories."""
        lib.generate_all()
        lib_path = Path(lib.library_path)
        subdirs = {d.name for d in lib_path.iterdir() if d.is_dir()}
        assert "combat" in subdirs
        assert "ambient" in subdirs
        assert "alerts" in subdirs
        assert "game" in subdirs
