# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FM radio demodulation using hackrf_transfer + numpy/scipy.

Captures IQ samples via hackrf_transfer subprocess, then performs
wideband FM demodulation entirely in Python with numpy and scipy.
No GNU Radio dependency required.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import tempfile
import time
import wave
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("hackrf.decoders.fm")

# Common US FM stations (frequency Hz -> call sign)
# Extend this table as needed
US_FM_STATIONS: dict[int, str] = {
    # San Francisco Bay Area stations
    87_900_000: "KSFH 87.9 (Mtn View)",
    88_100_000: "KSJS 88.1 (San Jose State)",
    88_500_000: "KQED 88.5 (NPR SF)",
    89_300_000: "KPFA 89.3 (Pacifica Berkeley)",
    89_700_000: "KFJC 89.7 (Foothill College)",
    90_100_000: "KZSU 90.1 (Stanford)",
    90_500_000: "KALX 90.5 (UC Berkeley)",
    90_700_000: "KAFP 90.7 (SF Public Radio)",
    91_100_000: "KCSM 91.1 (Jazz San Mateo)",
    91_500_000: "KKUP 91.5 (Cupertino)",
    92_100_000: "KFOG 92.1 (Classic Rock SF)",
    92_700_000: "KREV 92.7 (SF)",
    93_300_000: "KRZZ 93.3 (San Jose)",
    94_100_000: "KPFA 94.1",
    94_500_000: "KBAY 94.5 (San Jose)",
    94_900_000: "KYLD 94.9 (Wild SF)",
    95_700_000: "KBGG 95.7 (The Game SF)",
    96_500_000: "KOIT 96.5 (SF)",
    97_300_000: "KLLC 97.3 (Alice SF)",
    98_100_000: "KISQ 98.1 (SF)",
    98_500_000: "KUFX 98.5 (K-Fox San Jose)",
    99_700_000: "KMVQ 99.7 (V101 SF)",
    100_300_000: "KBRG 100.3 (La Raza SF)",
    101_300_000: "KIOI 101.3 (K-101 SF)",
    102_100_000: "KDFC 102.1 (Classical SF)",
    102_900_000: "KBLX 102.9 (Quiet Storm SF)",
    103_700_000: "KOSF 103.7 (Energy SF)",
    104_500_000: "KFOG 104.5 (SF)",
    104_900_000: "KXSC 104.9",
    105_300_000: "KITS 105.3 (Live 105 SF)",
    106_100_000: "KMEL 106.1 (SF)",
    106_500_000: "KEZR 106.5 (San Jose)",
    106_900_000: "KFRC 106.9 (K-Frog SF)",
    107_700_000: "KSAN 107.7 (Bone SF)",
}

# Audio output directory
DEFAULT_AUDIO_DIR = Path("/tmp/hackrf_audio")


class FMRadioDecoder:
    """FM broadcast radio demodulator.

    Uses hackrf_transfer to capture raw IQ samples, then demodulates
    FM audio using scipy signal processing. Outputs PCM float32 audio
    at 48 kHz sample rate.
    """

    def __init__(self, capture_dir: str | Path | None = None):
        self._capture_dir = Path(capture_dir) if capture_dir else DEFAULT_AUDIO_DIR
        self._audio_rate: int = 48_000
        self._last_capture: Path | None = None
        self._last_audio: np.ndarray | None = None
        self._last_freq_hz: int = 0

    async def capture_iq(
        self,
        freq_hz: int,
        duration_s: float = 5.0,
        sample_rate: int = 2_000_000,
        lna_gain: int = 32,
        vga_gain: int = 20,
    ) -> Path:
        """Capture IQ samples from HackRF at the given frequency.

        Args:
            freq_hz: Center frequency in Hz (e.g. 101_100_000 for 101.1 MHz).
            duration_s: Capture duration in seconds.
            sample_rate: Sample rate in samples/sec (default 2 MSPS).
            lna_gain: LNA gain 0-40 dB.
            vga_gain: VGA gain 0-62 dB.

        Returns:
            Path to the raw IQ capture file.

        Raises:
            RuntimeError: If hackrf_transfer fails.
        """
        self._capture_dir.mkdir(parents=True, exist_ok=True)
        num_samples = int(sample_rate * duration_s)
        freq_mhz = freq_hz / 1_000_000

        # Use a temp file for the capture
        capture_file = self._capture_dir / f"fm_{freq_mhz:.1f}MHz_{int(time.time())}.raw"

        cmd = [
            "hackrf_transfer",
            "-r", str(capture_file),
            "-f", str(freq_hz),
            "-s", str(sample_rate),
            "-l", str(max(0, min(40, lna_gain))),
            "-g", str(max(0, min(62, vga_gain))),
            "-n", str(num_samples),
        ]

        log.info(f"Capturing IQ: {freq_mhz:.1f} MHz, {duration_s}s, {sample_rate} SPS")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=duration_s + 30.0,
        )

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"hackrf_transfer failed (rc={proc.returncode}): {err}")

        if not capture_file.exists() or capture_file.stat().st_size == 0:
            raise RuntimeError("hackrf_transfer produced no output")

        self._last_capture = capture_file
        self._last_freq_hz = freq_hz
        log.info(f"Captured {capture_file.stat().st_size} bytes to {capture_file}")
        return capture_file

    def demodulate_fm(
        self,
        iq_data: np.ndarray | Path | str,
        sample_rate: int = 2_000_000,
        audio_rate: int = 48_000,
    ) -> np.ndarray:
        """Demodulate wideband FM from IQ samples.

        Pipeline:
        1. Load interleaved int8 IQ data from hackrf_transfer
        2. Convert to complex64
        3. Low-pass filter (150 kHz cutoff for FM broadcast)
        4. FM discriminator (instantaneous frequency via angle difference)
        5. Decimate to audio sample rate
        6. De-emphasis filter (75 us time constant, US standard)

        Args:
            iq_data: Either a numpy array of complex64 samples, or a
                     Path/string to a raw IQ file from hackrf_transfer.
            sample_rate: IQ sample rate in Hz.
            audio_rate: Output audio sample rate in Hz.

        Returns:
            Float32 numpy array of audio samples at audio_rate.
        """
        from scipy.signal import firwin, lfilter, decimate

        # Load from file if needed
        if isinstance(iq_data, (str, Path)):
            raw = np.fromfile(str(iq_data), dtype=np.int8)
            # hackrf_transfer outputs interleaved I, Q as int8
            if len(raw) % 2 != 0:
                raw = raw[:len(raw) - 1]
            iq = raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)
            iq /= 128.0  # Normalize to [-1, 1]
        elif isinstance(iq_data, np.ndarray):
            if np.issubdtype(iq_data.dtype, np.complexfloating):
                iq = iq_data.astype(np.complex64)
            else:
                # Assume interleaved int8
                raw = iq_data.astype(np.float32)
                iq = raw[0::2] + 1j * raw[1::2]
                iq /= 128.0
        else:
            raise TypeError(f"Unsupported iq_data type: {type(iq_data)}")

        if len(iq) < 100:
            raise ValueError(f"IQ data too short: {len(iq)} samples")

        log.info(f"Demodulating {len(iq)} IQ samples at {sample_rate} SPS")

        # Step 1: Low-pass filter — FM broadcast channel is +/- 100 kHz
        # Use a wider filter (150 kHz) to capture the full signal
        fm_bw = 150_000  # Hz
        num_taps = 101
        lpf_cutoff = fm_bw / (sample_rate / 2)
        lpf_cutoff = min(lpf_cutoff, 0.99)  # Keep below Nyquist
        lpf = firwin(num_taps, lpf_cutoff)
        iq_filtered = lfilter(lpf, 1.0, iq)

        # Step 2: FM discriminator — instantaneous frequency
        # d/dt(angle(iq)) = freq deviation
        # Using the conjugate-multiply method: angle(iq[n] * conj(iq[n-1]))
        iq_diff = iq_filtered[1:] * np.conj(iq_filtered[:-1])
        fm_demod = np.angle(iq_diff)

        # Step 3: Decimate to audio rate
        decimation_factor = sample_rate // audio_rate
        if decimation_factor < 1:
            decimation_factor = 1

        if decimation_factor > 1 and len(fm_demod) > decimation_factor * 10:
            # Use scipy decimate for anti-aliased downsampling
            # Break into stages if factor is large
            audio = fm_demod
            remaining = decimation_factor
            while remaining > 1:
                stage = min(remaining, 10)  # scipy decimate max factor per stage
                if len(audio) > stage * 10:
                    audio = decimate(audio, stage, ftype="fir", zero_phase=True)
                else:
                    # Too few samples for decimate, just slice
                    audio = audio[::stage]
                remaining //= stage
                if remaining <= 1:
                    break
        else:
            audio = fm_demod[::max(1, decimation_factor)]

        # Step 4: De-emphasis filter (75 us for US FM, reduces high-freq hiss)
        tau = 75e-6  # 75 microseconds
        dt = 1.0 / audio_rate
        alpha = dt / (tau + dt)
        deemph = np.zeros_like(audio)
        if len(audio) > 0:
            deemph[0] = audio[0]
            for i in range(1, len(audio)):
                deemph[i] = alpha * audio[i] + (1 - alpha) * deemph[i - 1]
            audio = deemph

        # Normalize to [-1, 1]
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak * 0.9  # Leave a bit of headroom

        self._last_audio = audio.astype(np.float32)
        self._audio_rate = audio_rate
        log.info(f"Demodulated: {len(audio)} audio samples at {audio_rate} Hz "
                 f"({len(audio) / audio_rate:.1f}s)")
        return self._last_audio

    def save_wav(
        self,
        audio: np.ndarray,
        filename: str | Path,
        sample_rate: int = 48_000,
    ) -> Path:
        """Save audio samples to a WAV file.

        Args:
            audio: Float32 audio samples in [-1, 1] range.
            filename: Output WAV file path.
            sample_rate: Audio sample rate in Hz.

        Returns:
            Path to the saved WAV file.
        """
        filepath = Path(filename)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Convert float32 [-1,1] to int16
        audio_clipped = np.clip(audio, -1.0, 1.0)
        audio_int16 = (audio_clipped * 32767).astype(np.int16)

        with wave.open(str(filepath), "w") as wf:
            wf.setnchannels(1)  # Mono
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())

        log.info(f"Saved WAV: {filepath} ({len(audio) / sample_rate:.1f}s, {filepath.stat().st_size} bytes)")
        return filepath

    def get_station_name(self, freq_hz: int) -> str:
        """Look up a US FM station by frequency.

        Rounds to nearest 100 kHz (FM channel spacing).

        Args:
            freq_hz: Frequency in Hz.

        Returns:
            Station call sign string, or "Unknown" if not in table.
        """
        # Round to nearest 100 kHz (US FM channel spacing)
        rounded = round(freq_hz / 100_000) * 100_000
        return US_FM_STATIONS.get(rounded, f"Unknown ({rounded / 1_000_000:.1f} MHz)")

    async def tune_and_demod(
        self,
        freq_hz: int,
        duration_s: float = 5.0,
        sample_rate: int = 2_000_000,
        save_audio: bool = True,
    ) -> dict:
        """Convenience: capture IQ, demodulate FM, optionally save WAV.

        Args:
            freq_hz: FM frequency in Hz.
            duration_s: Capture duration.
            sample_rate: IQ sample rate.
            save_audio: Whether to save a WAV file.

        Returns:
            Dict with capture info, audio stats, and optional WAV path.
        """
        capture_file = await self.capture_iq(freq_hz, duration_s, sample_rate)
        audio = self.demodulate_fm(capture_file, sample_rate)

        result = {
            "freq_hz": freq_hz,
            "freq_mhz": freq_hz / 1_000_000,
            "station": self.get_station_name(freq_hz),
            "capture_file": str(capture_file),
            "capture_size_bytes": capture_file.stat().st_size,
            "audio_samples": len(audio),
            "audio_duration_s": round(len(audio) / self._audio_rate, 2),
            "audio_rate": self._audio_rate,
            "audio_peak": float(np.max(np.abs(audio))),
            "audio_rms": float(np.sqrt(np.mean(audio ** 2))),
        }

        if save_audio:
            freq_mhz = freq_hz / 1_000_000
            wav_path = self._capture_dir / f"fm_{freq_mhz:.1f}MHz_{int(time.time())}.wav"
            self.save_wav(audio, wav_path, self._audio_rate)
            result["wav_file"] = str(wav_path)

        return result
