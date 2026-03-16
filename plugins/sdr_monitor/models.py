# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Pydantic models for the SDR Monitor plugin.

Defines the data structures for spectrum sweeps, ISM device detections,
ADS-B aircraft tracks, RF anomalies, and SDR configuration.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SpectrumSweep(BaseModel):
    """A single spectrum sweep capture for waterfall display."""

    freq_start_hz: float = Field(..., description="Start frequency in Hz")
    freq_end_hz: float = Field(..., description="End frequency in Hz")
    bin_count: int = Field(..., description="Number of FFT bins")
    power_dbm: list[float] = Field(..., description="Power per bin in dBm")
    timestamp: float = Field(..., description="Unix timestamp of capture")
    center_freq_hz: float = Field(0.0, description="Center frequency in Hz")
    bandwidth_hz: float = Field(0.0, description="Bandwidth in Hz")
    sample_rate_hz: int = Field(0, description="Sample rate used")
    source_id: str = Field("", description="SDR device that captured this")


class ISMDevice(BaseModel):
    """A detected ISM band device from rtl_433 or similar decoder.

    Modeled after rtl_433 JSON output format. Each decoded transmission
    produces one of these records. Devices are deduplicated by device_id.
    """

    protocol: str = Field("unknown", description="Protocol name (rtl_433 model)")
    device_id: str = Field(..., description="Unique device identifier")
    model: str = Field("unknown", description="Device model from rtl_433")
    frequency_mhz: float = Field(0.0, description="Transmission frequency in MHz")
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Decoded payload (temperature, humidity, pressure, etc.)",
    )
    rssi: float = Field(-100.0, description="Signal strength in dB")
    snr: float = Field(0.0, description="Signal-to-noise ratio in dB")
    timestamp: float = Field(0.0, description="Unix timestamp of detection")
    device_type: str = Field(
        "ism_device",
        description="Classified type (weather_station, tire_pressure, doorbell, etc.)",
    )
    message_count: int = Field(1, description="Total messages received from this device")
    first_seen: float = Field(0.0, description="Unix timestamp of first detection")
    last_seen: float = Field(0.0, description="Unix timestamp of most recent detection")


class ADSBTrack(BaseModel):
    """An ADS-B aircraft track from dump1090 or similar decoder.

    ADS-B (Automatic Dependent Surveillance-Broadcast) provides
    aircraft position, altitude, speed, and identification.
    """

    icao_hex: str = Field(..., description="ICAO 24-bit hex address")
    callsign: str = Field("", description="Flight callsign (e.g., UAL123)")
    lat: float = Field(0.0, description="Latitude in decimal degrees")
    lng: float = Field(0.0, description="Longitude in decimal degrees")
    altitude_ft: int = Field(0, description="Altitude in feet (barometric)")
    speed_kts: float = Field(0.0, description="Ground speed in knots")
    heading: float = Field(0.0, description="Track heading in degrees (0-360)")
    vertical_rate: int = Field(0, description="Vertical rate in ft/min")
    squawk: str = Field("", description="Squawk code (e.g., 7700 = emergency)")
    timestamp: float = Field(0.0, description="Unix timestamp of last update")
    message_count: int = Field(1, description="Total ADS-B messages from this aircraft")
    on_ground: bool = Field(False, description="Aircraft is on the ground")
    category: str = Field("", description="Aircraft category (A1-A7, B1-B7)")


class RFAnomaly(BaseModel):
    """An RF anomaly detected by the spectrum baseline comparison.

    Anomalies include new transmitters, significant power changes,
    unusual modulations, and out-of-band emissions.
    """

    frequency_mhz: float = Field(..., description="Frequency of anomaly in MHz")
    power_dbm: float = Field(..., description="Observed power in dBm")
    baseline_dbm: float = Field(0.0, description="Expected baseline power in dBm")
    anomaly_type: str = Field(
        "unknown",
        description="Type: new_transmitter, power_change, interference, jamming",
    )
    severity: str = Field("info", description="Severity: info, warning, critical")
    timestamp: float = Field(0.0, description="Unix timestamp of detection")
    duration_s: float = Field(0.0, description="How long anomaly has persisted")
    description: str = Field("", description="Human-readable description")
    source_id: str = Field("", description="SDR device that detected this")


class SDRConfig(BaseModel):
    """SDR receiver configuration."""

    center_freq_hz: float = Field(
        433_920_000, description="Center frequency in Hz"
    )
    sample_rate: int = Field(2_000_000, description="Sample rate in samples/sec")
    gain_db: float = Field(40.0, description="Receiver gain in dB")
    bandwidth_hz: float = Field(250_000, description="Filter bandwidth in Hz")
    antenna_port: str = Field("", description="Antenna port selection")
    agc_enabled: bool = Field(False, description="Automatic gain control")


class SDRDeviceInfo(BaseModel):
    """Information about a connected SDR hardware device."""

    device_id: str = Field(..., description="Unique device identifier")
    device_type: str = Field("unknown", description="SDR type (hackrf, rtlsdr, airspy)")
    serial: str = Field("", description="Hardware serial number")
    firmware_version: str = Field("", description="Firmware version")
    freq_range_mhz: list[float] = Field(
        default_factory=lambda: [1.0, 6000.0],
        description="Supported frequency range [min, max] in MHz",
    )
    sample_rates: list[int] = Field(
        default_factory=list, description="Supported sample rates"
    )
    status: str = Field("disconnected", description="connected, disconnected, busy, error")
    current_config: Optional[SDRConfig] = Field(
        None, description="Current receiver configuration"
    )


class SDRStatus(BaseModel):
    """Overall SDR system status."""

    connected_devices: list[SDRDeviceInfo] = Field(default_factory=list)
    active_receivers: int = Field(0, description="Number of active receive channels")
    ism_devices_tracked: int = Field(0, description="ISM devices currently tracked")
    adsb_aircraft_tracked: int = Field(0, description="ADS-B aircraft currently tracked")
    anomalies_active: int = Field(0, description="Active RF anomalies")
    uptime_s: float = Field(0.0, description="Plugin uptime in seconds")
    messages_total: int = Field(0, description="Total messages processed")
    demo_mode: bool = Field(False, description="Demo data generator active")
