# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the HackRF One SDR addon."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import Optional

import asyncio
import tempfile
import os


def create_router(device, spectrum, receiver, fm_decoder=None, tpms_decoder=None, ism_monitor=None, continuous_scanner=None, rtl433=None, fm_player=None, adsb_decoder=None, signal_db=None, radio_lock=None) -> APIRouter:
    """Create FastAPI router for HackRF addon endpoints.

    Args:
        device: HackRFDevice instance.
        spectrum: SpectrumAnalyzer instance.
        receiver: FMReceiver instance.
        fm_decoder: FMRadioDecoder instance (optional).
        tpms_decoder: TPMSDecoder instance (optional).
        ism_monitor: ISMBandMonitor instance (optional).

    Returns:
        Configured APIRouter.
    """

    router = APIRouter()

    @router.get("/status")
    async def status():
        """Overall HackRF addon status."""
        info = device.get_info()
        return {
            "available": device.is_available,
            "connected": info is not None,
            "device": {
                "serial": info.get("serial", "") if info else "",
                "firmware": info.get("firmware_version", "") if info else "",
                "board": info.get("board_name", "") if info else "",
            },
            "sweep": spectrum.get_status(),
            "receiver": receiver.get_status(),
            "radio_lock": radio_lock.get_status() if radio_lock else {"locked": False},
        }

    @router.get("/info")
    async def info():
        """Full device info from hackrf_info.

        Runs hackrf_info and returns parsed output. Refreshes cached info.
        """
        result = await device.detect()
        if result is None:
            return {
                "available": device.is_available,
                "connected": False,
                "error": "HackRF not detected. Is the device connected?",
            }
        # Remove raw output from API response (it's large)
        clean = {k: v for k, v in result.items() if k != "raw_output"}
        clean["connected"] = True
        return clean

    @router.get("/ports")
    async def detect_ports():
        """Detect connected HackRF devices.

        Checks for HackRF by running hackrf_info. Unlike serial devices,
        HackRF uses USB bulk transfer (not serial ports).
        """
        info = await device.detect()
        devices = []
        if info:
            devices.append({
                "type": "hackrf-one",
                "serial": info.get("serial", ""),
                "firmware": info.get("firmware_version", ""),
                "board": info.get("board_name", "HackRF One"),
                "hardware_revision": info.get("hardware_revision", ""),
            })
        return {
            "devices": devices,
            "count": len(devices),
            "hackrf_info_available": device.is_available,
        }

    @router.post("/sweep/start")
    async def sweep_start(body: dict = None):
        """Start a spectrum sweep.

        Body: {
            "freq_start": 88,       // Start frequency in MHz (default 0)
            "freq_end": 108,        // End frequency in MHz (default 6000)
            "bin_width": 500000     // Bin width in Hz (default 500000)
        }
        """
        body = body or {}
        freq_start = int(body.get("freq_start", 0))
        freq_end = int(body.get("freq_end", 6000))
        bin_width = int(body.get("bin_width", 500_000))

        # Check radio lock
        if radio_lock and not radio_lock.acquire("sweep", f"{freq_start}-{freq_end} MHz"):
            return {
                "success": False,
                "error": f"Radio busy: {radio_lock.current_owner} ({radio_lock.current_description})",
                "busy_owner": radio_lock.current_owner,
                "busy_description": radio_lock.current_description,
            }

        result = await spectrum.start_sweep(freq_start, freq_end, bin_width)
        if not result.get("success") and radio_lock:
            radio_lock.release("sweep")
        return result

    @router.post("/sweep/stop")
    async def sweep_stop():
        """Stop the running spectrum sweep."""
        result = await spectrum.stop_sweep()
        if radio_lock:
            radio_lock.release("sweep")
        return result

    @router.get("/sweep/data")
    async def sweep_data(max_points: int = 600):
        """Get latest sweep data, downsampled for display.

        Args:
            max_points: Maximum number of points to return (default 600 = canvas width).
                       The backend aggregates bins to fit. Use 0 for all raw data.
        """
        data = spectrum.get_data()
        status = spectrum.get_status()

        # Downsample if too many points
        if max_points > 0 and len(data) > max_points:
            step = len(data) / max_points
            downsampled = []
            for i in range(max_points):
                start_idx = int(i * step)
                end_idx = int((i + 1) * step)
                chunk = data[start_idx:end_idx]
                if chunk:
                    # Take the max power in each bin (peak-hold)
                    best = max(chunk, key=lambda p: p.get("power_dbm", -100))
                    downsampled.append(best)
            data = downsampled

        return {
            "data": data,
            "count": len(data),
            "raw_count": status.get("measurement_count", 0),
            "status": status,
        }

    @router.get("/sweep/peaks")
    async def sweep_peaks(threshold: float = -30.0):
        """Get frequency peaks above threshold.

        Query params:
            threshold: Minimum power in dBm (default -30).
        """
        peaks = spectrum.signal_db.get_peaks(threshold_dbm=threshold)
        return {
            "peaks": peaks,
            "count": len(peaks),
            "threshold_dbm": threshold,
        }

    @router.post("/tune")
    async def tune(body: dict):
        """Tune the receiver to a frequency.

        Body: {
            "freq_hz": 100000000,    // Center frequency in Hz
            "sample_rate": 2000000,  // Sample rate in Hz (optional)
            "lna_gain": 32,          // LNA gain 0-40 dB (optional)
            "vga_gain": 20           // VGA gain 0-62 dB (optional)
        }
        """
        freq_hz = int(body.get("freq_hz", 100_000_000))
        result = receiver.tune(freq_hz)
        if not result.get("success"):
            return result

        # Optionally start capture immediately
        if body.get("start_capture", False):
            capture_result = await receiver.start(
                freq_hz=freq_hz,
                sample_rate=body.get("sample_rate"),
                lna_gain=body.get("lna_gain"),
                vga_gain=body.get("vga_gain"),
                duration_seconds=body.get("duration_seconds"),
            )
            result["capture"] = capture_result

        return result

    @router.post("/capture/start")
    async def capture_start(body: dict = None):
        """Start IQ sample capture.

        Body: {
            "freq_hz": 100000000,      // Center frequency in Hz
            "sample_rate": 2000000,    // Sample rate (default 2 MSPS)
            "lna_gain": 32,            // LNA gain (default 32)
            "vga_gain": 20,            // VGA gain (default 20)
            "duration_seconds": null   // null = continuous
        }
        """
        body = body or {}
        return await receiver.start(
            freq_hz=body.get("freq_hz"),
            sample_rate=body.get("sample_rate"),
            lna_gain=body.get("lna_gain"),
            vga_gain=body.get("vga_gain"),
            duration_seconds=body.get("duration_seconds"),
        )

    @router.post("/capture/stop")
    async def capture_stop():
        """Stop IQ sample capture."""
        return await receiver.stop()

    @router.get("/capture/list")
    async def capture_list():
        """List all IQ capture files."""
        captures = receiver.get_captures()
        return {"captures": captures, "count": len(captures)}

    @router.get("/firmware")
    async def firmware_info():
        """Get firmware version information."""
        info = device.get_info()
        if not info:
            # Try to detect
            info = await device.detect()
        if not info:
            return {"error": "HackRF not detected"}
        return {
            "firmware_version": info.get("firmware_version", ""),
            "api_version": info.get("api_version", ""),
            "tool_version": info.get("tool_version", ""),
            "lib_version": info.get("lib_version", ""),
            "hardware_revision": info.get("hardware_revision", ""),
        }

    @router.post("/flash")
    async def flash_firmware(firmware: UploadFile = File(...)):
        """Flash firmware to the HackRF.

        Upload a .bin firmware file. The device will be flashed using hackrf_spiflash.
        WARNING: This is a destructive operation. Ensure the firmware is correct.
        """
        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            content = await firmware.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = await device.flash_firmware(tmp_path)
            return result
        finally:
            os.unlink(tmp_path)

    @router.get("/geojson")
    async def geojson():
        """SDR detections as GeoJSON FeatureCollection for the tactical map.

        Returns:
        - ADS-B aircraft as Point features with position, altitude, heading
        - RF signal peaks as Point features at the server's configured position
          (since SDR signals are received at our location)

        Each feature includes full properties for map popup display.
        """
        import time as _time

        features = []

        # ADS-B aircraft with decoded positions
        if adsb_decoder is not None:
            for ac in adsb_decoder.get_aircraft():
                lat = ac.get("latitude")
                lng = ac.get("longitude")
                if lat is None or lng is None:
                    continue
                icao = ac["icao"]
                callsign = ac.get("callsign", "")
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lng, lat],
                    },
                    "properties": {
                        "target_id": f"adsb_{icao}",
                        "name": callsign if callsign else f"ICAO {icao.upper()}",
                        "source": "adsb",
                        "asset_type": "aircraft",
                        "alliance": "unknown",
                        "icao": icao,
                        "callsign": callsign,
                        "altitude_ft": ac.get("altitude_ft"),
                        "velocity_kt": ac.get("velocity_kt"),
                        "heading": ac.get("heading"),
                        "vertical_rate_fpm": ac.get("vertical_rate_fpm"),
                        "squawk": ac.get("squawk", ""),
                        "on_ground": ac.get("on_ground", False),
                        "last_seen": ac.get("last_seen", 0),
                        "age_s": ac.get("age_s", 0),
                        "message_count": ac.get("message_count", 0),
                    },
                })

        # Strong RF signal peaks — positioned at server location
        # These represent signals received at our antenna, so they appear at our position
        if signal_db is not None:
            peaks = signal_db.get_peaks(threshold_dbm=-20.0)
            for peak in peaks[:10]:
                freq_mhz = peak["freq_hz"] / 1_000_000
                # RF signals don't have inherent positions; they are received at our location
                # The map layer can render these as a heatmap or signal indicators
                features.append({
                    "type": "Feature",
                    "geometry": None,  # No position — use map overlay rendering
                    "properties": {
                        "target_id": f"sdr_{peak['freq_hz']}",
                        "name": f"{freq_mhz:.1f} MHz",
                        "source": "sdr",
                        "asset_type": "rf_signal",
                        "freq_hz": peak["freq_hz"],
                        "freq_mhz": round(freq_mhz, 1),
                        "power_dbm": round(peak["power_dbm"], 1),
                        "timestamp": peak["timestamp"],
                    },
                })

        return {"type": "FeatureCollection", "features": features}

    @router.get("/health")
    async def health():
        """Addon health check."""
        info = device.get_info()
        return {
            "status": "ok" if info else "degraded",
            "available": device.is_available,
            "connected": info is not None,
            "sweep_running": spectrum.is_running,
        }

    # --- FM Radio Decoder Endpoints ---

    @router.post("/fm/tune")
    async def fm_tune(body: dict):
        """Tune to an FM frequency, capture IQ, and demodulate audio.

        Body: {
            "freq_hz": 101100000,     // FM frequency in Hz
            "duration_s": 5,          // Capture duration (default 5s)
            "sample_rate": 2000000,   // IQ sample rate (default 2 MSPS)
            "save_audio": true        // Save WAV file (default true)
        }
        """
        if fm_decoder is None:
            return {"success": False, "error": "FM decoder not available"}

        freq_hz = int(body.get("freq_hz", 101_100_000))
        duration_s = float(body.get("duration_s", 5.0))
        sample_rate = int(body.get("sample_rate", 2_000_000))
        save_audio = body.get("save_audio", True)

        try:
            result = await fm_decoder.tune_and_demod(
                freq_hz=freq_hz,
                duration_s=duration_s,
                sample_rate=sample_rate,
                save_audio=save_audio,
            )
            result["success"] = True
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    @router.get("/fm/stations")
    async def fm_stations():
        """List known FM stations with optional signal strength from sweep data.

        Returns station call signs and frequencies. If a sweep is running,
        includes measured signal strength for each station frequency.
        """
        if fm_decoder is None:
            return {"stations": [], "error": "FM decoder not available"}

        from .decoders.fm_radio import US_FM_STATIONS

        stations = []
        for freq_hz, name in sorted(US_FM_STATIONS.items()):
            entry = {
                "freq_hz": freq_hz,
                "freq_mhz": freq_hz / 1_000_000,
                "name": name,
                "power_dbm": None,
            }
            # Check sweep data for signal strength if available
            if spectrum.signal_db.count > 0:
                nearby = spectrum.signal_db.query(
                    freq_start=freq_hz - 200_000,
                    freq_end=freq_hz + 200_000,
                )
                if nearby:
                    entry["power_dbm"] = max(m["power_dbm"] for m in nearby)
            stations.append(entry)
        return {"stations": stations, "count": len(stations)}

    # --- TPMS Decoder Endpoints ---

    @router.post("/tpms/start")
    async def tpms_start(body: dict = None):
        """Start TPMS monitoring on 315 MHz (US) or 433.92 MHz (EU).

        Body: {
            "freq_hz": 315000000,     // Frequency (default 315 MHz US)
            "cycle_s": 30             // Capture cycle duration (default 30s)
        }
        """
        if tpms_decoder is None:
            return {"success": False, "error": "TPMS decoder not available"}

        body = body or {}
        freq_hz = int(body.get("freq_hz", 315_000_000))
        cycle_s = float(body.get("cycle_s", 30.0))

        return await tpms_decoder.start_monitoring(freq_hz=freq_hz, cycle_s=cycle_s)

    @router.post("/tpms/stop")
    async def tpms_stop():
        """Stop TPMS monitoring."""
        if tpms_decoder is None:
            return {"success": False, "error": "TPMS decoder not available"}
        return await tpms_decoder.stop_monitoring()

    @router.get("/tpms/sensors")
    async def tpms_sensors():
        """List detected TPMS sensors.

        Each sensor has a unique 32-bit ID that can track a specific vehicle.
        """
        if tpms_decoder is None:
            return {"sensors": [], "error": "TPMS decoder not available"}
        sensors = tpms_decoder.get_sensors()
        return {
            "sensors": sensors,
            "count": len(sensors),
            "status": tpms_decoder.get_status(),
        }

    @router.get("/tpms/transmissions")
    async def tpms_transmissions(limit: int = 100):
        """Get recent TPMS transmissions.

        Query params:
            limit: Maximum number of transmissions (default 100).
        """
        if tpms_decoder is None:
            return {"transmissions": [], "error": "TPMS decoder not available"}
        txs = tpms_decoder.get_transmissions(limit=limit)
        return {"transmissions": txs, "count": len(txs)}

    # --- ISM Band Monitor Endpoints ---

    @router.post("/ism/start")
    async def ism_start(body: dict = None):
        """Start ISM band monitoring (315, 433, 868, 915 MHz).

        Body: {
            "threshold_dbm": -50      // Signal detection threshold (default -50)
        }
        """
        if ism_monitor is None:
            return {"success": False, "error": "ISM monitor not available"}

        body = body or {}
        threshold = float(body.get("threshold_dbm", -50.0))
        return await ism_monitor.start_monitoring(threshold_dbm=threshold)

    @router.post("/ism/stop")
    async def ism_stop():
        """Stop ISM band monitoring."""
        if ism_monitor is None:
            return {"success": False, "error": "ISM monitor not available"}
        return await ism_monitor.stop_monitoring()

    @router.get("/ism/devices")
    async def ism_devices(max_age: float = 300.0):
        """List detected ISM band devices.

        Query params:
            max_age: Maximum age in seconds to show (default 300s = 5 min).
        """
        if ism_monitor is None:
            return {"devices": [], "error": "ISM monitor not available"}
        devices = ism_monitor.get_active_devices(max_age_s=max_age)
        return {
            "devices": devices,
            "count": len(devices),
            "status": ism_monitor.get_status(),
        }

    @router.get("/ism/log")
    async def ism_log(limit: int = 200):
        """Get ISM transmission log.

        Query params:
            limit: Maximum number of log entries (default 200).
        """
        if ism_monitor is None:
            return {"log": [], "error": "ISM monitor not available"}
        log_entries = ism_monitor.get_transmission_log(limit=limit)
        return {"log": log_entries, "count": len(log_entries)}

    @router.get("/ism/bands")
    async def ism_bands():
        """Get ISM band activity summary."""
        if ism_monitor is None:
            return {"bands": [], "error": "ISM monitor not available"}
        return {"bands": ism_monitor.get_band_summary()}

    # ── Continuous Scanner ──────────────────────────────────────

    @router.post("/scanner/start")
    async def scanner_start():
        """Start 24/7 continuous RF environment scanning.

        Cycles through all frequency bands, building a complete picture
        of the RF environment over time.
        """
        if continuous_scanner is None:
            return {"error": "Continuous scanner not available"}
        if radio_lock and not radio_lock.acquire("scanner", "Continuous 24/7 RF scan"):
            return {
                "success": False,
                "error": f"Radio busy: {radio_lock.current_owner} ({radio_lock.current_description})",
            }
        result = await continuous_scanner.start()
        if not result.get("success") and radio_lock:
            radio_lock.release("scanner")
        return result

    @router.post("/scanner/stop")
    async def scanner_stop():
        """Stop continuous scanning."""
        if continuous_scanner is None:
            return {"error": "Continuous scanner not available"}
        result = await continuous_scanner.stop()
        if radio_lock:
            radio_lock.release("scanner")
        return result

    @router.get("/scanner/summary")
    async def scanner_summary():
        """Get RF environment summary from continuous scanning."""
        if continuous_scanner is None:
            return {"error": "Continuous scanner not available"}
        return continuous_scanner.get_summary().to_dict()

    @router.get("/scanner/status")
    async def scanner_status():
        """Check if continuous scanner is running."""
        if continuous_scanner is None:
            return {"running": False, "error": "not available"}
        return {
            "running": continuous_scanner.is_running,
            "bands": len(continuous_scanner.bands),
            "band_names": [b.name for b in continuous_scanner.bands],
        }

    # ── rtl_433 Device Decoder ─────────────────────────────────

    @router.post("/rtl433/start")
    async def rtl433_start(body: dict = None):
        """Start rtl_433 ISM band device monitoring.

        Decodes 200+ device protocols: TPMS, weather stations, remotes, etc.

        Body: {
            "freq_hz": 315000000 (default US TPMS),
            "protocols": [59, 60] (optional — specific protocol numbers)
        }
        """
        if rtl433 is None:
            return {"error": "rtl_433 wrapper not available"}
        body = body or {}
        freq = int(body.get("freq_hz", 315000000))
        protocols = body.get("protocols")

        # Check radio lock
        freq_desc = f"{freq/1e6:.1f} MHz ISM"
        if radio_lock and not radio_lock.acquire("rtl_433", freq_desc):
            return {
                "success": False,
                "error": f"Radio busy: {radio_lock.current_owner} ({radio_lock.current_description})",
                "busy_owner": radio_lock.current_owner,
            }

        result = await rtl433.start_monitoring(freq_hz=freq, protocols=protocols)
        if not result.get("success") and radio_lock:
            radio_lock.release("rtl_433")
        return result

    @router.post("/rtl433/stop")
    async def rtl433_stop():
        """Stop rtl_433 monitoring."""
        if rtl433 is None:
            return {"error": "rtl_433 wrapper not available"}
        result = await rtl433.stop_monitoring()
        if radio_lock:
            radio_lock.release("rtl_433")
        return result

    @router.get("/rtl433/events")
    async def rtl433_events(limit: int = 50):
        """Get recent decoded device events."""
        if rtl433 is None:
            return {"events": [], "error": "not available"}
        return {"events": rtl433.get_events(limit=limit)}

    @router.get("/rtl433/devices")
    async def rtl433_devices():
        """Get all unique devices detected by rtl_433."""
        if rtl433 is None:
            return {"devices": [], "error": "not available"}
        return {"devices": rtl433.get_devices()}

    @router.get("/rtl433/tpms")
    async def rtl433_tpms():
        """Get detected TPMS tire pressure sensors."""
        if rtl433 is None:
            return {"sensors": [], "error": "not available"}
        return {"sensors": rtl433.get_tpms_sensors()}

    @router.get("/rtl433/stats")
    async def rtl433_stats():
        """Get rtl_433 monitoring statistics."""
        if rtl433 is None:
            return {"error": "not available"}
        return rtl433.get_stats()

    # ── Clock Configuration ──────────────────────────────────────

    @router.get("/clock")
    async def clock_info():
        """Get current clock configuration (CLKIN/CLKOUT)."""
        return await device.get_clock_info()

    @router.post("/clock/clkin")
    async def set_clkin(body: dict):
        """Set external clock input (CLKIN) frequency.

        Body: {
            "freq_hz": 10000000   // Frequency in Hz (e.g. 10 MHz GPS ref)
        }
        """
        freq_hz = int(body.get("freq_hz", 10_000_000))
        return await device.set_clkin(freq_hz)

    @router.post("/clock/clkout")
    async def set_clkout(body: dict):
        """Set clock output (CLKOUT) frequency and enable/disable.

        Body: {
            "freq_hz": 10000000,  // Frequency in Hz
            "enable": true        // Enable (default true) or disable
        }
        """
        freq_hz = int(body.get("freq_hz", 10_000_000))
        enable = bool(body.get("enable", True))
        return await device.set_clkout(freq_hz, enable=enable)

    # ── Opera Cake Antenna Switching ─────────────────────────────

    @router.get("/operacake")
    async def operacake_info():
        """List connected Opera Cake boards and current antenna config."""
        boards_result = await device.get_operacake_boards()
        config_result = await device.get_antenna_config()
        return {
            "boards": boards_result.get("boards", []),
            "config": config_result.get("boards", []),
            "available": boards_result.get("success", False),
        }

    @router.post("/operacake/port")
    async def set_antenna_port(body: dict):
        """Set Opera Cake antenna port.

        Body: {
            "port": "A1"   // Antenna port: A1-A4, B1-B4
        }
        """
        port = body.get("port", "A1")
        return await device.set_antenna_port(port)

    # ── Bias Tee Control ─────────────────────────────────────────

    @router.post("/bias-tee")
    async def set_bias_tee(body: dict):
        """Enable or disable the bias tee (DC power on antenna port).

        Body: {
            "enabled": true   // true = enable 3.3V DC, false = disable
        }
        """
        enabled = bool(body.get("enabled", False))
        return await device.set_bias_tee(enabled)

    # ── Device Diagnostics ───────────────────────────────────────

    @router.get("/diagnostics")
    async def diagnostics():
        """Full device diagnostics: PLL status, CPLD checksum, board ID."""
        board_id = await device.get_board_id()
        debug = await device.get_debug_info()
        cpld = await device.get_cpld_checksum()
        return {
            "board": board_id if board_id.get("success") else {"error": board_id.get("error")},
            "pll": debug.get("pll") if debug.get("success") else {"error": debug.get("error", debug.get("output", ""))},
            "cpld_checksum": cpld.get("cpld_checksum") if cpld.get("success") else None,
            "cpld_error": cpld.get("error") if not cpld.get("success") else None,
        }

    # ── Firmware Management (enhanced) ───────────────────────────

    @router.post("/firmware/flash")
    async def flash_main_firmware(firmware: UploadFile = File(...)):
        """Flash main SPI firmware to the HackRF.

        Upload a .bin firmware file. Uses hackrf_spiflash -w.
        WARNING: Destructive operation. Ensure the firmware file is correct.
        """
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            content = await firmware.read()
            tmp.write(content)
            tmp_path = tmp.name
        try:
            return await device.flash_firmware(tmp_path)
        finally:
            os.unlink(tmp_path)

    @router.post("/firmware/cpld")
    async def flash_cpld_firmware(firmware: UploadFile = File(...)):
        """Flash CPLD firmware to the HackRF.

        Upload a .xsvf CPLD firmware file. Uses hackrf_cpldjtag -x.
        WARNING: Destructive operation.
        """
        with tempfile.NamedTemporaryFile(suffix=".xsvf", delete=False) as tmp:
            content = await firmware.read()
            tmp.write(content)
            tmp_path = tmp.name
        try:
            return await device.flash_cpld(tmp_path)
        finally:
            os.unlink(tmp_path)

    @router.post("/device/reset")
    async def reset_device():
        """Reset HackRF into DFU mode for firmware recovery.

        WARNING: The device will disconnect and enter DFU bootloader mode.
        A USB re-enumeration is required after reset.
        """
        return await device.reset_device()

    # ── ADS-B Aircraft Tracking ───────────────────────────────────

    @router.post("/adsb/start")
    async def adsb_start(body: dict = None):
        """Start ADS-B aircraft monitoring on 1090 MHz.

        Body: {
            "cycle_s": 10    // Capture cycle duration (default 10s)
        }
        """
        if adsb_decoder is None:
            return {"success": False, "error": "ADS-B decoder not available"}
        body = body or {}
        cycle_s = float(body.get("cycle_s", 10.0))
        return await adsb_decoder.start_monitoring(cycle_s=cycle_s)

    @router.post("/adsb/stop")
    async def adsb_stop():
        """Stop ADS-B monitoring."""
        if adsb_decoder is None:
            return {"success": False, "error": "ADS-B decoder not available"}
        return await adsb_decoder.stop_monitoring()

    @router.get("/adsb/aircraft")
    async def adsb_aircraft():
        """List all detected aircraft."""
        if adsb_decoder is None:
            return {"aircraft": [], "error": "ADS-B decoder not available"}
        aircraft = adsb_decoder.get_aircraft()
        return {
            "aircraft": aircraft,
            "count": len(aircraft),
        }

    @router.get("/adsb/stats")
    async def adsb_stats():
        """Get ADS-B decoder statistics."""
        if adsb_decoder is None:
            return {"error": "ADS-B decoder not available"}
        return adsb_decoder.get_stats()

    # ── FM Radio Player (continuous streaming) ───────────────

    @router.post("/fm/play")
    async def fm_play(body: dict):
        """Start FM radio playback.

        Body: {
            "freq_mhz": 92.5     // FM frequency in MHz
        }
        """
        if fm_player is None:
            return {"success": False, "error": "FM player not available"}

        freq_mhz = float(body.get("freq_mhz", 101.1))
        return await fm_player.start(freq_mhz=freq_mhz)

    @router.post("/fm/stop")
    async def fm_stop_player():
        """Stop FM radio playback."""
        if fm_player is None:
            return {"success": False, "error": "FM player not available"}
        return await fm_player.stop()

    @router.get("/fm/status")
    async def fm_player_status():
        """Get current FM player state (frequency, playing, signal level)."""
        if fm_player is None:
            return {"playing": False, "error": "FM player not available"}
        return fm_player.get_status()

    @router.get("/fm/stream")
    async def fm_stream():
        """Server-Sent Events stream of FM audio data.

        Each event contains a base64-encoded WAV chunk (~0.5 seconds).
        The frontend can decode and play these via Web Audio API.

        Event format:
            event: audio
            data: {"chunk": "<base64 WAV>", "seq": 1, "freq_mhz": 92.5}
        """
        if fm_player is None:
            return {"error": "FM player not available"}

        import json

        async def event_generator():
            seq = 0
            last_chunk_count = 0
            while fm_player._playing:
                chunk = await fm_player.get_audio_chunk()
                if chunk and fm_player._chunks_produced > last_chunk_count:
                    last_chunk_count = fm_player._chunks_produced
                    seq += 1
                    data = json.dumps({
                        "chunk": chunk,
                        "seq": seq,
                        "freq_mhz": fm_player._freq_hz / 1_000_000,
                        "signal_dbfs": round(fm_player._signal_strength, 1),
                    })
                    yield f"event: audio\ndata: {data}\n\n"
                else:
                    await asyncio.sleep(0.1)

            # Send end event
            yield f"event: stopped\ndata: {{}}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/fm/capture")
    async def fm_capture(freq_mhz: float = 92.5, duration_s: float = 3.0):
        """Capture and demodulate FM audio, return as WAV file.

        This is a one-shot capture: tunes to frequency, records IQ for
        the specified duration, demodulates FM, and returns a WAV file
        that can be played in the browser with <audio> element.

        Query params:
            freq_mhz: FM frequency in MHz (default 92.5)
            duration_s: Duration in seconds (default 3, max 10)
        """
        from fastapi.responses import Response
        import subprocess, tempfile, os, numpy as np
        from scipy.signal import firwin, lfilter, decimate
        import wave, struct

        if radio_lock and not radio_lock.acquire("fm_capture", f"FM {freq_mhz} MHz"):
            return {"error": f"Radio busy: {radio_lock.current_owner}"}

        duration_s = min(duration_s, 10.0)  # Cap at 10 seconds
        freq_hz = int(freq_mhz * 1e6)
        sample_rate = 2000000
        num_samples = int(sample_rate * duration_s)

        try:
            # Capture IQ
            with tempfile.NamedTemporaryFile(suffix='.raw', delete=False) as f:
                raw_file = f.name

            proc = await asyncio.create_subprocess_exec(
                'hackrf_transfer', '-r', raw_file,
                '-f', str(freq_hz), '-s', str(sample_rate),
                '-n', str(num_samples * 2), '-l', '32', '-g', '20',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=duration_s + 10)

            raw = np.fromfile(raw_file, dtype=np.int8)
            os.unlink(raw_file)

            if len(raw) < 1000:
                return {"error": "Capture too short — device may be busy"}

            # Demodulate FM
            iq = raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)
            iq /= 128.0
            taps = firwin(101, 100000, fs=sample_rate)
            filtered = lfilter(taps, 1.0, iq)
            discriminated = np.angle(filtered[1:] * np.conj(filtered[:-1]))
            dec_factor = max(1, sample_rate // 48000)
            audio = decimate(discriminated, dec_factor, zero_phase=True)
            audio = (audio / max(0.001, np.max(np.abs(audio))) * 0.8 * 32767).astype(np.int16)

            # Encode WAV in memory
            import io
            buf = io.BytesIO()
            with wave.open(buf, 'w') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(48000)
                wf.writeframes(audio.tobytes())

            return Response(
                content=buf.getvalue(),
                media_type="audio/wav",
                headers={"Content-Disposition": f"inline; filename=fm_{freq_mhz:.1f}mhz.wav"},
            )
        except asyncio.TimeoutError:
            return {"error": "Capture timed out"}
        except Exception as e:
            return {"error": str(e)}
        finally:
            if radio_lock:
                radio_lock.release("fm_capture")

    @router.get("/antenna/profile")
    async def antenna_profile():
        """Characterize the connected antenna by sweeping 1-6000 MHz.

        Returns power levels across the full HackRF frequency range,
        showing where the antenna is most/least sensitive. Helps users
        understand what their antenna can actually receive.
        """
        if radio_lock and not radio_lock.acquire("antenna_profile", "1-6000 MHz characterization"):
            return {"error": f"Radio busy: {radio_lock.current_owner}"}

        try:
            result = await spectrum.start_sweep(1, 6000, 1000000)
            if not result.get("success"):
                return {"error": result.get("error", "Sweep failed")}

            import asyncio
            await asyncio.sleep(5)  # Let sweep collect data

            data = spectrum.get_data()
            await spectrum.stop_sweep()

            if not data:
                return {"error": "No data collected"}

            # Analyze by band
            bands = [
                ("VHF Low (30-88)", 30e6, 88e6),
                ("FM Radio (88-108)", 88e6, 108e6),
                ("VHF High (108-174)", 108e6, 174e6),
                ("UHF (300-500)", 300e6, 500e6),
                ("UHF TV (470-700)", 470e6, 700e6),
                ("Cellular (700-960)", 700e6, 960e6),
                ("L-Band (1-2 GHz)", 1e9, 2e9),
                ("S-Band (2-3 GHz)", 2e9, 3e9),
                ("WiFi 5GHz (5-6)", 5e9, 6e9),
            ]

            profile = []
            for name, flo, fhi in bands:
                pts = [p for p in data if flo <= p["freq_hz"] <= fhi]
                if pts:
                    avg = sum(p["power_dbm"] for p in pts) / len(pts)
                    peak = max(pts, key=lambda p: p["power_dbm"])
                    # Higher avg power = better antenna sensitivity at this band
                    profile.append({
                        "band": name,
                        "avg_power_dbm": round(avg, 1),
                        "peak_power_dbm": round(peak["power_dbm"], 1),
                        "peak_freq_hz": peak["freq_hz"],
                        "bins": len(pts),
                        "quality": "good" if avg > -60 else "fair" if avg > -70 else "poor",
                    })

            # Overall best/worst bands
            profile.sort(key=lambda b: -b["avg_power_dbm"])

            return {
                "profile": profile,
                "best_band": profile[0]["band"] if profile else None,
                "worst_band": profile[-1]["band"] if profile else None,
                "note": "Higher power = better antenna sensitivity. The default telescoping antenna works best at 300-600 MHz.",
            }
        finally:
            if radio_lock:
                radio_lock.release("antenna_profile")

    @router.get("/fm/scan")
    async def fm_scan(
        freq_start: float = 87.5,
        freq_end: float = 108.0,
        threshold: float = -40.0,
    ):
        """Scan the FM broadcast band for active stations.

        Query params:
            freq_start: Start frequency in MHz (default 87.5).
            freq_end: End frequency in MHz (default 108.0).
            threshold: Minimum power in dBm (default -40).
        """
        if fm_player is None:
            return {"stations": [], "error": "FM player not available"}

        # Acquire radio lock for scan
        if radio_lock and not radio_lock.acquire("fm_scan", f"FM {freq_start}-{freq_end} MHz"):
            return {
                "stations": [],
                "error": f"Radio busy: {radio_lock.current_owner} ({radio_lock.current_description})",
            }

        try:
            stations = await fm_player.scan_fm_band(
                freq_start_mhz=freq_start,
                freq_end_mhz=freq_end,
                threshold_dbm=threshold,
            )
        finally:
            if radio_lock:
                radio_lock.release("fm_scan")

        return {
            "stations": stations,
            "count": len(stations),
            "freq_range_mhz": [freq_start, freq_end],
            "threshold_dbm": threshold,
        }

    @router.post("/fm/save")
    async def fm_save():
        """Save the current audio buffer to a WAV file."""
        if fm_player is None:
            return {"success": False, "error": "FM player not available"}
        return await fm_player.save_wav()

    return router
