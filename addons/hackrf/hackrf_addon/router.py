# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the HackRF One SDR addon."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile, File
from typing import Optional

import tempfile
import os


def create_router(device, spectrum, receiver, fm_decoder=None, tpms_decoder=None, ism_monitor=None, continuous_scanner=None) -> APIRouter:
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
        return await spectrum.start_sweep(freq_start, freq_end, bin_width)

    @router.post("/sweep/stop")
    async def sweep_stop():
        """Stop the running spectrum sweep."""
        return await spectrum.stop_sweep()

    @router.get("/sweep/data")
    async def sweep_data():
        """Get latest sweep data points.

        Returns the most recent sweep as a list of {freq_hz, power_dbm} points.
        """
        data = spectrum.get_data()
        return {
            "data": data,
            "count": len(data),
            "status": spectrum.get_status(),
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
        return await continuous_scanner.start()

    @router.post("/scanner/stop")
    async def scanner_stop():
        """Stop continuous scanning."""
        if continuous_scanner is None:
            return {"error": "Continuous scanner not available"}
        return await continuous_scanner.stop()

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

    return router
