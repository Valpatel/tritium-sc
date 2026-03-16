# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SDR Monitor plugin — comprehensive SDR monitoring for ISM, ADS-B, and spectrum.

Bridges rtl_433 (ISM band devices), dump1090 (ADS-B aircraft), and raw
spectrum data into the command center's EventBus and TargetTracker.

Components:
    SDRMonitorPlugin  — main plugin class with lifecycle management
    SpectrumAnalyzer  — RF spectrum processing and anomaly detection
    ADSBProcessor     — ADS-B aircraft track management
    ISMDecoder        — ISM band device decoder (rtl_433 integration)
    SDRDemoGenerator  — synthetic data generator for demo mode

Pydantic models for API serialization are in models.py.
"""
from __future__ import annotations

from .plugin import SDRMonitorPlugin, ISMDevice, ADSBTrack
from .spectrum import SpectrumAnalyzer
from .adsb import ADSBProcessor, ADSBTrack as ADSBTrackModule
from .ism_decoder import ISMDecoder, classify_device_type, build_device_id

__all__ = [
    "SDRMonitorPlugin",
    "ISMDevice",
    "ADSBTrack",
    "SpectrumAnalyzer",
    "ADSBProcessor",
    "ISMDecoder",
    "classify_device_type",
    "build_device_id",
]
