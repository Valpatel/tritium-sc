# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Spectrum analyzer using hackrf_sweep subprocess.

hackrf_sweep outputs CSV lines:
    timestamp, freq_low_hz, freq_high_hz, bin_width_hz, num_samples, dB1, dB2, ...

Each line covers a frequency range divided into bins of bin_width_hz.
Power values are in dBm for each bin.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from typing import Optional

from .signal_db import SignalDatabase

log = logging.getLogger("hackrf.spectrum")


class SpectrumAnalyzer:
    """Continuous spectrum sweep using hackrf_sweep.

    Runs hackrf_sweep as a subprocess and parses its CSV output in real-time.
    Measurements are stored in a SignalDatabase for query and peak detection.
    """

    def __init__(self, signal_db: SignalDatabase | None = None):
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._running = False
        self._freq_start_mhz: int = 0
        self._freq_end_mhz: int = 6000
        self._bin_width: int = 500_000
        self._sweep_count: int = 0
        self._last_sweep_time: float = 0.0
        self.signal_db = signal_db or SignalDatabase()

    @property
    def is_running(self) -> bool:
        """Whether a sweep subprocess is currently active."""
        return self._running and self._process is not None

    @property
    def sweep_count(self) -> int:
        """Number of sweep lines parsed so far."""
        return self._sweep_count

    async def start_sweep(
        self,
        freq_start_mhz: int = 0,
        freq_end_mhz: int = 6000,
        bin_width: int = 500_000,
    ) -> dict:
        """Start a continuous hackrf_sweep subprocess.

        Args:
            freq_start_mhz: Start frequency in MHz (default 0).
            freq_end_mhz: End frequency in MHz (default 6000).
            bin_width: FFT bin width in Hz (default 500000).

        Returns:
            Status dict with success and parameters.
        """
        if self._running:
            return {"success": False, "error": "Sweep already running"}

        if not shutil.which("hackrf_sweep"):
            return {"success": False, "error": "hackrf_sweep not found on PATH"}

        # Input validation
        if freq_start_mhz >= freq_end_mhz:
            return {"success": False, "error": f"Start frequency ({freq_start_mhz} MHz) must be less than end ({freq_end_mhz} MHz)"}
        if freq_start_mhz < 0:
            return {"success": False, "error": f"Start frequency cannot be negative ({freq_start_mhz} MHz)"}
        if freq_end_mhz > 7250:
            return {"success": False, "error": f"End frequency exceeds HackRF range ({freq_end_mhz} MHz > 7250 MHz)"}
        if bin_width <= 0:
            return {"success": False, "error": f"Bin width must be positive ({bin_width} Hz)"}

        self._freq_start_mhz = freq_start_mhz
        self._freq_end_mhz = freq_end_mhz
        self._bin_width = bin_width
        self._sweep_count = 0

        cmd = [
            "hackrf_sweep",
            "-f", f"{freq_start_mhz}:{freq_end_mhz}",
            "-w", str(bin_width),
        ]

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            log.error(f"Failed to start hackrf_sweep: {e}")
            return {"success": False, "error": str(e)}

        self._running = True
        self._reader_task = asyncio.create_task(self._read_output())

        log.info(f"Spectrum sweep started: {freq_start_mhz}-{freq_end_mhz} MHz, "
                 f"bin_width={bin_width} Hz")
        return {
            "success": True,
            "freq_start_mhz": freq_start_mhz,
            "freq_end_mhz": freq_end_mhz,
            "bin_width": bin_width,
        }

    async def stop_sweep(self) -> dict:
        """Stop the running hackrf_sweep subprocess.

        Returns:
            Status dict with sweep count and duration.
        """
        if not self._running:
            return {"success": True, "sweep_count": self._sweep_count, "already_stopped": True}

        self._running = False

        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass  # Already exited
            self._process = None

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        log.info(f"Spectrum sweep stopped after {self._sweep_count} lines")
        return {
            "success": True,
            "sweep_count": self._sweep_count,
        }

    def get_data(self) -> list[dict]:
        """Return the latest sweep data from the signal database.

        Returns:
            List of dicts with freq_hz and power_dbm.
        """
        return self.signal_db.get_latest_sweep()

    async def _read_output(self) -> None:
        """Background task: read and parse hackrf_sweep CSV output."""
        if not self._process or not self._process.stdout:
            log.warning("Sweep reader: no process or stdout available")
            return
        log.info("Sweep reader started, reading output...")

        try:
            while self._running:
                line_bytes = await self._process.stdout.readline()
                if not line_bytes:
                    # Process ended
                    break

                line = line_bytes.decode(errors="replace").strip()
                if not line:
                    continue

                measurements = self._parse_sweep_line(line)
                if measurements:
                    self.signal_db.store_batch(measurements)
                    self._sweep_count += 1
                    self._last_sweep_time = time.time()

        except asyncio.CancelledError:
            log.info(f"Sweep reader cancelled after {self._sweep_count} sweeps")
        except Exception as e:
            log.error(f"Sweep reader error: {e}")
        finally:
            log.info(f"Sweep reader exiting, {self._sweep_count} sweeps processed")
            self._running = False

    def _parse_sweep_line(self, line: str) -> list[dict] | None:
        """Parse a single hackrf_sweep CSV line into measurements.

        Format: date, time, freq_low_hz, freq_high_hz, bin_width_hz, num_samples, dB1, dB2, ...

        The first two fields are date and time (e.g., "2024-01-15, 12:34:56.789").
        Then freq_low, freq_high, bin_width, num_samples, followed by power values per bin.

        Returns:
            List of measurement dicts, or None if line can't be parsed.
        """
        parts = line.split(",")
        # Need at least: date, time, freq_low, freq_high, bin_width, num_samples, 1 power value
        if len(parts) < 7:
            return None

        try:
            # Skip date (parts[0]) and time (parts[1])
            freq_low = int(float(parts[2].strip()))
            freq_high = int(float(parts[3].strip()))
            bin_width = float(parts[4].strip())
            # parts[5] = num_samples (skip)
            power_values = parts[6:]
        except (ValueError, IndexError):
            return None

        if bin_width <= 0:
            return None

        ts = time.time()
        measurements = []
        freq = freq_low
        bin_width_int = int(bin_width)

        for pv in power_values:
            pv = pv.strip()
            if not pv:
                continue
            try:
                power_dbm = float(pv)
            except ValueError:
                freq += bin_width_int
                continue

            measurements.append({
                "freq_hz": freq + bin_width_int // 2,  # Center of bin
                "power_dbm": power_dbm,
                "timestamp": ts,
            })
            freq += bin_width_int

        return measurements if measurements else None

    def get_status(self) -> dict:
        """Return current analyzer status."""
        return {
            "running": self.is_running,
            "freq_start_mhz": self._freq_start_mhz,
            "freq_end_mhz": self._freq_end_mhz,
            "bin_width": self._bin_width,
            "sweep_count": self._sweep_count,
            "last_sweep_time": self._last_sweep_time,
            "measurement_count": self.signal_db.count,
        }
