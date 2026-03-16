# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the SDR Monitor plugin.

Provides REST endpoints for:
- SDR system status (connected devices, active receivers)
- Spectrum data (waterfall display, frequency activity)
- ISM band device detections (rtl_433 output)
- ADS-B aircraft tracks (dump1090 output)
- RF anomaly detection (baseline comparison)
- SDR configuration (frequency, gain, sample rate)
- Demo data generation
- Manual message ingestion
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field


# -- Request models --------------------------------------------------------

class SDRConfigureRequest(BaseModel):
    """Request body to configure SDR receiver."""

    center_freq_hz: Optional[float] = Field(
        None, description="Center frequency in Hz"
    )
    sample_rate: Optional[int] = Field(
        None, description="Sample rate in samples/sec"
    )
    gain_db: Optional[float] = Field(None, description="Receiver gain in dB")
    bandwidth_hz: Optional[float] = Field(
        None, description="Filter bandwidth in Hz"
    )


def create_router(plugin: Any) -> APIRouter:
    """Build SDR Monitor API router.

    Parameters
    ----------
    plugin:
        SDRMonitorPlugin instance.
    """
    router = APIRouter(prefix="/api/sdr", tags=["sdr_monitor"])

    # -- System status -----------------------------------------------------

    @router.get("/status")
    async def get_status():
        """SDR system status — connected devices, active receivers, counts.

        Returns an overview of the SDR monitoring system including
        how many ISM devices and ADS-B aircraft are currently tracked,
        active anomalies, and whether demo mode is running.
        """
        return plugin.get_status()

    # -- Spectrum ----------------------------------------------------------

    @router.get("/spectrum")
    async def get_spectrum():
        """Current spectrum data — frequency activity summary.

        Returns a map of frequency (MHz) to message count, showing
        which ISM frequencies have the most activity. Use /spectrum/sweeps
        for raw FFT data suitable for waterfall display.
        """
        return plugin.get_spectrum()

    @router.get("/spectrum/sweeps")
    async def get_spectrum_sweeps(
        limit: int = Query(default=50, ge=1, le=100),
    ):
        """Recent spectrum sweep captures for waterfall display.

        Returns raw FFT bin data from spectrum sweeps. Each capture
        includes start/end frequency, bin count, and power-per-bin
        in dBm.
        """
        sweeps = plugin.get_spectrum_history(limit)
        return {"sweeps": sweeps, "count": len(sweeps)}

    # -- ISM band devices --------------------------------------------------

    @router.get("/devices")
    async def get_devices():
        """Detected ISM band devices from rtl_433.

        Returns weather stations, TPMS sensors, doorbells, key fobs,
        soil sensors, and any other device decoded by rtl_433.
        Each device includes model, frequency, RSSI, metadata, and
        classification.
        """
        devices = plugin.get_devices()
        return {"devices": devices, "count": len(devices)}

    # -- ADS-B aircraft tracks ---------------------------------------------

    @router.get("/adsb")
    async def get_adsb():
        """ADS-B aircraft tracks from dump1090.

        Returns currently tracked aircraft with ICAO hex, callsign,
        position (lat/lng), altitude, speed, heading, and squawk code.
        Stale tracks (>60s without update) are automatically pruned.
        """
        tracks = plugin.get_adsb_tracks()
        return {"tracks": tracks, "count": len(tracks)}

    # -- RF anomalies ------------------------------------------------------

    @router.get("/anomalies")
    async def get_anomalies(
        limit: int = Query(default=100, ge=1, le=500),
    ):
        """RF anomalies detected by baseline comparison.

        Returns anomalies including new transmitters, power changes,
        interference, and possible jamming. Each anomaly includes
        frequency, observed power, baseline power, type, and severity.
        """
        anomalies = plugin.get_anomalies(limit)
        return {"anomalies": anomalies, "count": len(anomalies)}

    # -- SDR configuration -------------------------------------------------

    @router.post("/configure")
    async def configure_sdr(body: SDRConfigureRequest):
        """Configure SDR receiver parameters.

        Sets frequency range, gain, sample rate, and bandwidth.
        Configuration is forwarded to edge SDR devices via MQTT/EventBus.
        """
        config = body.model_dump(exclude_none=True)
        result = plugin.configure_sdr(config)
        return result

    # -- Signal history ----------------------------------------------------

    @router.get("/signals")
    async def get_signals(limit: int = Query(default=50, ge=1, le=2000)):
        """Recent signal history (decoded RF messages)."""
        signals = plugin.get_signals(limit=limit)
        return {"signals": signals, "count": len(signals)}

    # -- Statistics --------------------------------------------------------

    @router.get("/stats")
    async def get_stats():
        """Detection statistics — message counts, device types, uptime."""
        return plugin.get_stats()

    # -- Health check ------------------------------------------------------

    @router.get("/health")
    async def get_health():
        """Plugin health status."""
        stats = plugin.get_stats()
        return {
            "healthy": plugin.healthy,
            "plugin_id": plugin.plugin_id,
            "version": plugin.version,
            "devices_active": stats.get("devices_active", 0),
            "adsb_tracks_active": stats.get("adsb_tracks_active", 0),
            "messages_received": stats.get("messages_received", 0),
            "anomalies_active": stats.get("anomalies_active", 0),
            "demo_mode": stats.get("demo_mode", False),
        }

    # -- Demo mode ---------------------------------------------------------

    @router.post("/demo/start")
    async def start_demo():
        """Start the SDR demo data generator.

        Generates synthetic ADS-B aircraft tracks, ISM device
        detections, spectrum sweeps, and RF anomalies.
        """
        result = plugin.start_demo()
        return result

    @router.post("/demo/stop")
    async def stop_demo():
        """Stop the SDR demo data generator."""
        result = plugin.stop_demo()
        return result

    # -- Manual ingestion --------------------------------------------------

    @router.post("/ingest")
    async def ingest_message(body: dict):
        """Manually ingest an rtl_433 JSON message.

        Useful for testing or when rtl_433 data arrives via HTTP
        instead of MQTT.
        """
        result = plugin.ingest_message(body)
        return {"status": "ok", "device": result}

    @router.post("/ingest/adsb")
    async def ingest_adsb(body: dict):
        """Manually ingest an ADS-B message (dump1090 JSON format).

        Useful for testing or when ADS-B data arrives via HTTP.
        """
        result = plugin.ingest_adsb(body)
        if result:
            return {"status": "ok", "track": result}
        return {"status": "error", "message": "Invalid ADS-B message (missing hex field)"}

    return router
