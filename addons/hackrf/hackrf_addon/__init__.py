# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""HackRF One SDR addon for Tritium.

Provides spectrum analysis, FM reception, and signal monitoring
using HackRF One hardware via subprocess wrappers (no Python bindings).
"""

from tritium_lib.sdk import SensorAddon, AddonInfo, DeviceRegistry, DeviceState, SubprocessManager

from .data_store import HackRFDataStore
from .device import HackRFDevice, detect_all_hackrfs
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
        version="3.0.0",
        description="Software Defined Radio — spectrum analyzer, FM demodulation, TPMS tracking, ISM monitoring, ADS-B aircraft tracking (multi-device)",
        author="Valpatel Software LLC",
        category="radio",
        icon="📻",
    )

    def __init__(self):
        super().__init__()
        # Multi-device support via DeviceRegistry
        self.registry = DeviceRegistry("hackrf")
        self.subprocess_mgr = SubprocessManager("hackrf")

        # Per-device instances keyed by device_id
        self._device_instances: dict[str, HackRFDevice] = {}
        self._spectrum_instances: dict[str, SpectrumAnalyzer] = {}
        self._radio_locks: dict[str, RadioLock] = {}
        self._signal_dbs: dict[str, SignalDatabase] = {}

        # Default/first device (backwards compatibility)
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
        self.subprocess_mgr.kill_all()
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

        # Auto-detect all connected HackRF devices
        detected = await detect_all_hackrfs()
        if detected:
            for dev_info in detected:
                device_id = dev_info["device_id"]
                dev_instance = HackRFDevice()
                dev_instance._info = {k: v for k, v in dev_info.items()
                                       if k not in ("device_id", "index")}

                # Register in DeviceRegistry
                self.registry.add_device(
                    device_id=device_id,
                    device_type="hackrf",
                    transport_type="local",
                    metadata={
                        "serial": dev_info.get("serial", ""),
                        "firmware": dev_info.get("firmware_version", ""),
                        "index": dev_info.get("index", 0),
                        "board_name": dev_info.get("board_name", ""),
                    },
                )
                self.registry.set_state(device_id, DeviceState.CONNECTED)
                self.registry.touch(device_id)

                # Create per-device service instances
                self._device_instances[device_id] = dev_instance
                sig_db = SignalDatabase()
                self._signal_dbs[device_id] = sig_db
                self._spectrum_instances[device_id] = SpectrumAnalyzer(signal_db=sig_db)
                self._radio_locks[device_id] = RadioLock()

                log.info(f"Registered HackRF device: {device_id} "
                         f"(serial={dev_info.get('serial', '?')}, "
                         f"firmware={dev_info.get('firmware_version', '?')})")

            # Backwards compatibility: alias first device
            first_id = detected[0]["device_id"]
            self.device = self._device_instances[first_id]
            self.signal_db = self._signal_dbs[first_id]
            self.spectrum = self._spectrum_instances[first_id]
            self.radio_lock = self._radio_locks[first_id]
            self.continuous_scanner = ContinuousScanner(self.spectrum, self.signal_db)

            log.info(f"Detected {len(detected)} HackRF device(s), "
                     f"primary={first_id}")
        else:
            # No devices detected — fall back to single-device degraded mode
            info = await self.device.detect()
            if info:
                device_id = f"hackrf-{self.device.serial_short}" if self.device.serial_short else "hackrf-0"
                self.registry.add_device(
                    device_id=device_id,
                    device_type="hackrf",
                    transport_type="local",
                    metadata={"serial": info.get("serial", "")},
                )
                self.registry.set_state(device_id, DeviceState.CONNECTED)
                self._device_instances[device_id] = self.device
                self._signal_dbs[device_id] = self.signal_db
                self._spectrum_instances[device_id] = self.spectrum
                self._radio_locks[device_id] = self.radio_lock
                log.info(f"HackRF One detected (single): {device_id}")
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
            registry=self.registry,
            device_instances=self._device_instances,
            spectrum_instances=self._spectrum_instances,
            radio_locks=self._radio_locks,
            signal_dbs=self._signal_dbs,
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

        # Stop per-device spectrum analyzers
        for spec in self._spectrum_instances.values():
            if spec.is_running:
                await spec.stop_sweep()

        if self.receiver.is_running:
            await self.receiver.stop()
        if self.tpms_decoder.is_running:
            await self.tpms_decoder.stop_monitoring()
        if self.ism_monitor.is_running:
            await self.ism_monitor.stop_monitoring()
        if self.data_store:
            await self.data_store.close()
            self.data_store = None

        # Kill all tracked subprocesses and disconnect devices
        self.subprocess_mgr.kill_all()
        await self.registry.disconnect_all()
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
                was_available = self.device.is_available
                if not self.device.get_info():
                    info = await self.device.detect()
                    if not was_available and info and info.get("connected"):
                        import logging
                        logging.getLogger("hackrf").info("HackRF reconnected!")
                    elif was_available and (not info or not info.get("connected")):
                        import logging
                        logging.getLogger("hackrf").warning("HackRF disconnected — stopping operations")
                        # Stop all running operations gracefully
                        if self.spectrum.is_running:
                            await self.spectrum.stop_sweep()
                        if self.rtl433.is_running:
                            await self.rtl433.stop_monitoring()
                        if self.continuous_scanner.is_running:
                            await self.continuous_scanner.stop()
                        self.radio_lock.force_release()

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
        per_device = {}
        for dev_id, dev in self._device_instances.items():
            d_info = dev.get_info()
            spec = self._spectrum_instances.get(dev_id)
            sig_db = self._signal_dbs.get(dev_id)
            per_device[dev_id] = {
                "connected": d_info is not None,
                "serial": d_info.get("serial", "") if d_info else "",
                "sweep_running": spec.is_running if spec else False,
                "measurement_count": sig_db.count if sig_db else 0,
            }
        return {
            "status": "ok" if info else "degraded",
            "available": self.device.is_available,
            "connected": info is not None,
            "serial": info.get("serial", "") if info else "",
            "firmware": info.get("firmware_version", "") if info else "",
            "sweep_running": self.spectrum.is_running,
            "measurement_count": self.signal_db.count,
            "device_count": self.registry.device_count,
            "devices": per_device,
        }
