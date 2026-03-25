# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the HackRF FM radio player.

Tests the DSP pipeline, WAV encoding, tune/status, and scan logic
using synthetic IQ data (no hardware required).
"""

import asyncio
import base64
import io
import sys
import wave

import numpy as np
import pytest

# Ensure addon is importable — prefer tritium-addons submodule, fall back to local
import os as _os
_addons_root = _os.path.join(_os.path.dirname(__file__), "..", "..", "..", "..", "tritium-addons", "hackrf")
if _os.path.isdir(_addons_root):
    sys.path.insert(0, _addons_root)
else:
    sys.path.insert(0, "addons/hackrf")

from hackrf_addon.fm_player import FMPlayer, SAMPLE_RATE, AUDIO_RATE


@pytest.fixture
def player():
    """Create an FMPlayer instance with DSP initialized."""
    p = FMPlayer()
    p._init_dsp()
    return p


class TestTune:
    """Test frequency tuning."""

    def test_tune_valid_frequency(self, player):
        result = player.tune(92.5)
        assert result["success"] is True
        assert result["freq_mhz"] == 92.5
        assert result["freq_hz"] == 92_500_000

    def test_tune_below_fm_band(self, player):
        result = player.tune(50.0)
        assert result["success"] is False
        assert "out of FM broadcast range" in result["error"]

    def test_tune_above_fm_band(self, player):
        result = player.tune(200.0)
        assert result["success"] is False

    def test_tune_edge_low(self, player):
        result = player.tune(87.5)
        assert result["success"] is True

    def test_tune_edge_high(self, player):
        result = player.tune(108.0)
        assert result["success"] is True

    def test_tune_known_station(self, player):
        # Use a Bay Area station that exists in the database
        result = player.tune(88.5)  # KQED NPR
        assert result["success"] is True
        assert "KQED" in result["station"] or "Unknown" not in result["station"]


class TestGetStatus:
    """Test status reporting."""

    def test_status_default(self, player):
        status = player.get_status()
        assert status["playing"] is False
        assert status["freq_mhz"] == 0.0
        assert status["chunks_produced"] == 0

    def test_status_after_tune(self, player):
        player.tune(92.5)
        status = player.get_status()
        assert status["freq_mhz"] == 92.5
        assert status["playing"] is False


class TestDSPInit:
    """Test DSP coefficient initialization."""

    def test_lpf_coefficients(self, player):
        assert player._lpf_coeffs is not None
        assert len(player._lpf_coeffs) == 101

    def test_decimation_factor(self, player):
        assert player._decimation_factor == SAMPLE_RATE // AUDIO_RATE
        assert player._decimation_factor == 41

    def test_deemphasis_alpha(self, player):
        # 75us de-emphasis at 48kHz: dt/(tau+dt) = (1/48000)/(75e-6 + 1/48000)
        expected = (1.0 / AUDIO_RATE) / (75e-6 + 1.0 / AUDIO_RATE)
        assert abs(player._deemph_alpha - expected) < 1e-6


class TestWAVEncoding:
    """Test WAV chunk encoding."""

    def test_encode_wav_basic(self):
        audio = np.zeros(4800, dtype=np.float32)
        wav_b64 = FMPlayer._encode_wav_chunk(audio, AUDIO_RATE)
        assert isinstance(wav_b64, str)
        assert len(wav_b64) > 0

    def test_encode_wav_roundtrip(self):
        # Generate 1 second of 440 Hz sine
        t = np.arange(AUDIO_RATE) / AUDIO_RATE
        audio = (np.sin(2 * np.pi * 440 * t) * 0.8).astype(np.float32)

        wav_b64 = FMPlayer._encode_wav_chunk(audio, AUDIO_RATE)
        wav_data = base64.b64decode(wav_b64)

        buf = io.BytesIO(wav_data)
        with wave.open(buf, "r") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == AUDIO_RATE
            assert wf.getnframes() == AUDIO_RATE  # 1 second

    def test_encode_wav_clipping(self):
        # Audio beyond [-1, 1] should be clipped
        audio = np.array([2.0, -2.0, 0.5], dtype=np.float32)
        wav_b64 = FMPlayer._encode_wav_chunk(audio, AUDIO_RATE)
        wav_data = base64.b64decode(wav_b64)

        buf = io.BytesIO(wav_data)
        with wave.open(buf, "r") as wf:
            frames = np.frombuffer(wf.readframes(3), dtype=np.int16)
            assert frames[0] == 32767   # Clipped to max
            assert frames[1] == -32767  # Clipped to min


class TestFMDemodulation:
    """Test FM demodulation with synthetic IQ data."""

    @staticmethod
    def _generate_fm_iq(audio_freq: float = 1000.0, duration: float = 0.5) -> bytes:
        """Generate synthetic FM-modulated IQ as interleaved int8 bytes."""
        n_samples = int(SAMPLE_RATE * duration)
        t = np.arange(n_samples) / SAMPLE_RATE

        # Audio signal
        audio = np.sin(2 * np.pi * audio_freq * t)

        # FM modulate (75 kHz deviation)
        phase = 2 * np.pi * 75000 * np.cumsum(audio) / SAMPLE_RATE
        iq = np.exp(1j * phase).astype(np.complex64)

        # Convert to interleaved int8
        raw = np.empty(n_samples * 2, dtype=np.int8)
        raw[0::2] = np.clip(iq.real * 127, -128, 127).astype(np.int8)
        raw[1::2] = np.clip(iq.imag * 127, -128, 127).astype(np.int8)
        return raw.tobytes()

    def test_demod_recovers_tone(self, player):
        """Demodulate synthetic FM and verify recovered tone frequency."""
        from scipy.signal import lfilter

        raw_bytes = self._generate_fm_iq(1000.0, 0.5)
        raw = np.frombuffer(raw_bytes, dtype=np.int8)

        # Convert to complex
        iq = (raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)) / 128.0

        # LPF
        iq_filtered = lfilter(player._lpf_coeffs, 1.0, iq)

        # FM discriminator
        iq_diff = iq_filtered[1:] * np.conj(iq_filtered[:-1])
        fm_demod = np.angle(iq_diff)

        # Decimate
        dec = player._decimation_factor
        n_out = len(fm_demod) // dec
        audio = fm_demod[:n_out * dec].reshape(n_out, dec).mean(axis=1)

        # Check peak frequency via FFT
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1 / AUDIO_RATE)
        peak_freq = freqs[np.argmax(fft[1:]) + 1]

        # Should be within 200 Hz of 1000 Hz
        assert abs(peak_freq - 1000) < 200, f"Recovered {peak_freq} Hz, expected ~1000 Hz"

    def test_demod_different_frequencies(self, player):
        """Test demodulation at different audio frequencies."""
        from scipy.signal import lfilter

        for test_freq in [440, 2000, 5000]:
            raw_bytes = self._generate_fm_iq(test_freq, 0.5)
            raw = np.frombuffer(raw_bytes, dtype=np.int8)
            iq = (raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)) / 128.0
            iq_filtered = lfilter(player._lpf_coeffs, 1.0, iq)
            iq_diff = iq_filtered[1:] * np.conj(iq_filtered[:-1])
            fm_demod = np.angle(iq_diff)
            dec = player._decimation_factor
            n_out = len(fm_demod) // dec
            audio = fm_demod[:n_out * dec].reshape(n_out, dec).mean(axis=1)
            fft = np.abs(np.fft.rfft(audio))
            freqs = np.fft.rfftfreq(len(audio), 1 / AUDIO_RATE)
            peak_freq = freqs[np.argmax(fft[1:]) + 1]
            assert abs(peak_freq - test_freq) < 300, \
                f"At {test_freq} Hz: recovered {peak_freq} Hz"


class TestScanFMBand:
    """Test FM band scanning."""

    @pytest.mark.asyncio
    async def test_scan_without_hackrf_sweep(self, player, monkeypatch):
        """Scan should return empty list when hackrf_sweep is not found."""
        import shutil
        monkeypatch.setattr(shutil, "which", lambda x: None)
        stations = await player.scan_fm_band()
        assert stations == []

    @pytest.mark.asyncio
    async def test_scan_frequency_validation(self, player):
        """Scan should accept valid FM range parameters."""
        # This will fail gracefully without hardware
        stations = await player.scan_fm_band(88.0, 92.0, -30.0)
        # Just verify it returns a list (may be empty without hardware)
        assert isinstance(stations, list)


class TestStartStop:
    """Test start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_without_tune(self):
        """Start without tuning should fail."""
        p = FMPlayer()
        result = await p.start()
        assert result["success"] is False
        assert "No frequency set" in result["error"]

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """Stop without starting should fail."""
        p = FMPlayer()
        result = await p.stop()
        assert result["success"] is False
        assert "Not playing" in result["error"]

    @pytest.mark.asyncio
    async def test_double_start(self):
        """Starting twice should fail on second call."""
        p = FMPlayer()
        p._init_dsp()
        # First start (will succeed if hackrf_transfer is on PATH)
        result = await p.start(freq_mhz=92.5)
        if result["success"]:
            # Second start should fail
            result2 = await p.start(freq_mhz=92.5)
            assert result2["success"] is False
            assert "Already playing" in result2["error"]
            # Cleanup
            await p.stop()

    @pytest.mark.asyncio
    async def test_start_without_hackrf(self, monkeypatch):
        """Start should fail gracefully when hackrf_transfer is missing."""
        import shutil
        monkeypatch.setattr(shutil, "which", lambda x: None)
        p = FMPlayer()
        p._init_dsp()
        result = await p.start(freq_mhz=92.5)
        assert result["success"] is False
        assert "hackrf_transfer not found" in result["error"]


class TestGetAudioChunk:
    """Test audio chunk retrieval."""

    @pytest.mark.asyncio
    async def test_no_chunks_when_not_playing(self):
        p = FMPlayer()
        chunk = await p.get_audio_chunk()
        assert chunk is None

    @pytest.mark.asyncio
    async def test_get_all_chunks_empty(self):
        p = FMPlayer()
        chunks = await p.get_all_chunks()
        assert chunks == []
