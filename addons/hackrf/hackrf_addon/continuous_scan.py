# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Continuous RF environment scanner — runs 24/7 building up spectrum knowledge.

Cycles through frequency bands, records signal levels, detects anomalies,
tracks device transmissions, and builds a complete picture of the local
RF environment over time.

Scan schedule:
1. Full 1-6GHz sweep (2 seconds) — baseline
2. ISM 315 MHz focus (5 seconds) — TPMS
3. ISM 433 MHz focus (5 seconds) — remotes, weather stations
4. ISM 915 MHz focus (5 seconds) — LoRa, Meshtastic
5. FM 88-108 MHz focus (2 seconds) — broadcast
6. ADS-B 1090 MHz focus (5 seconds) — aircraft
7. WiFi 2.4 GHz focus (2 seconds) — WiFi/BT
8. Back to step 1...

Each focused scan has higher resolution (smaller bin width) to detect
individual transmissions.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("hackrf.continuous_scan")


@dataclass
class ScanBand:
    """A frequency band to scan."""
    name: str
    freq_start_mhz: int
    freq_end_mhz: int
    bin_width: int = 500000  # Hz
    duration_s: float = 3.0  # How long to scan this band
    priority: int = 1        # Higher = scan more often


# Default scan schedule — cycles through these bands
DEFAULT_BANDS = [
    ScanBand("Full Sweep",   1,    6000, 1000000, 3.0, 1),
    ScanBand("TPMS 315",     314,  316,  100000,  5.0, 2),
    ScanBand("ISM 433",      432,  434,  100000,  5.0, 2),
    ScanBand("LoRa 915",     902,  928,  100000,  5.0, 2),
    ScanBand("FM Radio",     88,   108,  500000,  2.0, 1),
    ScanBand("ADS-B 1090",   1085, 1095, 100000,  5.0, 2),
    ScanBand("WiFi 2.4GHz",  2400, 2500, 500000,  2.0, 1),
    ScanBand("Aircraft VHF", 118,  137,  100000,  3.0, 1),
    ScanBand("Cellular 700", 698,  806,  500000,  2.0, 1),
]


@dataclass
class RFEnvironmentSummary:
    """Aggregated view of the RF environment."""
    total_scans: int = 0
    total_measurements: int = 0
    uptime_s: float = 0.0
    bands_scanned: int = 0
    peak_signals: list = field(default_factory=list)  # top 10 strongest
    anomalies: list = field(default_factory=list)       # unusual signals
    active_band: str = ""
    last_scan_time: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_scans": self.total_scans,
            "total_measurements": self.total_measurements,
            "uptime_s": round(self.uptime_s, 0),
            "bands_scanned": self.bands_scanned,
            "peak_signals": self.peak_signals[:10],
            "anomalies": self.anomalies[:20],
            "active_band": self.active_band,
            "last_scan_time": self.last_scan_time,
        }


class ContinuousScanner:
    """Runs 24/7 cycling through frequency bands, building RF knowledge.

    Uses hackrf_sweep in short bursts for each band, with the
    SpectrumAnalyzer for actual data collection.
    """

    def __init__(self, spectrum_analyzer, signal_db):
        self.spectrum = spectrum_analyzer
        self.signal_db = signal_db
        self.bands = list(DEFAULT_BANDS)
        self._running = False
        self._task = None
        self._start_time = 0.0
        self._scan_count = 0
        self._measurement_count = 0
        self._current_band = ""
        self._peak_signals = []  # (freq_hz, power_dbm, band_name, timestamp)
        self._anomalies = []

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self):
        """Start continuous scanning loop."""
        if self._running:
            return {"success": False, "error": "Already running"}
        self._running = True
        self._start_time = time.time()
        self._task = asyncio.create_task(self._scan_loop())
        log.info("Continuous RF scanner started")
        return {"success": True, "bands": len(self.bands)}

    async def stop(self):
        """Stop scanning."""
        self._running = False
        await self.spectrum.stop_sweep()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info(f"Continuous scanner stopped after {self._scan_count} scans")
        return {"success": True, "total_scans": self._scan_count}

    def get_summary(self) -> RFEnvironmentSummary:
        """Get current RF environment summary."""
        return RFEnvironmentSummary(
            total_scans=self._scan_count,
            total_measurements=self._measurement_count,
            uptime_s=time.time() - self._start_time if self._start_time else 0,
            bands_scanned=len(self.bands),
            peak_signals=self._peak_signals[:10],
            anomalies=self._anomalies[:20],
            active_band=self._current_band,
            last_scan_time=time.time(),
        )

    async def _scan_loop(self):
        """Main scanning loop — cycles through bands continuously."""
        band_index = 0

        while self._running:
            band = self.bands[band_index % len(self.bands)]
            self._current_band = band.name

            try:
                # Start sweep for this band
                result = await self.spectrum.start_sweep(
                    band.freq_start_mhz, band.freq_end_mhz, band.bin_width,
                )

                if not result.get("success"):
                    log.warning(f"Sweep start failed for {band.name}: {result.get('error')}")
                    await asyncio.sleep(2)
                    band_index += 1
                    continue

                # Let it run for the configured duration
                await asyncio.sleep(band.duration_s)

                # Get data
                data = self.spectrum.get_data()
                await self.spectrum.stop_sweep()

                if data:
                    self._scan_count += 1
                    self._measurement_count += len(data)

                    # Find peaks in this scan
                    for point in data:
                        power = point.get("power_dbm", -100)
                        freq = point.get("freq_hz", 0)
                        if power > -30:  # Strong signal
                            entry = {
                                "freq_hz": freq,
                                "freq_mhz": round(freq / 1e6, 2),
                                "power_dbm": round(power, 1),
                                "band": band.name,
                                "timestamp": time.time(),
                            }
                            self._peak_signals.append(entry)
                            # Keep only top 100
                            self._peak_signals.sort(key=lambda x: -x["power_dbm"])
                            self._peak_signals = self._peak_signals[:100]

                    log.debug(f"Scanned {band.name}: {len(data)} points")

                # Small delay between bands
                await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"Scan error on {band.name}: {e}")
                await asyncio.sleep(2)

            band_index += 1

    def add_band(self, name: str, freq_start_mhz: int, freq_end_mhz: int,
                 bin_width: int = 500000, duration_s: float = 3.0):
        """Add a custom frequency band to the scan schedule."""
        self.bands.append(ScanBand(name, freq_start_mhz, freq_end_mhz, bin_width, duration_s))

    def remove_band(self, name: str):
        """Remove a band from the scan schedule."""
        self.bands = [b for b in self.bands if b.name != name]
