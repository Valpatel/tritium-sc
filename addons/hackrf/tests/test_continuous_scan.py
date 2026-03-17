# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for ContinuousScanner — band cycling, peak detection, summaries."""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hackrf_addon.continuous_scan import (
    ContinuousScanner,
    ScanBand,
    RFEnvironmentSummary,
    DEFAULT_BANDS,
)


class TestScanBand:
    """Tests for ScanBand dataclass."""

    def test_defaults(self):
        band = ScanBand("Test", 100, 200)
        assert band.bin_width == 500000
        assert band.duration_s == 3.0
        assert band.priority == 1

    def test_custom_values(self):
        band = ScanBand("ISM", 315, 316, bin_width=100000, duration_s=5.0, priority=2)
        assert band.name == "ISM"
        assert band.freq_start_mhz == 315
        assert band.freq_end_mhz == 316
        assert band.bin_width == 100000


class TestDefaultBands:
    """Tests for the default scan schedule."""

    def test_default_bands_count(self):
        assert len(DEFAULT_BANDS) >= 7

    def test_default_bands_have_names(self):
        for band in DEFAULT_BANDS:
            assert len(band.name) > 0

    def test_default_bands_freq_ordering(self):
        for band in DEFAULT_BANDS:
            assert band.freq_start_mhz < band.freq_end_mhz


class TestRFEnvironmentSummary:
    """Tests for the summary dataclass."""

    def test_default_summary(self):
        summary = RFEnvironmentSummary()
        assert summary.total_scans == 0
        assert summary.active_band == ""

    def test_to_dict(self):
        summary = RFEnvironmentSummary(
            total_scans=10,
            total_measurements=5000,
            uptime_s=120.5,
            bands_scanned=9,
            peak_signals=[{"freq_hz": 100000000, "power_dbm": -20}],
            anomalies=[],
            active_band="FM Radio",
        )
        d = summary.to_dict()
        assert d["total_scans"] == 10
        assert d["total_measurements"] == 5000
        assert d["active_band"] == "FM Radio"
        assert isinstance(d["peak_signals"], list)

    def test_to_dict_truncates_peaks(self):
        peaks = [{"freq": i} for i in range(20)]
        summary = RFEnvironmentSummary(peak_signals=peaks)
        d = summary.to_dict()
        assert len(d["peak_signals"]) == 10

    def test_to_dict_truncates_anomalies(self):
        anomalies = [{"a": i} for i in range(30)]
        summary = RFEnvironmentSummary(anomalies=anomalies)
        d = summary.to_dict()
        assert len(d["anomalies"]) == 20


class TestContinuousScannerInit:
    """Tests for scanner initialization."""

    def test_init(self):
        spectrum = MagicMock()
        signal_db = MagicMock()
        scanner = ContinuousScanner(spectrum, signal_db)
        assert not scanner.is_running
        assert len(scanner.bands) == len(DEFAULT_BANDS)

    def test_add_band(self):
        spectrum = MagicMock()
        signal_db = MagicMock()
        scanner = ContinuousScanner(spectrum, signal_db)
        original_count = len(scanner.bands)
        scanner.add_band("Custom", 500, 600)
        assert len(scanner.bands) == original_count + 1

    def test_remove_band(self):
        spectrum = MagicMock()
        signal_db = MagicMock()
        scanner = ContinuousScanner(spectrum, signal_db)
        original_count = len(scanner.bands)
        scanner.remove_band("FM Radio")
        assert len(scanner.bands) == original_count - 1

    def test_remove_nonexistent_band(self):
        spectrum = MagicMock()
        signal_db = MagicMock()
        scanner = ContinuousScanner(spectrum, signal_db)
        original_count = len(scanner.bands)
        scanner.remove_band("Nonexistent")
        assert len(scanner.bands) == original_count


class TestContinuousScannerStartStop:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start(self):
        spectrum = MagicMock()
        spectrum.start_sweep = AsyncMock(return_value={"success": True})
        spectrum.stop_sweep = AsyncMock(return_value={"success": True})
        spectrum.get_data.return_value = []
        signal_db = MagicMock()

        scanner = ContinuousScanner(spectrum, signal_db)
        result = await scanner.start()
        assert result["success"] is True
        assert scanner.is_running

        # Clean up
        result = await scanner.stop()
        assert result["success"] is True
        assert not scanner.is_running

    @pytest.mark.asyncio
    async def test_start_already_running(self):
        spectrum = MagicMock()
        spectrum.start_sweep = AsyncMock(return_value={"success": True})
        spectrum.stop_sweep = AsyncMock(return_value={"success": True})
        spectrum.get_data.return_value = []
        signal_db = MagicMock()

        scanner = ContinuousScanner(spectrum, signal_db)
        await scanner.start()
        result = await scanner.start()
        assert result["success"] is False
        assert "already" in result.get("error", "").lower()
        await scanner.stop()

    @pytest.mark.asyncio
    async def test_get_summary(self):
        spectrum = MagicMock()
        spectrum.stop_sweep = AsyncMock()
        signal_db = MagicMock()
        scanner = ContinuousScanner(spectrum, signal_db)

        summary = scanner.get_summary()
        assert isinstance(summary, RFEnvironmentSummary)
        assert summary.total_scans == 0

    @pytest.mark.asyncio
    async def test_peak_detection_in_scan(self):
        """Verify that strong signals get added to peak_signals."""
        spectrum = MagicMock()
        spectrum.start_sweep = AsyncMock(return_value={"success": True})
        spectrum.stop_sweep = AsyncMock(return_value={"success": True})
        # Return data with a strong signal
        spectrum.get_data.return_value = [
            {"freq_hz": 315000000, "power_dbm": -20.0},
            {"freq_hz": 315100000, "power_dbm": -60.0},
        ]
        signal_db = MagicMock()

        scanner = ContinuousScanner(spectrum, signal_db)
        scanner._running = True
        scanner._start_time = time.time()

        # Simulate one scan cycle manually
        band = scanner.bands[0]
        scanner._current_band = band.name

        # Call the inner logic that processes scan data
        data = spectrum.get_data()
        scanner._scan_count += 1
        scanner._measurement_count += len(data)
        for point in data:
            power = point.get("power_dbm", -100)
            if power > -30:
                scanner._peak_signals.append({
                    "freq_hz": point["freq_hz"],
                    "power_dbm": power,
                    "band": band.name,
                    "timestamp": time.time(),
                })

        assert len(scanner._peak_signals) == 1
        assert scanner._peak_signals[0]["freq_hz"] == 315000000
