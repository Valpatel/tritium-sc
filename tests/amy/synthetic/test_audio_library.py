"""Unit tests for AudioLibrary — effect catalog, generation, caching, WAV writing.

Tests with tmp_path for isolated file I/O. Requires numpy only.
"""
from __future__ import annotations

import struct

import numpy as np
import pytest

from amy.audio.audio_library import (
    AudioLibrary,
    _EFFECT_CATALOG,
    _write_wav,
    _write_wav_raw,
)


# ===========================================================================
# WAV Writing
# ===========================================================================

@pytest.mark.unit
class TestWriteWav:
    """_write_wav and _write_wav_raw — PCM16 WAV file output."""

    def test_write_wav_raw_creates_file(self, tmp_path):
        path = tmp_path / "test.wav"
        audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
        pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        _write_wav_raw(str(path), pcm16, 16000)
        assert path.exists()
        assert path.stat().st_size > 44  # Header + some data

    def test_write_wav_raw_header(self, tmp_path):
        path = tmp_path / "test.wav"
        audio = np.zeros(16000, dtype=np.int16)  # 1 second of silence
        _write_wav_raw(str(path), audio, 16000)

        with open(path, "rb") as f:
            assert f.read(4) == b"RIFF"
            f.read(4)  # file size
            assert f.read(4) == b"WAVE"
            assert f.read(4) == b"fmt "
            chunk_size = struct.unpack("<I", f.read(4))[0]
            assert chunk_size == 16
            fmt = struct.unpack("<H", f.read(2))[0]
            assert fmt == 1  # PCM
            channels = struct.unpack("<H", f.read(2))[0]
            assert channels == 1
            sample_rate = struct.unpack("<I", f.read(4))[0]
            assert sample_rate == 16000

    def test_write_wav_creates_file(self, tmp_path):
        path = tmp_path / "test.wav"
        audio = np.sin(np.linspace(0, 2 * np.pi * 440, 16000)).astype(np.float32)
        _write_wav(str(path), audio, 16000)
        assert path.exists()

    def test_write_wav_clipping(self, tmp_path):
        """Values outside [-1, 1] are clipped, not wrapped."""
        path = tmp_path / "clipped.wav"
        audio = np.array([2.0, -2.0, 0.5], dtype=np.float32)
        _write_wav(str(path), audio, 16000)
        assert path.exists()


# ===========================================================================
# Effect Catalog
# ===========================================================================

@pytest.mark.unit
class TestEffectCatalog:
    """_EFFECT_CATALOG — static effect registry."""

    def test_catalog_not_empty(self):
        assert len(_EFFECT_CATALOG) > 0

    def test_all_entries_are_tuples(self):
        for name, entry in _EFFECT_CATALOG.items():
            assert isinstance(entry, tuple), f"{name} is not a tuple"
            assert len(entry) == 4, f"{name} has {len(entry)} elements, expected 4"

    def test_categories_valid(self):
        valid = {"combat", "ambient", "alerts", "game"}
        for name, (cat, _, _, _) in _EFFECT_CATALOG.items():
            assert cat in valid, f"{name} has unknown category {cat!r}"

    def test_durations_positive(self):
        for name, (_, _, dur, _) in _EFFECT_CATALOG.items():
            assert dur > 0, f"{name} has non-positive duration {dur}"

    def test_combat_effects_exist(self):
        combat = [n for n, (c, _, _, _) in _EFFECT_CATALOG.items() if c == "combat"]
        assert "nerf_shot" in combat
        assert "explosion" in combat

    def test_game_effects_exist(self):
        game = [n for n, (c, _, _, _) in _EFFECT_CATALOG.items() if c == "game"]
        assert "wave_start" in game
        assert "victory_fanfare" in game

    def test_elimination_streak_effects(self):
        streaks = [n for n in _EFFECT_CATALOG if "elimination_streak" in n]
        assert len(streaks) >= 4


# ===========================================================================
# AudioLibrary — Construction
# ===========================================================================

@pytest.mark.unit
class TestAudioLibraryInit:
    """AudioLibrary construction."""

    def test_default_path(self):
        lib = AudioLibrary()
        assert lib.library_path == "data/synthetic/audio"

    def test_custom_path(self, tmp_path):
        lib = AudioLibrary(str(tmp_path / "audio"))
        assert lib.library_path == str(tmp_path / "audio")


# ===========================================================================
# AudioLibrary — Effect Path
# ===========================================================================

@pytest.mark.unit
class TestAudioLibraryEffectPath:
    """AudioLibrary._effect_path — path resolution."""

    def test_known_effect(self, tmp_path):
        lib = AudioLibrary(str(tmp_path))
        path = lib._effect_path("nerf_shot")
        assert str(path).endswith("combat/nerf_shot.wav")

    def test_unknown_effect_raises(self, tmp_path):
        lib = AudioLibrary(str(tmp_path))
        with pytest.raises(KeyError, match="Unknown effect"):
            lib._effect_path("nonexistent")


# ===========================================================================
# AudioLibrary — Generation
# ===========================================================================

@pytest.mark.unit
class TestAudioLibraryGeneration:
    """AudioLibrary effect generation."""

    def test_generate_single_effect(self, tmp_path):
        lib = AudioLibrary(str(tmp_path))
        path = lib._generate_effect("nerf_shot")
        assert path.exists()
        assert path.suffix == ".wav"

    def test_generate_unknown_raises(self, tmp_path):
        lib = AudioLibrary(str(tmp_path))
        with pytest.raises(KeyError):
            lib._generate_effect("bogus")

    def test_get_effect_generates_lazily(self, tmp_path):
        lib = AudioLibrary(str(tmp_path))
        path = lib.get_effect("alert_tone")
        assert path.exists()

    def test_get_effect_returns_cached(self, tmp_path):
        lib = AudioLibrary(str(tmp_path))
        path1 = lib.get_effect("alert_tone")
        mtime1 = path1.stat().st_mtime
        path2 = lib.get_effect("alert_tone")
        mtime2 = path2.stat().st_mtime
        assert mtime1 == mtime2  # Same file, not regenerated

    def test_get_wav_bytes(self, tmp_path):
        lib = AudioLibrary(str(tmp_path))
        data = lib.get_wav_bytes("dispatch_ack")
        assert isinstance(data, bytes)
        assert len(data) > 44  # WAV header + data
        assert data[:4] == b"RIFF"

    def test_generate_all(self, tmp_path):
        lib = AudioLibrary(str(tmp_path))
        result = lib.generate_all()
        assert len(result) == len(_EFFECT_CATALOG)
        for name, path in result.items():
            assert path.exists(), f"{name} not generated"


# ===========================================================================
# AudioLibrary — Listing
# ===========================================================================

@pytest.mark.unit
class TestAudioLibraryListing:
    """AudioLibrary listing and category queries."""

    def test_list_effects_before_generation(self, tmp_path):
        lib = AudioLibrary(str(tmp_path))
        effects = lib.list_effects()
        assert len(effects) == len(_EFFECT_CATALOG)
        for e in effects:
            assert "name" in e
            assert "category" in e
            assert "duration" in e
            assert e["file_size"] == 0  # Not generated yet

    def test_list_effects_after_generation(self, tmp_path):
        lib = AudioLibrary(str(tmp_path))
        lib.generate_all()
        effects = lib.list_effects()
        for e in effects:
            assert e["file_size"] > 0, f"{e['name']} has 0 file size"

    def test_categories(self):
        cats = AudioLibrary.categories()
        assert "combat" in cats
        assert "ambient" in cats
        assert "alerts" in cats
        assert "game" in cats

    def test_effects_in_category(self):
        combat = AudioLibrary.effects_in_category("combat")
        assert "nerf_shot" in combat
        assert "explosion" in combat

    def test_effects_in_empty_category(self):
        result = AudioLibrary.effects_in_category("nonexistent")
        assert result == []
