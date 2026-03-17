# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Continuous FM radio player for HackRF One.

Captures IQ samples via hackrf_transfer stdout pipe, demodulates FM
in real-time using numpy/scipy, and provides audio chunks for streaming.
No GNU Radio dependency required.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import shutil
import struct
import time
import wave
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("hackrf.fm_player")

# Audio output directory
DEFAULT_AUDIO_DIR = Path("/tmp/hackrf_fm_audio")

# IQ capture parameters
SAMPLE_RATE = 2_000_000      # 2 MSPS from hackrf_transfer
AUDIO_RATE = 48_000           # Output audio sample rate
CHUNK_IQ_BYTES = 256 * 1024  # Read 256 KB of IQ at a time (~64K complex samples)
CHUNK_DURATION = 0.5          # Target chunk duration in seconds for streaming


class FMPlayer:
    """Continuous FM radio player with real-time demodulation.

    Runs hackrf_transfer with stdout pipe, reads IQ samples in chunks,
    demodulates wideband FM, and makes audio available for streaming.
    """

    def __init__(self, audio_dir: str | Path | None = None):
        self._audio_dir = Path(audio_dir) if audio_dir else DEFAULT_AUDIO_DIR
        self._freq_hz: int = 0
        self._playing: bool = False
        self._process: asyncio.subprocess.Process | None = None
        self._read_task: asyncio.Task | None = None
        self._signal_strength: float = -100.0  # dBFS estimate
        self._start_time: float = 0.0
        self._chunks_produced: int = 0
        self._total_audio_samples: int = 0

        # Ring buffer of recent audio chunks (base64-encoded WAV)
        self._max_chunks = 10
        self._audio_chunks: list[str] = []
        self._chunk_lock = asyncio.Lock()

        # Latest raw audio for WAV saving
        self._latest_audio: np.ndarray | None = None

        # Pre-compute DSP coefficients (lazy init on first use)
        self._lpf_coeffs: np.ndarray | None = None
        self._deemph_alpha: float = 0.0
        self._decimation_factor: int = 1

        # Residual IQ from previous chunk for overlap (continuity)
        self._iq_residual: np.ndarray | None = None

    def _init_dsp(self) -> None:
        """Pre-compute FIR filter coefficients and decimation parameters."""
        from scipy.signal import firwin

        # Low-pass filter for FM broadcast bandwidth (~150 kHz)
        fm_bw = 150_000
        num_taps = 101
        lpf_cutoff = fm_bw / (SAMPLE_RATE / 2)
        lpf_cutoff = min(lpf_cutoff, 0.99)
        self._lpf_coeffs = firwin(num_taps, lpf_cutoff).astype(np.float32)

        # De-emphasis filter coefficient (75 us for US FM)
        tau = 75e-6
        dt = 1.0 / AUDIO_RATE
        self._deemph_alpha = dt / (tau + dt)

        # Decimation factor: 2 MHz -> 48 kHz = ~41.67, use 41
        self._decimation_factor = SAMPLE_RATE // AUDIO_RATE
        if self._decimation_factor < 1:
            self._decimation_factor = 1

        log.info(f"DSP initialized: LPF {num_taps} taps, "
                 f"decimation {self._decimation_factor}x, "
                 f"de-emphasis alpha={self._deemph_alpha:.4f}")

    def tune(self, freq_mhz: float) -> dict:
        """Tune to an FM frequency.

        Args:
            freq_mhz: Frequency in MHz (e.g., 92.5).

        Returns:
            Status dict.
        """
        freq_hz = int(freq_mhz * 1_000_000)
        if freq_hz < 87_500_000 or freq_hz > 108_000_000:
            return {
                "success": False,
                "error": f"Frequency {freq_mhz} MHz out of FM broadcast range (87.5-108 MHz)",
            }

        was_playing = self._playing
        self._freq_hz = freq_hz

        # Look up station name
        from .decoders.fm_radio import US_FM_STATIONS
        rounded = round(freq_hz / 100_000) * 100_000
        station_name = US_FM_STATIONS.get(rounded, f"Unknown ({freq_mhz:.1f} MHz)")

        log.info(f"Tuned to {freq_mhz:.1f} MHz — {station_name}")
        return {
            "success": True,
            "freq_mhz": freq_mhz,
            "freq_hz": freq_hz,
            "station": station_name,
            "was_playing": was_playing,
        }

    async def start(self, freq_mhz: float | None = None) -> dict:
        """Start continuous FM capture, demodulation, and audio output.

        Args:
            freq_mhz: Optional frequency to tune to before starting.

        Returns:
            Status dict.
        """
        if self._playing:
            return {"success": False, "error": "Already playing"}

        if freq_mhz is not None:
            result = self.tune(freq_mhz)
            if not result.get("success"):
                return result

        if self._freq_hz == 0:
            return {"success": False, "error": "No frequency set — call tune() first"}

        if not shutil.which("hackrf_transfer"):
            return {"success": False, "error": "hackrf_transfer not found on PATH"}

        # Initialize DSP coefficients
        if self._lpf_coeffs is None:
            self._init_dsp()

        # Clear state
        self._audio_chunks.clear()
        self._iq_residual = None
        self._chunks_produced = 0
        self._total_audio_samples = 0
        self._signal_strength = -100.0

        # Start hackrf_transfer with stdout pipe for continuous IQ streaming
        cmd = [
            "hackrf_transfer",
            "-r", "-",               # Write to stdout
            "-f", str(self._freq_hz),
            "-s", str(SAMPLE_RATE),
            "-a", "1",               # Amp enable
            "-l", "32",              # LNA gain
            "-g", "20",              # VGA gain
        ]

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            log.error(f"Failed to start hackrf_transfer: {e}")
            return {"success": False, "error": str(e)}

        self._playing = True
        self._start_time = time.time()

        # Start background reader task
        self._read_task = asyncio.create_task(self._reader_loop())

        freq_mhz_val = self._freq_hz / 1_000_000
        log.info(f"FM player started: {freq_mhz_val:.1f} MHz")
        return {
            "success": True,
            "freq_mhz": freq_mhz_val,
            "freq_hz": self._freq_hz,
            "sample_rate": SAMPLE_RATE,
            "audio_rate": AUDIO_RATE,
        }

    async def stop(self) -> dict:
        """Stop FM playback."""
        if not self._playing:
            return {"success": False, "error": "Not playing"}

        self._playing = False
        duration = time.time() - self._start_time

        # Cancel reader task
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        # Kill hackrf_transfer
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass
            self._process = None

        log.info(f"FM player stopped after {duration:.1f}s, "
                 f"{self._chunks_produced} chunks produced")
        return {
            "success": True,
            "duration_s": round(duration, 1),
            "chunks_produced": self._chunks_produced,
            "total_audio_samples": self._total_audio_samples,
        }

    def get_status(self) -> dict:
        """Get current player status."""
        freq_mhz = self._freq_hz / 1_000_000 if self._freq_hz > 0 else 0.0

        station = ""
        if self._freq_hz > 0:
            from .decoders.fm_radio import US_FM_STATIONS
            rounded = round(self._freq_hz / 100_000) * 100_000
            station = US_FM_STATIONS.get(rounded, f"Unknown ({freq_mhz:.1f} MHz)")

        return {
            "playing": self._playing,
            "freq_mhz": freq_mhz,
            "freq_hz": self._freq_hz,
            "station": station,
            "signal_strength_dbfs": round(self._signal_strength, 1),
            "duration_s": round(time.time() - self._start_time, 1) if self._playing else 0,
            "chunks_produced": self._chunks_produced,
            "chunks_buffered": len(self._audio_chunks),
        }

    async def get_audio_chunk(self) -> str | None:
        """Return the latest demodulated audio as a base64-encoded WAV chunk.

        Returns:
            Base64-encoded WAV string, or None if no audio available.
        """
        async with self._chunk_lock:
            if not self._audio_chunks:
                return None
            return self._audio_chunks[-1]

    async def get_all_chunks(self) -> list[str]:
        """Return all buffered audio chunks and clear the buffer.

        Returns:
            List of base64-encoded WAV strings.
        """
        async with self._chunk_lock:
            chunks = list(self._audio_chunks)
            self._audio_chunks.clear()
            return chunks

    async def scan_fm_band(
        self,
        freq_start_mhz: float = 87.5,
        freq_end_mhz: float = 108.0,
        threshold_dbm: float = -40.0,
    ) -> list[dict]:
        """Scan the FM broadcast band for active stations.

        Uses hackrf_sweep to scan the FM band and find peaks above threshold.

        Args:
            freq_start_mhz: Start frequency in MHz.
            freq_end_mhz: End frequency in MHz.
            threshold_dbm: Minimum power in dBm to report.

        Returns:
            List of dicts with freq_mhz, power_dbm, and name for each station.
        """
        if not shutil.which("hackrf_sweep"):
            log.warning("hackrf_sweep not found — returning empty scan")
            return []

        freq_start = int(freq_start_mhz)
        freq_end = int(freq_end_mhz) + 1  # hackrf_sweep uses integer MHz

        cmd = [
            "hackrf_sweep",
            "-f", f"{freq_start}:{freq_end}",
            "-w", "100000",   # 100 kHz bin width (matches FM channel spacing)
            "-1",             # Single sweep
        ]

        log.info(f"Scanning FM band {freq_start_mhz}-{freq_end_mhz} MHz")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=30.0,
            )
        except asyncio.TimeoutError:
            log.error("FM band scan timed out")
            return []
        except FileNotFoundError:
            log.error("hackrf_sweep not found")
            return []
        except Exception as e:
            log.error(f"FM band scan failed: {e}")
            return []

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            log.error(f"hackrf_sweep failed (rc={proc.returncode}): {err}")
            return []

        # Parse hackrf_sweep CSV output
        # Format: date, time, hz_low, hz_high, hz_bin_width, num_samples, dB, dB, ...
        from .decoders.fm_radio import US_FM_STATIONS

        measurements: dict[int, float] = {}  # freq_hz -> max power_dbm

        for line in stdout.decode(errors="replace").strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) < 7:
                continue
            try:
                hz_low = int(float(parts[2].strip()))
                hz_high = int(float(parts[3].strip()))
                hz_bin_width = int(float(parts[4].strip()))
                # Each subsequent field is power in dB for one bin
                for i, db_str in enumerate(parts[6:]):
                    db_val = float(db_str.strip())
                    freq_hz = hz_low + i * hz_bin_width
                    if freq_hz in measurements:
                        measurements[freq_hz] = max(measurements[freq_hz], db_val)
                    else:
                        measurements[freq_hz] = db_val
            except (ValueError, IndexError):
                continue

        # Find peaks above threshold, snap to nearest 100 kHz (FM channels)
        channels: dict[int, float] = {}  # rounded freq -> max power
        for freq_hz, power_dbm in measurements.items():
            if power_dbm < threshold_dbm:
                continue
            # Snap to nearest 200 kHz (FM channel spacing)
            rounded = round(freq_hz / 200_000) * 200_000
            if rounded not in channels or power_dbm > channels[rounded]:
                channels[rounded] = power_dbm

        # Build result with station names
        stations = []
        for freq_hz, power_dbm in sorted(channels.items()):
            freq_mhz = freq_hz / 1_000_000
            # Look up station name
            name_rounded = round(freq_hz / 100_000) * 100_000
            name = US_FM_STATIONS.get(name_rounded, f"Unknown ({freq_mhz:.1f} MHz)")
            stations.append({
                "freq_mhz": round(freq_mhz, 1),
                "freq_hz": freq_hz,
                "power_dbm": round(power_dbm, 1),
                "name": name,
            })

        # Sort by power (strongest first)
        stations.sort(key=lambda s: s["power_dbm"], reverse=True)
        log.info(f"FM scan found {len(stations)} stations above {threshold_dbm} dBm")
        return stations

    async def _reader_loop(self) -> None:
        """Background task: read IQ from hackrf_transfer stdout, demodulate, buffer audio."""
        from scipy.signal import lfilter

        log.info("FM reader loop started")
        prev_sample: complex = 0 + 0j  # For FM discriminator continuity
        deemph_state: float = 0.0       # De-emphasis filter state

        try:
            while self._playing and self._process and self._process.stdout:
                # Read a chunk of IQ bytes from hackrf_transfer stdout
                try:
                    raw_bytes = await asyncio.wait_for(
                        self._process.stdout.read(CHUNK_IQ_BYTES),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    log.warning("Timeout reading IQ data")
                    continue

                if not raw_bytes:
                    log.warning("hackrf_transfer stdout closed")
                    break

                # Convert interleaved int8 I/Q to complex64
                raw = np.frombuffer(raw_bytes, dtype=np.int8)
                if len(raw) < 4:
                    continue
                if len(raw) % 2 != 0:
                    raw = raw[:-1]

                iq = (raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)) / 128.0

                # Estimate signal strength (RMS power in dBFS)
                rms = np.sqrt(np.mean(np.abs(iq) ** 2))
                if rms > 0:
                    self._signal_strength = 20.0 * np.log10(rms)

                # Prepend residual from previous chunk for filter continuity
                if self._iq_residual is not None and len(self._iq_residual) > 0:
                    iq = np.concatenate([self._iq_residual, iq])

                # Save tail as residual for next chunk (filter overlap)
                overlap = len(self._lpf_coeffs) - 1 if self._lpf_coeffs is not None else 100
                if len(iq) > overlap * 2:
                    self._iq_residual = iq[-overlap:]
                else:
                    self._iq_residual = None

                # Step 1: Low-pass filter
                iq_filtered = lfilter(self._lpf_coeffs, 1.0, iq)

                # Step 2: FM discriminator (angle of conjugate product)
                # Prepend previous sample for continuity
                iq_with_prev = np.concatenate([[prev_sample], iq_filtered])
                prev_sample = iq_filtered[-1]
                iq_diff = iq_with_prev[1:] * np.conj(iq_with_prev[:-1])
                fm_demod = np.angle(iq_diff)

                # Step 3: Decimate to audio rate
                dec = self._decimation_factor
                if dec > 1 and len(fm_demod) > dec * 2:
                    # Simple decimation with averaging (anti-alias via LPF already applied)
                    n_out = len(fm_demod) // dec
                    audio = fm_demod[:n_out * dec].reshape(n_out, dec).mean(axis=1)
                else:
                    audio = fm_demod

                # Step 4: De-emphasis filter (IIR, maintains state across chunks)
                alpha = self._deemph_alpha
                deemph = np.empty_like(audio)
                if len(audio) > 0:
                    deemph[0] = alpha * audio[0] + (1 - alpha) * deemph_state
                    for i in range(1, len(audio)):
                        deemph[i] = alpha * audio[i] + (1 - alpha) * deemph[i - 1]
                    deemph_state = float(deemph[-1])
                    audio = deemph

                # Normalize to [-1, 1]
                peak = np.max(np.abs(audio))
                if peak > 0:
                    audio = (audio / peak * 0.9).astype(np.float32)
                else:
                    audio = audio.astype(np.float32)

                # Encode as base64 WAV chunk
                wav_b64 = self._encode_wav_chunk(audio, AUDIO_RATE)

                async with self._chunk_lock:
                    self._audio_chunks.append(wav_b64)
                    if len(self._audio_chunks) > self._max_chunks:
                        self._audio_chunks.pop(0)

                self._chunks_produced += 1
                self._total_audio_samples += len(audio)
                self._latest_audio = audio

                # Yield control to event loop
                await asyncio.sleep(0)

        except asyncio.CancelledError:
            log.info("FM reader loop cancelled")
        except Exception as e:
            log.error(f"FM reader loop error: {e}", exc_info=True)
        finally:
            self._playing = False
            log.info(f"FM reader loop ended, {self._chunks_produced} chunks produced")

    @staticmethod
    def _encode_wav_chunk(audio: np.ndarray, sample_rate: int) -> str:
        """Encode float32 audio as a base64-encoded WAV.

        Args:
            audio: Float32 audio samples in [-1, 1].
            sample_rate: Audio sample rate in Hz.

        Returns:
            Base64-encoded WAV string.
        """
        audio_clipped = np.clip(audio, -1.0, 1.0)
        audio_int16 = (audio_clipped * 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())

        return base64.b64encode(buf.getvalue()).decode("ascii")

    async def save_wav(self, filename: str | None = None) -> dict:
        """Save the latest audio buffer to a WAV file.

        Args:
            filename: Output path. Auto-generated if None.

        Returns:
            Dict with file path and audio info.
        """
        if self._latest_audio is None or len(self._latest_audio) == 0:
            return {"success": False, "error": "No audio data available"}

        self._audio_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            freq_mhz = self._freq_hz / 1_000_000
            filename = str(
                self._audio_dir / f"fm_{freq_mhz:.1f}MHz_{int(time.time())}.wav"
            )

        filepath = Path(filename)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        audio = self._latest_audio
        audio_clipped = np.clip(audio, -1.0, 1.0)
        audio_int16 = (audio_clipped * 32767).astype(np.int16)

        with wave.open(str(filepath), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(AUDIO_RATE)
            wf.writeframes(audio_int16.tobytes())

        duration = len(audio) / AUDIO_RATE
        log.info(f"Saved WAV: {filepath} ({duration:.1f}s)")
        return {
            "success": True,
            "path": str(filepath),
            "duration_s": round(duration, 2),
            "samples": len(audio),
            "size_bytes": filepath.stat().st_size,
        }
