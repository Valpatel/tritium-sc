# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SDR Monitor plugin — comprehensive SDR monitoring for ISM, ADS-B, and spectrum.

Bridges rtl_433 (ISM band devices), dump1090 (ADS-B aircraft), and raw
spectrum data into the command center's EventBus and TargetTracker.

Components:
    SDRMonitorPlugin — main plugin class with lifecycle management
    ISMDevice        — internal ISM band device tracking object
    ADSBTrack        — internal ADS-B aircraft track object
    SDRDemoGenerator — synthetic data generator for demo mode

Pydantic models for API serialization are in models.py.
"""
from __future__ import annotations

from .plugin import SDRMonitorPlugin, ISMDevice, ADSBTrack

__all__ = ["SDRMonitorPlugin", "ISMDevice", "ADSBTrack"]
