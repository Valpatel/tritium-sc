# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for SDR plugin.

Provides REST endpoints for spectrum display, RF device registry,
signal detection, ADS-B tracks, and SDR configuration/tuning.

Works with any SDR backend (generic, HackRF, RTL-SDR, Airspy, etc.)
and exposes HackRF-specific endpoints when the backend supports them.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel


class TuneRequest(BaseModel):
    """Request body to tune the SDR to a new frequency."""
    freq_mhz: float
    bandwidth_khz: Optional[float] = None


class GainRequest(BaseModel):
    """Request body to set HackRF gain stages."""
    lna_db: Optional[int] = None
    vga_db: Optional[int] = None
    amp: Optional[bool] = None


class SweepRequest(BaseModel):
    """Request body to start a spectrum sweep."""
    start_mhz: float = 1.0
    stop_mhz: float = 6000.0
    step_mhz: float = 1.0


def create_router(plugin: Any) -> APIRouter:
    """Build SDR API router.

    Works with any SDRPlugin subclass. HackRF-specific endpoints
    check for method availability before calling.

    Parameters
    ----------
    plugin:
        SDRPlugin (or subclass) instance.
    """
    router = APIRouter(prefix="/api/sdr", tags=["sdr"])

    # -- Generic SDR endpoints (work with any backend) ---------------------

    @router.get("/devices")
    async def get_devices(limit: int = Query(default=100, ge=1, le=5000)):
        """Return detected ISM/RF devices, newest first.

        Includes weather stations, tire pressure sensors, car key fobs,
        garage door openers, and any other device detected via rtl_433
        or similar decoders.
        """
        devices = plugin.get_devices(limit)
        return {"devices": devices, "count": len(devices)}

    @router.get("/spectrum")
    async def get_spectrum():
        """Return current spectrum data for waterfall display.

        Returns the latest FFT capture with power-per-bin data.
        If hardware is available, triggers a live capture.
        Falls back to the most recent buffered capture.
        """
        spectrum = plugin.get_spectrum()
        if spectrum:
            return {"spectrum": spectrum, "status": "ok"}
        return {"spectrum": None, "status": "no_data"}

    @router.get("/spectrum/history")
    async def get_spectrum_history(limit: int = Query(default=50, ge=1, le=100)):
        """Return recent spectrum captures for waterfall rendering."""
        history = plugin.get_spectrum_history(limit)
        return {"captures": history, "count": len(history)}

    @router.get("/signals")
    async def get_signals(limit: int = Query(default=100, ge=1, le=1000)):
        """Return decoded RF signals with classification.

        Signals come from rtl_433, dump1090, or the plugin's own
        signal detection pipeline.
        """
        signals = plugin.get_signals(limit)
        return {"signals": signals, "count": len(signals)}

    @router.get("/config")
    async def get_config():
        """Return current SDR configuration.

        Includes hardware-specific settings when available
        (HackRF gains, frequency range, sample rates, etc.).
        """
        return plugin.get_config()

    @router.post("/tune")
    async def tune(body: TuneRequest):
        """Tune the SDR to a new center frequency.

        For HackRF: valid range is 1 MHz to 6 GHz.
        For RTL-SDR: valid range is ~24 MHz to 1.7 GHz.
        """
        result = plugin.tune(body.freq_mhz, body.bandwidth_khz)
        return result

    @router.get("/stats")
    async def get_stats():
        """Return SDR plugin statistics.

        Includes signal count, device count, spectrum captures,
        ADS-B messages, hardware status, and current tuning.
        """
        return plugin.get_stats()

    @router.get("/health")
    async def get_health():
        """Return plugin health status."""
        config = plugin.get_config()
        return {
            "healthy": plugin.healthy,
            "plugin_id": plugin.plugin_id,
            "version": plugin.version,
            "hw_name": config.get("hw_name", "unknown"),
            "hackrf_available": config.get("hackrf_available", False),
            "soapy_available": config.get("soapy_available", False),
        }

    # -- ADS-B endpoints ---------------------------------------------------

    @router.get("/adsb")
    async def get_adsb():
        """Return ADS-B aircraft tracks.

        Requires dump1090 running (either started by this plugin
        or running independently with data bridged via MQTT).
        Returns aircraft currently tracked with position, altitude,
        speed, and callsign.
        """
        if hasattr(plugin, "get_adsb_tracks"):
            tracks = plugin.get_adsb_tracks()
            return {"tracks": tracks, "count": len(tracks)}
        return {"tracks": [], "count": 0, "note": "ADS-B not supported by this SDR backend"}

    @router.post("/adsb/start")
    async def start_adsb():
        """Start ADS-B decoding via dump1090 subprocess.

        Only available on HackRF backend (or when dump1090 is installed).
        """
        if hasattr(plugin, "start_adsb"):
            result = plugin.start_adsb()
            return result
        return {"status": "error", "message": "ADS-B start not supported by this SDR backend"}

    # -- HackRF-specific endpoints -----------------------------------------
    # These check for method availability so they gracefully degrade
    # when used with a non-HackRF SDR backend.

    @router.post("/gains")
    async def set_gains(body: GainRequest):
        """Set HackRF gain stages (LNA, VGA, RF amp).

        HackRF-specific. Returns current gain settings after update.
        Other backends will return an unsupported message.
        """
        if hasattr(plugin, "set_gains"):
            result = plugin.set_gains(
                lna_db=body.lna_db,
                vga_db=body.vga_db,
                amp=body.amp,
            )
            return result
        return {"status": "error", "message": "Gain control not supported by this SDR backend"}

    @router.post("/sweep/start")
    async def start_sweep(body: SweepRequest):
        """Start a background spectrum sweep across a frequency range.

        HackRF-specific. Sweeps from start_mhz to stop_mhz in step_mhz
        increments, collecting spectrum data at each step.
        """
        if hasattr(plugin, "start_sweep"):
            result = plugin.start_sweep(
                start_mhz=body.start_mhz,
                stop_mhz=body.stop_mhz,
                step_mhz=body.step_mhz,
            )
            return result
        return {"status": "error", "message": "Spectrum sweep not supported by this SDR backend"}

    @router.post("/sweep/stop")
    async def stop_sweep():
        """Stop an active spectrum sweep."""
        if hasattr(plugin, "stop_sweep"):
            return plugin.stop_sweep()
        return {"status": "error", "message": "Spectrum sweep not supported by this SDR backend"}

    @router.get("/sweep/result")
    async def get_sweep_result():
        """Return the latest sweep result."""
        if hasattr(plugin, "get_sweep_result"):
            result = plugin.get_sweep_result()
            if result:
                return {"result": result, "status": "ok"}
            return {"result": None, "status": "no_data"}
        return {"result": None, "status": "unsupported"}

    @router.get("/signals/detected")
    async def get_detected_signals(limit: int = Query(default=100, ge=1, le=500)):
        """Return signals detected via energy threshold during sweeps.

        HackRF-specific. Returns signals above the noise floor
        with basic modulation classification.
        """
        if hasattr(plugin, "get_detected_signals"):
            signals = plugin.get_detected_signals(limit)
            return {"signals": signals, "count": len(signals)}
        return {"signals": [], "count": 0, "note": "Signal detection not supported"}

    return router
