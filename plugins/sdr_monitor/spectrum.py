# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SpectrumAnalyzer — RF spectrum data processing and anomaly detection.

Processes raw FFT spectrum sweep data from SDR receivers, maintains a
rolling RF baseline (24h window), and detects anomalous transmitters
by comparing current power levels against the learned baseline.

Used by SDRMonitorPlugin for:
- Spectrum sweep storage (waterfall display backend)
- RF baseline learning and anomaly detection
- Peak detection and signal identification

The SpectrumAnalyzer is designed to work independently of the plugin
so it can be tested and reused in other contexts (edge firmware,
standalone monitoring scripts, etc.).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Optional

log = logging.getLogger("sdr_monitor.spectrum")

# Rolling baseline window (24 hours)
BASELINE_WINDOW_S = 86400.0

# Minimum samples before baseline is considered valid
MIN_BASELINE_SAMPLES = 5

# Power threshold above baseline to flag an anomaly (dB)
DEFAULT_ANOMALY_THRESHOLD_DB = 15.0

# Maximum history sizes
MAX_SPECTRUM_HISTORY = 100
MAX_ANOMALY_HISTORY = 500


class SpectrumAnalyzer:
    """RF spectrum analysis engine with baseline learning and anomaly detection.

    Maintains a rolling 24-hour power baseline per frequency band. When
    new spectrum sweeps arrive, compares observed power against the
    baseline and flags anomalies (new transmitters, jammers, interference).

    Usage::

        analyzer = SpectrumAnalyzer()

        # Feed spectrum sweep data
        anomalies = analyzer.process_sweep(sweep_dict)

        # Query state
        history = analyzer.get_history(limit=50)
        baseline = analyzer.get_baseline_power(433.92)
        anomalies = analyzer.get_anomalies(limit=100)
    """

    def __init__(
        self,
        anomaly_threshold_db: float = DEFAULT_ANOMALY_THRESHOLD_DB,
        baseline_window_s: float = BASELINE_WINDOW_S,
    ) -> None:
        self._anomaly_threshold_db = anomaly_threshold_db
        self._baseline_window_s = baseline_window_s

        # Spectrum sweep history (for waterfall display)
        self._history: list[dict] = []

        # RF baseline: freq_mhz (rounded to 0.1) -> deque of (timestamp, power_dbm)
        self._baseline: dict[float, deque] = defaultdict(
            lambda: deque(maxlen=1440)  # 1 sample/minute for 24h
        )

        # Detected anomalies
        self._anomalies: list[dict] = []

        # Statistics
        self._sweeps_processed = 0
        self._anomalies_detected = 0

    def process_sweep(self, sweep: dict) -> list[dict]:
        """Process a spectrum sweep and return any detected anomalies.

        Args:
            sweep: Dict with keys:
                freq_start_hz: float — start frequency in Hz
                freq_end_hz: float — end frequency in Hz
                bin_count: int — number of FFT bins
                power_dbm: list[float] — power per bin in dBm
                timestamp: float — unix timestamp (optional, defaults to now)
                source_id: str — SDR device ID (optional)

        Returns:
            List of anomaly dicts detected in this sweep (may be empty).
        """
        self._sweeps_processed += 1

        # Store in history
        self._history.append(sweep)
        if len(self._history) > MAX_SPECTRUM_HISTORY:
            self._history = self._history[-MAX_SPECTRUM_HISTORY:]

        # Check for anomalies
        return self._check_anomalies(sweep)

    def update_baseline(self, freq_mhz: float, power_dbm: float) -> None:
        """Update the rolling RF baseline for a specific frequency.

        Called when ISM device messages arrive to build the baseline
        from decoded signal observations (not just spectrum sweeps).
        """
        rounded = round(freq_mhz, 1)
        self._baseline[rounded].append((time.time(), power_dbm))

    def get_baseline_power(self, freq_mhz: float) -> Optional[float]:
        """Get the average baseline power for a frequency.

        Returns None if insufficient samples (< 5) are available.
        """
        rounded = round(freq_mhz, 1)
        samples = self._baseline.get(rounded)
        if not samples or len(samples) < MIN_BASELINE_SAMPLES:
            return None

        now = time.time()
        recent = [p for t, p in samples if now - t < self._baseline_window_s]
        if not recent:
            return None
        return sum(recent) / len(recent)

    def get_history(self, limit: int = 50) -> list[dict]:
        """Return recent spectrum sweep captures for waterfall display."""
        return list(self._history[-limit:])

    def get_anomalies(self, limit: int = 100) -> list[dict]:
        """Return recent RF anomalies."""
        return list(self._anomalies[-limit:])

    def record_anomaly(self, anomaly: dict) -> None:
        """Record an externally detected RF anomaly."""
        self._anomalies_detected += 1
        self._anomalies.append(anomaly)
        if len(self._anomalies) > MAX_ANOMALY_HISTORY:
            self._anomalies = self._anomalies[-MAX_ANOMALY_HISTORY:]

    def get_stats(self) -> dict:
        """Return analyzer statistics."""
        return {
            "sweeps_processed": self._sweeps_processed,
            "anomalies_detected": self._anomalies_detected,
            "history_size": len(self._history),
            "baseline_frequencies": len(self._baseline),
            "anomaly_threshold_db": self._anomaly_threshold_db,
        }

    def prune_baseline(self) -> int:
        """Remove expired baseline samples. Returns count of pruned frequencies."""
        cutoff = time.time() - self._baseline_window_s
        pruned = 0
        for freq in list(self._baseline.keys()):
            samples = self._baseline[freq]
            while samples and samples[0][0] < cutoff:
                samples.popleft()
            if not samples:
                del self._baseline[freq]
                pruned += 1
        return pruned

    def detect_peaks(
        self,
        sweep: dict,
        threshold_db: float = 10.0,
    ) -> list[dict]:
        """Detect peaks above noise floor in a spectrum sweep.

        Args:
            sweep: Spectrum sweep dict with power_dbm, freq_start_hz, freq_end_hz.
            threshold_db: Minimum dB above noise floor to consider a peak.

        Returns:
            List of peak dicts with frequency_mhz, power_dbm, snr_db.
        """
        power_dbm = sweep.get("power_dbm", [])
        if not power_dbm or len(power_dbm) < 5:
            return []

        freq_start = sweep.get("freq_start_hz", 0)
        freq_end = sweep.get("freq_end_hz", 0)
        if freq_start <= 0 or freq_end <= 0:
            return []

        # Noise floor = median
        sorted_bins = sorted(power_dbm)
        noise_floor = sorted_bins[len(sorted_bins) // 2]
        threshold = noise_floor + threshold_db

        num_bins = len(power_dbm)
        freq_step = (freq_end - freq_start) / num_bins
        peaks = []

        for i in range(2, num_bins - 2):
            p = power_dbm[i]
            if (
                p > threshold
                and p >= power_dbm[i - 1]
                and p >= power_dbm[i + 1]
                and p >= power_dbm[i - 2]
                and p >= power_dbm[i + 2]
            ):
                freq_hz = freq_start + i * freq_step
                peaks.append({
                    "frequency_mhz": round(freq_hz / 1e6, 4),
                    "power_dbm": round(p, 1),
                    "noise_floor_dbm": round(noise_floor, 1),
                    "snr_db": round(p - noise_floor, 1),
                    "bin_index": i,
                })

        # Sort by power descending
        peaks.sort(key=lambda pk: pk["power_dbm"], reverse=True)
        return peaks

    # -- Internal: anomaly detection ----------------------------------------

    def _check_anomalies(self, sweep: dict) -> list[dict]:
        """Check spectrum sweep for anomalies against the baseline."""
        power_dbm = sweep.get("power_dbm", [])
        if not power_dbm:
            return []

        freq_start = sweep.get("freq_start_hz", 0)
        freq_end = sweep.get("freq_end_hz", 0)
        bin_count = sweep.get("bin_count", len(power_dbm))

        if freq_start <= 0 or freq_end <= 0 or bin_count <= 0:
            return []

        freq_step = (freq_end - freq_start) / bin_count
        found: list[dict] = []

        for i, power in enumerate(power_dbm):
            freq_hz = freq_start + i * freq_step
            freq_mhz = freq_hz / 1e6
            baseline = self.get_baseline_power(freq_mhz)

            if baseline is not None and power - baseline > self._anomaly_threshold_db:
                anomaly = {
                    "frequency_mhz": round(freq_mhz, 3),
                    "power_dbm": round(power, 1),
                    "baseline_dbm": round(baseline, 1),
                    "deviation_db": round(power - baseline, 1),
                    "anomaly_type": "power_change",
                    "severity": "warning" if power - baseline < 25 else "critical",
                    "timestamp": time.time(),
                    "description": (
                        f"Power {power - baseline:.1f} dB above baseline "
                        f"at {freq_mhz:.3f} MHz"
                    ),
                    "source_id": sweep.get("source_id", ""),
                }
                self.record_anomaly(anomaly)
                found.append(anomaly)

        return found
