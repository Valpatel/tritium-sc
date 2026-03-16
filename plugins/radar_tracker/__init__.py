# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Radar tracker plugin package.

Ingests radar track data via MQTT, converts range/azimuth to lat/lng,
and creates TrackedTarget entries for display on the tactical map.
Supports any radar system that publishes tracks in the Tritium JSON format
(e.g., Aeris-10 bridge, SDR-based passive radar).
"""
from __future__ import annotations

from .plugin import RadarTrackerPlugin

__all__ = ["RadarTrackerPlugin"]
