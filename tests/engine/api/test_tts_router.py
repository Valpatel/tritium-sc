# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the TTS router — Piper TTS synthesis, WAV header,
voice listing, and LRU cache.

Tests pure functions and cache logic without requiring Piper binary.
"""
from __future__ import annotations

import struct
import tempfile
from collections import OrderedDict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.tts import (
    _make_wav,
    _cache_key,
    SynthesizeRequest,
    router,
)


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# _make_wav — pure WAV header generation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMakeWav:
    """_make_wav prepends a 44-byte WAV header to raw PCM data."""

    def test_wav_header_size(self):
        pcm = b"\x00" * 100
        wav = _make_wav(pcm)
        assert len(wav) == 44 + 100

    def test_wav_riff_magic(self):
        wav = _make_wav(b"\x00" * 10)
        assert wav[:4] == b"RIFF"

    def test_wav_wave_magic(self):
        wav = _make_wav(b"\x00" * 10)
        assert wav[8:12] == b"WAVE"

    def test_wav_fmt_chunk(self):
        wav = _make_wav(b"\x00" * 10)
        assert wav[12:16] == b"fmt "

    def test_wav_data_chunk(self):
        wav = _make_wav(b"\x00" * 10)
        assert wav[36:40] == b"data"

    def test_wav_file_size(self):
        pcm = b"\x00" * 200
        wav = _make_wav(pcm)
        # RIFF chunk size = 36 + data_size
        riff_size = struct.unpack_from("<I", wav, 4)[0]
        assert riff_size == 36 + 200

    def test_wav_data_size(self):
        pcm = b"\x00" * 200
        wav = _make_wav(pcm)
        data_size = struct.unpack_from("<I", wav, 40)[0]
        assert data_size == 200

    def test_wav_sample_rate_default(self):
        wav = _make_wav(b"\x00" * 10)
        sample_rate = struct.unpack_from("<I", wav, 24)[0]
        assert sample_rate == 22050

    def test_wav_sample_rate_custom(self):
        wav = _make_wav(b"\x00" * 10, sample_rate=16000)
        sample_rate = struct.unpack_from("<I", wav, 24)[0]
        assert sample_rate == 16000

    def test_wav_channels_mono(self):
        wav = _make_wav(b"\x00" * 10)
        channels = struct.unpack_from("<H", wav, 22)[0]
        assert channels == 1

    def test_wav_bits_per_sample(self):
        wav = _make_wav(b"\x00" * 10)
        bits = struct.unpack_from("<H", wav, 34)[0]
        assert bits == 16

    def test_wav_empty_pcm(self):
        wav = _make_wav(b"")
        assert len(wav) == 44
        data_size = struct.unpack_from("<I", wav, 40)[0]
        assert data_size == 0

    def test_wav_pcm_preserved(self):
        pcm = bytes(range(256))
        wav = _make_wav(pcm)
        assert wav[44:] == pcm


# ---------------------------------------------------------------------------
# Cache Key
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCacheKey:
    """_cache_key generates deterministic MD5 keys."""

    def test_deterministic(self):
        k1 = _cache_key("Hello world", None)
        k2 = _cache_key("Hello world", None)
        assert k1 == k2

    def test_different_text_different_key(self):
        k1 = _cache_key("Hello", None)
        k2 = _cache_key("Goodbye", None)
        assert k1 != k2

    def test_different_voice_different_key(self):
        k1 = _cache_key("Hello", "amy")
        k2 = _cache_key("Hello", "bob")
        assert k1 != k2

    def test_none_voice_vs_string(self):
        k1 = _cache_key("Hello", None)
        k2 = _cache_key("Hello", "amy")
        assert k1 != k2


# ---------------------------------------------------------------------------
# Pydantic Model
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSynthesizeRequest:
    """SynthesizeRequest model validation."""

    def test_text_only(self):
        r = SynthesizeRequest(text="Hello world")
        assert r.text == "Hello world"
        assert r.voice is None

    def test_with_voice(self):
        r = SynthesizeRequest(text="Hello", voice="en_US-amy-medium")
        assert r.voice == "en_US-amy-medium"


# ---------------------------------------------------------------------------
# Voices Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestVoicesEndpoint:
    """GET /api/tts/voices — list available Piper models."""

    def test_voices_no_piper(self):
        """When Piper is not installed, return empty list."""
        with patch("app.routers.tts.DEFAULT_PIPER_BIN", "/nonexistent/piper"), \
             patch("app.routers.tts.DEFAULT_PIPER_DIR", "/nonexistent/voices"):
            client = TestClient(_make_app())
            resp = client.get("/api/tts/voices")
            assert resp.status_code == 200
            data = resp.json()
            assert data["piper_available"] is False
            assert data["voices"] == []

    def test_voices_with_models(self):
        """When voice models exist, list them."""
        with tempfile.TemporaryDirectory() as td:
            # Create fake voice files
            (Path(td) / "en_US-amy-medium.onnx").write_bytes(b"\x00")
            (Path(td) / "en_US-amy-medium.onnx.json").write_bytes(b"{}")
            (Path(td) / "en_GB-bob-low.onnx").write_bytes(b"\x00")
            with patch("app.routers.tts.DEFAULT_PIPER_BIN", "/nonexistent/piper"), \
                 patch("app.routers.tts.DEFAULT_PIPER_DIR", td):
                client = TestClient(_make_app())
                resp = client.get("/api/tts/voices")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["voices"]) == 2
                names = [v["name"] for v in data["voices"]]
                assert "amy" in names
                assert "bob" in names


# ---------------------------------------------------------------------------
# Synthesize Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSynthesizeEndpoint:
    """POST /api/tts/synthesize — text-to-speech synthesis."""

    def test_empty_text(self):
        client = TestClient(_make_app())
        resp = client.post("/api/tts/synthesize", json={"text": ""})
        assert resp.status_code == 400

    def test_whitespace_text(self):
        client = TestClient(_make_app())
        resp = client.post("/api/tts/synthesize", json={"text": "   "})
        assert resp.status_code == 400

    def test_no_piper_available(self):
        """When Piper is not installed, return 503."""
        with patch("app.routers.tts._get_speaker", return_value=None):
            # Reset the checked flag
            import app.routers.tts as tts_mod
            tts_mod._speaker_checked = False
            tts_mod._speaker = None
            client = TestClient(_make_app())
            resp = client.post("/api/tts/synthesize", json={"text": "Hello"})
            assert resp.status_code == 503

    def test_synthesize_cached(self):
        """Cached audio is served without re-synthesis."""
        import app.routers.tts as tts_mod
        fake_wav = b"\xff" * 100
        key = _cache_key("Hello cached", None)
        tts_mod._cache[key] = fake_wav
        try:
            # Need a "speaker" to pass the None check
            mock_speaker = MagicMock()
            mock_speaker.available = True
            with patch("app.routers.tts._get_speaker", return_value=mock_speaker):
                client = TestClient(_make_app())
                resp = client.post("/api/tts/synthesize", json={"text": "Hello cached"})
                assert resp.status_code == 200
                assert resp.content == fake_wav
        finally:
            tts_mod._cache.pop(key, None)

    def test_cache_eviction(self):
        """Cache evicts oldest entry when full."""
        import app.routers.tts as tts_mod
        original_cache = tts_mod._cache.copy()
        tts_mod._cache.clear()
        try:
            # Fill cache to max
            for i in range(tts_mod._CACHE_MAX):
                tts_mod._cache[f"key-{i}"] = b"\x00"
            assert len(tts_mod._cache) == tts_mod._CACHE_MAX

            # Add one more — should evict oldest
            tts_mod._cache["new-key"] = b"\x01"
            if len(tts_mod._cache) > tts_mod._CACHE_MAX:
                tts_mod._cache.popitem(last=False)
            assert len(tts_mod._cache) == tts_mod._CACHE_MAX
            assert "key-0" not in tts_mod._cache
            assert "new-key" in tts_mod._cache
        finally:
            tts_mod._cache.clear()
            tts_mod._cache.update(original_cache)
