# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""HackRF One SDR addon for Tritium.

Provides spectrum analysis, FM reception, and signal monitoring
using HackRF One hardware via subprocess wrappers (no Python bindings).
"""

from tritium_lib.sdk import SensorAddon, AddonInfo

from .data_store import HackRFDataStore
from .device import HackRFDevice
from .spectrum import SpectrumAnalyzer
from .receiver import FMReceiver
from .signal_db import SignalDatabase
from .router import create_router
from .decoders import FMRadioDecoder, TPMSDecoder, ISMBandMonitor, ADSBDecoder
from .decoders.rtl433_wrapper import RTL433Wrapper
from .continuous_scan import ContinuousScanner
from .radio_lock import RadioLock
from .fm_player import FMPlayer


class HackRFAddon(SensorAddon):
    """HackRF One Software Defined Radio integration."""

    info = AddonInfo(
        id="hackrf",
        name="HackRF One SDR",
        version="2.2.0",
        description="Software Defined Radio — spectrum analyzer, FM demodulation, TPMS tracking, ISM monitoring, ADS-B aircraft tracking",
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
        self.adsb_decoder = ADSBDecoder()
        self.continuous_scanner = ContinuousScanner(self.spectrum, self.signal_db)
        self.rtl433 = RTL433Wrapper()
        self.radio_lock = RadioLock()
        self.fm_player = FMPlayer()
        self.data_store: HackRFDataStore | None = None
        self.target_tracker = None
        self._poll_task = None

    async def register(self, app):
        await super().register(app)

        import logging
        log = logging.getLogger("hackrf")

        # Kill any orphaned HackRF subprocesses from previous runs
        self._kill_orphan_processes()

        # Resolve target_tracker from app.state.amy (same pattern as meshtastic addon)
        target_tracker = None
        amy = getattr(getattr(app, 'state', None), 'amy', None)
        if amy is not None:
            target_tracker = getattr(amy, 'target_tracker', None)
        if target_tracker is None:
            target_tracker = getattr(app, 'target_tracker', None)

        self.target_tracker = target_tracker
        # Wire ADS-B decoder to target tracker for live aircraft updates
        self.adsb_decoder.target_tracker = target_tracker

        if target_tracker:
            log.info("HackRF addon wired to TargetTracker")
        else:
            log.warning("HackRF addon: no TargetTracker found — SDR targets will not appear on tactical map")

        # Initialize persistent data store
        self.data_store = HackRFDataStore()
        try:
            await self.data_store.initialize()
            log.info("HackRF persistent data store ready")
        except Exception as e:
            log.warning(f"HackRF data store init failed (non-fatal): {e}")
            self.data_store = None

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
            rtl433=self.rtl433,
            radio_lock=self.radio_lock,
            adsb_decoder=self.adsb_decoder,
            fm_player=self.fm_player,
            signal_db=self.signal_db,
        )
        if hasattr(app, 'include_router'):
            app.include_router(router, prefix="/api/addons/hackrf", tags=["hackrf"])

        # Start background polling for spectrum data
        import asyncio
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._background_tasks.append(self._poll_task)

    async def unregister(self, app):
        # Stop all running operations
        if self.fm_player._playing:
            await self.fm_player.stop()
        if self.rtl433.is_running:
            await self.rtl433.stop_monitoring()
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
        if self.data_store:
            await self.data_store.close()
            self.data_store = None
        # Kill any remaining subprocesses
        self._kill_orphan_processes()
        await super().unregister(app)

    @staticmethod
    def _kill_orphan_processes():
        """Kill any orphaned HackRF-related subprocesses from previous runs."""
        import subprocess
        try:
            result = subprocess.run(
                ["pkill", "-f", "hackrf_sweep|hackrf_transfer|rtl_433.*hackrf"],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                import logging
                logging.getLogger("hackrf").info("Killed orphaned HackRF subprocesses")
        except Exception:
            pass

    async def gather(self) -> list[dict]:
        """Return SDR-detected entities as target dicts.

        Includes:
        - ADS-B aircraft with lat/lng (source=adsb, asset_type=aircraft)
        - TPMS tire pressure sensors (source=sdr, asset_type=vehicle)
        - Strong RF signal peaks (source=sdr, asset_type=rf_signal)
        """
        targets = []

        # ADS-B aircraft with positions
        for ac_dict in self.adsb_decoder.get_aircraft():
            lat = ac_dict.get("latitude")
            lng = ac_dict.get("longitude")
            if lat is None or lng is None:
                continue
            icao = ac_dict["icao"]
            callsign = ac_dict.get("callsign", "")
            name = callsign if callsign else f"ICAO {icao.upper()}"
            targets.append({
                "target_id": f"adsb_{icao}",
                "name": name,
                "source": "adsb",
                "asset_type": "aircraft",
                "alliance": "unknown",
                "lat": lat,
                "lng": lng,
                "altitude_ft": ac_dict.get("altitude_ft"),
                "heading": ac_dict.get("heading", 0),
                "speed": ac_dict.get("velocity_kt", 0),
                "classification": "aircraft",
                "icao": icao,
                "callsign": callsign,
                "squawk": ac_dict.get("squawk", ""),
                "vertical_rate_fpm": ac_dict.get("vertical_rate_fpm"),
                "on_ground": ac_dict.get("on_ground", False),
                "last_seen": ac_dict.get("last_seen", 0),
            })

        # TPMS sensors — each unique sensor ID likely corresponds to a vehicle
        if self.tpms_decoder.is_running:
            for sensor in self.tpms_decoder.get_sensors():
                sensor_id = sensor.get("sensor_id", "")
                if not sensor_id:
                    continue
                targets.append({
                    "target_id": f"tpms_{sensor_id}",
                    "name": f"TPMS {sensor_id[:8]}",
                    "source": "sdr",
                    "asset_type": "vehicle",
                    "alliance": "unknown",
                    "classification": "vehicle",
                    "pressure_psi": sensor.get("pressure_psi"),
                    "temperature_c": sensor.get("temperature_c"),
                    "last_seen": sensor.get("last_seen", 0),
                })

        # Strong RF signal peaks
        peaks = self.signal_db.get_peaks(threshold_dbm=-20.0)
        for peak in peaks[:20]:
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
        """Background loop: periodic device health check and data persistence."""
        import asyncio
        while self._registered:
            try:
                # Periodically re-check device availability
                if not self.device.get_info():
                    await self.device.detect()

                # Persist signal peaks and ADS-B aircraft to data store
                if self.data_store:
                    # Store strong signal detections
                    peaks = self.signal_db.get_peaks(threshold_dbm=-30.0)
                    for peak in peaks[:50]:
                        try:
                            await self.data_store.store_signal(
                                peak["freq_hz"], peak["power_dbm"],
                            )
                        except Exception:
                            pass

                    # Store ADS-B aircraft
                    for ac in self.adsb_decoder.get_aircraft():
                        try:
                            await self.data_store.store_aircraft(ac)
                        except Exception:
                            pass

                    # Store TPMS sensors
                    if self.tpms_decoder.is_running:
                        for sensor in self.tpms_decoder.get_sensors():
                            try:
                                await self.data_store.store_tpms(sensor)
                            except Exception:
                                pass

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
            {"id": "adsbAircraft", "label": "ADS-B Aircraft", "category": "SDR",
             "color": "#ffaa00", "key": "showAdsbAircraft"},
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
