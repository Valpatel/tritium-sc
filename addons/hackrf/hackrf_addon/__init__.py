# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""HackRF One SDR addon for Tritium.

Provides spectrum analysis, FM reception, and signal monitoring
using HackRF One hardware via subprocess wrappers (no Python bindings).
"""

from tritium_lib.sdk import SensorAddon, AddonInfo

from .device import HackRFDevice
from .spectrum import SpectrumAnalyzer
from .receiver import FMReceiver
from .signal_db import SignalDatabase
from .router import create_router
from .decoders import FMRadioDecoder, TPMSDecoder, ISMBandMonitor
from .continuous_scan import ContinuousScanner


class HackRFAddon(SensorAddon):
    """HackRF One Software Defined Radio integration."""

    info = AddonInfo(
        id="hackrf",
        name="HackRF One SDR",
        version="2.0.0",
        description="Software Defined Radio — spectrum analyzer, FM demodulation, TPMS tracking, ISM monitoring",
        author="Valpatel Software LLC",
        category="radio",
        icon="📻",
    )

    def __init__(self):
        super().__init__()
        self.device = HackRFDevice()
        self.signal_db = SignalDatabase()
        self.spectrum = SpectrumAnalyzer(signal_db=self.signal_db)
        self.receiver = FMReceiver()
        self.fm_decoder = FMRadioDecoder()
        self.tpms_decoder = TPMSDecoder()
        self.ism_monitor = ISMBandMonitor()
        self.continuous_scanner = ContinuousScanner(self.spectrum, self.signal_db)
        self._poll_task = None

    async def register(self, app):
        await super().register(app)

        import logging
        log = logging.getLogger("hackrf")

        # Auto-detect HackRF device
        info = await self.device.detect()
        if info:
            log.info(f"HackRF One detected: serial={info.get('serial', '?')}, "
                      f"firmware={info.get('firmware_version', '?')}")
        else:
            log.warning("HackRF One not detected — addon running in degraded mode")

        # Add API routes
        router = create_router(
            self.device, self.spectrum, self.receiver,
            fm_decoder=self.fm_decoder,
            tpms_decoder=self.tpms_decoder,
            ism_monitor=self.ism_monitor,
            continuous_scanner=self.continuous_scanner,
        )
        if hasattr(app, 'include_router'):
            app.include_router(router, prefix="/api/addons/hackrf", tags=["hackrf"])

        # Start background polling for spectrum data
        import asyncio
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._background_tasks.append(self._poll_task)

    async def unregister(self, app):
        # Stop all running operations
        if self.continuous_scanner.is_running:
            await self.continuous_scanner.stop()
        if self.spectrum.is_running:
            await self.spectrum.stop_sweep()
        if self.receiver.is_running:
            await self.receiver.stop()
        if self.tpms_decoder.is_running:
            await self.tpms_decoder.stop_monitoring()
        if self.ism_monitor.is_running:
            await self.ism_monitor.stop_monitoring()
        await super().unregister(app)

    async def gather(self) -> list[dict]:
        """Return current spectrum peaks as target-like dicts.

        Strong signals become SDR targets that can appear on the tactical map.
        """
        peaks = self.signal_db.get_peaks(threshold_dbm=-20.0)
        targets = []
        for peak in peaks[:20]:  # Limit to top 20 signals
            freq_mhz = peak["freq_hz"] / 1_000_000
            targets.append({
                "target_id": f"sdr_{peak['freq_hz']}",
                "source": "sdr",
                "label": f"{freq_mhz:.1f} MHz ({peak['power_dbm']:.0f} dBm)",
                "freq_hz": peak["freq_hz"],
                "power_dbm": peak["power_dbm"],
                "classification": "rf_signal",
                "timestamp": peak["timestamp"],
            })
        return targets

    async def _poll_loop(self):
        """Background loop: periodic device health check."""
        import asyncio
        while self._registered:
            try:
                # Periodically re-check device availability
                if not self.device.get_info():
                    await self.device.detect()
            except Exception as e:
                import logging
                logging.getLogger("hackrf").warning(f"Poll error: {e}")
            await asyncio.sleep(30)

    def get_panels(self):
        return [
            {"id": "hackrf-sdr", "title": "HACKRF SDR", "file": "hackrf.js",
             "category": "radio", "tab_order": 2},
        ]

    def get_layers(self):
        return [
            {"id": "rfSpectrum", "label": "RF Spectrum", "category": "SDR",
             "color": "#b060ff", "key": "showRfSpectrum"},
        ]

    def health_check(self):
        info = self.device.get_info()
        return {
            "status": "ok" if info else "degraded",
            "available": self.device.is_available,
            "connected": info is not None,
            "serial": info.get("serial", "") if info else "",
            "firmware": info.get("firmware_version", "") if info else "",
            "sweep_running": self.spectrum.is_running,
            "measurement_count": self.signal_db.count,
        }
